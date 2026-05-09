# Dominion — Performance & Security Remediation

**Date:** 2026-05-07
**Scope:** P0 security/correctness fixes and best-effort P1 performance improvements found during a comprehensive architecture audit. P2 and P3 items are documented but not implemented in this phase.

---

## Summary of Changes

### P0 — Blockers

| # | What | File | Change |
|---|------|------|--------|
| 1 | SECRET_KEY hardcoded | `app/settings.py` | Read from `SECRET_KEY` env var; fall back to the existing insecure string so dev environments keep working without configuration. Production must set the env var. |
| 2 | SQL injection in `get_user_domains` | `app/src/dominion/utils.py` | Replace f-string interpolation of domain IDs into raw SQL with parameterised `%s` placeholders. Domain IDs come from the DB so the practical risk is low, but it is an anti-pattern that must be removed. |
| 3 | Pickle RCE surface in email model | `app/src/dominion/mail/models.py` | Wrap `pickle.loads()` in `try/except Exception`. Full migration from pickle to structured JSON fields is deferred but documented (see P3 below). |
| 4 | Race condition in `send_mail` task | `app/src/dominion/mail/tasks.py` | Replace the non-atomic check-then-set with an atomic `update(sent=True)` filtered on `sent=False`. The row-count return value is used as the lock — only the worker that flipped the flag sends the mail. If the send itself fails, the flag is rolled back so the beat task can retry. |
| 5 | Race condition in OAuth shadow-user creation | `app/src/dominion/oauth_validators.py` | Replace `try: get() except DoesNotExist: create()` with `get_or_create()`. The existing `username` unique constraint ensures DB-level atomicity; Django's `get_or_create` automatically retries the `get` after an `IntegrityError`. No migration required. |

### P1 — Performance (best effort)

| # | What | File | Change |
|---|------|------|--------|
| 6 | **Bug: `get_resource_roles` / `get_resource_permissions` infinite loop** | `app/src/dominion/utils.py` | Both functions had two bugs: (a) `filter(resource=resource)` queried the original resource on every iteration instead of the current `parent`, so ancestor roles/permissions were never found; (b) `parent = resource.parent` never advanced the loop variable, causing an infinite loop for any resource with a parent. Fixed to `filter(resource=parent)` and `parent = parent.parent`. |
| 7 | N×M query explosion in role/permission matrix | `app/src/dominion/utils.py` | `domain_roles_permissions_mapping` and `resource_roles_permissions_mapping` each issued one `aexists()` query per (role × permission) cell. Replaced with a single query that fetches all active `(role_id, permission_id)` pairs into a set, then checks membership in Python. |
| 8 | List concatenation in recursive permission checks | `app/src/dominion/utils.py` | `_user_has_permission_for_domain` and `_user_has_permission_for_resource` built accumulator lists via `ids + [new_id]` on each recursion step — O(D²) allocations for tree depth D. Changed to sets using `ids \| {new_id}`. |
| 9 | Request-scoped permission cache | `app/src/dominion/utils.py` | Added a `contextvars.ContextVar`-backed dict (per-ASGI-request lifetime, no cross-request leakage). Caches: Domain objects by ID (eliminates repeated `aget(id=...)` during tree traversal), `user_has_role_for_domain` results, `domain_has_permission_for_role` results, `user_has_permission_for_domain` top-level results, and `user_has_permission_for_resource` top-level results. If the same permission check is repeated within one request (e.g. checking `read` then `update` on the same domain hierarchy) the ancestor traversal only happens once. |
| 10 | N+1 from missing `select_related("parent")` in `get_user_domains` | `app/src/dominion/utils.py` | Added `.select_related("parent")` to the final QuerySet returned by `get_user_domains`, so `DomainSerializer` and callers that access `domain.parent` don't trigger a separate query per domain. |
| 11 | Missing `select_related` in list endpoints | `app/src/dominion_api/userdomainrole.py`, `role.py`, `permission.py` | Added `.select_related("role", "domain", "user")` / `.select_related("domain")` to `search()` querysets so FK fields accessed by serializers are fetched in a single JOIN rather than one query per row. Also fixed a missing `paginate_result` import in `userdomainrole.py` that would cause `NameError` on the search endpoint at runtime. |

---

## Deferred: P2 (acknowledged, not implemented)

The following were identified but are out of scope for this phase:

1. **Cookie expiry bug** — `middleware.py` sets a future expiry on the `oauth_redirect_next` cookie instead of deleting it; should use a past expiry.
2. **No rate limiting** — login, register, and API-key lookup endpoints are unthrottled.
3. **No audit logging** — role/permission mutations have no audit trail.
4. **Docker image** — no multi-stage build (build tools included in final image); runs as root; no `HEALTHCHECK`.
5. **Gunicorn workers** — `--workers=12` hardcoded in `run-gunicorn.sh`.
6. **Missing test coverage** — `views.py`, access-check endpoints, user auth endpoints have no dedicated tests.
7. **Missing `.env.example`** and deployment runbook.

