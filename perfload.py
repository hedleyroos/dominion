#!/usr/bin/env python
"""perfload.py — Dominion RBAC performance load test.

Subcommands:
    setup   Bulk-create test data via the Django ORM.  Run once; idempotent.
    run     Fire async HTTP load scenarios against a live server.
    all     setup then run.

Environment:
    DATABASE_URL        Postgres DSN (default: postgresql://dominion:dominion@localhost:5432/dominion)
    MEMCACHED_LOCATION  Memcached host:port (default: localhost:11211)

    Migrations are handled by the Docker entrypoint; do not run them here.

Examples:
    python perfload.py setup --users 50000 --domains 200 --resources 1000000
    python perfload.py run --base-url http://localhost:8000/api/v1.0 --concurrency 100 --duration 60
    python perfload.py all --users 1000 --domains 10 --resources 50000 --duration 30
"""

import argparse
import asyncio
import collections
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field

import httpx

# ---------------------------------------------------------------------------
# Environment defaults — must be set before Django boots.
# ---------------------------------------------------------------------------

os.environ.setdefault("DATABASE_URL", "postgresql://dominion:dominion@localhost:5433/dominion")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("SECRET_KEY", "perftesting123")
os.environ.setdefault("MEMCACHED_LOCATION", "localhost:11211")
os.environ.setdefault("MEMCACHED_KEY_PREFIX", "perftest")


# ---------------------------------------------------------------------------
# Django bootstrap — must precede any model imports.
# ---------------------------------------------------------------------------

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dominion.conf.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

get_wsgi_application()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db.models import F  # noqa: E402

from dominion.models import (  # noqa: E402
    Domain,
    DomainPermission,
    DomainRolePermission,
    Permission,
    Resource,
    ResourcePermission,
    ResourceRolePermission,
    Role,
    UserDomainRole,
    UserResourceRole,
)

User = get_user_model()

# System permissions exercised by access-check scenarios.
SYSTEM_PERMISSIONS = ["create", "read", "update", "delete", "check_access", "manage_roles", "view"]

# Domain hierarchy fan-out.
CHILDREN_PER_ROOT = 5
GRANDCHILDREN_PER_CHILD = 2

BULK_BATCH = 50_000


# ---------------------------------------------------------------------------
# Test data container — populated by load_test_data() for the run command.
# ---------------------------------------------------------------------------

@dataclass
class TestData:
    # All user IDs as strings (str(UUID)).
    user_ids: list[str] = field(default_factory=list)

    # (domain_id, checker_user_id) — checker has check_access on the domain.
    domain_checker_pairs: list[tuple[str, str]] = field(default_factory=list)

    # (domain_id, owner_user_id) — owner holds all system permissions on the domain.
    domain_owner_pairs: list[tuple[str, str]] = field(default_factory=list)

    # domain IDs at each tree level.
    child_domain_ids: list[str] = field(default_factory=list)
    grandchild_domain_ids: list[str] = field(default_factory=list)

    # (resource_id, checker_user_id) — checker has check_access on resource's domain.
    resource_checker_pairs: list[tuple[str, str]] = field(default_factory=list)

    # (resource_id, owner_user_id) — owner holds permissions on the resource's domain.
    deep_resource_ids: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100
    floor = int(k)
    ceil = floor + 1
    if ceil >= len(sorted_data):
        return sorted_data[floor]
    return sorted_data[floor] + (k - floor) * (sorted_data[ceil] - sorted_data[floor])


def print_results(name: str, latencies: list[float], statuses: list[int], elapsed: float) -> None:
    total = len(latencies)
    if total == 0:
        print(f"\n{name}: no requests made.")
        return
    ok = sum(1 for s in statuses if 200 <= s < 300)
    errors = total - ok
    rps = total / elapsed if elapsed > 0 else 0
    print(f"\n{'=' * 64}")
    print(f"  {name}")
    print(f"{'=' * 64}")
    print(f"  Total     : {total:>8,}   RPS    : {rps:>8.1f}")
    print(f"  OK (2xx)  : {ok:>8,}   Errors : {errors:>8,}")
    if latencies:
        p50 = _percentile(latencies, 50)
        p95 = _percentile(latencies, 95)
        p99 = _percentile(latencies, 99)
        p_max = max(latencies)
        print(f"  Latency ms  p50: {p50:>7.1f}  p95: {p95:>7.1f}  p99: {p99:>7.1f}  max: {p_max:>7.1f}")


# ---------------------------------------------------------------------------
# Setup: users
# ---------------------------------------------------------------------------

def setup_users(num_users: int) -> list[str]:
    """Bulk-create perf test users; return list of user ID strings."""
    if User.objects.filter(username__startswith="perfuser").exists():
        existing = list(
            User.objects.filter(username__startswith="perfuser")
            .order_by("username")
            .values_list("id", flat=True)
        )
        print(f"  Users already exist ({len(existing):,}) — skipping.")
        return [str(uid) for uid in existing]

    print(f"  Creating {num_users:,} users...")
    t0 = time.time()
    batch = []
    for i in range(num_users):
        uid = uuid.uuid4()
        user = User(
            id=uid,
            username=f"perfuser{i:08d}",
            email=f"perfuser{i:08d}@perf.test",
            api_key=uid,
            password="!",  # Unusable password — auth uses api_key only.
        )
        batch.append(user)
        if len(batch) >= BULK_BATCH:
            User.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        User.objects.bulk_create(batch, ignore_conflicts=True)
    user_ids = list(
        User.objects.filter(username__startswith="perfuser")
        .order_by("username")
        .values_list("id", flat=True)
    )
    print(f"  Done: {len(user_ids):,} users in {time.time() - t0:.1f}s.")
    return [str(uid) for uid in user_ids]


