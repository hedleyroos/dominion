# TripleA — Performance & Security Remediation

**Date:** 2026-05-07
**Scope:** P0 security/correctness fixes and best-effort P1 performance improvements found during a comprehensive architecture audit. P2 and P3 items are documented but not implemented in this phase.

---

## Summary of Changes

### P0 — Blockers

| # | What | File | Change |
|---|------|------|--------|
| 1 | SECRET_KEY hardcoded | `app/settings.py` | Read from `SECRET_KEY` env var; fall back to the existing insecure string so dev environments keep working without configuration. Production must set the env var. |
| 2 | SQL injection in `get_user_domains` | `app/src/triplea/utils.py` | Replace f-string interpolation of domain IDs into raw SQL with parameterised `%s` placeholders. Domain IDs come from the DB so the practical risk is low, but it is an anti-pattern that must be removed. |
| 3 | Pickle RCE surface in email model | `app/src/triplea/mail/models.py` | Wrap `pickle.loads()` in `try/except Exception`. Full migration from pickle to structured JSON fields is deferred but documented (see P3 below). |
| 4 | Race condition in `send_mail` task | `app/src/triplea/mail/tasks.py` | Replace the non-atomic check-then-set with an atomic `update(sent=True)` filtered on `sent=False`. The row-count return value is used as the lock — only the worker that flipped the flag sends the mail. If the send itself fails, the flag is rolled back so the beat task can retry. |
| 5 | Race condition in OAuth shadow-user creation | `app/src/triplea/oauth_validators.py` | Replace `try: get() except DoesNotExist: create()` with `get_or_create()`. The existing `username` unique constraint ensures DB-level atomicity; Django's `get_or_create` automatically retries the `get` after an `IntegrityError`. No migration required. |

### P1 — Performance (best effort)

| # | What | File | Change |
|---|------|------|--------|
| 6 | **Bug: `get_resource_roles` / `get_resource_permissions` infinite loop** | `app/src/triplea/utils.py` | Both functions had two bugs: (a) `filter(resource=resource)` queried the original resource on every iteration instead of the current `parent`, so ancestor roles/permissions were never found; (b) `parent = resource.parent` never advanced the loop variable, causing an infinite loop for any resource with a parent. Fixed to `filter(resource=parent)` and `parent = parent.parent`. |
| 7 | N×M query explosion in role/permission matrix | `app/src/triplea/utils.py` | `domain_roles_permissions_mapping` and `resource_roles_permissions_mapping` each issued one `aexists()` query per (role × permission) cell. Replaced with a single query that fetches all active `(role_id, permission_id)` pairs into a set, then checks membership in Python. |
| 8 | List concatenation in recursive permission checks | `app/src/triplea/utils.py` | `_user_has_permission_for_domain` and `_user_has_permission_for_resource` built accumulator lists via `ids + [new_id]` on each recursion step — O(D²) allocations for tree depth D. Changed to sets using `ids \| {new_id}`. |
| 9 | Request-scoped permission cache | `app/src/triplea/utils.py` | Added a `contextvars.ContextVar`-backed dict (per-ASGI-request lifetime, no cross-request leakage). Caches: Domain objects by ID (eliminates repeated `aget(id=...)` during tree traversal), `user_has_role_for_domain` results, `domain_has_permission_for_role` results, `user_has_permission_for_domain` top-level results, and `user_has_permission_for_resource` top-level results. If the same permission check is repeated within one request (e.g. checking `read` then `update` on the same domain hierarchy) the ancestor traversal only happens once. |
| 10 | N+1 from missing `select_related("parent")` in `get_user_domains` | `app/src/triplea/utils.py` | Added `.select_related("parent")` to the final QuerySet returned by `get_user_domains`, so `DomainSerializer` and callers that access `domain.parent` don't trigger a separate query per domain. |
| 11 | Missing `select_related` in list endpoints | `app/src/triplea_api/userdomainrole.py`, `role.py`, `permission.py` | Added `.select_related("role", "domain", "user")` / `.select_related("domain")` to `search()` querysets so FK fields accessed by serializers are fetched in a single JOIN rather than one query per row. Also fixed a missing `paginate_result` import in `userdomainrole.py` that would cause `NameError` on the search endpoint at runtime. |

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

## Deferred: P3 (documented only)

1. **Cross-request permission caching** — Use Django's cache backend (`django.core.cache`) for caching permission check results across requests. Configure via Django's `CACHES` setting (Redis, Memcached, DB — never talk to Redis directly). Invalidate on role/permission mutations. This builds on the request-scoped cache added in P1.

2. **Full pickle → JSON migration for email model** — Replace the `pickled BinaryField` with individual structured columns (`subject`, `body`, `from_email`, `to`, `cc`, `bcc`, `reply_to`, `headers`). Requires a schema migration and a data migration that unpickles existing rows. The minimum fix (try/except) in this phase reduces but does not eliminate the RCE surface.

3. **Probabilistic limit checks** — `Domain.clean` and `Resource.clean` use `randint(1, limit/10) == 1` sampling, meaning the limit can be exceeded 10× (domains) or 1000× (resources) before detection. Replace with a counter cache on the parent model using `F()` expressions for atomic increments.

4. **Async view migration** — The groundwork (ASGI app, `@django()` decorator, pytest-asyncio) is in place. Migrate API views from WSGI-sync to ASGI-async for better throughput under high concurrency.

5. **`async_to_sync` in admin and OAuth validator** — `admin_views.py` and `oauth_validators.py` call async utils via `async_to_sync`, blocking the WSGI thread. The admin views should be converted to async CBVs (Django 5.2+) or given sync utility variants. The OAuth validator's `get_user_domains` call should use a sync variant backed by the sync ORM so it does not pay the event-loop overhead.

---

## Verification

After this implementation:

- `tox` must pass green.
- The `get_resource_roles` / `get_resource_permissions` bug can be verified by running `get_resource_roles` on a child resource whose grandparent has a role assigned, and confirming the role is returned.
- The atomic `send_mail` behaviour can be verified with a concurrent test: two tasks both attempt to send the same unsent mail; assert only one send happens.
- Query counts for list endpoints can be asserted using `assertNumQueries` in existing or new tests.
