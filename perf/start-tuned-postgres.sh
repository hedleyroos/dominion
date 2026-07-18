#!/bin/bash
# Start a throwaway Postgres container tuned for perf-testing on this box, instead of
# ad-hoc `docker run postgres:16` with stock defaults (shared_buffers=128MB, work_mem=4MB
# — roughly 16x under-provisioned relative to what's actually available). Numbers below
# mirror the philosophy of a hand-tuned "conservative for a shared machine" config,
# scaled down proportionally for this box's real resources (check with `nproc`/`free -h`
# and adjust if this container will run alongside other heavy workloads).
#
# Usage:
#   perf/start-tuned-postgres.sh [container_name] [port]
#
# Then point DATABASE_URL at it, e.g.:
#   postgresql://test:test@localhost:${port:-5432}/<dbname>
#
# Set PG_LOG_SQL=1 to make Postgres log every statement with its duration
# (opt-in, off by default — statement logging adds I/O overhead that skews
# perf numbers). View the logs with: docker logs -f <container_name>

set -euo pipefail

NAME="${1:-dominion_perf_pg}"
PORT="${2:-5432}"

PG_ARGS=(
  -c shared_buffers=4GB
  -c effective_cache_size=12GB
  -c work_mem=32MB
  -c maintenance_work_mem=1GB
  -c wal_buffers=16MB
  -c random_page_cost=1.1
  -c effective_io_concurrency=200
  -c checkpoint_timeout=15min
  -c checkpoint_completion_target=0.9
  -c min_wal_size=2GB
  -c max_wal_size=8GB
  -c wal_compression=on
  -c max_worker_processes=16
  -c max_parallel_workers=8
  -c max_parallel_workers_per_gather=4
  -c max_parallel_maintenance_workers=4
  -c max_locks_per_transaction=1024
  -c default_statistics_target=100
)

if [ -n "${PG_LOG_SQL:-}" ]; then
  # Log every statement with its duration; log_statement stays "none" to
  # avoid duplicate lines since log_min_duration_statement=0 already covers it.
  PG_ARGS+=(
    -c log_min_duration_statement=0
    -c log_statement=none
    -c "log_line_prefix=%m [%p] "
  )
fi

docker run -d --rm \
  --name "$NAME" \
  -e POSTGRES_USER=test \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=dominion_test \
  -p "${PORT}:5432" \
  postgres:16 \
  "${PG_ARGS[@]}"

MESSAGE="Started $NAME on port $PORT (tuned)."
if [ -n "${PG_LOG_SQL:-}" ]; then
  MESSAGE="$MESSAGE (SQL logging ON)"
fi
echo "$MESSAGE Stop with: docker stop $NAME"
