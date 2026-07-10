#!/usr/bin/env bash
# Wipe MAAT's ledger for a clean demo take (run on the deployment host).
# vLLM keeps running; only the gateway restarts with a fresh database.
set -e
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.amd.yml"
$COMPOSE stop maat
rm -f data/maat.db data/maat.db-shm data/maat.db-wal
$COMPOSE start maat
sleep 3
curl -s localhost:8080/healthz && echo " — ledger is clean"