# ---------------------------------------------------------------------------
# Setup: domains
# ---------------------------------------------------------------------------

def setup_domains(num_root: int, user_ids: list[str]) -> tuple[list, list, list]:
    """Create root, child, and grandchild domains.

    Root domains go through DomainManager.create() to get default
    DomainRolePermissions and the owner's UserDomainRole assignments.
    Children and grandchildren are bulk-created for speed.

    Returns (root_domains, child_domains, grandchild_domains) as ORM objects.
    """
    if Domain.objects.filter(title__startswith="perf-root-").exists():
        root_domains = list(Domain.objects.filter(title__startswith="perf-root-").order_by("title"))
        child_domains = list(Domain.objects.filter(title__startswith="perf-child-").order_by("title"))
        grandchild_domains = list(Domain.objects.filter(title__startswith="perf-grand-").order_by("title"))
        print(f"  Domains already exist (roots={len(root_domains):,}, children={len(child_domains):,}, grandchildren={len(grandchild_domains):,}) — skipping.")
        return root_domains, child_domains, grandchild_domains

    num_users = len(user_ids)

    print(f"  Creating {num_root:,} root domains (with default permissions)...")
    t0 = time.time()
    root_domains = []
    for i in range(num_root):
        owner = User.objects.get(id=user_ids[i % num_users])
        domain = Domain.objects.create(title=f"perf-root-{i:06d}", owner=owner)
        root_domains.append(domain)
        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{num_root}")
    print(f"  Root domains done in {time.time() - t0:.1f}s.")

    print(f"  Creating {num_root * CHILDREN_PER_ROOT:,} child domains...")
    t0 = time.time()
    children_to_create = []
    for root in root_domains:
        for j in range(CHILDREN_PER_ROOT):
            children_to_create.append(Domain(
                id=uuid.uuid4(),
                title=f"perf-child-{str(root.id)[:8]}-{j:02d}",
                parent_id=root.id,
                root_id=root.id,
                descendant_count=0,
                resource_count=0,
            ))
    Domain.objects.bulk_create(children_to_create, ignore_conflicts=True)
    for root in root_domains:
        Domain.objects.filter(id=root.id).update(
            descendant_count=F("descendant_count") + CHILDREN_PER_ROOT
        )
    child_domains = list(Domain.objects.filter(title__startswith="perf-child-").order_by("title"))
    print(f"  Child domains done in {time.time() - t0:.1f}s.")

    print(f"  Creating {len(child_domains) * GRANDCHILDREN_PER_CHILD:,} grandchild domains...")
    t0 = time.time()
    grand_to_create = []
    for child in child_domains:
        root_id = child.parent_id
        for k in range(GRANDCHILDREN_PER_CHILD):
            grand_to_create.append(Domain(
                id=uuid.uuid4(),
                title=f"perf-grand-{str(child.id)[:8]}-{k:02d}",
                parent_id=child.id,
                root_id=root_id,
                descendant_count=0,
                resource_count=0,
            ))
    Domain.objects.bulk_create(grand_to_create, ignore_conflicts=True)
    for root in root_domains:
        Domain.objects.filter(id=root.id).update(
            descendant_count=F("descendant_count") + CHILDREN_PER_ROOT * GRANDCHILDREN_PER_CHILD
        )
    grandchild_domains = list(Domain.objects.filter(title__startswith="perf-grand-").order_by("title"))
    print(f"  Grandchild domains done in {time.time() - t0:.1f}s.")

    return root_domains, child_domains, grandchild_domains


# ---------------------------------------------------------------------------
# Setup: custom roles, permissions, and domain-level assignments
# ---------------------------------------------------------------------------

def setup_custom_roles(root_domains: list) -> dict[str, list]:
    """Create custom roles and permissions per root domain.

    Returns a dict mapping root domain ID → list of custom Role objects.
    """
    # Three custom roles per root domain: viewer (read/view), editor (read/update/view),
    # auditor (read/check_access/view — can call the access-check endpoint).
    print("  Setting up custom roles and permissions...")
    t0 = time.time()

    perm_read = Permission.objects.get(code="read")
    perm_view = Permission.objects.get(code="view")
    perm_update = Permission.objects.get(code="update")
    perm_check_access = Permission.objects.get(code="check_access")

    roles_by_root: dict[str, list] = {}
    for root in root_domains:
        root_id_short = str(root.id)[:8]
        roles = []
        for suffix, perms in [
            (f"viewer-{root_id_short}", [perm_read, perm_view]),
            (f"editor-{root_id_short}", [perm_read, perm_update, perm_view]),
            (f"auditor-{root_id_short}", [perm_read, perm_check_access, perm_view]),
        ]:
            role, _ = Role.objects.get_or_create(
                code=f"perf-{suffix}",
                defaults={"title": f"Perf {suffix}", "domain": root},
            )
            roles.append(role)
            for perm in perms:
                DomainRolePermission.objects.get_or_create(
                    domain=root, role=role, permission=perm
                )
        roles_by_root[str(root.id)] = roles

    # Also add a DomainPermission(inherit=False) on a sample of child domains
    # to create inheritance-blocking scenarios for the load test.
    sample_children = Domain.objects.filter(title__startswith="perf-child-").order_by("title")[::10]
    for child in sample_children:
        DomainPermission.objects.get_or_create(
            domain=child, permission=perm_read, defaults={"inherit": False}
        )

    print(f"  Custom roles done in {time.time() - t0:.1f}s.")
    return roles_by_root


