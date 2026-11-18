---
name: postgres-doctor
description: Diagnose PostgreSQL connection limits, blocked locks, slow queries, and service logs.
triggers: postgres, postgresql, psql, pg_stat_activity, database lock
---
# PostgreSQL Doctor Runbook

1. Check service status & recent logs: `<systemd unit="postgresql" lines="40" />`.
2. Inspect active/idle-in-transaction connections and locks:
   `psql -c "SELECT pid, state, wait_event_type, left(query, 80) FROM pg_stat_activity WHERE state != 'idle';"`
3. Check disk/tablespace pressure with `<disk />` (WAL bloat often fills `/var/lib/postgresql`).
4. Never restart PostgreSQL without checking for long-running migrations or replication lag.
