#!/usr/bin/env python
"""Profile the resource access check — count, time, and categorise every SQL query.

Captures queries via Postgres-side statement logging (``log_min_duration_statement=0``)
rather than Django's ``DEBUG=True`` + ``connection.queries``. DEBUG buffers every query's
SQL and params in memory and changes ORM behaviour vs. production; more importantly, the
access check is async, so its ORM calls can run on threadpool connections that DEBUG's
per-connection capture misses. Postgres-side logging captures every statement regardless
of which connection or thread ran it.

The cross-request Django permission cache is disabled for this run (``DISABLE_PERM_CACHE``)
so each measured call recomputes from scratch; the request-scoped contextvar cache in
``dominion/utils.py`` stays intact.

Usage:
    PG_LOG_SQL=1 perf/start-tuned-postgres.sh

    DATABASE_URL=postgresql://test:test@localhost:5432/dominion_test \\
        PG_CONTAINER=dominion_perf_pg \\
        python perf/profile_resource_access.py

    DATABASE_URL=... python perf/profile_resource_access.py --scale full
    DATABASE_URL=... python perf/profile_resource_access.py --scale full --explain

Environment:
    PG_CONTAINER   Name of the running Postgres container to read logs from via
                   ``docker logs`` (default: dominion_perf_pg, matching
                   perf/start-tuned-postgres.sh).
"""

import argparse
import os
import re
import subprocess
import sys
import time
import uuid
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dominion.conf.settings")
os.environ.setdefault("DEBUG", "False")
os.environ.setdefault("DISABLE_PERM_CACHE", "True")
os.environ.setdefault("SECRET_KEY", "perftesting123")

import django
django.setup()

from asgiref.sync import async_to_sync
from django.core.cache import cache as django_cache
from django.db import connection

from dominion.utils import reset_request_cache, user_has_permission_for_resource

from perf.perfload import (
    SCALES, _apply_scale, clear_perf_data, load_test_data,
    setup_additional_user_domain_roles, setup_custom_roles, setup_domains,
    setup_resource_permissions, setup_resources, setup_user_resource_roles,
    setup_users,
)

# Matches just the timestamp+pid prefix shared by every log line, e.g.:
#   2024-01-01 12:00:00.000 UTC [123] ...
LOG_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ \S+ \[\d+\] ")

# Matches a Postgres duration-log line produced by log_min_duration_statement=0 with
# log_line_prefix='%m [%p] '. Django's psycopg3 backend sends parameterised queries via
# the extended query protocol, so most queries log as separate parse/bind/execute lines
# with placeholders ($1, $2, ...) rather than one literal "statement: ..." line, e.g.:
#   2024-01-01 12:00:00.000 UTC [123] LOG:  duration: 0.123 ms  execute <unnamed>: SELECT $1
LOG_ENTRY_PATTERN = re.compile(
    LOG_PREFIX_PATTERN.pattern
    + r"LOG:  duration: (?P<duration_ms>[\d.]+) ms  "
    r"(?P<verb>statement|parse|bind|execute)(?: \S+)?: (?P<sql>.*)$"
)

# Matches the DETAIL line Postgres logs immediately after a bind/execute step, carrying
# the real parameter values for that step's placeholders, e.g.:
#   2024-01-01 12:00:00.000 UTC [123] DETAIL:  parameters: $1 = 'some-value'
LOG_DETAIL_PATTERN = re.compile(LOG_PREFIX_PATTERN.pattern + r"DETAIL:  (?P<detail>parameters: .*)$")


