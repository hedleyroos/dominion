from asgiref.sync import async_to_sync, sync_to_async
from django.db import connection
from django.test.utils import CaptureQueriesContext

from dominion.tests.base import BaseTestCase
from dominion import models
from dominion.utils import (
    domain_has_permission_for_role,
    domain_roles_permissions_mapping,
    domain_roles_permissions_mapping_sync,
    get_domain_permissions,
    get_domain_roles,
    get_resource_permissions,
    get_resource_roles,
    get_user_domains,
    get_user_domains_sync,
    invalidate_rules_permissions,
    invalidate_user_permissions,
    reset_request_cache,
    resource_roles_permissions_mapping,
    resource_roles_permissions_mapping_sync,
    user_has_permission_for_domain,
    user_has_role_for_domain,
)


class UserHasRoleForDomainTestCase(BaseTestCase):
    async def test_owner_has_owner_role_on_domaina(self):
        self.assertTrue(await user_has_role_for_domain(self.owner.id, "owner", self.domaina.id))

    async def test_owner_has_owner_role_inherited_by_child_domain(self):
        # Owner owns domaina; domainaa is a child of domaina.
        # user_has_role_for_domain checks direct role then recurses to parent.
        self.assertTrue(await user_has_role_for_domain(self.owner.id, "owner", self.domainaa.id))

    async def test_jan_does_not_have_owner_role(self):
        self.assertFalse(await user_has_role_for_domain(self.jan.id, "owner", self.domaina.id))

    async def test_unknown_user_has_no_role(self):
        import uuid
        self.assertFalse(await user_has_role_for_domain(uuid.uuid4(), "owner", self.domaina.id))


class DomainHasPermissionForRoleTestCase(BaseTestCase):
    async def test_manager_has_read_on_domaina(self):
        self.assertTrue(await domain_has_permission_for_role(self.domaina.id, "read", "manager"))

    async def test_manager_does_not_have_delete_on_domaina(self):
        # Manager only gets delete if explicitly set (which is not the case on domaina root).
        self.assertFalse(await domain_has_permission_for_role(self.domaina.id, "delete", "manager"))

    async def test_manager_has_delete_on_domainab_explicitly(self):
        # domainab has DomainRolePermission(role=manager, permission=delete) set in BaseTestCase.
        self.assertTrue(await domain_has_permission_for_role(self.domainab.id, "delete", "manager"))

    async def test_child_inherits_parent_permission(self):
        # domainaa is a child of domaina; manager has read on domaina; should inherit.
        self.assertTrue(await domain_has_permission_for_role(self.domainaa.id, "read", "manager"))

    async def test_unknown_role_returns_none(self):
        result = await domain_has_permission_for_role(self.domaina.id, "read", "nonexistent_role")
        # No role-permission mapping exists; traversal reaches root with no parent → returns None.
        self.assertFalse(result)


class GetUserDomainsTestCase(BaseTestCase):
    async def test_owner_has_domains(self):
        domains = await get_user_domains(self.owner)
        domain_ids = [d.id async for d in domains]
        self.assertIn(self.domaina.id, domain_ids)

    async def test_owner_domains_include_descendants(self):
        # domaina is owner's root domain; its children (domainaa, domainab, domainaaa)
        # should also appear because get_user_domains recurses downward.
        domains = await get_user_domains(self.owner)
        domain_ids = [d.id async for d in domains]
        self.assertIn(self.domainaa.id, domain_ids)
        self.assertIn(self.domainab.id, domain_ids)

    async def test_user_with_no_domain_roles_gets_empty_queryset(self):
        # Create a fresh user with no domain roles.
        from django.contrib.auth import get_user_model
        User = get_user_model()
        no_role_user = await User.objects.acreate(
            username="no_domain_role_user", email="ndr@test.com"
        )
        domains = await get_user_domains(no_role_user)
        count = await domains.acount()
        self.assertEqual(count, 0)