---

## Implemented: P2 (phase two session)

All items below were implemented and verified (`tox` green) in the follow-up session:

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Cookie expiry bug | ✅ Done | `middleware.py` now calls `delete_cookie()` on the authenticated branch; test updated to assert `max-age == 0`. |
| 2 | Rate limiting | ✅ Done | Added `django-ratelimit 4.1.0`. Login (10/5m), register (5/h), by-api-key (30/m) via `is_ratelimited` in async Connexion endpoints; Django `LoginView` and `RegistrationView` wrapped with `ratelimit(key="ip", block=True)` decorator. `CACHES` configured with Memcached in production (when `DEBUG=False`) and Django's default `LocMemCache` in development/tests. `RATELIMIT_USE_CACHE = "default"` added to `settings.py`. |
| 3 | Audit logging | ✅ Done | Added `LOGGING` config in `settings.py` (handler: `StreamHandler`, logger: `dominion.audit` at `DEBUG`). Added `logger.debug("action=... object_type=... object_id=... user=...")` calls on successful create/update/delete in `userdomainrole.py`, `userresourcerole.py`, `domainrolepermission.py`, `resourcerolepermission.py`. |
| 4 | Docker image | ✅ Done | Multi-stage build: `builder` stage installs deps; `final` stage uses `python:3.12-slim` with only `libpq5`, creates non-root `appuser`, copies deps from builder. `HEALTHCHECK` calls `/healthz`. `HealthView` added to `views.py` and `urls.py`. |
| 5 | Gunicorn workers | ⏸ Deferred | `run-gunicorn.sh` is for local dev only. Left as-is per user instruction. |
| 6 | Test coverage | ✅ Done | Added tests in `test_api.py`: `test_access_domain_permission_allowed`, `test_access_domain_permission_denied_no_check_access`, `test_login_no_matching_email`, `test_login_with_email`, `test_login_wrong_password`, `test_by_api_key_success`, `test_by_api_key_not_found`. Added `app/src/dominion/tests/test_views.py`: `test_healthz_returns_200`, `test_home_view_returns_200`. |
| 7 | `.env.example` | ✅ Done | Created at repo root with all required env vars. Deployment runbook remains deferred. |

---

## Implemented: P3 (phase three session)

All items below were implemented and verified (`tox` green):

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Cross-request permission caching | ✅ Done | `utils.py` uses `django.core.cache` (Memcached in production, LocMem in dev) with versioned keys (TTL 300s). `invalidate_user_permissions(user_id)` and `invalidate_rules_permissions()` called on all relevant mutations in `userdomainrole.py`, `userresourcerole.py`, `domainrolepermission.py`, `resourcerolepermission.py`. |
| 2 | Full pickle → structured fields for email model | ✅ Done | `EmailMessage` now has `subject`, `body`, `from_email`, `to`, `cc`, `bcc`, `reply_to`, `headers` fields. Three migrations: 0004 adds fields, 0005 data-migrates from pickle, 0006 removes `pickled` column. `mail/backends.py` writes structured fields; `mail/tasks.py` reconstructs `DjangoEmailMessage` from them. |
| 3 | Counter-cache limit checks (replace probabilistic) | ✅ Done | `Domain` has `descendant_count` and `resource_count` (PositiveIntegerField). Maintained by `post_save`/`post_delete` signals using `F()` expressions for atomic increments. `Domain.clean()` and `Resource.clean()` read these counters instead of doing probabilistic `count()` queries. |
| 4 | Sync utility variants for admin/OAuth | ✅ Done | `get_user_domains_sync`, `_get_domain_roles_sync`, `_get_domain_permissions_sync`, `_get_resource_roles_sync`, `_get_resource_permissions_sync`, `domain_roles_permissions_mapping_sync`, `resource_roles_permissions_mapping_sync` — used by `admin_views.py` and `oauth_validators.py` instead of `async_to_sync` wrappers. Shared helpers extracted for CTE query, inherit-default, and mapping row building. |

## Deferred: remaining items

1. **Async view migration** — The groundwork (ASGI app, pytest-asyncio) is in place. Migrate API views from WSGI-sync to ASGI-async for better throughput under high concurrency.

---

## Verification

After this implementation:

- `tox` must pass green.
- The `get_resource_roles` / `get_resource_permissions` bug can be verified by running `get_resource_roles` on a child resource whose grandparent has a role assigned, and confirming the role is returned.
- The atomic `send_mail` behaviour can be verified with a concurrent test: two tasks both attempt to send the same unsent mail; assert only one send happens.
- Query counts for list endpoints can be asserted using `assertNumQueries` in existing or new tests.
