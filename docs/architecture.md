# Dominion Architecture

Dominion is an API-driven RBAC (Role-Based Access Control) system built in Django. It also acts as an OIDC (OpenID Connect) provider. Clients integrate with Dominion to manage users, organise resources into domain hierarchies, define roles and permissions, and perform access-control checks via a REST API.

Version: **0.1.14**

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Web framework | Django 5.2 LTS |
| REST API | Connexion 2 (OpenAPI 3.0 → Flask) |
| Serialization | Django REST Framework |
| OAuth2 / OIDC | django-oauth-toolkit + mozilla-django-oidc |
| Async tasks | Celery 5 |
| Message broker | RabbitMQ (AMQP) |
| Task result backend | Redis |
| Database | PostgreSQL (production), SQLite (development) |
| Database adapter | psycopg 3 |
| Registration | django-registration |

---

## Dependency Management

Top-level dependencies are declared in `requirements.in` with loose version pins. Run `pip-compile requirements.in --output-file requirements.txt` to regenerate the fully-pinned `requirements.txt`. This is the source of truth for production installs.

---

## Test Stack

| Tool | Purpose |
|------|---------|
| pytest | Test runner (via `tox`) |
| pytest-django | Django integration — `@pytest.mark.django_db`, test settings |
| pytest-asyncio | Async/await test support (`asyncio_mode = auto`) |
| pytest-xdist | Parallel execution (`-n auto`) |

Configuration lives in `pytest.ini` (project root) and `conftest.py` (project root).

Run all environments:
```
tox
```

Run a single environment with extra args:
```
tox -e app -- -k test_domaina_read
```

---

## Async Groundwork

Views are currently synchronous (WSGI). The groundwork for async is in place:

- `dominion/conf/asgi.py` exposes a standard ASGI application.
- `dominion/decorators.py` provides a `@django()` decorator that refreshes database connections for both sync and async callables.
- `pytest-asyncio` is installed and configured.

Full async view conversion is deferred to a future phase.

---

## Docker

`Dockerfile` — `python:3.12-slim` base, `gcc`+`libpq-dev` for psycopg compilation, gunicorn+gevent entrypoint on port 8000. Validates the build architecture via `uname -m` and errors on unsupported targets. Builds for both `amd64` and `arm64` without modification (no arch-specific wheel splits needed as there are no GPU/native-binary dependencies).

`docker-compose.yaml` — local development stack: app + celery worker + PostgreSQL 16 + RabbitMQ 3 + Redis 7. All service images pulled from the local registry (`localhost:5000`).

Build:
```
docker build -t dominion:latest .
docker buildx build --platform linux/amd64,linux/arm64 -t dominion:latest .
```

---

## Data Model

The RBAC model is built around two independent hierarchies — **domains** and **resources** — with roles and permissions that can be granted at any level and inherited down the tree.

### Core Entities

**User** (`dominion.User`) — extends `AbstractUser`.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | auto-generated |
| `api_key` | UUID | used for API key authentication |
| `created_by` | FK → User | tracks who created this user |
| `activation_date` | datetime | set when account is activated |
| `application_id` | int | non-zero for application-scoped users (see OAuth section) |

**Domain** (`dominion.Domain`) — hierarchical organisational unit.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `title` | string | must be unique among its own ancestors |
| `parent` | FK → Domain | null for root domains |
| `root` | FK → Domain | computed on save; points to the topmost ancestor |

A domain tree may contain at most 1,000 descendants per root (checked probabilistically). When a root domain is created via `DomainManager.create()`, a default set of `DomainRolePermission` entries is automatically created and the creating user is assigned the `owner` and `access_checker` roles.

**Role** (`dominion.Role`) — a named role, identified by a string `code`.

| Field | Type | Notes |
|-------|------|-------|
| `code` | string (unique) | primary identifier |
| `title` | string | display name |
| `domain` | FK → Domain | optional; must be a root domain if set |

**System roles** (global, no domain): `anonymous`, `authenticated`, `manager`, `owner`, `access_checker`.

**Permission** (`dominion.Permission`) — a named capability, identified by a string `code`.

| Field | Type | Notes |
|-------|------|-------|
| `code` | string (unique) | primary identifier |
| `title` | string | display name |
| `domain` | FK → Domain | optional; must be a root domain if set |

**System permissions** (global): `create`, `read`, `update`, `delete`, `check_access`, `manage_roles`, `view`.