def _parse_log_entries(log_text: str) -> list[dict]:
    """Parse Postgres duration-log lines into query dicts, shaped like the old
    ``connection.queries`` entries: ``{"sql": str, "time": str(seconds)}``.

    One entry is emitted per logical query: for ``execute``, using its own duration
    (``parse``/``bind`` are separate protocol round-trips for the same query and are
    not counted again, so one app-level query call stays one entry); for ``statement``
    (simple-protocol queries such as BEGIN/COMMIT), directly. A following DETAIL line's
    real parameter values are merged into the entry's SQL text, since the placeholder
    text alone ("SELECT $1") can't otherwise be searched for a sentinel marker or read
    for its real values. Postgres also logs a multi-line statement as one duration line
    followed by the statement's remaining lines with no log prefix, so any such
    continuation lines are accumulated onto the current entry too.
    """
    entries = []
    pending = None
    for line in log_text.splitlines():
        match = LOG_ENTRY_PATTERN.match(line)
        if match:
            if pending is not None:
                entries.append(pending)
                pending = None
            if match.group("verb") in ("statement", "execute"):
                duration_ms = float(match.group("duration_ms"))
                pending = {"sql": match.group("sql"), "time": str(duration_ms / 1000)}
            continue
        detail_match = LOG_DETAIL_PATTERN.match(line)
        if detail_match and pending is not None:
            pending["sql"] += f"  [{detail_match.group('detail')}]"
            continue
        if pending is not None and not LOG_PREFIX_PATTERN.match(line):
            pending["sql"] += "\n" + line
            continue
        if pending is not None:
            entries.append(pending)
            pending = None
    if pending is not None:
        entries.append(pending)
    return entries


def _find_marker_index(entries: list[dict], marker: str) -> int:
    for index, entry in enumerate(entries):
        if marker in entry["sql"]:
            return index
    raise RuntimeError(f"Sentinel marker not found in Postgres logs: {marker}")


def capture_queries(subject_id: str, resource_id: str) -> tuple[bool, float, list[dict]]:
    """Run the access check once, timed, and return its queries via Postgres logs.

    Brackets the measured call with two sentinel queries so their literal text
    marks the boundary in the container's Postgres logs, then reads those logs
    with ``docker logs`` and slices out everything strictly between the markers.
    """
    container = os.environ.get("PG_CONTAINER", "dominion_perf_pg")
    token = uuid.uuid4().hex
    start_marker = f"PROFILE_START_{token}"
    end_marker = f"PROFILE_END_{token}"

    with connection.cursor() as cursor:
        cursor.execute("SELECT %s", [start_marker])

    t0 = time.monotonic()
    result = async_to_sync(user_has_permission_for_resource)(subject_id, "read", resource_id)
    elapsed = time.monotonic() - t0

    with connection.cursor() as cursor:
        cursor.execute("SELECT %s", [end_marker])

    log_process = subprocess.run(
        ["docker", "logs", container], capture_output=True, text=True, check=True,
    )
    log_text = log_process.stdout + log_process.stderr
    entries = _parse_log_entries(log_text)
    start_index = _find_marker_index(entries, start_marker)
    end_index = _find_marker_index(entries, end_marker)
    queries = entries[start_index + 1:end_index]
    return result, elapsed, queries


def setup_data(scale: str):
    args = argparse.Namespace(
        scale=scale, users=None, domains=None, resources=None,
        concurrency=None, duration=None,
    )
    _apply_scale(args)
    django_cache.clear()
    clear_perf_data()

    print(f"\n=== Setting up {scale} data ===")
    user_ids = setup_users(args.users)
    root_domains, child_domains, grandchild_domains = setup_domains(args.domains, user_ids)
    roles_by_root = setup_custom_roles(root_domains)
    setup_additional_user_domain_roles(root_domains, child_domains, grandchild_domains, user_ids, roles_by_root)
    root_resource_ids, _ = setup_resources(root_domains, child_domains, user_ids, args.resources)
    setup_resource_permissions(root_resource_ids, root_domains, roles_by_root)
    setup_user_resource_roles(root_resource_ids, user_ids, roles_by_root, root_domains)

    data = load_test_data()
    if not data.domain_checker_pairs:
        print("ERROR: no domain checker pairs."); sys.exit(1)

    domain_id, checker_id = data.domain_checker_pairs[0]

    from dominion.models import Resource
    resource = Resource.objects.filter(domain_id=domain_id, urn__startswith="perf:root:").first()
    if resource is None:
        resource = Resource.objects.filter(urn__startswith="perf:root:").first()
    if resource is None:
        print("ERROR: no perf resources."); sys.exit(1)

    subject_id = data.user_ids[1] if len(data.user_ids) > 1 else data.user_ids[0]
    print(f"  Checker  : {checker_id}")
    print(f"  Subject  : {subject_id}")
    print(f"  Resource : {resource.id}  (domain={resource.domain_id})")
    print(f"  Permission: read")
    return checker_id, subject_id, str(resource.id)