class GetDomainRolesTestCase(BaseTestCase):
    async def test_domaina_has_default_roles(self):
        # DomainManager.create sets up authenticated, manager, owner, access_checker roles.
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        roles = await get_domain_roles(domain)
        codes = [r.code for r in roles]
        self.assertIn("manager", codes)
        self.assertIn("owner", codes)
        self.assertIn("authenticated", codes)
        self.assertIn("access_checker", codes)

    async def test_domaina_has_customviewer_role(self):
        # BaseTestCase adds customviewer role to domaina.
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        roles = await get_domain_roles(domain)
        codes = [r.code for r in roles]
        self.assertIn("customviewer", codes)

    async def test_roles_are_sorted_by_code(self):
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        roles = await get_domain_roles(domain)
        codes = [r.code for r in roles]
        self.assertEqual(codes, sorted(codes))


class GetDomainPermissionsTestCase(BaseTestCase):
    async def test_domaina_has_standard_permissions(self):
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        permissions = await get_domain_permissions(domain)
        codes = [p.code for p in permissions]
        self.assertIn("read", codes)
        self.assertIn("create", codes)
        self.assertIn("delete", codes)

    async def test_permissions_are_sorted_by_code(self):
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        permissions = await get_domain_permissions(domain)
        codes = [p.code for p in permissions]
        self.assertEqual(codes, sorted(codes))


class DomainRolesPermissionsMappingTestCase(BaseTestCase):
    async def test_mapping_returns_list(self):
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        mapping = await domain_roles_permissions_mapping(domain)
        self.assertIsInstance(mapping, list)

    async def test_each_row_starts_with_permission(self):
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        mapping = await domain_roles_permissions_mapping(domain)
        for row in mapping:
            self.assertIsInstance(row[0], models.Permission)

    async def test_row_cells_contain_role_and_active_flag(self):
        domain = await models.Domain.objects.aget(id=self.domaina.id)
        mapping = await domain_roles_permissions_mapping(domain)
        for row in mapping:
            for cell in row[1:]:
                self.assertIn("role", cell)
                self.assertIn("active", cell)
                self.assertIn("permission", cell)


class GetResourceRolesTestCase(BaseTestCase):
    async def test_resource_includes_domain_roles(self):
        resource = await models.Resource.objects.select_related("domain").aget(
            id=self.domaina_resourcea.id
        )
        roles = await get_resource_roles(resource)
        codes = [r.code for r in roles]
        # Domain roles should bubble up.
        self.assertIn("owner", codes)

    async def test_roles_are_sorted_by_code(self):
        resource = await models.Resource.objects.select_related("domain").aget(
            id=self.domaina_resourcea.id
        )
        roles = await get_resource_roles(resource)
        codes = [r.code for r in roles]
        self.assertEqual(codes, sorted(codes))


class GetResourcePermissionsTestCase(BaseTestCase):
    async def test_resource_includes_domain_permissions(self):
        resource = await models.Resource.objects.select_related("domain").aget(
            id=self.domaina_resourcea.id
        )
        permissions = await get_resource_permissions(resource)
        codes = [p.code for p in permissions]
        self.assertIn("read", codes)

    async def test_permissions_are_sorted_by_code(self):
        resource = await models.Resource.objects.select_related("domain").aget(
            id=self.domaina_resourcea.id
        )
        permissions = await get_resource_permissions(resource)
        codes = [p.code for p in permissions]
        self.assertEqual(codes, sorted(codes))


class ResourceRolesPermissionsMappingTestCase(BaseTestCase):
    async def test_mapping_returns_list(self):
        resource = await models.Resource.objects.select_related("domain").aget(
            id=self.domaina_resourcea.id
        )
        mapping = await resource_roles_permissions_mapping(resource)
        self.assertIsInstance(mapping, list)

    async def test_each_row_starts_with_permission(self):
        resource = await models.Resource.objects.select_related("domain").aget(
            id=self.domaina_resourcea.id
        )
        mapping = await resource_roles_permissions_mapping(resource)
        for row in mapping:
            self.assertIsInstance(row[0], models.Permission)


