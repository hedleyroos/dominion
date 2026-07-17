#!/usr/bin/env python
import os
import sys

import connexion
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


# Configure Django so the ORM works
if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dominion.conf.settings")

application = get_wsgi_application()

# Imported after Django is configured — dominion.utils pulls in dominion.models,
# which requires the app registry to be ready.
from dominion.utils import reset_request_cache

# Create Connexion app
app = connexion.AsyncApp("main", specification_dir='dominion/conf/')
# A wildcard origin cannot be combined with credentialed requests (browsers reject
# it), so only honour allow_credentials when explicit origins are configured.
_cors_origins = settings.CORS_ALLOWED_ORIGINS
_cors_allow_credentials = settings.CORS_ALLOW_CREDENTIALS and "*" not in _cors_origins
app.add_middleware(
    CORSMiddleware,
    position=connexion.middleware.MiddlewarePosition.BEFORE_ROUTING,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_api(
    'openapi.yaml',
    resolver=connexion.resolver.RestyResolver('dominion.api'),
    strict_validation=True,
)


# Replicate Django's request hooks to clean up database connections.
class DjangoConnectionsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await sync_to_async(close_old_connections)()
        reset_request_cache()
        await self.app(scope, receive, send)


app.add_middleware(
    DjangoConnectionsMiddleware, connexion.middleware.MiddlewarePosition.BEFORE_SECURITY
)


if __name__ == "__main__":
    app.run("main:app", port=8090)
