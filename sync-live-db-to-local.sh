#!/bin/bash

rsync -avz -e "ssh -p 11022 -o 'StrictHostKeyChecking=no'" plankton@ocean1.plankton.mobi:/backups/triplea.sql ~/triplea.sql

sudo -u postgres dropdb triplealive --if-exists
sudo -u postgres createdb triplealive --owner=test
sudo -u postgres pg_restore -d triplealive --role=test --no-owner ~/triplea.sql
