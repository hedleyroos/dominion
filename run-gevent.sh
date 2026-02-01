#!/bin/bash

./ve/bin/gunicorn  --bind 0.0.0.0:8090 --workers=12    --access-logfile - --worker-class gevent patched:app
