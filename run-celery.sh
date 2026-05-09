#!/bin/bash
CELERY_ALWAYS_EAGER=False ./ve/bin/celery --app dominion.conf.celery  worker  --loglevel=info -n dominion
