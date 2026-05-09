#!/bin/bash

rsync -avz -e "ssh -p 11022 -o 'StrictHostKeyChecking=no'" plankton@ocean1.plankton.mobi:/backups/dominion.sql ~/dominion.sql

sudo -u postgres dropdb dominionlive --if-exists
sudo -u postgres createdb dominionlive --owner=test
sudo -u postgres pg_restore -d dominionlive --role=test --no-owner ~/dominion.sql