class CrossRequestCacheTestCase(BaseTestCase):
    """P3.1 — cross-request permission cache actually caches, and invalidation forces recompute.

    Each logical "request" is delineated with reset_request_cache(), mirroring the
    per-request context isolation that main.py's middleware provides in production.
    django_assert_num_queries proves cache hits avoid the database entirely.
    """

    def setUp(self):
        super().setUp()
        # LocMemCache is process-global; clear it so query-count assertions are not
        # contaminated by cached results from other tests.
        from django.core.cache import cache as django_cache
        django_cache.clear()
        reset_request_cache()

    # These tests assert exact DB query counts, which CaptureQueriesContext can only
    # do from a synchronous context. Each async_to_sync() call runs the thread-sensitive
    # ORM work on the test thread (so the query capture sees it) and constitutes one
    # logical "request" — its request-scoped cache does not leak to the next call.

    def _check(self, user_id, perm, domain_id):
        return async_to_sync(user_has_permission_for_domain)(user_id, perm, domain_id)

    def test_cold_call_hits_db(self):
        with CaptureQueriesContext(connection) as ctx:
            result = self._check(self.owner.id, "read", self.domaina.id)
        self.assertTrue(result)
        self.assertGreater(len(ctx.captured_queries), 0)

    def test_cross_request_cache_hit_avoids_db(self):
        # First request populates the Django cache.
        self._check(self.owner.id, "read", self.domaina.id)
        # Second request: with a fresh request-scoped cache the result must still
        # resolve from the Django cache without touching the database.
        reset_request_cache()
        with CaptureQueriesContext(connection) as ctx:
            result = self._check(self.owner.id, "read", self.domaina.id)
        self.assertTrue(result)
        self.assertEqual(len(ctx.captured_queries), 0)

    def test_rules_invalidation_forces_recompute(self):
        self._check(self.owner.id, "read", self.domaina.id)
        async_to_sync(invalidate_rules_permissions)()
        # Next request must recompute (hit the DB again) rather than serve a stale hit.
        reset_request_cache()
        with CaptureQueriesContext(connection) as ctx:
            result = self._check(self.owner.id, "read", self.domaina.id)
        self.assertTrue(result)
        self.assertGreater(len(ctx.captured_queries), 0)

    def test_user_invalidation_forces_recompute(self):
        self._check(self.owner.id, "read", self.domaina.id)
        async_to_sync(invalidate_user_permissions)(str(self.owner.id))
        reset_request_cache()
        with CaptureQueriesContext(connection) as ctx:
            result = self._check(self.owner.id, "read", self.domaina.id)
        self.assertTrue(result)
        self.assertGreater(len(ctx.captured_queries), 0)

    def test_mutation_via_orm_invalidates_cache(self):
        """A6 — a rule change made outside the API (admin / host-project ORM) is reflected.

        jan has only the customviewer (read) role on domaina, so 'delete' is denied
        and that denial is cached. Granting customviewer the delete permission via a
        plain ORM create must fire the invalidation signal so the next request sees True.
        """
        self.assertFalse(self._check(self.jan.id, "delete", self.domaina.id))

        permission_delete = models.Permission.objects.get(code="delete")
        role_customviewer = models.Role.objects.get(code="customviewer")
        # Plain ORM create — no explicit invalidate_* call, exactly like admin_forms.
        models.DomainRolePermission.objects.create(
            domain=self.domaina, role=role_customviewer, permission=permission_delete
        )

        reset_request_cache()
        self.assertTrue(self._check(self.jan.id, "delete", self.domaina.id))


