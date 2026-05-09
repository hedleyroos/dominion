#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-true}" != "false" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
