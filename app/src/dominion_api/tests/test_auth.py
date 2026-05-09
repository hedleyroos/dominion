from tests.base import BaseTestCase
from dominion_api.auth import apikey_auth, basic_auth


class BasicAuthTestCase(BaseTestCase):
    async def test_valid_credentials_return_user_info(self):
        result = await basic_auth("owner", "password")
        self.assertIsNotNone(result)
        self.assertEqual(result["uid"], "owner")
        self.assertEqual(result["scope"], "")
        self.assertEqual(result["user"], self.owner)

    async def test_wrong_password_returns_none(self):
        result = await basic_auth("owner", "wrongpassword")
        self.assertIsNone(result)

    async def test_nonexistent_username_returns_none(self):
        result = await basic_auth("nobody", "password")
        self.assertIsNone(result)

    async def test_returns_correct_user_object(self):
        result = await basic_auth("jan", "password")
        self.assertIsNotNone(result)
        self.assertEqual(result["user"].username, "jan")

    async def test_required_scopes_ignored(self):
        # required_scopes parameter is accepted but not used.
        result = await basic_auth("owner", "password", required_scopes=["some_scope"])
        self.assertIsNotNone(result)


class ApiKeyAuthTestCase(BaseTestCase):
    async def test_valid_api_key_returns_user_info(self):
        result = await apikey_auth(str(self.owner.api_key))
        self.assertIsNotNone(result)
        self.assertEqual(result["uid"], self.owner.username)
        self.assertEqual(result["scope"], "")

    async def test_invalid_api_key_returns_none(self):
        import uuid
        result = await apikey_auth(str(uuid.uuid4()))
        self.assertIsNone(result)

    async def test_returns_correct_user_for_key(self):
        result = await apikey_auth(str(self.jan.api_key))
        self.assertIsNotNone(result)
        self.assertEqual(result["uid"], "jan")

    async def test_required_scopes_ignored(self):
        result = await apikey_auth(str(self.owner.api_key), required_scopes=["x"])
        self.assertIsNotNone(result)