**Resource** (`dominion.Resource`) — a domain-owned object with a stable identifier.

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `urn` | string (unique) | Uniform Resource Name |
| `parent` | FK → Resource | null for root resources |
| `domain` | FK → Domain | owning domain; must match parent's domain |

A domain may contain at most 10,000,000 resources (checked probabilistically). When a root resource is created via `ResourceManager.create()`, the creating user is assigned the `owner` role on that resource.

### Relationship Tables

These tables are **sparse** — not every combination of (domain/resource, role, permission) needs a row. Absence of a row means the permission is not granted at that level (but may still be inherited from a parent).

| Model | Meaning |
|-------|---------|
| `UserDomainRole` | A user holds a role on a specific domain |
| `UserResourceRole` | A user holds a role on a specific resource |
| `DomainRolePermission` | A role grants a permission within a domain |
| `ResourceRolePermission` | A role grants a permission within a resource |

All four have a UUID PK and a `unique_together` constraint on their logical key.

### Inheritance Helpers

`DomainPermission` and `ResourcePermission` are internal models (never exposed in the API or UI) that control permission inheritance.

| Field | Meaning |
|-------|---------|
| `domain` / `resource` | The domain or resource this rule applies to |
| `permission` | The permission code |
| `inherit` | If `False`, blocks inheritance at this level |

By default, permissions flow **downward** through the tree. A `DomainPermission` or `ResourcePermission` row with `inherit=False` cuts off that inheritance for the subtree below.

### Entity Relationship Summary

```
User ──────────────────── UserDomainRole ─── Domain ─── DomainRolePermission ─┐
                          (user, domain,                 (domain, role,         │
                           role)                          permission)           │
                                                                                Role
User ──────────────────── UserResourceRole ─ Resource ─ ResourceRolePermission ─┘
                          (user, resource,              (resource, role,
                           role)                         permission)

Domain ──── parent FK ──► Domain  (tree)
Resource ── parent FK ──► Resource  (tree)
Resource ─────────────── domain FK ──► Domain
```

---

## Authentication

The API supports two authentication methods, declared in `dominion/conf/openapi.yaml` under `securitySchemes`.

### HTTP Basic Auth

Handler: `dominion.api.auth.basic_auth(username, password)`

Looks up the user by username, verifies the password with Django's `check_password()`, and returns a token-info dict: `{"uid": username, "scope": "", "user": <User>}`. Returns `None` on failure (Connexion then returns 401).

### API Key

Handler: `dominion.api.auth.apikey_auth(api_key)`

The client sends the API key in the `X-Auth` request header. The handler looks up the user by `User.api_key` and returns the same token-info structure. Returns `None` if not found.

### OAuth2 / OIDC

