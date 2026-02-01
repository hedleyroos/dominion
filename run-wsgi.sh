#!/bin/bash

./ve/bin/uwsgi  --http :8090 --callable app --file main.py --processes 2 --threads 4 --enable-threads