def setup_additional_user_domain_roles(
    root_domains: list,
    child_domains: list,
    grandchild_domains: list,
    user_ids: list[str],
    roles_by_root: dict[str, list],
) -> None:
    """Assign a diverse set of users to domains with varied roles.

    Each root domain gets:
    - 10 managers
    - 50 viewers (custom role)
    - 20 editors (custom role)
    - 10 auditors (custom role — they can call the access-check endpoint too)

    Also assign managers and viewers to a subset of child and grandchild domains.
    """
    if UserDomainRole.objects.filter(user__username__startswith="perfuser").exclude(role__code__in=["owner", "access_checker"]).exists():
        print("  Additional user domain roles already exist — skipping.")
        return

    print("  Assigning users to domains with varied roles...")
    t0 = time.time()
    role_manager = Role.objects.get(code="manager")
    num_users = len(user_ids)
    assignments = []

    for i, root in enumerate(root_domains):
        custom_roles = roles_by_root[str(root.id)]
        role_viewer, role_editor, role_auditor = custom_roles
        base = i * 100  # Offset into user pool per domain to spread assignments.

        # 10 managers.
        for j in range(10):
            assignments.append(UserDomainRole(
                id=uuid.uuid4(),
                user_id=user_ids[(base + j) % num_users],
                domain_id=root.id,
                role=role_manager,
            ))
        # 50 viewers.
        for j in range(10, 60):
            assignments.append(UserDomainRole(
                id=uuid.uuid4(),
                user_id=user_ids[(base + j) % num_users],
                domain_id=root.id,
                role=role_viewer,
            ))
        # 20 editors.
        for j in range(60, 80):
            assignments.append(UserDomainRole(
                id=uuid.uuid4(),
                user_id=user_ids[(base + j) % num_users],
                domain_id=root.id,
                role=role_editor,
            ))
        # 10 auditors — they can also call the access-check endpoint.
        for j in range(80, 90):
            assignments.append(UserDomainRole(
                id=uuid.uuid4(),
                user_id=user_ids[(base + j) % num_users],
                domain_id=root.id,
                role=role_auditor,
            ))

    # Assign managers to every 5th child domain.
    for k, child in enumerate(child_domains[::5]):
        root_id = str(child.root_id)
        custom_roles = roles_by_root.get(root_id, [])
        if not custom_roles:
            continue
        role_viewer = custom_roles[0]
        assignments.append(UserDomainRole(
            id=uuid.uuid4(),
            user_id=user_ids[k % num_users],
            domain_id=child.id,
            role=role_manager,
        ))
        assignments.append(UserDomainRole(
            id=uuid.uuid4(),
            user_id=user_ids[(k + 1) % num_users],
            domain_id=child.id,
            role=role_viewer,
        ))

    # Assign viewers to every 10th grandchild domain.
    for k, grand in enumerate(grandchild_domains[::10]):
        root_id = str(grand.root_id)
        custom_roles = roles_by_root.get(root_id, [])
        if not custom_roles:
            continue
        role_viewer = custom_roles[0]
        assignments.append(UserDomainRole(
            id=uuid.uuid4(),
            user_id=user_ids[k % num_users],
            domain_id=grand.id,
            role=role_viewer,
        ))

    UserDomainRole.objects.bulk_create(assignments, ignore_conflicts=True, batch_size=BULK_BATCH)
    print(f"  Assigned {len(assignments):,} extra user-domain roles in {time.time() - t0:.1f}s.")


# ---------------------------------------------------------------------------
# Setup: resources
# ---------------------------------------------------------------------------

