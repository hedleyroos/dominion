from dominion.tests.base import BaseTestCase
from dominion.serializers import (
    DomainSerializer,
    PermissionSerializer,
    ResourceSerializer,
    RoleSerializer,
    UserSerializer,
)


class DomainSerializerTestCase(BaseTestCase):
    async def test_async_representation(self):
        rep = await DomainSerializer(instance=self.domaina).ato_representation(self.domaina)
        self.assertEqual(rep["id"], str(self.domaina.id))
        self.assertEqual(rep["title"], "Domain A")
        self.assertIsNone(rep["parent"])

    def test_sync_representation(self):
        rep = DomainSerializer(instance=self.domainaa).to_representation(self.domainaa)
        self.assertEqual(rep["id"], str(self.domainaa.id))
        self.assertEqual(rep["title"], "Domain AA")
        self.assertEqual(str(rep["parent"]), str(self.domaina.id))


class UserSerializerTestCase(BaseTestCase):
    async def test_async_representation_includes_domains(self):
        # owner has at least one domain (domaina).
        rep = await UserSerializer(instance=self.owner).ato_representation(self.owner)
        self.assertIn("domains", rep)
        self.assertGreater(len(rep["domains"]), 0)
        domain_ids = [d["id"] for d in rep["domains"]]
        self.assertIn(str(self.domaina.id), domain_ids)

    async def test_async_representation_user_fields(self):
        rep = await UserSerializer(instance=self.owner).ato_representation(self.owner)
        self.assertEqual(rep["username"], self.owner.username)
        self.assertIn("email", rep)
        self.assertIn("api_key", rep)

    def test_sync_representation_omits_domains(self):
        rep = UserSerializer(instance=self.owner).to_representation(self.owner)
        self.assertEqual(rep["domains"], [])

    async def test_async_representation_no_domains_user(self):
        # Create a fresh user with no domain roles.
        from django.contrib.auth import get_user_model
        User = get_user_model()
        no_domain_user = await User.objects.acreate(
            username="no_domain_user", email="nd@test.com"
        )
        rep = await UserSerializer(instance=no_domain_user).ato_representation(no_domain_user)
        self.assertEqual(rep["domains"], [])


class RoleSerializerTestCase(BaseTestCase):
    async def test_async_representation(self):
        from dominion.models import Role
        role = await Role.objects.aget(code="manager")
        rep = await RoleSerializer(instance=role).ato_representation(role)
        self.assertEqual(rep["code"], "manager")
        self.assertEqual(rep["title"], "Manager")

    def test_sync_representation(self):
        from dominion.models import Role
        role = Role.objects.get(code="owner")
        rep = RoleSerializer(instance=role).to_representation(role)
        self.assertEqual(rep["code"], "owner")


class PermissionSerializerTestCase(BaseTestCase):
    async def test_async_representation(self):
        from dominion.models import Permission
        perm = await Permission.objects.aget(code="read")
        rep = await PermissionSerializer(instance=perm).ato_representation(perm)
        self.assertEqual(rep["code"], "read")
        self.assertEqual(rep["title"], "Read")

    def test_sync_representation(self):
        from dominion.models import Permission
        perm = Permission.objects.get(code="create")
        rep = PermissionSerializer(instance=perm).to_representation(perm)
        self.assertEqual(rep["code"], "create")


class ResourceSerializerTestCase(BaseTestCase):
    async def test_async_representation(self):
        rep = await ResourceSerializer(instance=self.domaina_resourcea).ato_representation(
            self.domaina_resourcea
        )
        self.assertEqual(rep["id"], str(self.domaina_resourcea.id))
        self.assertEqual(rep["urn"], "domaina:resourcea")
        self.assertIsNone(rep["parent"])
        self.assertEqual(str(rep["domain"]), str(self.domaina.id))

    def test_sync_representation(self):
        rep = ResourceSerializer(instance=self.domaina_resourceaa).to_representation(
            self.domaina_resourceaa
        )
        self.assertEqual(rep["urn"], "domaina:resourceaa")
        self.assertEqual(str(rep["parent"]), str(self.domaina_resourcea.id))
