import django
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app", "src"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")

django.setup()