def setup_resources(
    root_domains: list,
    child_domains: list,
    user_ids: list[str],
    num_resources: int,
) -> tuple[list, list]:
    """Bulk-create resources distributed across all domains.

    ~70% are root resources; ~30% are children of root resources.
    Returns (root_resource_ids, child_resource_ids).
    """
    if Resource.objects.filter(urn__startswith="perf:").exists():
        root_ids = list(
            Resource.objects.filter(urn__startswith="perf:", parent__isnull=True)
            .values_list("id", flat=True)
        )
        child_ids = list(
            Resource.objects.filter(urn__startswith="perf:", parent__isnull=False)
            .values_list("id", flat=True)
        )
        print(f"  Resources already exist (root={len(root_ids):,}, child={len(child_ids):,}) — skipping.")
        return root_ids, child_ids

    all_domains = root_domains + child_domains
    num_domains = len(all_domains)
    num_root_resources = int(num_resources * 0.7)
    num_child_resources = num_resources - num_root_resources

    print(f"  Creating {num_root_resources:,} root resources...")
    t0 = time.time()
    batch = []
    for i in range(num_root_resources):
        batch.append(Resource(
            id=uuid.uuid4(),
            urn=f"perf:root:{i:010d}",
            domain_id=all_domains[i % num_domains].id,
            parent=None,
        ))
        if len(batch) >= BULK_BATCH:
            Resource.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        Resource.objects.bulk_create(batch, ignore_conflicts=True)
    print(f"  Root resources done in {time.time() - t0:.1f}s.")

    # Load root resource IDs to use as parents.
    root_resource_ids = list(
        Resource.objects.filter(urn__startswith="perf:root:")
        .values_list("id", flat=True)[:num_root_resources]
    )
    # Load domain_id for root resources in bulk.
    root_resource_domain_map = dict(
        Resource.objects.filter(urn__startswith="perf:root:")
        .values_list("id", "domain_id")
    )

    print(f"  Creating {num_child_resources:,} child resources...")
    t0 = time.time()
    num_parents = len(root_resource_ids)
    batch = []
    for i in range(num_child_resources):
        parent_id = root_resource_ids[i % num_parents]
        batch.append(Resource(
            id=uuid.uuid4(),
            urn=f"perf:child:{i:010d}",
            domain_id=root_resource_domain_map[parent_id],
            parent_id=parent_id,
        ))
        if len(batch) >= BULK_BATCH:
            Resource.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        Resource.objects.bulk_create(batch, ignore_conflicts=True)
    print(f"  Child resources done in {time.time() - t0:.1f}s.")

    return root_resource_ids, list(
        Resource.objects.filter(urn__startswith="perf:child:")
        .values_list("id", flat=True)
    )


def setup_resource_permissions(
    root_resource_ids: list,
    root_domains: list,
    roles_by_root: dict[str, list],
) -> None:
    """Set up ResourceRolePermissions on a sample of root resources.

    Also block inheritance on a small fraction to create diverse code paths.
    """
    if ResourceRolePermission.objects.filter(resource__urn__startswith="perf:").exists():
        print("  Resource role permissions already exist — skipping.")
        return

    print("  Setting up resource role permissions...")
    t0 = time.time()
    perm_read = Permission.objects.get(code="read")
    perm_view = Permission.objects.get(code="view")
    role_owner = Role.objects.get(code="owner")

    # Build domain → root custom roles map for quick lookup.
    domain_roles = {str(root.id): roles_by_root[str(root.id)] for root in root_domains if str(root.id) in roles_by_root}
    domain_id_by_resource = dict(
        Resource.objects.filter(id__in=root_resource_ids).values_list("id", "domain_id")
    )
    # Look up root_id for each domain.
    domain_root_map = {
        str(d.id): str(d.root_id) for d in Domain.objects.filter(
            id__in=set(domain_id_by_resource.values())
        )
    }

    # Grant owner+viewer roles read+view permission on every 20th root resource.
    rrp_batch = []
    rp_batch = []
    sample = root_resource_ids[::20]
    for resource_id in sample:
        domain_id = str(domain_id_by_resource.get(resource_id, ""))
        root_id = domain_root_map.get(domain_id, "")
        custom_roles = domain_roles.get(root_id, [])
        rrp_batch.append(ResourceRolePermission(
            id=uuid.uuid4(),
            resource_id=resource_id,
            role=role_owner,
            permission=perm_read,
        ))
        if custom_roles:
            role_viewer = custom_roles[0]
            rrp_batch.append(ResourceRolePermission(
                id=uuid.uuid4(),
                resource_id=resource_id,
                role=role_viewer,
                permission=perm_view,
            ))

    # Block inheritance on every 50th root resource.
    for resource_id in root_resource_ids[::50]:
        rp_batch.append(ResourcePermission(
            resource_id=resource_id,
            permission=perm_read,
            inherit=False,
        ))

    ResourceRolePermission.objects.bulk_create(rrp_batch, ignore_conflicts=True, batch_size=BULK_BATCH)
    ResourcePermission.objects.bulk_create(rp_batch, ignore_conflicts=True, batch_size=BULK_BATCH)
    print(f"  Resource permissions done in {time.time() - t0:.1f}s "
          f"({len(rrp_batch):,} RRP, {len(rp_batch):,} RP).")


def setup_user_resource_roles(
    root_resource_ids: list,
    user_ids: list[str],
    roles_by_root: dict[str, list],
    root_domains: list,
) -> None:
    """Assign users to a sample of root resources with the owner role.

    One user per resource on every 10th root resource — these are the
    resource-level role holders exercised by the resource access-check scenario.
    """
    if UserResourceRole.objects.filter(user__username__startswith="perfuser").exists():
        print("  User resource roles already exist — skipping.")
        return

    print("  Assigning users to resources...")
    t0 = time.time()
    role_owner = Role.objects.get(code="owner")
    num_users = len(user_ids)

    domain_id_by_resource = dict(
        Resource.objects.filter(id__in=root_resource_ids).values_list("id", "domain_id")
    )
    domain_root_map = {
        str(d.id): str(d.root_id) for d in Domain.objects.filter(
            id__in=set(domain_id_by_resource.values())
        )
    }
    domain_roles = {str(root.id): roles_by_root[str(root.id)] for root in root_domains if str(root.id) in roles_by_root}

    batch = []
    # Every 10th root resource gets an explicit owner assignment.
    for k, resource_id in enumerate(root_resource_ids[::10]):
        batch.append(UserResourceRole(
            id=uuid.uuid4(),
            user_id=user_ids[k % num_users],
            resource_id=resource_id,
            role=role_owner,
        ))
        # Also assign the matching custom viewer where available.
        domain_id = str(domain_id_by_resource.get(resource_id, ""))
        root_id = domain_root_map.get(domain_id, "")
        custom_roles = domain_roles.get(root_id, [])
        if custom_roles:
            role_viewer = custom_roles[0]
            batch.append(UserResourceRole(
                id=uuid.uuid4(),
                user_id=user_ids[(k + 1) % num_users],
                resource_id=resource_id,
                role=role_viewer,
            ))
        if len(batch) >= BULK_BATCH:
            UserResourceRole.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        UserResourceRole.objects.bulk_create(batch, ignore_conflicts=True)
    print(f"  User resource roles done in {time.time() - t0:.1f}s.")


