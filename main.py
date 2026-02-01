#!/usr/bin/env python
import os
import sys

import connexion
from connexion.resolver import RestyResolver
from django.conf import settings
from django.core import management
from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections


# Adjust path
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/app/src')

# Configure Django so the ORM works
if not settings.configured:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    application = get_wsgi_application()

# Start Connexion
app = connexion.App(__name__, specification_dir='app/')
app.add_api('openapi.yaml', resolver=RestyResolver('triplea_api'), strict_validation=True)

# Replicate Django's request hooks to clean up database connections
@app.app.before_request
def on_before_request():
    close_old_connections()

if __name__ == "__main__":
    app.run(port=8090)
