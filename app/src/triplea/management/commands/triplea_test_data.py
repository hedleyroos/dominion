import random
import string
import uuid

from django.db import transaction

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from oauth2_provider.models import Application

from triplea.models import Domain, Role, UserDomainRole


def get_password(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


class Command(BaseCommand):
    help = "Set up Triple A with minimal required data. If setting.DEBUG is true then predictable values are used, else random values."

    @transaction.atomic
    def handle(self, *args, **options):

        # Admin user
        User = get_user_model()
        try:
            user = User.objects.get(username="admin")
        except User.DoesNotExist:
            user = User.objects.create(id="f65e8752-df99-458a-9bf1-f5e926fda922", username="admin", email="admin@aaa.com", is_staff=True, is_superuser=True)
            password = "local" if settings.DEBUG else get_password()
            user.set_password(password)
            user.api_key = "c843f0f2-4a3a-4290-872d-0eba17bdc539" if settings.DEBUG else uuid.uuid4()
            user.save()
            print(f"Created user {user.username} with password {password} and API key {user.api_key}.")

        # TODO: everything from here on must live in triplea-plankton, not this project

        # Inventory system specific setup

        # Inventory OIDC application
        # TODO: this needs to consider DEBUG as well
        try:
            app = Application.objects.get(client_id="bzsmU5P8XG9IE4xYjKP314EEwg6ebbaUDVQGYtla")
        except Application.DoesNotExist:
            app = Application.objects.create(
                redirect_uris="http://localhost:8001/oidc/callback/",
                client_type="confidential",
                authorization_grant_type="authorization-code",
                algorithm="HS256"
            )
        app.client_id = "bzsmU5P8XG9IE4xYjKP314EEwg6ebbaUDVQGYtla"
        app.client_secret = "er291kW1ZR61ZGYzAFlh7uDMCOXBtdS3cHq057YjskrxKaq4UFZbZ4VpQPeTGrEhJPBLSPEBK6HBFoTffU3GRxWg0hi3ODCpcOYKCJQcOfGpn1o0Jo1nNOSmAglpXYoY"
        app.save()

        # Domain
        try:
            domain = Domain.objects.get(id="88b3343c-af7a-4285-8ebc-acd378abb66f")
        except Domain.DoesNotExist:
            domain = Domain.objects.create(
                id="88b3343c-af7a-4285-8ebc-acd378abb66f",
                title="Inventory root domain",
                owner=user
            )

        # Inventory API user. Much like admin, except not staff or superuser.
        try:
            api_user = User.objects.get(username="inventory-api")
        except User.DoesNotExist:
            api_user = User.objects.create(id="c5c6a2e6-eebe-4716-b185-2036e812f3a6", username="inventory-api", email="inventory-api@aaa.com")
            password = "local" if settings.DEBUG else get_password()
            api_user.set_password(password)
            api_user.api_key = "2646354c-9c4e-4d0b-ae3c-f83285e2589a" if settings.DEBUG else uuid.uuid4()
            api_user.save()
            print(f"Created user {api_user.username} with password {password} and API key {api_user.api_key}.")

        # Grant required roles to API user
        udr, dc = UserDomainRole.objects.get_or_create(user=api_user, domain=domain, role=Role.objects.get(code="owner"))

        # Camera system specific setup

        # Camera OIDC application
        # TODO: this needs to consider DEBUG as well
        try:
            app = Application.objects.get(client_id="czsmU5P8XG9IE4xYjKP314EEwg6ebbaUDVQGYtlb")
        except Application.DoesNotExist:
            app = Application.objects.create(
                redirect_uris="http://localhost:8001/oidc/callback/",
                client_type="confidential",
                authorization_grant_type="authorization-code",
                algorithm="HS256"
            )
        app.client_id = "czsmU5P8XG9IE4xYjKP314EEwg6ebbaUDVQGYtlb"
        app.client_secret = "dr291kW1ZR61ZGYzAFlh7uDMCOXBtdS3cHq057YjskrxKaq4UFZbZ4VpQPeTGrEhJPBLSPEBK6HBFoTffU3GRxWg0hi3ODCpcOYKCJQcOfGpn1o0Jo1nNOSmAglpXYoZ"
        app.save()

        # Domain
        try:
            domain = Domain.objects.get(id="98b3343c-af7a-4285-8ebc-acd378abb66a")
        except Domain.DoesNotExist:
            domain = Domain.objects.create(
                id="98b3343c-af7a-4285-8ebc-acd378abb66a",
                title="Camera root domain",
                owner=user
            )

        # Camera API user. Much like admin, except not staff or superuser.
        try:
            api_user = User.objects.get(username="camera-api")
        except User.DoesNotExist:
            api_user = User.objects.create(id="d5c6a2e6-eebe-4716-b185-2036e812f3a7", username="camera-api", email="camera-api@aaa.com")
            password = "local" if settings.DEBUG else get_password()
            api_user.set_password(password)
            api_user.api_key = "3646354c-9c4e-4d0b-ae3c-f83285e2589b" if settings.DEBUG else uuid.uuid4()
            api_user.save()
            print(f"Created user {api_user.username} with password {password} and API key {api_user.api_key}.")

        # Grant required roles to API user
        udr, dc = UserDomainRole.objects.get_or_create(user=api_user, domain=domain, role=Role.objects.get(code="owner"))