Full OAuth2 and OIDC flows are provided by django-oauth-toolkit with a custom validator (`dominion.oauth_validators.CustomOAuth2Validator`). The authorization endpoint is at `/o/authorize/` (overridden by Dominion's own `AuthorizationView` to handle redirect cookie logic — see Request Pipeline).

**Application-scoped users.** When an OAuth client completes the authorization flow, `get_additional_claims()` in the custom validator creates (or retrieves) a shadow user with the username pattern `{real_username}%{oauth_app_id}` and `application_id` set to the OAuth app's ID. This user has its own `api_key` and its own domain/resource role assignments, sandboxing the application's access from the real user's access.

The OIDC JWT includes these additional claims:

| Claim | Value |
|-------|-------|
| `given_name`, `family_name`, `name` | From the real user |
| `preferred_username` | Real username |
| `email` | Real email |
| `uuid` | UUID of the application-scoped user |
| `api_key` | API key of the application-scoped user |
| `domains` | List of `{uuid, title}` objects the app-scoped user can access |

Silent login is supported: `validate_silent_login()` returns `True` for any authenticated, non-anonymous session.

---

## Authorization & Access Control

Permission checks are implemented in `dominion.utils` and work recursively over the domain and resource trees.

### Domain Permission Check

`user_has_permission_for_domain(user_id, permission_code, domain_id)`

1. Collect the user's roles on the target domain (via `UserDomainRole`).
2. Check whether any of those roles has the requested permission on the domain (via `DomainRolePermission`).
3. If not found, check `DomainPermission` for `inherit=False`. If present, **stop** — inheritance is blocked.
4. Otherwise, recurse to the parent domain.
5. Return `False` if the root is reached without a match.

### Resource Permission Check

`user_has_permission_for_resource(user_id, permission_code, resource_id)`

1. Collect the user's roles on the target resource (via `UserResourceRole`).
2. Check `ResourceRolePermission` for any matching role + permission.
3. If not found, check `ResourcePermission` for `inherit=False`. If present, **stop**.
4. If the resource has a parent, recurse up the resource tree.
5. When the root resource is reached (no parent), **transition to the domain tree**:
   - Check whether the user's resource roles satisfy the permission at the domain level (`domain_has_permission_for_role`).
   - Check whether any `ResourceRolePermission` row for the traversed resources maps to a role the user holds on the domain (`user_has_role_for_domain`).
   - Fall back to `user_has_permission_for_domain` on the resource's owning domain.

### Performance Note

Each check may issue multiple recursive SQL queries. There are no caches today; this is a known limitation flagged in the source with `TODO` comments.

---

## API Design

The REST API is built with **Connexion**, which maps OpenAPI 3.0 operation IDs to Python functions. The spec lives at `dominion/conf/openapi.yaml` and is served at `/api/v1.0/`.

### Conventions

- Each endpoint module (`domain.py`, `resource.py`, etc.) exports functions named `post`, `get`, `put`, `delete`, or `search`.
- Connexion injects `body` (parsed request body), `user` (authenticated `User` object), and `token_info` (the dict returned by the auth handler).
- Functions return `(data_dict, http_status_code)` tuples.
- Pagination is handled by `dominion.api.utils.paginate_result()`. The default page size is 100 (`DOMINION_API_RESULTS_PER_PAGE`).

### Endpoints

**User**

| Method | Path | Auth required | Description |
|--------|------|--------------|-------------|
| `POST` | `/api/v1.0/user/register` | No | Register a new user; sends activation email |
| `POST` | `/api/v1.0/user/login` | No | Login with email + password; returns User |
| `GET` | `/api/v1.0/user/by-api-key/{api_key}` | No | Fetch user by their API key |
| `POST` | `/api/v1.0/user` | Yes | Create a user (admin path, bypasses registration) |

**Domain**

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1.0/domain` | Create a domain |
| `GET` | `/api/v1.0/domain` | List domains accessible to the authenticated user (paginated) |
| `GET` | `/api/v1.0/domain/{id}` | Fetch a single domain |
| `PUT` | `/api/v1.0/domain/{id}` | Update a domain |
| `DELETE` | `/api/v1.0/domain/{id}` | Delete a domain |

**Resource**

| Method | Path | Notes |
|--------|------|-------|
| `POST` | `/api/v1.0/resource` | Create; supports `?dryrun=true` |
| `GET` | `/api/v1.0/resource/{id}` | Fetch a single resource |
| `PUT` | `/api/v1.0/resource/{id}` | Update; supports `?dryrun=true` |
| `DELETE` | `/api/v1.0/resource/{id}` | Delete; supports `?dryrun=true` |

List (`GET /api/v1.0/resource`) is intentionally not implemented; resource counts can reach 10 million.

**Role / Permission**

Both follow the same pattern:

| Method | Path |
|--------|------|
| `POST` | `/api/v1.0/role` |
| `GET` | `/api/v1.0/role` (paginated) |
| `GET` | `/api/v1.0/role/{code}` |
| `PUT` | `/api/v1.0/role/{code}` |
| `DELETE` | `/api/v1.0/role/{code}` |

Same structure for `/api/v1.0/permission/{code}`.

**Assignments**

| Path | What it manages |
|------|----------------|
| `/api/v1.0/userdomainrole[/{id}]` | User ↔ Domain ↔ Role |
| `/api/v1.0/userresourcerole[/{id}]` | User ↔ Resource ↔ Role |
| `/api/v1.0/domainrolepermission[/{id}]` | Domain ↔ Role ↔ Permission |
| `/api/v1.0/resourcerolepermission[/{id}]` | Resource ↔ Role ↔ Permission |

All four support `GET` (list), `POST`, `GET /{id}`, `PUT /{id}`, `DELETE /{id}`. The list endpoints for `domainrolepermission` and `resourcerolepermission` require a `?domain=` or `?resource=` query parameter.

**Access Checks**

| Method | Path |
|--------|------|
| `GET` | `/api/v1.0/access/domain/permission/{user_id}/{domain_id}/{permission}` |
| `GET` | `/api/v1.0/access/resource/permission/{user_id}/{resource_id}/{permission}` |

The caller must have the `check_access` permission on the target domain or resource. Returns `{"result": true|false}`.

---

## URL Structure

```
/admin/                          Django admin
/o/authorize/                    Custom OAuth2 authorization view (Dominion)
/o/                              django-oauth-toolkit endpoints
/oidc/                           mozilla-django-oidc endpoints
/accounts/register/              User registration (web UI)
/accounts/activate/...           Account activation via emailed token
/accounts/login/                 Django login
/accounts/logout/                Django logout
/accounts/password*/             Django password reset/change
/                                Home (TemplateView)
/api/v1.0/                       Connexion REST API (Flask sub-application)
```

---

## Request Pipeline

### Middleware Stack

Defined in `dominion/conf/settings.py` (`MIDDLEWARE`):

1. `SecurityMiddleware`
2. `SessionMiddleware`
3. `CommonMiddleware`
4. `CsrfViewMiddleware`
5. `AuthenticationMiddleware`
6. `MessageMiddleware`
7. `XFrameOptionsMiddleware`
8. `dominion.middleware.oauth_complete_process` — custom (see below)

### OAuth Redirect Middleware

`dominion.middleware.oauth_complete_process` manages the redirect cycle around OAuth2 authorization:

- When a user arrives at `/o/authorize/`, a cookie named `oauth_redirect_next` (365-day expiry) is set to the URL they came from.
- After authentication, the middleware reads this cookie and redirects back to the original location.
- The cookie is deleted after the redirect.

### Signal Handlers

`dominion.handlers.on_user_activated()` — connected to django-registration's activation signal. Sets `User.activation_date` to `now()` when a user activates their account via the emailed link.

---

## Email Subsystem

All outbound email is queued through Celery rather than sent inline. The system uses a mixin pattern that wraps any real Django email backend.

### Model

`dominion.mail.EmailMessage` — stores each email as a pickled object.

| Field | Type |
|-------|------|
| `pickled` | BinaryField — a `pickle.dumps()` of a `django.core.mail.EmailMessage` |
| `sent` | BooleanField (indexed) |
| `created` | DateTimeField auto-now-add (indexed) |

The `unpickled` property deserializes on access.

### Backends

| Class | Use |
|-------|-----|
| `CelerySmtpBackend` | Production (wraps Django's SMTP backend) |
| `CeleryFileBackend` | Default (writes to `/tmp/app-messages`) |
| `CeleryLocMemBackend` | Tests |
| `CelerySESBackend` | AWS SES |

Each backend is a mixin of the Celery queuing logic combined with the appropriate Django backend. The active backend is set by the `EMAIL_BACKEND` environment variable.

### Send Flow

1. Django calls `backend.send_messages(messages)`.
2. Each message is pickled and saved as an `EmailMessage` row.
3. `send_mail.apply_async(args=[email_message_id], countdown=5)` is queued (5-second delay).
4. The Celery worker unpickles the message and calls the underlying real backend with `immediate=True`, which bypasses the queue and sends directly.

Failed sends are retried by the `send_unsent_mails` beat task.

---

## Async Tasks

### Celery Configuration (`dominion/conf/celery.py`)

All config keys use the modern lowercase form (Celery 5+ style).

| Setting | Value |
|---------|-------|
| Broker | `amqp://localhost:5672//` (RabbitMQ) — overridable via env |
| Result backend | `redis://localhost:6379/3` — overridable via env |
| `task_acks_late` | `True` — acknowledge after completion |
| `task_reject_on_worker_lost` | `True` — requeue if worker dies |
| `result_expires` | 604800 s (7 days) |
| `broker_heartbeat` | 300 s — tolerates internet-speed connections |

### Beat Schedule

| Schedule | Task | Expiry |
|----------|------|--------|
| Every 5 minutes | `dominion.mail.tasks.send_unsent_mails` | 60 s |
| Daily at 01:15 UTC | `dominion.mail.tasks.vacuum` | 60 s |

### Tasks

| Task | What it does |
|------|-------------|
| `dominion.mail.tasks.send_mail(email_message_id)` | Unpickle and send one queued email |
| `dominion.mail.tasks.send_unsent_mails()` | Retry all unsent emails |
| `dominion.mail.tasks.vacuum()` | Delete email records older than 14 days |
| `dominion.tasks.vacuum()` | Delete unactivated users older than 7 days |

---

## Admin Interface

The Django admin provides a standard CRUD interface for all models. Two custom views add a matrix UI for managing role↔permission mappings.

### Role/Permission Matrix

`DomainManageRolesPermissionsView` and `ResourceManageRolesPermissionsView` (both `UpdateView` subclasses in `dominion.admin_views`) render a checkbox grid with roles as columns and permissions as rows. The grid is built by `domain_roles_permissions_mapping()` / `resource_roles_permissions_mapping()` in `dominion.utils`.

The corresponding form classes (`dominion.admin_forms`) parse submitted field names in the format `role_{role_id}_checkbox_{permission_id}` to create or delete `DomainRolePermission` / `ResourceRolePermission` rows and manage the `inherit` flag on `DomainPermission` / `ResourcePermission`.

---

## Registration & User Lifecycle

### Web Registration

1. User submits `/accounts/register/` (backed by `dominion.registration.RegistrationView`, which extends django-registration's activation backend).
2. An activation email is sent. The account is inactive until the link is clicked.
3. On activation, `on_user_activated()` sets `User.activation_date`.
4. The activation window is 7 days (`ACCOUNT_ACTIVATION_DAYS = 7`).

### API Registration

`POST /api/v1.0/user/register` — accepts `{username, email, password}`. Internally reuses django-registration's `RegistrationView` to trigger the same activation email flow. Returns the created `User` object (201).

### Admin User Creation

`POST /api/v1.0/user` (auth required) — creates a user directly, bypassing registration and email activation. Sets `created_by` to the authenticated user. Intended for controlled programmatic user creation by trusted clients.

### Application-Scoped Users

When an OAuth2 client completes authorization, a shadow user (`{username}%{app_id}`) is created automatically with `application_id` set to the OAuth app's integer ID. This user has its own `api_key` and independent role assignments, so the OAuth client can only access domains and resources explicitly granted to it.

### User Cleanup

Unactivated users older than 7 days are removed by the `dominion.tasks.vacuum` Celery task, run daily.

---

## Configuration

Key settings in `dominion/conf/settings.py`. Most runtime values are read from environment variables via `environs`.

| Setting | Default | Description |
|---------|---------|-------------|
| `AUTH_USER_MODEL` | `dominion.User` | Custom user model |
| `LOGIN_URL` | `/accounts/login/` | |
| `SESSION_COOKIE_NAME` | `dominionid` | |
| `DATABASE_URL` | SQLite | PostgreSQL in production (psycopg 3) |
| `EMAIL_BACKEND` | `CeleryFileBackend` | Set to `CelerySmtpBackend` or `CelerySESBackend` for production |
| `DOMINION_API_RESULTS_PER_PAGE` | 100 | Pagination page size |
| `DOMINION_MAX_DESCENDANT_DOMAINS` | 1000 | Soft limit on domains per root |
| `DOMINION_MAX_RESOURCES_PER_DOMAIN` | 10,000,000 | Soft limit on resources per domain |
| `ACCOUNT_ACTIVATION_DAYS` | 7 | Registration window in days |
| `OAUTH2_PROVIDER.OIDC_ENABLED` | `True` | Enable OIDC |
| `OAUTH2_PROVIDER.OAUTH2_VALIDATOR_CLASS` | `dominion.oauth_validators.CustomOAuth2Validator` | Custom claims + app-scoped users |

For PostgreSQL, `CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True`, and `statement_timeout=10000` ms are applied automatically when a PostgreSQL `DATABASE_URL` is detected.

---

## Deployment

### Entry Points

| File | Purpose |
|------|---------|
| `dominion/conf/wsgi.py` | Standard Django WSGI application |
| `dominion/conf/asgi.py` | Standard Django ASGI application |

### Startup Scripts

| Script | Runs |
|--------|------|
| `run-wsgi.sh` | Basic WSGI server |
| `run-gunicorn.sh` | Gunicorn WSGI workers |
| `run-gevent.sh` | Gunicorn with gevent worker class |
| `run-celery.sh` | Celery worker process |

In production, run at least one Celery worker process alongside the web process. The Celery beat scheduler is required for periodic tasks (`send_unsent_mails`, `vacuum`).
