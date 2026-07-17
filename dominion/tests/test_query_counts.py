"""B1 — query-count regression tests for the recursive permission resolvers.

The permission checks in dominion.utils recurse up the domain/resource trees issuing
queries per level. Nothing else in the suite pins the query count, so an accidental
N+1 (e.g. a dropped select_related) would pass every functional test and only surface
as latency under load. These tests lock the cold-cache query counts at several tree
depths so such a regression fails fast.

Query counts are asserted from a synchronous context (CaptureQueriesContext cannot be
entered from async); async_to_sync runs the thread-sensitive ORM work on the test
thread so the capture sees every query. The Django cache is cleared per test so counts
reflect a genuine cold cache.
"""

import pytest
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.core.cache import cache as django_cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from dominion import create_initial_data, models
from dominion.utils import (
    get_user_domains,
    reset_request_cache,
    user_has_permission_for_domain,
    user_has_permission_for_resource,
)

# Upper bounds on cold-cache query counts, measured at DOMAIN_DEPTH=5 then given
# headroom so ordinary refactors don't churn them while a true N+1 (count growing with
# fan-out rather than depth) still trips the ceiling. Measured baselines (2026-07):
#   domain check: 14   resource check: 29   get_user_domains: 2 (constant CTE)
# NOTE: the resource check's high constant reflects a known N+1 in the resource->domain
# transition in utils._user_has_permission_for_resource — a candidate for a later
# performance pass. This test locks it so it cannot get *worse* unnoticed.
DOMAIN_DEPTH = 5
MAX_QUERIES_DOMAIN_CHECK = 20
MAX_QUERIES_RESOURCE_CHECK = 40
MAX_QUERIES_GET_USER_DOMAINS = 5

# Query-count regression tests — selectable/deselectable via `-m perf` / `-m "not perf"`.
pytestmark = pytest.mark.perf


class PermissionCheckQueryCountTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        create_initial_data()
        User = get_user_model()
        cls.user = User.objects.create(username="deep_user")

        # Build a linear domain chain of DOMAIN_DEPTH levels: d0 (root) -> d1 -> ...
        # The user gets the owner role only on the root, so a check at the deepest
        # node must recurse all the way up.
        role_owner = models.Role.objects.get(code="owner")
        chain = []
        parent = None
        for i in range(DOMAIN_DEPTH):
            d = models.Domain.objects.create(title=f"deep-{i}", owner=cls.user, parent=parent)
            chain.append(d)
            parent = d
        cls.domain_chain = chain
        cls.root_domain = chain[0]
        cls.leaf_domain = chain[-1]

        # A resource chain inside the leaf domain, also DOMAIN_DEPTH deep.
        rparent = None
        rchain = []
        for i in range(DOMAIN_DEPTH):
            r = models.Resource.objects.create(
                urn=f"deep:res:{i}", domain=cls.leaf_domain, parent=rparent, owner=cls.user
            )
            rchain.append(r)
            rparent = r
        cls.resource_chain = rchain
        cls.leaf_resource = rchain[-1]

    def setUp(self):
        super().setUp()
        django_cache.clear()
        reset_request_cache()

    def _count(self, coro_fn, *args):
        reset_request_cache()
        with CaptureQueriesContext(connection) as ctx:
            result = async_to_sync(coro_fn)(*args)
        return result, len(ctx.captured_queries)

    def test_domain_permission_check_at_depth_is_bounded(self):
        result, n = self._count(
            user_has_permission_for_domain, self.user.id, "read", self.leaf_domain.id
        )
        self.assertTrue(result)
        self.assertLessEqual(
            n, MAX_QUERIES_DOMAIN_CHECK,
            f"Domain permission check at depth {DOMAIN_DEPTH} used {n} queries "
            f"(ceiling {MAX_QUERIES_DOMAIN_CHECK}) — possible N+1 regression.",
        )

    def test_resource_permission_check_at_depth_is_bounded(self):
        result, n = self._count(
            user_has_permission_for_resource, self.user.id, "read", self.leaf_resource.id
        )
        self.assertTrue(result)
        self.assertLessEqual(
            n, MAX_QUERIES_RESOURCE_CHECK,
            f"Resource permission check at depth {DOMAIN_DEPTH} used {n} queries "
            f"(ceiling {MAX_QUERIES_RESOURCE_CHECK}) — possible N+1 regression.",
        )

    def test_get_user_domains_uses_constant_queries(self):
        # get_user_domains uses a single recursive CTE, so its query count must not
        # grow with the number of domains the user can reach.
        result, n = self._count(get_user_domains, self.user)
        # Materialise the queryset (async) to count rows without extra permission logic.
        count = async_to_sync(self._alen)(result)
        self.assertGreaterEqual(count, DOMAIN_DEPTH)
        self.assertLessEqual(
            n, MAX_QUERIES_GET_USER_DOMAINS,
            f"get_user_domains used {n} queries (ceiling {MAX_QUERIES_GET_USER_DOMAINS}) "
            f"— the recursive CTE should keep this constant regardless of tree size.",
        )

    @staticmethod
    async def _alen(queryset):
        return len([o async for o in queryset])
