import connexion
from connexion.resolver import RestyResolver
from django.core.wsgi import get_wsgi_application
from django.test import override_settings
from webtest.app import TestApp, AppError

from tests.base import BaseTestCase
from triplea.models import User, Role, Permission, DomainRolePermission, DomainPermission, \
    ResourceRolePermission, ResourcePermission


def create_app():
    app = connexion.App(__name__, specification_dir="../../../")
    app.add_api("openapi.yaml", resolver=RestyResolver("triplea_api"), strict_validation=True)
    return app


class APITestCase(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = TestApp(create_app())

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def test_create_user(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.post_json(
            "/api/v1.0/user", {"username": "john", "email": "john@aaa.com", "first_name": "John", "last_name": "Smith", "password": "password"}
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="john")
        self.assertEqual(response.json["id"], str(user.id))
        self.assertEqual(response.json["username"], "john")
        self.assertEqual(response.json["email"], "john@aaa.com")
        self.assertEqual(response.json["first_name"], "John")
        self.assertEqual(response.json["last_name"], "Smith")
        self.assertEqual(response.json["api_key"], str(user.api_key))
        self.assertTrue(user.is_active)
        self.assertEqual(user.created_by, self.owner)
        self.assertTrue(self.client.login(username="john", password="password"))

    def test_register(self):
        response = self.app.post_json(
            "/api/v1.0/user/register",
            {
                "username": "johnn",
                "email": "johnn@aaa.com",
                "first_name": "John",
                "last_name": "Smith",
                "password": "password",
            },
        )
        self.assertEqual(response.status_code, 201)
        as_json = response.json
        self.assertEqual(as_json["username"], "johnn")
        obj = User.objects.get(id=as_json["id"])
        self.assertEqual(obj.username, "johnn")
        self.assertEqual(as_json["domains"], [])

        response = self.app.post_json(
            "/api/v1.0/user/register",
            {
                "username": "johnnx",
                "email": "johnnx@aaa.com",
                "first_name": "John",
                "last_name": "Smith",
                "password": "password",
            },
        )
        self.assertEqual(response.status_code, 201)
        as_json = response.json
        self.assertEqual(as_json["username"], "johnnx")
        obj = User.objects.get(id=as_json["id"])
        self.assertEqual(obj.username, "johnnx")
        self.assertEqual(as_json["domains"], [])

    def test_root_domain_create_domain(self):

        # Simple case
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.post_json("/api/v1.0/domain", {"title": "Domain created a"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["parent"], None)
        self.assertEqual(response.json["title"], "Domain created a")

        # Domain with parent that user may not create within
        self.app.authorization = ("Basic", ("piet", "password"))
        response = self.app.post_json(
            "/api/v1.0/domain",
            {"title": "Domain created b", "parent": str(self.domaina.id)},
            status=403,
        )
        self.assertEqual(response.status_code, 403)

    def test_domaina_create_domain(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.post_json(
            "/api/v1.0/domain", {"title": "Domain created", "parent": str(self.domaina.id)}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["parent"], str(self.domaina.id))
        self.assertEqual(response.json["title"], "Domain created")

    def test_domaina_read(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.get("/api/v1.0/domain/%s" % self.domaina.id)
        self.assertEqual(response.status_code, 200)

        self.app.authorization = ("Basic", ("piet", "password"))
        response = self.app.get("/api/v1.0/domain/%s" % self.domaina.id, status=403)
        self.assertEqual(response.status_code, 403)

        self.app.authorization = ("Basic", ("jan", "password"))
        response = self.app.get("/api/v1.0/domain/%s" % self.domaina.id)
        self.assertEqual(response.status_code, 200)

    def test_domaina_update(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.put_json(
            "/api/v1.0/domain/%s" % self.domaina.id, {"title": "Domain A updated"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json, {"id": str(self.domaina.id), "parent": None, "title": "Domain A updated"}
        )

        self.app.authorization = ("Basic", ("piet", "password"))
        response = self.app.put_json(
            "/api/v1.0/domain/%s" % self.domaina.id, {"title": "Domain A updated"}, status=403
        )
        self.assertEqual(response.status_code, 403)

    def test_domaina_create_resource(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.post_json(
            "/api/v1.0/resource", {"urn": "Resource created", "domain": str(self.domaina.id)}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["domain"], str(self.domaina.id))
        self.assertEqual(response.json["parent"], None)
        self.assertEqual(response.json["urn"], "Resource created")

    def test_domainaa_read(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.get("/api/v1.0/domain/%s" % self.domainaa.id)
        self.assertEqual(response.status_code, 200)

        self.app.authorization = ("Basic", ("piet", "password"))
        response = self.app.get("/api/v1.0/domain/%s" % self.domainaa.id, status=403)
        self.assertEqual(response.status_code, 403)

        self.app.authorization = ("Basic", ("jan", "password"))
        response = self.app.get("/api/v1.0/domain/%s" % self.domainaa.id)
        self.assertEqual(response.status_code, 200)

    def test_domain_delete(self):
        self.app.authorization = ("Basic", ("owner", "password"))

        # Protection error
        response = self.app.delete("/api/v1.0/domain/%s" % self.undeletable_domain.id, status=422)
        self.assertEqual(response.status_code, 422)

        # Delete dependent items and try again
        # TODO

    def test_piets_root_domain_update(self):
        self.app.authorization = ("Basic", ("piet", "password"))

        # Simple case
        response = self.app.put_json(
            "/api/v1.0/domain/%s" % self.piets_root_domain.id, {"title": "Domain updated"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json,
            {"id": str(self.piets_root_domain.id), "parent": None, "title": "Domain updated"},
        )

        # Domain with parent that user may not create within
        response = self.app.put_json(
            "/api/v1.0/domain/%s" % self.piets_root_domain.id,
            {"title": "Domain updated", "parent": str(self.domaina.id)},
            status=403,
        )
        self.assertEqual(response.status_code, 403)

    def test_domaina_resourcea_read(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.get("/api/v1.0/resource/%s" % self.domaina_resourcea.id)
        self.assertEqual(response.status_code, 200)

        self.app.authorization = ("Basic", ("piet", "password"))
        response = self.app.get("/api/v1.0/resource/%s" % self.domaina_resourcea.id, status=403)
        self.assertEqual(response.status_code, 403)

        self.app.authorization = ("Basic", ("jan", "password"))
        response = self.app.get("/api/v1.0/resource/%s" % self.domaina_resourcea.id)
        self.assertEqual(response.status_code, 200)

    def test_domaina_resourceaa_read(self):
        """Nobody can read domaina_resourceaa."""
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.get("/api/v1.0/resource/%s" % self.domaina_resourceaa.id, status=403)
        self.assertEqual(response.status_code, 403)

        self.app.authorization = ("Basic", ("jan", "password"))
        response = self.app.get("/api/v1.0/resource/%s" % self.domaina_resourceaa.id, status=403)
        self.assertEqual(response.status_code, 403)

    def test_access_resource_permission(self):
        # Note how owner may check for permission for other users
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.get(
            "/api/v1.0/access/resource/permission/%s/%s/read"
            % (self.owner.id, self.domaina_resourcea.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"result": True})

        response = self.app.get(
            "/api/v1.0/access/resource/permission/%s/%s/read"
            % (self.piet.id, self.domaina_resourcea.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"result": False})

        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.get(
            "/api/v1.0/access/resource/permission/%s/%s/read"
            % (self.jan.id, self.domaina_resourcea.id)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"result": True})

        # Piet may not may check for permission for other users
        self.app.authorization = ("Basic", ("piet", "password"))
        response = self.app.get(
            "/api/v1.0/access/resource/permission/%s/%s/read"
            % (self.owner.id, self.domaina_resourcea.id),
            status=403,
        )
        self.assertEqual(response.status_code, 403)

    def test_user_domain_roles(self):
        self.app.authorization = ("Basic", ("owner", "password"))

        # Create
        response = self.app.post_json(
            "/api/v1.0/userdomainrole", {"user": str(self.piet.id), "domain": str(self.domaina.id), "role": "owner"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"], str(self.piet.id))
        self.assertEqual(response.json["domain"], str(self.domaina.id))
        self.assertEqual(response.json["role"], "owner")
        id = response.json["id"]

        # Read
        response = self.app.get(
            "/api/v1.0/userdomainrole/%s" % id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"id": id, "user": str(self.piet.id), "domain": str(self.domaina.id), "role": "owner"})

        # Update
        response = self.app.put_json(
            "/api/v1.0/userdomainrole/%s" % id,
            {"role": "manager"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"], str(self.piet.id))
        self.assertEqual(response.json["domain"], str(self.domaina.id))
        self.assertEqual(response.json["role"], "manager")

        # Delete
        response = self.app.delete(
            "/api/v1.0/userdomainrole/%s" % id,
        )
        self.assertEqual(response.status_code, 204)

        # Create with invalid user uuid
        response = self.app.post_json(
            "/api/v1.0/userdomainrole", {"user": "d37899a3-c34b-438b-9e6e-8de844b5dcd9", "domain": str(self.domaina.id), "role": "owner"},
            status=422
        )
        self.assertEqual(response.status_code, 422)

    def test_user_resource_roles(self):
        self.app.authorization = ("Basic", ("owner", "password"))

        # Create
        response = self.app.post_json(
            "/api/v1.0/userresourcerole", {"user": str(self.piet.id), "resource": str(self.domaina_resourcea.id), "role": "owner"}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"], str(self.piet.id))
        self.assertEqual(response.json["resource"], str(self.domaina_resourcea.id))
        self.assertEqual(response.json["role"], "owner")
        id = response.json["id"]

        # Read
        response = self.app.get(
            "/api/v1.0/userresourcerole/%s" % id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"id": id, "user": str(self.piet.id), "resource": str(self.domaina_resourcea.id), "role": "owner"})

        # Update
        response = self.app.put_json(
            "/api/v1.0/userresourcerole/%s" % id,
            {"role": "manager"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"], str(self.piet.id))
        self.assertEqual(response.json["resource"], str(self.domaina_resourcea.id))
        self.assertEqual(response.json["role"], "manager")

        # Delete
        response = self.app.delete(
            "/api/v1.0/userresourcerole/%s" % id,
        )
        self.assertEqual(response.status_code, 204)

        # Create with invalid user uuid
        response = self.app.post_json(
            "/api/v1.0/userresourcerole", {"user": "d37899a3-c34b-438b-9e6e-8de844b5dcd9", "resource": str(self.domaina_resourcea.id), "role": "owner"},
            status=422
        )
        self.assertEqual(response.status_code, 422)

    @override_settings(TRIPLEA_API_RESULTS_PER_PAGE=2)
    def test_domain_list(self):
        self.app.authorization = ("Basic", ("owner", "password"))
        response = self.app.get("/api/v1.0/domain?page=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["results"][0], {'id': str(self.deletable_domain.id), 'parent': None, 'title': 'Deletable domain'})

        response = self.app.get("/api/v1.0/domain?page=a", status=400)
        self.assertEqual(response.status_code, 400)

        response = self.app.get("/api/v1.0/domain?page=0", status=400)
        self.assertEqual(response.status_code, 400)

        response = self.app.get("/api/v1.0/domain?page=2")
        self.assertEqual(response.json["previous"], "http://localhost/api/v1.0/domain?page=1")
        self.assertEqual(response.json["next"], "http://localhost/api/v1.0/domain?page=3")

        response = self.app.get("/api/v1.0/domain?page=4")
        self.assertEqual(response.json["previous"], "http://localhost/api/v1.0/domain?page=3")
        self.assertFalse("next" in response.json)

        response = self.app.get("/api/v1.0/domain?page=5")
        self.assertEqual(response.json["previous"], "http://localhost/api/v1.0/domain?page=3")
        self.assertFalse("next" in response.json)

    def test_role_crud(self):
        self.app.authorization = ("Basic", ("owner", "password"))

        # Create
        response = self.app.post_json("/api/v1.0/role", {"title": "Custom role A", "code": "custom-role-a", "domain": str(self.domaina.id)})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json, {"title": "Custom role A", "code": "custom-role-a", "domain": str(self.domaina.id)})

        # Attempt to create a role with the same code
        response = self.app.post_json("/api/v1.0/role", {"title": "Custom role Another", "code": "custom-role-a", "domain": str(self.domaina.id)}, status=422)
        self.assertEqual(response.status_code, 422)

        # Attempt to create a role with a non-root domain
        response = self.app.post_json("/api/v1.0/role", {"title": "Custom role AA", "code": "custom-role-aa", "domain": str(self.domainaa.id)}, status=422)
        self.assertEqual(response.status_code, 422)

        # Read
        response = self.app.get("/api/v1.0/role/custom-role-a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"title": "Custom role A", "code": "custom-role-a", "domain": str(self.domaina.id)})

        # Update
        response = self.app.put_json("/api/v1.0/role/custom-role-a", {"title": "Custom role A!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"title": "Custom role A!", "code": "custom-role-a", "domain": str(self.domaina.id)})

        # Update and attempt to set domain
        with self.assertRaises(AppError):
            response = self.app.put_json("/api/v1.0/role/custom-role-a", {"domain": str(self.domaina.id)})

        # List
        response = self.app.get("/api/v1.0/role?page=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["results"][0], {"title": "Access checker", "code": "access_checker", "domain": None})

        # Delete
        response = self.app.delete("/api/v1.0/role/custom-role-a")
        self.assertEqual(response.status_code, 204)

        # Attempt to delete a role that is not ours
        response = self.app.delete("/api/v1.0/role/owner", status=403)
        self.assertEqual(response.status_code, 403)

    def test_permission_crud(self):
        self.app.authorization = ("Basic", ("owner", "password"))

        # Create
        response = self.app.post_json("/api/v1.0/permission", {"title": "Custom permission A", "code": "custom-permission-a", "domain": str(self.domaina.id)})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json, {"title": "Custom permission A", "code": "custom-permission-a", "domain": str(self.domaina.id)})

        # Attempt to create a permission with the same code
        response = self.app.post_json("/api/v1.0/permission", {"title": "Custom permission Another", "code": "custom-permission-a", "domain": str(self.domaina.id)}, status=422)
        self.assertEqual(response.status_code, 422)

        # Attempt to create a permission with a non-root domain
        response = self.app.post_json("/api/v1.0/permission", {"title": "Custom permission AA", "code": "custom-permission-aa", "domain": str(self.domainaa.id)}, status=422)
        self.assertEqual(response.status_code, 422)

        # Read
        response = self.app.get("/api/v1.0/permission/custom-permission-a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"title": "Custom permission A", "code": "custom-permission-a", "domain": str(self.domaina.id)})

        # Update
        response = self.app.put_json("/api/v1.0/permission/custom-permission-a", {"title": "Custom permission A!"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"title": "Custom permission A!", "code": "custom-permission-a", "domain": str(self.domaina.id)})

        # Update and attempt to set domain
        with self.assertRaises(AppError):
            response = self.app.put_json("/api/v1.0/permission/custom-permission-a", {"domain": str(self.domaina.id)})

        # List
        response = self.app.get("/api/v1.0/permission?page=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["results"][0], {"title": "Check access", "code": "check_access", "domain": None})

        # Delete
        response = self.app.delete("/api/v1.0/permission/custom-permission-a")
        self.assertEqual(response.status_code, 204)

        # Attepmt to delete a permission that is not ours
        response = self.app.delete("/api/v1.0/permission/read", status=403)
        self.assertEqual(response.status_code, 403)

    def test_domainrolepermission_crud(self):
        self.app.authorization = ("Basic", ("owner", "password"))

        # Create
        response = self.app.post_json("/api/v1.0/domainrolepermission", {"domain": str(self.domaina.id), "role": "anonymous", "permission": "read"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["domain"], str(self.domaina.id))
        self.assertEqual(response.json["role"], "anonymous")
        self.assertEqual(response.json["permission"], "read")
        self.assertEqual(response.json["inherit"], True)

        # We'll need this later
        drp_id = response.json["id"]

        # Create but set inherit to false
        response = self.app.post_json("/api/v1.0/domainrolepermission", {"domain": str(self.domaina.id), "role": "anonymous", "permission": "view", "inherit": False})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["domain"], str(self.domaina.id))
        self.assertEqual(response.json["role"], "anonymous")
        self.assertEqual(response.json["permission"], "view")
        self.assertEqual(response.json["inherit"], False)
        self.assertTrue(DomainPermission.objects.filter(domain=self.domaina, permission__code="view").exists())

        # Attempt to create an item that already exists
        response = self.app.post_json(
            "/api/v1.0/domainrolepermission",
            {"domain": str(self.domaina.id), "role": "anonymous", "permission": "read"},
            status=422
        )
        self.assertEqual(response.status_code, 422)

        # Attempt to create an item on domain that is not ours
        response = self.app.post_json(
            "/api/v1.0/domainrolepermission",
            {"domain": str(self.piets_root_domain.id), "role": "manager", "permission": "read"},
            status=403
        )
        self.assertEqual(response.status_code, 403)

        # Attempt to create an item with role we don't have access to
        Role.objects.create(code="some-role", title="Some role", domain=self.piets_root_domain)
        response = self.app.post_json(
            "/api/v1.0/domainrolepermission",
            {"domain": str(self.domaina.id), "role": "some-role", "permission": "read"},
            status=404
        )
        self.assertEqual(response.status_code, 404)

        # Attempt to create an item with permission we don't have access to
        Permission.objects.create(code="some-permission", title="Some permission", domain=self.piets_root_domain)
        response = self.app.post_json(
            "/api/v1.0/domainrolepermission",
            {"domain": str(self.domaina.id), "role": "manager", "permission": "some-permission"},
            status=404
        )
        self.assertEqual(response.status_code, 404)

        # Read
        response = self.app.get(
            "/api/v1.0/domainrolepermission/%s" % drp_id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["domain"], str(self.domaina.id))
        self.assertEqual(response.json["role"], "anonymous")
        self.assertEqual(response.json["permission"], "read")
        self.assertEqual(response.json["inherit"], True)

        # List. Just check for a response.
        response = self.app.get(
            "/api/v1.0/domainrolepermission?domain=%s" % self.domaina.id,
        )
        self.assertEqual(response.status_code, 200)

        # Update
        response = self.app.put_json("/api/v1.0/domainrolepermission/%s" % drp_id, {"role": "authenticated"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["domain"], str(self.domaina.id))
        self.assertEqual(response.json["role"], "authenticated")

        # Attempt to update an item with role we don't have access to
        response = self.app.put_json(
            "/api/v1.0/domainrolepermission/%s" % drp_id,
            {"role": "some-role"},
            status=404
        )
        self.assertEqual(response.status_code, 404)

        # Attempt to update an item with permission we don't have access to
        response = self.app.put_json(
            "/api/v1.0/domainrolepermission/%s" % drp_id,
            {"permission": "some-permission"},
            status=404
        )
        self.assertEqual(response.status_code, 404)

        # Attempt to update an item that is not ours
        obj = DomainRolePermission.objects.filter(domain=self.piets_root_domain).first()
        response = self.app.put_json("/api/v1.0/domainrolepermission/%s" % obj.id, {"role": "authenticated"}, status=403)
        self.assertEqual(response.status_code, 403)

        # Delete
        response = self.app.delete("/api/v1.0/domainrolepermission/%s" % drp_id)
        self.assertEqual(response.status_code, 204)

        # Attempt to delete an item that is not ours
        obj = DomainRolePermission.objects.filter(domain=self.piets_root_domain).first()
        response = self.app.delete("/api/v1.0/domainrolepermission/%s" % obj.id, status=403)
        self.assertEqual(response.status_code, 403)

    def test_resourcerolepermission_crud(self):
        self.app.authorization = ("Basic", ("owner", "password"))

        # Create
        response = self.app.post_json("/api/v1.0/resourcerolepermission", {"resource": str(self.domaina_resourcea.id), "role": "anonymous", "permission": "read"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["resource"], str(self.domaina_resourcea.id))
        self.assertEqual(response.json["role"], "anonymous")
        self.assertEqual(response.json["permission"], "read")
        self.assertEqual(response.json["inherit"], True)

        # We'll need this later
        rrp_id = response.json["id"]

        # Create but set inherit to false
        response = self.app.post_json("/api/v1.0/resourcerolepermission", {"resource": str(self.domaina_resourcea.id), "role": "anonymous", "permission": "view", "inherit": False})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["resource"], str(self.domaina_resourcea.id))
        self.assertEqual(response.json["role"], "anonymous")
        self.assertEqual(response.json["permission"], "view")
        self.assertEqual(response.json["inherit"], False)
        self.assertTrue(ResourcePermission.objects.filter(resource=self.domaina_resourcea, permission__code="view").exists())

        # Attempt to create an item that already exists
        response = self.app.post_json(
            "/api/v1.0/resourcerolepermission",
            {"resource": str(self.domaina_resourcea.id), "role": "anonymous", "permission": "read"},
            status=422
        )
        self.assertEqual(response.status_code, 422)

        # Read
        response = self.app.get(
            "/api/v1.0/resourcerolepermission/%s" % rrp_id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["resource"], str(self.domaina_resourcea.id))
        self.assertEqual(response.json["role"], "anonymous")
        self.assertEqual(response.json["permission"], "read")
        self.assertEqual(response.json["inherit"], True)

        # List. Just check for a response.
        response = self.app.get(
            "/api/v1.0/resourcerolepermission?resource=%s" % self.domaina_resourcea.id,
        )
        self.assertEqual(response.status_code, 200)

        # Update
        response = self.app.put_json("/api/v1.0/resourcerolepermission/%s" % rrp_id, {"role": "authenticated"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["resource"], str(self.domaina_resourcea.id))
        self.assertEqual(response.json["role"], "authenticated")

        # Delete
        response = self.app.delete("/api/v1.0/resourcerolepermission/%s" % rrp_id)
        self.assertEqual(response.status_code, 204)