class RequestScopedCacheIsolationTestCase(BaseTestCase):
    """The request-scoped cache must not leak across request boundaries."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache as django_cache
        django_cache.clear()
        reset_request_cache()

    async def test_reset_clears_request_scoped_entries(self):
        from dominion.utils import _request_cache

        await user_has_permission_for_domain(self.owner.id, "read", self.domaina.id)
        # Something is cached for this context.
        self.assertIsNotNone(_request_cache.get())
        self.assertGreater(len(_request_cache.get()), 0)

        reset_request_cache()
        # After a reset the next access starts from an empty cache.
        self.assertIsNone(_request_cache.get())


class SyncUtilVariantsTestCase(BaseTestCase):
    """P3.5 — synchronous utility variants match the async equivalents."""

    def test_get_user_domains_sync_returns_owner_domains(self):
        domains = get_user_domains_sync(self.owner)
        domain_ids = [d.id for d in domains]
        self.assertIn(self.domaina.id, domain_ids)

    def test_get_user_domains_sync_includes_descendants(self):
        domains = get_user_domains_sync(self.owner)
        domain_ids = [d.id for d in domains]
        self.assertIn(self.domainaa.id, domain_ids)

    def test_get_user_domains_sync_empty_for_no_roles(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        new_user = User.objects.create(username="sync_test_user")
        domains = get_user_domains_sync(new_user)
        self.assertEqual(domains.count(), 0)

    def test_domain_roles_permissions_mapping_sync_returns_list(self):
        mapping = domain_roles_permissions_mapping_sync(self.domaina)
        self.assertIsInstance(mapping, list)
        self.assertGreater(len(mapping), 0)

    def test_domain_roles_permissions_mapping_sync_structure(self):
        mapping = domain_roles_permissions_mapping_sync(self.domaina)
        for row in mapping:
            self.assertIsInstance(row[0], models.Permission)
            for cell in row[1:]:
                self.assertIn("active", cell)
                self.assertIn("role", cell)

    def test_resource_roles_permissions_mapping_sync_returns_list(self):
        resource = models.Resource.objects.select_related("domain").get(id=self.domaina_resourcea.id)
        mapping = resource_roles_permissions_mapping_sync(resource)
        self.assertIsInstance(mapping, list)


class AsyncMatrixHelperParityTestCase(BaseTestCase):
    """A10 — the async matrix helpers (public API for embedded host projects) must
    traverse the parent chain without raising SynchronousOnlyOperation and must
    return the same roles/permissions as their sync counterparts.

    domainaaa is a grandchild (domainaaa -> domainaa -> domaina), so these calls
    exercise the multi-level async parent walk that previously crashed.
    """

    def _codes(self, objs):
        return sorted(o.code for o in objs)

    async def test_get_domain_roles_matches_sync_at_depth(self):
        from dominion.utils import _get_domain_roles_sync
        domain = await models.Domain.objects.select_related("parent").aget(id=self.domainaaa.id)
        async_roles = await get_domain_roles(domain)
        sync_roles = await sync_to_async(_get_domain_roles_sync)(domain)
        self.assertEqual(self._codes(async_roles), self._codes(sync_roles))

    async def test_get_domain_permissions_matches_sync_at_depth(self):
        from dominion.utils import _get_domain_permissions_sync
        domain = await models.Domain.objects.select_related("parent").aget(id=self.domainaaa.id)
        async_perms = await get_domain_permissions(domain)
        sync_perms = await sync_to_async(_get_domain_permissions_sync)(domain)
        self.assertEqual(self._codes(async_perms), self._codes(sync_perms))

    async def test_get_resource_roles_matches_sync_at_depth(self):
        from dominion.utils import _get_resource_roles_sync
        # domaina_resourceaa has a parent (domaina_resourcea), so this walks the
        # resource tree then transitions to the domain tree.
        resource = await models.Resource.objects.select_related("domain").aget(id=self.domaina_resourceaa.id)
        async_roles = await get_resource_roles(resource)
        sync_roles = await sync_to_async(_get_resource_roles_sync)(resource)
        self.assertEqual(self._codes(async_roles), self._codes(sync_roles))

    async def test_get_resource_permissions_matches_sync_at_depth(self):
        from dominion.utils import _get_resource_permissions_sync
        resource = await models.Resource.objects.select_related("domain").aget(id=self.domaina_resourceaa.id)
        async_perms = await get_resource_permissions(resource)
        sync_perms = await sync_to_async(_get_resource_permissions_sync)(resource)
        self.assertEqual(self._codes(async_perms), self._codes(sync_perms))

    async def test_mapping_helpers_run_at_depth(self):
        from dominion.utils import domain_roles_permissions_mapping
        domain = await models.Domain.objects.select_related("parent").aget(id=self.domainaaa.id)
        mapping = await domain_roles_permissions_mapping(domain)
        self.assertIsInstance(mapping, list)

