import base64
import os
from unittest import mock

import connexion
import httpx
from asgiref.sync import sync_to_async
from django.test import override_settings

from dominion.tests.base import BaseTestCase
from dominion.models import User, Role, Permission, DomainRolePermission, DomainPermission, \
    ResourceRolePermission, ResourcePermission, UserDomainRole, Resource


_SPEC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../conf"))


def create_app():
    application = connexion.AsyncApp(__name__, specification_dir=_SPEC_DIR)
    application.add_api(
        "openapi.yaml",
        resolver=connexion.resolver.RestyResolver("dominion.api"),
        strict_validation=True,
    )
    return application


def auth_header(username, password):
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {credentials}"}


class APITestCase(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.application = create_app()

    async def get_client(self, username=None, password=None):
        transport = httpx.ASGITransport(app=self.application)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        if username:
            client.headers.update(auth_header(username, password or "password"))
        return client

    async def test_create_user(self):
        async with await self.get_client("owner") as client:
            response = await client.post(
                "/api/v1.0/user",
                json={"username": "john", "email": "john@aaa.com", "first_name": "John", "last_name": "Smith", "password": "password"}
            )
            assert response.status_code == 201
            user = await User.objects.select_related("created_by").aget(username="john")
            assert response.json()["id"] == str(user.id)
            assert response.json()["username"] == "john"
            assert response.json()["email"] == "john@aaa.com"
            assert response.json()["first_name"] == "John"
            assert response.json()["last_name"] == "Smith"
            assert response.json()["api_key"] == str(user.api_key)
            assert user.is_active
            assert user.created_by == self.owner

    async def test_register(self):
        transport = httpx.ASGITransport(app=self.application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1.0/user/register",
                json={
                    "username": "johnn",
                    "email": "johnn@aaa.com",
                    "first_name": "John",
                    "last_name": "Smith",
                    "password": "password",
                },
            )
            assert response.status_code == 201
            as_json = response.json()
            assert as_json["username"] == "johnn"
            obj = await User.objects.aget(id=as_json["id"])
            assert obj.username == "johnn"
            assert as_json["domains"] == []

            response = await client.post(
                "/api/v1.0/user/register",
                json={
                    "username": "johnnx",
                    "email": "johnnx@aaa.com",
                    "first_name": "John",
                    "last_name": "Smith",
                    "password": "password",
                },
            )
            assert response.status_code == 201
            as_json = response.json()
            assert as_json["username"] == "johnnx"
            obj = await User.objects.aget(id=as_json["id"])
            assert obj.username == "johnnx"
            assert as_json["domains"] == []

    async def test_root_domain_create_domain(self):
        # Simple case
        async with await self.get_client("owner") as client:
            response = await client.post("/api/v1.0/domain", json={"title": "Domain created a"})
            assert response.status_code == 201
            assert response.json()["parent"] is None
            assert response.json()["title"] == "Domain created a"

            # Domain with parent that user may not create within
        async with await self.get_client("piet") as client:
            response = await client.post(
                "/api/v1.0/domain",
                json={"title": "Domain created b", "parent": str(self.domaina.id)},
            )
            assert response.status_code == 403

    async def test_domaina_create_domain(self):
        async with await self.get_client("owner") as client:
            response = await client.post(
                "/api/v1.0/domain", json={"title": "Domain created", "parent": str(self.domaina.id)}
            )
            assert response.status_code == 201
            assert response.json()["parent"] == str(self.domaina.id)
            assert response.json()["title"] == "Domain created"

    async def test_domaina_read(self):
        async with await self.get_client("owner") as client:
            response = await client.get("/api/v1.0/domain/%s" % self.domaina.id)
            assert response.status_code == 200

        async with await self.get_client("piet") as client:
            response = await client.get("/api/v1.0/domain/%s" % self.domaina.id)
            assert response.status_code == 403

        async with await self.get_client("jan") as client:
            response = await client.get("/api/v1.0/domain/%s" % self.domaina.id)
            assert response.status_code == 200

    async def test_domaina_update(self):
        async with await self.get_client("owner") as client:
            response = await client.put(
                "/api/v1.0/domain/%s" % self.domaina.id, json={"title": "Domain A updated"}
            )
            assert response.status_code == 200
            assert response.json() == {"id": str(self.domaina.id), "parent": None, "title": "Domain A updated"}

        async with await self.get_client("piet") as client:
            response = await client.put(
                "/api/v1.0/domain/%s" % self.domaina.id, json={"title": "Domain A updated"}
            )
            assert response.status_code == 403

    async def test_domaina_create_resource(self):
        async with await self.get_client("owner") as client:
            response = await client.post(
                "/api/v1.0/resource", json={"urn": "Resource created", "domain": str(self.domaina.id)}
            )
            assert response.status_code == 201
            assert response.json()["domain"] == str(self.domaina.id)
            assert response.json()["parent"] is None
            assert response.json()["urn"] == "Resource created"

    async def test_domainaa_read(self):
        async with await self.get_client("owner") as client:
            response = await client.get("/api/v1.0/domain/%s" % self.domainaa.id)
            assert response.status_code == 200

        async with await self.get_client("piet") as client:
            response = await client.get("/api/v1.0/domain/%s" % self.domainaa.id)
            assert response.status_code == 403

        async with await self.get_client("jan") as client:
            response = await client.get("/api/v1.0/domain/%s" % self.domainaa.id)
            assert response.status_code == 200

    async def test_domain_delete(self):
        async with await self.get_client("owner") as client:
            # Protection error
            response = await client.delete("/api/v1.0/domain/%s" % self.undeletable_domain.id)
            assert response.status_code == 422

    async def test_piets_root_domain_update(self):
        async with await self.get_client("piet") as client:
            # Simple case
            response = await client.put(
                "/api/v1.0/domain/%s" % self.piets_root_domain.id, json={"title": "Domain updated"}
            )
            assert response.status_code == 200
            assert response.json() == {
                "id": str(self.piets_root_domain.id), "parent": None, "title": "Domain updated"
            }

            # Domain with parent that user may not create within
            response = await client.put(
                "/api/v1.0/domain/%s" % self.piets_root_domain.id,
                json={"title": "Domain updated", "parent": str(self.domaina.id)},
            )
            assert response.status_code == 403

    async def test_domaina_resourcea_read(self):
        async with await self.get_client("owner") as client:
            response = await client.get("/api/v1.0/resource/%s" % self.domaina_resourcea.id)
            assert response.status_code == 200

        async with await self.get_client("piet") as client:
            response = await client.get("/api/v1.0/resource/%s" % self.domaina_resourcea.id)
            assert response.status_code == 403

        async with await self.get_client("jan") as client:
            response = await client.get("/api/v1.0/resource/%s" % self.domaina_resourcea.id)
            assert response.status_code == 200

    async def test_domaina_resourceaa_read(self):
        """Nobody can read domaina_resourceaa."""
        async with await self.get_client("owner") as client:
            response = await client.get("/api/v1.0/resource/%s" % self.domaina_resourceaa.id)
            assert response.status_code == 403

        async with await self.get_client("jan") as client:
            response = await client.get("/api/v1.0/resource/%s" % self.domaina_resourceaa.id)
            assert response.status_code == 403

    async def test_access_resource_permission(self):
        # Note how owner may check for permission for other users
        async with await self.get_client("owner") as client:
            response = await client.get(
                "/api/v1.0/access/resource/permission/%s/%s/read"
                % (self.owner.id, self.domaina_resourcea.id)
            )
            assert response.status_code == 200
            assert response.json() == {"result": True}

            response = await client.get(
                "/api/v1.0/access/resource/permission/%s/%s/read"
                % (self.piet.id, self.domaina_resourcea.id)
            )
            assert response.status_code == 200
            assert response.json() == {"result": False}

            response = await client.get(
                "/api/v1.0/access/resource/permission/%s/%s/read"
                % (self.jan.id, self.domaina_resourcea.id)
            )
            assert response.status_code == 200
            assert response.json() == {"result": True}

        # Piet may not check for permission for other users
        async with await self.get_client("piet") as client:
            response = await client.get(
                "/api/v1.0/access/resource/permission/%s/%s/read"
                % (self.owner.id, self.domaina_resourcea.id)
            )
            assert response.status_code == 403

    async def test_user_domain_roles(self):
        async with await self.get_client("owner") as client:
            # Create
            response = await client.post(
                "/api/v1.0/userdomainrole",
                json={"user": str(self.piet.id), "domain": str(self.domaina.id), "role": "owner"}
            )
            assert response.status_code == 201
            assert response.json()["user"] == str(self.piet.id)
            assert response.json()["domain"] == str(self.domaina.id)
            assert response.json()["role"] == "owner"
            item_id = response.json()["id"]

            # Read
            response = await client.get("/api/v1.0/userdomainrole/%s" % item_id)
            assert response.status_code == 200
            assert response.json() == {"id": item_id, "user": str(self.piet.id), "domain": str(self.domaina.id), "role": "owner"}

            # Update
            response = await client.put(
                "/api/v1.0/userdomainrole/%s" % item_id,
                json={"role": "manager"}
            )
            assert response.status_code == 200
            assert response.json()["user"] == str(self.piet.id)
            assert response.json()["domain"] == str(self.domaina.id)
            assert response.json()["role"] == "manager"

            # Delete
            response = await client.delete("/api/v1.0/userdomainrole/%s" % item_id)
            assert response.status_code == 204

            # Create with invalid user uuid
            response = await client.post(
                "/api/v1.0/userdomainrole",
                json={"user": "d37899a3-c34b-438b-9e6e-8de844b5dcd9", "domain": str(self.domaina.id), "role": "owner"}
            )
            assert response.status_code == 422

    async def test_user_resource_roles(self):
        async with await self.get_client("owner") as client:
            # Create
            response = await client.post(
                "/api/v1.0/userresourcerole",
                json={"user": str(self.piet.id), "resource": str(self.domaina_resourcea.id), "role": "owner"}
            )
            assert response.status_code == 201
            assert response.json()["user"] == str(self.piet.id)
            assert response.json()["resource"] == str(self.domaina_resourcea.id)
            assert response.json()["role"] == "owner"
            item_id = response.json()["id"]

            # Read
            response = await client.get("/api/v1.0/userresourcerole/%s" % item_id)
            assert response.status_code == 200
            assert response.json() == {"id": item_id, "user": str(self.piet.id), "resource": str(self.domaina_resourcea.id), "role": "owner"}

            # Update
            response = await client.put(
                "/api/v1.0/userresourcerole/%s" % item_id,
                json={"role": "manager"}
            )
            assert response.status_code == 200
            assert response.json()["user"] == str(self.piet.id)
            assert response.json()["resource"] == str(self.domaina_resourcea.id)
            assert response.json()["role"] == "manager"

            # Delete
            response = await client.delete("/api/v1.0/userresourcerole/%s" % item_id)
            assert response.status_code == 204

            # Create with invalid user uuid
            response = await client.post(
                "/api/v1.0/userresourcerole",
                json={"user": "d37899a3-c34b-438b-9e6e-8de844b5dcd9", "resource": str(self.domaina_resourcea.id), "role": "owner"}
            )
            assert response.status_code == 422

    @override_settings(DOMINION_API_RESULTS_PER_PAGE=2)
    async def test_domain_list(self):
        async with await self.get_client("owner") as client:
            response = await client.get("/api/v1.0/domain?page=1")
            assert response.status_code == 200
            assert response.json()["results"][0] == {"id": str(self.deletable_domain.id), "parent": None, "title": "Deletable domain"}

            response = await client.get("/api/v1.0/domain?page=2")
            assert response.json()["previous"] == "http://testserver/api/v1.0/domain?page=1"
            assert response.json()["next"] == "http://testserver/api/v1.0/domain?page=3"

            # Page 3 is the true last page (6 domains, 2 per page): it must be
            # reachable, non-empty, and carry no "next" link.
            response = await client.get("/api/v1.0/domain?page=3")
            assert response.json()["previous"] == "http://testserver/api/v1.0/domain?page=2"
            assert "next" not in response.json()
            assert len(response.json()["results"]) > 0

            # Out-of-range pages clamp to the last real page.
            response = await client.get("/api/v1.0/domain?page=4")
            assert response.json()["previous"] == "http://testserver/api/v1.0/domain?page=2"
            assert "next" not in response.json()
            assert len(response.json()["results"]) > 0

            response = await client.get("/api/v1.0/domain?page=5")
            assert response.json()["previous"] == "http://testserver/api/v1.0/domain?page=2"
            assert "next" not in response.json()

    async def test_role_crud(self):
        async with await self.get_client("owner") as client:
            # Create
            response = await client.post(
                "/api/v1.0/role",
                json={"title": "Custom role A", "code": "custom-role-a", "domain": str(self.domaina.id)}
            )
            assert response.status_code == 201
            assert response.json() == {"title": "Custom role A", "code": "custom-role-a", "domain": str(self.domaina.id)}

            # Attempt to create a role with the same code
            response = await client.post(
                "/api/v1.0/role",
                json={"title": "Custom role Another", "code": "custom-role-a", "domain": str(self.domaina.id)}
            )
            assert response.status_code == 422

            # Attempt to create a role with a non-root domain
            response = await client.post(
                "/api/v1.0/role",
                json={"title": "Custom role AA", "code": "custom-role-aa", "domain": str(self.domainaa.id)}
            )
            assert response.status_code == 422

            # Read
            response = await client.get("/api/v1.0/role/custom-role-a")
            assert response.status_code == 200
            assert response.json() == {"title": "Custom role A", "code": "custom-role-a", "domain": str(self.domaina.id)}

            # Update
            response = await client.put("/api/v1.0/role/custom-role-a", json={"title": "Custom role A!"})
            assert response.status_code == 200
            assert response.json() == {"title": "Custom role A!", "code": "custom-role-a", "domain": str(self.domaina.id)}

            # List
            response = await client.get("/api/v1.0/role?page=1")
            assert response.status_code == 200
            assert response.json()["results"][0] == {"title": "Access checker", "code": "access_checker", "domain": None}

            # Delete
            response = await client.delete("/api/v1.0/role/custom-role-a")
            assert response.status_code == 204

            # Attempt to delete a role that is not ours
            response = await client.delete("/api/v1.0/role/owner")
            assert response.status_code == 403

    async def test_permission_crud(self):
        async with await self.get_client("owner") as client:
            # Create
            response = await client.post(
                "/api/v1.0/permission",
                json={"title": "Custom permission A", "code": "custom-permission-a", "domain": str(self.domaina.id)}
            )
            assert response.status_code == 201
            assert response.json() == {"title": "Custom permission A", "code": "custom-permission-a", "domain": str(self.domaina.id)}

            # Attempt to create a permission with the same code
            response = await client.post(
                "/api/v1.0/permission",
                json={"title": "Custom permission Another", "code": "custom-permission-a", "domain": str(self.domaina.id)}
            )
            assert response.status_code == 422

            # Attempt to create a permission with a non-root domain
            response = await client.post(
                "/api/v1.0/permission",
                json={"title": "Custom permission AA", "code": "custom-permission-aa", "domain": str(self.domainaa.id)}
            )
            assert response.status_code == 422

            # Read
            response = await client.get("/api/v1.0/permission/custom-permission-a")
            assert response.status_code == 200
            assert response.json() == {"title": "Custom permission A", "code": "custom-permission-a", "domain": str(self.domaina.id)}

            # Update
            response = await client.put("/api/v1.0/permission/custom-permission-a", json={"title": "Custom permission A!"})
            assert response.status_code == 200
            assert response.json() == {"title": "Custom permission A!", "code": "custom-permission-a", "domain": str(self.domaina.id)}

            # List
            response = await client.get("/api/v1.0/permission?page=1")
            assert response.status_code == 200
            assert response.json()["results"][0] == {"title": "Check access", "code": "check_access", "domain": None}

            # Delete
            response = await client.delete("/api/v1.0/permission/custom-permission-a")
            assert response.status_code == 204

            # Attempt to delete a permission that is not ours
            response = await client.delete("/api/v1.0/permission/read")
            assert response.status_code == 403

    async def test_domainrolepermission_crud(self):
        async with await self.get_client("owner") as client:
            # Create
            response = await client.post(
                "/api/v1.0/domainrolepermission",
                json={"domain": str(self.domaina.id), "role": "anonymous", "permission": "read"}
            )
            assert response.status_code == 201
            assert response.json()["domain"] == str(self.domaina.id)
            assert response.json()["role"] == "anonymous"
            assert response.json()["permission"] == "read"
            assert response.json()["inherit"] is True
            drp_id = response.json()["id"]

            # Create but set inherit to false
            response = await client.post(
                "/api/v1.0/domainrolepermission",
                json={"domain": str(self.domaina.id), "role": "anonymous", "permission": "view", "inherit": False}
            )
            assert response.status_code == 201
            assert response.json()["inherit"] is False
            assert await DomainPermission.objects.filter(domain=self.domaina, permission__code="view").aexists()

            # Attempt to create an item that already exists
            response = await client.post(
                "/api/v1.0/domainrolepermission",
                json={"domain": str(self.domaina.id), "role": "anonymous", "permission": "read"}
            )
            assert response.status_code == 422

            # Attempt to create an item on domain that is not ours
            response = await client.post(
                "/api/v1.0/domainrolepermission",
                json={"domain": str(self.piets_root_domain.id), "role": "manager", "permission": "read"}
            )
            assert response.status_code == 403

            # Attempt to create an item with role we don't have access to
            await Role.objects.acreate(code="some-role", title="Some role", domain=self.piets_root_domain)
            response = await client.post(
                "/api/v1.0/domainrolepermission",
                json={"domain": str(self.domaina.id), "role": "some-role", "permission": "read"}
            )
            assert response.status_code == 404

            # Attempt to create an item with permission we don't have access to
            await Permission.objects.acreate(code="some-permission", title="Some permission", domain=self.piets_root_domain)
            response = await client.post(
                "/api/v1.0/domainrolepermission",
                json={"domain": str(self.domaina.id), "role": "manager", "permission": "some-permission"}
            )
            assert response.status_code == 404

            # Read
            response = await client.get("/api/v1.0/domainrolepermission/%s" % drp_id)
            assert response.status_code == 200
            assert response.json()["domain"] == str(self.domaina.id)
            assert response.json()["role"] == "anonymous"
            assert response.json()["permission"] == "read"
            assert response.json()["inherit"] is True

            # List
            response = await client.get("/api/v1.0/domainrolepermission?domain=%s" % self.domaina.id)
            assert response.status_code == 200

            # Update
            response = await client.put(
                "/api/v1.0/domainrolepermission/%s" % drp_id,
                json={"role": "authenticated"}
            )
            assert response.status_code == 200
            assert response.json()["role"] == "authenticated"

            # Attempt to update an item with role we don't have access to
            response = await client.put(
                "/api/v1.0/domainrolepermission/%s" % drp_id,
                json={"role": "some-role"}
            )
            assert response.status_code == 404

            # Attempt to update an item with permission we don't have access to
            response = await client.put(
                "/api/v1.0/domainrolepermission/%s" % drp_id,
                json={"permission": "some-permission"}
            )
            assert response.status_code == 404

            # Attempt to update an item that is not ours
            obj = await DomainRolePermission.objects.filter(domain=self.piets_root_domain).afirst()
            response = await client.put(
                "/api/v1.0/domainrolepermission/%s" % obj.id,
                json={"role": "authenticated"}
            )
            assert response.status_code == 403

            # Delete
            response = await client.delete("/api/v1.0/domainrolepermission/%s" % drp_id)
            assert response.status_code == 204

            # Attempt to delete an item that is not ours
            obj = await DomainRolePermission.objects.filter(domain=self.piets_root_domain).afirst()
            response = await client.delete("/api/v1.0/domainrolepermission/%s" % obj.id)
            assert response.status_code == 403

    async def test_resourcerolepermission_crud(self):
        async with await self.get_client("owner") as client:
            # Create
            response = await client.post(
                "/api/v1.0/resourcerolepermission",
                json={"resource": str(self.domaina_resourcea.id), "role": "anonymous", "permission": "read"}
            )
            assert response.status_code == 201
            assert response.json()["resource"] == str(self.domaina_resourcea.id)
            assert response.json()["role"] == "anonymous"
            assert response.json()["permission"] == "read"
            assert response.json()["inherit"] is True
            rrp_id = response.json()["id"]

            # Create but set inherit to false
            response = await client.post(
                "/api/v1.0/resourcerolepermission",
                json={"resource": str(self.domaina_resourcea.id), "role": "anonymous", "permission": "view", "inherit": False}
            )
            assert response.status_code == 201
            assert response.json()["inherit"] is False
            assert await ResourcePermission.objects.filter(resource=self.domaina_resourcea, permission__code="view").aexists()

            # Attempt to create an item that already exists
            response = await client.post(
                "/api/v1.0/resourcerolepermission",
                json={"resource": str(self.domaina_resourcea.id), "role": "anonymous", "permission": "read"}
            )
            assert response.status_code == 422

            # Read
            response = await client.get("/api/v1.0/resourcerolepermission/%s" % rrp_id)
            assert response.status_code == 200
            assert response.json()["resource"] == str(self.domaina_resourcea.id)
            assert response.json()["role"] == "anonymous"
            assert response.json()["permission"] == "read"
            assert response.json()["inherit"] is True

            # List
            response = await client.get("/api/v1.0/resourcerolepermission?resource=%s" % self.domaina_resourcea.id)
            assert response.status_code == 200

            # Update
            response = await client.put(
                "/api/v1.0/resourcerolepermission/%s" % rrp_id,
                json={"role": "authenticated"}
            )
            assert response.status_code == 200
            assert response.json()["resource"] == str(self.domaina_resourcea.id)
            assert response.json()["role"] == "authenticated"

            # Delete
            response = await client.delete("/api/v1.0/resourcerolepermission/%s" % rrp_id)
            assert response.status_code == 204

    async def test_access_domain_permission_allowed(self):
        # Owner has check_access on domaina (owner role includes check_access).
        async with await self.get_client("owner") as client:
            response = await client.get(
                "/api/v1.0/access/domain/permission/%s/%s/read"
                % (self.owner.id, self.domaina.id)
            )
            assert response.status_code == 200
            assert response.json() == {"result": True}

    async def test_access_domain_permission_denied_no_check_access(self):
        # Piet has no check_access permission on domaina so the endpoint returns 403.
        async with await self.get_client("piet") as client:
            response = await client.get(
                "/api/v1.0/access/domain/permission/%s/%s/read"
                % (self.piet.id, self.domaina.id)
            )
            assert response.status_code == 403

    async def test_duplicate_userdomainrole_race_returns_409_not_500(self):
        """A concurrent duplicate assignment (full_clean passes, DB constraint fires)
        must surface as a clean 409, never an uncaught IntegrityError 500.

        The in-memory full_clean() normally catches duplicates and returns 422; we
        patch it to a no-op to simulate the race window where two requests both pass
        the check and the database unique_together is the only guard left.
        """
        # Pre-create the assignment so the DB row already exists.
        role_manager = await Role.objects.aget(code="manager")
        await UserDomainRole.objects.acreate(
            user=self.piet, domain=self.domaina, role=role_manager
        )
        async with await self.get_client("owner") as client:
            with mock.patch.object(UserDomainRole, "full_clean", return_value=None):
                response = await client.post(
                    "/api/v1.0/userdomainrole",
                    json={"user": str(self.piet.id), "domain": str(self.domaina.id), "role": "manager"},
                )
            assert response.status_code == 409

    async def test_effective_permissions_lists_granted_codes(self):
        # Owner has check_access and holds the owner role on domaina, so the
        # introspection endpoint returns the full set of permissions owner effectively has.
        async with await self.get_client("owner") as client:
            response = await client.get(
                "/api/v1.0/access/domain/permissions/%s/%s" % (self.owner.id, self.domaina.id)
            )
            assert response.status_code == 200
            body = response.json()
            assert body["user"] == str(self.owner.id)
            assert body["domain"] == str(self.domaina.id)
            # owner role grants create/read/update/delete/manage_roles; check_access comes
            # from the access_checker role also assigned to the creator.
            assert "read" in body["permissions"]
            assert "delete" in body["permissions"]
            assert body["permissions"] == sorted(body["permissions"])

    async def test_effective_permissions_requires_check_access(self):
        # Piet lacks check_access on domaina.
        async with await self.get_client("piet") as client:
            response = await client.get(
                "/api/v1.0/access/domain/permissions/%s/%s" % (self.piet.id, self.domaina.id)
            )
            assert response.status_code == 403

    async def test_effective_permissions_missing_domain_returns_404(self):
        import uuid
        async with await self.get_client("owner") as client:
            response = await client.get(
                "/api/v1.0/access/domain/permissions/%s/%s" % (self.owner.id, uuid.uuid4())
            )
            assert response.status_code == 404

    async def test_duplicate_role_race_returns_409_not_500(self):
        """Concurrent duplicate role create (unique code) → 409, not an IntegrityError 500."""
        await Role.objects.acreate(code="race-role", title="Race", domain=self.domaina)
        async with await self.get_client("owner") as client:
            with mock.patch.object(Role, "full_clean", return_value=None):
                response = await client.post(
                    "/api/v1.0/role",
                    json={"title": "Race", "code": "race-role", "domain": str(self.domaina.id)},
                )
            assert response.status_code == 409

    async def test_duplicate_permission_race_returns_409_not_500(self):
        await Permission.objects.acreate(code="race-perm", title="Race", domain=self.domaina)
        async with await self.get_client("owner") as client:
            with mock.patch.object(Permission, "full_clean", return_value=None):
                response = await client.post(
                    "/api/v1.0/permission",
                    json={"title": "Race", "code": "race-perm", "domain": str(self.domaina.id)},
                )
            assert response.status_code == 409

    async def test_duplicate_resource_race_returns_409_not_500(self):
        """Concurrent duplicate resource create (unique urn) → 409, not a 500."""
        await sync_to_async(Resource.objects.create)(urn="race:res", domain=self.domaina, owner=self.owner)
        async with await self.get_client("owner") as client:
            with mock.patch.object(Resource, "full_clean", return_value=None):
                response = await client.post(
                    "/api/v1.0/resource",
                    json={"urn": "race:res", "domain": str(self.domaina.id)},
                )
            assert response.status_code == 409

    async def test_access_domain_permission_missing_domain_returns_404(self):
        import uuid
        async with await self.get_client("owner") as client:
            response = await client.get(
                "/api/v1.0/access/domain/permission/%s/%s/read"
                % (self.owner.id, uuid.uuid4())
            )
            assert response.status_code == 404

    async def test_access_resource_permission_missing_resource_returns_404(self):
        import uuid
        async with await self.get_client("owner") as client:
            response = await client.get(
                "/api/v1.0/access/resource/permission/%s/%s/read"
                % (self.owner.id, uuid.uuid4())
            )
            assert response.status_code == 404

    async def test_login_no_matching_email(self):
        transport = httpx.ASGITransport(app=self.application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1.0/user/login",
                json={"email": "nobody@test.com", "password": "password"},
            )
            assert response.status_code == 401

    async def test_login_with_email(self):
        # Set email on owner so login can find the user by email.
        self.owner.email = "owner@test.com"
        await self.owner.asave()
        transport = httpx.ASGITransport(app=self.application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1.0/user/login",
                json={"email": "owner@test.com", "password": "password"},
            )
            assert response.status_code == 200
            assert response.json()["username"] == "owner"

    async def test_login_wrong_password(self):
        self.owner.email = "owner@test.com"
        await self.owner.asave()
        transport = httpx.ASGITransport(app=self.application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1.0/user/login",
                json={"email": "owner@test.com", "password": "wrongpassword"},
            )
            assert response.status_code == 401

    async def test_by_api_key_success(self):
        transport = httpx.ASGITransport(app=self.application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1.0/user/by-api-key/%s" % self.owner.api_key
            )
            assert response.status_code == 200
            assert response.json()["username"] == "owner"

    async def test_by_api_key_not_found(self):
        import uuid
        transport = httpx.ASGITransport(app=self.application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/v1.0/user/by-api-key/%s" % uuid.uuid4()
            )
            assert response.status_code == 404


class PaginationTestCase(BaseTestCase):
    """Exercise paginate_result via the role list endpoint.

    Covers the exact-multiple page count (no phantom empty page), link
    presence on first/middle/last pages, and out-of-range page clamping.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.application = create_app()

    async def _client(self):
        transport = httpx.ASGITransport(app=self.application)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        client.headers.update(auth_header("owner", "password"))
        return client

    async def _create_roles(self, prefix, n):
        from asgiref.sync import sync_to_async
        for i in range(n):
            await sync_to_async(Role.objects.create)(
                code="%s%s" % (prefix, i), title="Pagination %s %s" % (prefix, i), domain=self.domaina
            )

    async def _collect_pages(self, client):
        pages = []
        url = "/api/v1.0/role"
        while url:
            response = await client.get(url)
            assert response.status_code == 200
            data = response.json()
            pages.append(data)
            url = data.get("next")
        return pages

    async def test_single_page_has_no_links(self):
        async with await self._client() as client:
            response = await client.get("/api/v1.0/role")
            data = response.json()
            assert "previous" not in data
            assert "next" not in data
            assert len(data["results"]) == data["count"]

    async def test_exact_multiple_of_page_size(self):
        async with await self._client() as client:
            with override_settings(DOMINION_API_RESULTS_PER_PAGE=2):
                count = (await client.get("/api/v1.0/role")).json()["count"]
                # Top up so the total is an exact multiple of the page size.
                await self._create_roles("pageven", (2 - count % 2) % 2)

                pages = await self._collect_pages(client)
                total = pages[0]["count"]
                assert total % 2 == 0
                assert len(pages) == total // 2
                assert all(len(page["results"]) == 2 for page in pages)
                assert "previous" not in pages[0]
                assert "next" not in pages[-1]
                if len(pages) > 1:
                    assert "previous" in pages[-1]
                    assert "next" in pages[0]
                codes = [role["code"] for page in pages for role in page["results"]]
                assert len(codes) == total
                assert len(set(codes)) == total

    async def test_odd_remainder_last_page(self):
        async with await self._client() as client:
            with override_settings(DOMINION_API_RESULTS_PER_PAGE=2):
                count = (await client.get("/api/v1.0/role")).json()["count"]
                # Top up so the total is odd.
                await self._create_roles("pagodd", 1 if count % 2 == 0 else 2)

                pages = await self._collect_pages(client)
                total = pages[0]["count"]
                assert total % 2 == 1
                assert len(pages) == total // 2 + 1
                assert len(pages[-1]["results"]) == 1
                assert "next" not in pages[-1]

    async def test_out_of_range_page_clamps_to_last(self):
        async with await self._client() as client:
            with override_settings(DOMINION_API_RESULTS_PER_PAGE=2):
                response = await client.get("/api/v1.0/role", params={"page": 9999})
                data = response.json()
                assert response.status_code == 200
                assert "next" not in data
                assert len(data["results"]) >= 1
