import django
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dominion.conf.settings")

django.setup()