# ---------------------------------------------------------------------------
# Load test data (for the run command)
# ---------------------------------------------------------------------------

def load_test_data() -> TestData:
    """Query the database and build the TestData structure needed by scenarios."""
    print("  Loading test data from database...")
    t0 = time.time()
    data = TestData()

    # Users.
    data.user_ids = [
        str(uid)
        for uid in User.objects.filter(username__startswith="perfuser")
        .order_by("username")
        .values_list("id", flat=True)
    ]

    # Domain checker pairs: users with access_checker role.
    role_access_checker = Role.objects.get(code="access_checker")
    data.domain_checker_pairs = [
        (str(domain_id), str(user_id))
        for user_id, domain_id in UserDomainRole.objects.filter(role=role_access_checker)
        .values_list("user_id", "domain_id")
    ]

    # Domain owner pairs: users with owner role on root domains.
    role_owner = Role.objects.get(code="owner")
    data.domain_owner_pairs = [
        (str(domain_id), str(user_id))
        for user_id, domain_id in UserDomainRole.objects.filter(
            role=role_owner, domain__title__startswith="perf-root-"
        ).values_list("user_id", "domain_id")
    ]

    # Child and grandchild domain IDs.
    data.child_domain_ids = [
        str(did)
        for did in Domain.objects.filter(title__startswith="perf-child-")
        .values_list("id", flat=True)
    ]
    data.grandchild_domain_ids = [
        str(did)
        for did in Domain.objects.filter(title__startswith="perf-grand-")
        .values_list("id", flat=True)
    ]

    # Resource checker pairs: root resources where a user has an explicit role.
    # The checker is the domain owner (who has check_access on the domain).
    root_checker_map = dict(data.domain_checker_pairs)
    resource_checker_pairs = []
    for resource_id, domain_id in (
        Resource.objects.filter(urn__startswith="perf:root:", parent__isnull=True)
        .select_related("domain")
        .values_list("id", "domain_id")[:5000]
    ):
        checker = root_checker_map.get(str(domain_id))
        if checker:
            resource_checker_pairs.append((str(resource_id), checker))
    data.resource_checker_pairs = resource_checker_pairs

    # Deep resource IDs: child resources paired with a domain owner for access checks.
    owner_map = {domain_id: user_id for domain_id, user_id in data.domain_owner_pairs}
    deep_pairs = []
    for resource_id, domain_id in (
        Resource.objects.filter(urn__startswith="perf:child:", parent__isnull=False)
        .values_list("id", "domain_id")[:2000]
    ):
        owner = owner_map.get(str(domain_id))
        if owner:
            deep_pairs.append((str(resource_id), owner))
    data.deep_resource_ids = deep_pairs

    print(f"  Loaded in {time.time() - t0:.1f}s: {len(data.user_ids):,} users, "
          f"{len(data.domain_checker_pairs):,} domain checkers, "
          f"{len(data.resource_checker_pairs):,} resource checkers.")
    return data


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _make_client(base_url: str, concurrency: int) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_connections=concurrency + 20,
        max_keepalive_connections=concurrency,
    )
    timeout = httpx.Timeout(15.0, connect=5.0)
    return httpx.AsyncClient(base_url=base_url, limits=limits, timeout=timeout)


async def _get(client: httpx.AsyncClient, path: str, api_key: str) -> tuple[float, int]:
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    try:
        response = await client.get(path, headers={"X-Auth": api_key})
        return (loop.time() - t0) * 1000, response.status_code
    except Exception:
        return (loop.time() - t0) * 1000, 0


async def _post(client: httpx.AsyncClient, path: str, api_key: str, body: dict) -> tuple[float, int, str]:
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    try:
        response = await client.post(path, json=body, headers={"X-Auth": api_key})
        data = response.json() if response.status_code < 400 else {}
        return (loop.time() - t0) * 1000, response.status_code, data.get("id", "")
    except Exception:
        return (loop.time() - t0) * 1000, 0, ""


async def _delete(client: httpx.AsyncClient, path: str, api_key: str) -> tuple[float, int]:
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    try:
        response = await client.delete(path, headers={"X-Auth": api_key})
        return (loop.time() - t0) * 1000, response.status_code
    except Exception:
        return (loop.time() - t0) * 1000, 0


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------

async def _run_with_semaphore(
    tasks: list,
    concurrency: int,
) -> list[tuple[float, int]]:
    """Run tasks concurrently up to concurrency limit; return (latency, status) pairs."""
    semaphore = asyncio.Semaphore(concurrency)
    results = []

    async def bounded(coro):
        async with semaphore:
            result = await coro
            results.append(result)

    await asyncio.gather(*[bounded(t) for t in tasks])
    return results