def categorise(sql: str) -> str:
    s = sql.strip().upper()
    tables = [
        "dominion_userresourcerole", "dominion_resourcerolepermission",
        "dominion_resourcepermission", "dominion_resource",
        "dominion_userdomainrole", "dominion_domainrolepermission",
        "dominion_domainpermission", "dominion_domain", "dominion_role",
        "dominion_user", "dominion_permission", "django_cache",
    ]
    for t in tables:
        if t.upper() in s:
            return f"SELECT {t}"
    if "SELECT" in s: return "SELECT other"
    if "INSERT" in s: return "INSERT"
    if "UPDATE" in s: return "UPDATE"
    if "DELETE" in s: return "DELETE"
    if "SAVEPOINT" in s or "RELEASE" in s: return "SAVEPOINT"
    return "OTHER"


def profile(scale: str, explain: bool = False):
    print(f"\n{'='*72}\n  Resource Access Check Profile ({scale})\n{'='*72}")

    checker_id, subject_id, resource_id = setup_data(scale)
    django_cache.clear()
    reset_request_cache()

    # Warm-up to initialise connection pools and caches; its queries aren't inspected.
    async_to_sync(user_has_permission_for_resource)(subject_id, "read", resource_id)
    django_cache.clear()
    reset_request_cache()

    # Cold-cache measurement, captured via Postgres-side query logging.
    print("\n--- Running user_has_permission_for_resource (cold cache) ---")
    result, elapsed, queries = capture_queries(subject_id, resource_id)

    print(f"\nResult: {result}  (wall: {elapsed*1000:.1f} ms,  queries: {len(queries)})")

    # Grouped breakdown.
    by_cat = defaultdict(list)
    for q in queries:
        by_cat[categorise(q["sql"])].append(q)

    print("\n--- By table ---")
    for cat in sorted(by_cat):
        qs = by_cat[cat]
        print(f"  {cat:48s} {len(qs):>3d}  {sum(float(q['time']) for q in qs)*1000:>8.2f} ms")

    print(f"\n--- All queries ({len(queries)}) ---")
    for i, q in enumerate(queries, 1):
        sql = q["sql"].replace("\n", " ").replace("  ", " ")
        if len(sql) > 180:
            sql = sql[:177] + "..."
        print(f"  [{i:>3d}] {float(q['time'])*1000:>8.2f} ms  {sql}")

    slowest = sorted(queries, key=lambda q: float(q["time"]), reverse=True)[:5]
    print("\n--- Top 5 slowest ---")
    for q in slowest:
        sql = q["sql"].replace("\n", " ").replace("  ", " ")
        if len(sql) > 180:
            sql = sql[:177] + "..."
        print(f"  {float(q['time'])*1000:>8.2f} ms  {sql}")

    if explain:
        print("\n--- EXPLAIN ANALYZE (slowest 5) ---")
        for q in slowest:
            sql = q["sql"]
            if not sql.strip().upper().startswith("SELECT"):
                continue
            print(f"\n  {sql[:120]}...")
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"EXPLAIN ANALYZE {sql}")
                    for row in cursor.fetchall():
                        print(f"    {row[0]}")
            except Exception as exc:
                print(f"    EXPLAIN failed: {exc}")

    print(f"\n{'='*72}\n  Done — {len(queries)} queries in {elapsed*1000:.1f} ms\n{'='*72}")


def main():
    p = argparse.ArgumentParser(description="Profile resource access check queries.")
    p.add_argument("--scale", choices=sorted(SCALES), default="medium")
    p.add_argument("--explain", action="store_true")
    profile(**vars(p.parse_args()))


if __name__ == "__main__":
    main()
