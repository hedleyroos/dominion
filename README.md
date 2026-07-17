# Dominion

Dominion is an API-driven **RBAC** (Role-Based Access Control) system built on Django,
which also acts as an **OIDC** (OpenID Connect) provider. Clients manage users, organise
resources into domain hierarchies, define roles and permissions, and perform access-control
checks over a REST API.

It runs two ways:

- **Standalone service** — the Connexion (OpenAPI 3) async API plus the Django admin / OIDC
  provider, deployed together.
- **Embedded library** — installed as a Django app into a host project, which calls the
  permission resolvers in `dominion.utils` directly.

> Because Dominion is used both ways, `dominion/utils.py` is a public API: its functions are
> not removed or re-signatured, only fixed and extended.

---

## Core concepts

Dominion models access around **two independent hierarchies** — **domains** (organisational
units) and **resources** (domain-owned objects) — with **roles** and **permissions** granted
at any level and inherited downward through the tree.

| Concept | Meaning |
|---------|---------|
| **Domain** | Hierarchical org unit (`parent` FK). A root domain seeds default roles/permissions. |
| **Resource** | A domain-owned object with a stable `urn`, itself hierarchical. |
| **Role** | A named capability holder (`owner`, `manager`, `access_checker`, …). |
| **Permission** | A named action (`create`, `read`, `update`, `delete`, `check_access`, …). |
| **UserDomainRole / UserResourceRole** | A user holds a role on a domain / resource. |
| **DomainRolePermission / ResourceRolePermission** | A role grants a permission in a domain / resource. |

Permissions flow **down** the tree; a `DomainPermission`/`ResourcePermission` row with
`inherit=False` cuts inheritance for that subtree.

See [docs/architecture.md](docs/architecture.md) for the full data model, request pipeline,
caching, and deployment details.

---

## Quickstart (local, Docker Compose)

```bash
cp .env.example .env          # then edit SECRET_KEY etc.
docker compose up --build     # app + celery + postgres + rabbitmq + redis + memcached
```

Or run it directly against SQLite for a quick look:

```bash
python -m venv ve && ./ve/bin/pip install -r requirements.txt
export DJANGO_SETTINGS_MODULE=dominion.conf.settings
./ve/bin/python manage.py migrate
# API (Connexion/uvicorn) on :8090
./ve/bin/uvicorn main:app --host 0.0.0.0 --port 8090
# Django admin + OIDC provider (separate ASGI/WSGI app) on :8000
./ve/bin/python manage.py runserver 0.0.0.0:8000
```

> **Two apps:** the REST API (`main:app`) and the Django admin/OIDC/registration app
> (`dominion.conf.wsgi` / `asgi`) are separate ASGI/WSGI applications. In production run
> both (e.g. behind one reverse proxy) plus at least one Celery worker and Celery beat.

### Try the API

Register and authenticate (Basic auth or the `X-Auth: <api_key>` header), then:

```bash
# Create a root domain (you become its owner + access_checker)
curl -X POST http://localhost:8090/api/v1.0/domain \
     -H "X-Auth: $API_KEY" -H "Content-Type: application/json" \
     -d '{"title": "Acme"}'

# Grant a user the manager role on that domain
curl -X POST http://localhost:8090/api/v1.0/userdomainrole \
     -H "X-Auth: $API_KEY" -H "Content-Type: application/json" \
     -d '{"user": "<user-id>", "domain": "<domain-id>", "role": "manager"}'

# Check whether a user has a permission (requires check_access on the domain)
curl http://localhost:8090/api/v1.0/access/domain/permission/<user-id>/<domain-id>/read \
     -H "X-Auth: $API_KEY"
# -> {"result": true}
```

Full API reference: the OpenAPI spec at `dominion/conf/openapi.yaml` (served at
`/api/v1.0/`), and the Sphinx docs under `sphinx/`.

---

## Development

Dependencies are declared in `requirements.in` and compiled to a pinned `requirements.txt`:

```bash
pip-compile requirements.in --output-file requirements.txt
```

### Tests

Tests run under `tox` (pytest + pytest-django + pytest-asyncio, parallel via pytest-xdist):

```bash
tox                         # app + api on sqlite and postgres
tox -e app                  # unit tests, sqlite
tox -e app-postgres         # unit tests, postgres (needs a postgres on :5432)
tox -e perf                 # query-count / cache regression tests only (fast, no server)
```

The `-postgres` envs expect `postgresql://test:test@localhost:5432/dominion_test`.

### Performance regression testing

`perf/perfload.py` is a load generator with a regression gate:

```bash
# Seed data and capture a baseline against a running server
tox -e perfload -- setup --scale small
tox -e perfload -- run --scale small --baseline perf/baseline-small.json

# Later, fail (exit non-zero) if RPS drops or p95/p99 grows beyond tolerance
tox -e perfload -- run --scale small --baseline perf/baseline-small.json --check
```

Scales: `small` (CI smoke), `medium`, `full` (the original 50k-user / 1M-resource soak).
Baselines are environment-specific — generate one per target runner; don't share across
machines.

CI (GitHub Actions, `.github/workflows/ci.yml`) runs the tox test matrix on every push/PR
plus a best-effort small-scale load smoke.