# ---------------------------------------------------------------------------
# Scenario 1: domain access checks
# ---------------------------------------------------------------------------

async def run_domain_access_checks(base_url: str, data: TestData, concurrency: int) -> None:
    """Fire access-check requests across many (checker, domain, permission) permutations.

    Covers:
    - All 7 system permissions
    - Root, child, and grandchild domain depths
    - Callers with access_checker role (200 OK expected)
    - Random users as subjects (result varies by role)
    - Inheritance-blocked child domains
    """
    if not data.domain_checker_pairs:
        print("  No domain checker pairs available — skipping domain access checks.")
        return

    print("\n  Building domain access-check task list...")
    tasks = []
    checker_pairs = data.domain_checker_pairs
    num_checkers = len(checker_pairs)
    num_users = len(data.user_ids)
    all_domain_ids = (
        [p[0] for p in data.domain_checker_pairs]
        + data.child_domain_ids
        + data.grandchild_domain_ids
    )
    num_domains = len(all_domain_ids)

    async def check(client, checker_user_id, subject_user_id, domain_id, permission):
        path = f"/access/domain/permission/{subject_user_id}/{domain_id}/{permission}"
        return await _get(client, path, checker_user_id)

    async with _make_client(base_url, concurrency) as client:
        for i in range(5000):
            domain_id, checker_user_id = checker_pairs[i % num_checkers]
            subject_user_id = data.user_ids[i % num_users]
            permission = SYSTEM_PERMISSIONS[i % len(SYSTEM_PERMISSIONS)]
            tasks.append(check(client, checker_user_id, subject_user_id, domain_id, permission))

        # Also check on child and grandchild domains (exercises inheritance traversal).
        for i in range(2000):
            domain_id = all_domain_ids[(i * 7) % num_domains]
            checker_user_id = checker_pairs[i % num_checkers][1]
            subject_user_id = data.user_ids[(i * 3) % num_users]
            permission = SYSTEM_PERMISSIONS[i % len(SYSTEM_PERMISSIONS)]
            tasks.append(check(client, checker_user_id, subject_user_id, domain_id, permission))

        print(f"  Firing {len(tasks):,} domain access-check requests (concurrency={concurrency})...")
        t0 = time.time()
        results = await _run_with_semaphore(tasks, concurrency)

    latencies = [r[0] for r in results]
    statuses = [r[1] for r in results]
    elapsed = time.time() - t0
    print_results("Domain Access Checks", latencies, statuses, elapsed)


# ---------------------------------------------------------------------------
# Scenario 2: resource access checks
# ---------------------------------------------------------------------------

async def run_resource_access_checks(base_url: str, data: TestData, concurrency: int) -> None:
    """Fire access-check requests across (checker, resource, permission) permutations.

    Covers:
    - Root resources (permission check can stop at resource level)
    - Child resources (must traverse up to parent resource, then domain)
    - Resources with inherit=False blocks
    - Domains with and without explicit resource role permissions
    """
    if not data.resource_checker_pairs:
        print("  No resource checker pairs available — skipping resource access checks.")
        return

    all_resource_pairs = data.resource_checker_pairs + data.deep_resource_ids
    num_pairs = len(all_resource_pairs)
    num_users = len(data.user_ids)

    async def check(client, checker_user_id, subject_user_id, resource_id, permission):
        path = f"/access/resource/permission/{subject_user_id}/{resource_id}/{permission}"
        return await _get(client, path, checker_user_id)

    async with _make_client(base_url, concurrency) as client:
        tasks = []
        for i in range(4000):
            resource_id, checker_user_id = all_resource_pairs[i % num_pairs]
            subject_user_id = data.user_ids[i % num_users]
            permission = SYSTEM_PERMISSIONS[i % len(SYSTEM_PERMISSIONS)]
            tasks.append(check(client, checker_user_id, subject_user_id, resource_id, permission))

        print(f"  Firing {len(tasks):,} resource access-check requests (concurrency={concurrency})...")
        t0 = time.time()
        results = await _run_with_semaphore(tasks, concurrency)

    latencies = [r[0] for r in results]
    statuses = [r[1] for r in results]
    elapsed = time.time() - t0
    print_results("Resource Access Checks", latencies, statuses, elapsed)


# ---------------------------------------------------------------------------
# Scenario 3: mixed read/write
# ---------------------------------------------------------------------------

