#!/bin/bash
CELERY_ALWAYS_EAGER=False ./ve/bin/celery --app app.celery  worker  --loglevel=info -n triplea