async def run_mixed_read_write(
    base_url: str, data: TestData, concurrency: int, duration: int
) -> None:
    """Run concurrent workers for `duration` seconds, each picking a random action.

    Action mix:
    - 40%  GET domain  (read, exercises DB + cache hits)
    - 15%  GET resource (read)
    - 20%  GET access/domain/permission (access check, exercises recursive tree)
    - 10%  POST userdomainrole + DELETE (role mutation → cache invalidation)
    - 10%  POST resource (create, exercises counter-cache increment)
    - 5%   GET /domain list (paginated list)
    """
    if not data.domain_checker_pairs or not data.domain_owner_pairs:
        print("  Insufficient test data for mixed scenario — skipping.")
        return

    num_users = len(data.user_ids)
    num_checker_pairs = len(data.domain_checker_pairs)
    num_owner_pairs = len(data.domain_owner_pairs)
    num_resource_pairs = max(len(data.resource_checker_pairs), 1)

    action_latencies: dict[str, list[float]] = collections.defaultdict(list)
    action_statuses: dict[str, list[int]] = collections.defaultdict(list)
    stop_event = asyncio.Event()

    async def action_read_domain(client: httpx.AsyncClient, idx: int) -> tuple[str, float, int]:
        domain_id, checker = data.domain_checker_pairs[idx % num_checker_pairs]
        latency, status = await _get(client, f"/domain/{domain_id}", checker)
        return "GET /domain/{id}", latency, status

    async def action_read_resource(client: httpx.AsyncClient, idx: int) -> tuple[str, float, int]:
        if not data.resource_checker_pairs:
            return "GET /resource/{id}", 0, 0
        resource_id, checker = data.resource_checker_pairs[idx % num_resource_pairs]
        latency, status = await _get(client, f"/resource/{resource_id}", checker)
        return "GET /resource/{id}", latency, status

    async def action_access_check(client: httpx.AsyncClient, idx: int) -> tuple[str, float, int]:
        domain_id, checker = data.domain_checker_pairs[idx % num_checker_pairs]
        subject = data.user_ids[idx % num_users]
        permission = SYSTEM_PERMISSIONS[idx % len(SYSTEM_PERMISSIONS)]
        path = f"/access/domain/permission/{subject}/{domain_id}/{permission}"
        latency, status = await _get(client, path, checker)
        return "GET /access/domain/permission", latency, status

    async def action_mutate_role(client: httpx.AsyncClient, idx: int) -> tuple[str, float, int]:
        # Assign a role then immediately revoke it — exercises cache invalidation.
        domain_id, owner = data.domain_owner_pairs[idx % num_owner_pairs]
        subject = data.user_ids[(idx * 7) % num_users]
        body = {"user": subject, "domain": domain_id, "role": "manager"}
        create_latency, create_status, udr_id = await _post(client, "/userdomainrole", owner, body)
        if udr_id:
            await _delete(client, f"/userdomainrole/{udr_id}", owner)
        return "POST+DELETE /userdomainrole", create_latency, create_status

    async def action_create_resource(client: httpx.AsyncClient, idx: int) -> tuple[str, float, int]:
        domain_id, owner = data.domain_owner_pairs[idx % num_owner_pairs]
        urn = f"perf:mixed:{uuid.uuid4().hex}"
        body = {"domain": domain_id, "urn": urn}
        latency, status, _ = await _post(client, "/resource", owner, body)
        return "POST /resource", latency, status

    async def action_list_domains(client: httpx.AsyncClient, idx: int) -> tuple[str, float, int]:
        _, checker = data.domain_checker_pairs[idx % num_checker_pairs]
        latency, status = await _get(client, "/domain?page=1", checker)
        return "GET /domain (list)", latency, status

    # Weighted action table: (action_fn, weight).
    actions = [
        (action_read_domain, 40),
        (action_read_resource, 15),
        (action_access_check, 20),
        (action_mutate_role, 10),
        (action_create_resource, 10),
        (action_list_domains, 5),
    ]
    action_fns = [a[0] for a in actions]
    weights = [a[1] for a in actions]

    async def worker(client: httpx.AsyncClient) -> None:
        idx = random.randint(0, 10_000)
        while not stop_event.is_set():
            action_fn = random.choices(action_fns, weights=weights)[0]
            try:
                name, latency, status = await action_fn(client, idx)
                action_latencies[name].append(latency)
                action_statuses[name].append(status)
            except Exception:
                pass
            idx += 1

    async def _set_stop() -> None:
        await asyncio.sleep(duration)
        stop_event.set()

    print(f"\n  Mixed read/write: {concurrency} workers for {duration}s...")
    t0 = time.time()
    async with _make_client(base_url, concurrency) as client:
        worker_tasks = [asyncio.create_task(worker(client)) for _ in range(concurrency)]
        await asyncio.gather(asyncio.create_task(_set_stop()), *worker_tasks)
    elapsed = time.time() - t0

    # Print per-action results then an aggregate.
    all_latencies = []
    all_statuses = []
    for action_name in sorted(action_latencies):
        lats = action_latencies[action_name]
        stats = action_statuses[action_name]
        all_latencies.extend(lats)
        all_statuses.extend(stats)
        print_results(f"Mixed — {action_name}", lats, stats, elapsed)

    print_results("Mixed Read/Write (aggregate)", all_latencies, all_statuses, elapsed)


# ---------------------------------------------------------------------------
# Scenario 4: listing stress
# ---------------------------------------------------------------------------

async def run_listing_stress(base_url: str, data: TestData, concurrency: int) -> None:
    """Hammer paginated and unpaginated list endpoints.

    Deliberately hits GET /userresourcerole (no pagination) to expose
    its O(n) response size problem at scale.
    """
    if not data.domain_checker_pairs:
        print("  No checker pairs available — skipping listing stress.")
        return

    num_checker_pairs = len(data.domain_checker_pairs)

    async def list_domains(client, i):
        page = (i % 5) + 1
        _, checker = data.domain_checker_pairs[i % num_checker_pairs]
        return await _get(client, f"/domain?page={page}", checker)

    async def list_roles(client, i):
        _, checker = data.domain_checker_pairs[i % num_checker_pairs]
        return await _get(client, "/role", checker)

    async def list_userdomainroles(client, i):
        _, checker = data.domain_checker_pairs[i % num_checker_pairs]
        return await _get(client, "/userdomainrole", checker)

    async def list_domainrolepermissions(client, i):
        domain_id, checker = data.domain_checker_pairs[i % num_checker_pairs]
        return await _get(client, f"/domainrolepermission?domain={domain_id}", checker)

    async def list_userresourceroles(client, i):
        # No pagination — will expose scaling problem at large datasets.
        _, checker = data.domain_checker_pairs[i % num_checker_pairs]
        return await _get(client, "/userresourcerole", checker)

    scenarios = [
        ("GET /domain (paginated)", list_domains, 500),
        ("GET /role (list)", list_roles, 200),
        ("GET /userdomainrole (list)", list_userdomainroles, 300),
        ("GET /domainrolepermission (filtered)", list_domainrolepermissions, 300),
        ("GET /userresourcerole (no pagination)", list_userresourceroles, 100),
    ]

    async with _make_client(base_url, concurrency) as client:
        for name, fn, count in scenarios:
            tasks = [fn(client, i) for i in range(count)]
            print(f"  Firing {count} × {name}...")
            t0 = time.time()
            results = await _run_with_semaphore(tasks, concurrency)
            elapsed = time.time() - t0
            latencies = [r[0] for r in results]
            statuses = [r[1] for r in results]
            print_results(name, latencies, statuses, elapsed)


# ---------------------------------------------------------------------------
# Subcommand: setup
# ---------------------------------------------------------------------------

def cmd_setup(args) -> None:
    print("\n=== SETUP PHASE ===")
    print(f"  Database  : {os.environ['DATABASE_URL']}")

    print("\n[1/7] Users")
    user_ids = setup_users(args.users)
    if not user_ids:
        print("ERROR: no users available.")
        sys.exit(1)

    print("\n[2/7] Domains")
    root_domains, child_domains, grandchild_domains = setup_domains(args.domains, user_ids)

    print("\n[3/7] Custom roles and permissions")
    roles_by_root = setup_custom_roles(root_domains)

    print("\n[4/7] User-domain-role assignments")
    setup_additional_user_domain_roles(
        root_domains, child_domains, grandchild_domains, user_ids, roles_by_root
    )

    print("\n[5/7] Resources")
    root_resource_ids, _ = setup_resources(
        root_domains, child_domains, user_ids, args.resources
    )

    print("\n[6/7] Resource role permissions")
    setup_resource_permissions(root_resource_ids, root_domains, roles_by_root)

    print("\n[7/7] User resource roles")
    setup_user_resource_roles(root_resource_ids, user_ids, roles_by_root, root_domains)

    print("\n=== SETUP COMPLETE ===")


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------

def cmd_run(args) -> None:
    print("\n=== LOAD TEST ===")
    print(f"  Base URL   : {args.base_url}")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  Duration   : {args.duration}s (mixed scenario)")

    data = load_test_data()
    if not data.user_ids:
        print("ERROR: no perf test data found. Run 'setup' first.")
        sys.exit(1)

    asyncio.run(_run_all_scenarios(args.base_url, data, args.concurrency, args.duration))

    print("\n=== DONE ===")


async def _run_all_scenarios(
    base_url: str, data: TestData, concurrency: int, duration: int
) -> None:
    print("\n--- Scenario 1: Domain Access Checks ---")
    await run_domain_access_checks(base_url, data, concurrency)

    print("\n--- Scenario 2: Resource Access Checks ---")
    await run_resource_access_checks(base_url, data, concurrency)

    print("\n--- Scenario 3: Mixed Read/Write ---")
    await run_mixed_read_write(base_url, data, concurrency, duration)

    print("\n--- Scenario 4: Listing Stress ---")
    await run_listing_stress(base_url, data, concurrency)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dominion performance load test.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Setup subcommand.
    setup_parser = subparsers.add_parser("setup", help="Create test data in the database.")
    setup_parser.add_argument("--users", type=int, default=50_000, help="Number of users to create.")
    setup_parser.add_argument("--domains", type=int, default=200, help="Number of root domains to create.")
    setup_parser.add_argument("--resources", type=int, default=1_000_000, help="Total resources to create.")

    # Run subcommand.
    run_parser = subparsers.add_parser("run", help="Run load scenarios against a live server.")
    run_parser.add_argument("--base-url", default="http://localhost:8090/api/v1.0", help="API base URL.")
    run_parser.add_argument("--concurrency", type=int, default=100, help="Concurrent workers/requests.")
    run_parser.add_argument("--duration", type=int, default=60, help="Duration (seconds) for mixed scenario.")

    # All subcommand.
    all_parser = subparsers.add_parser("all", help="Run setup then run.")
    all_parser.add_argument("--users", type=int, default=50_000)
    all_parser.add_argument("--domains", type=int, default=200)
    all_parser.add_argument("--resources", type=int, default=1_000_000)
    all_parser.add_argument("--base-url", default="http://localhost:8090/api/v1.0")
    all_parser.add_argument("--concurrency", type=int, default=100)
    all_parser.add_argument("--duration", type=int, default=60)

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "all":
        cmd_setup(args)
        cmd_run(args)


if __name__ == "__main__":
    main()
