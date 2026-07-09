---
title: Sanitize stale Hermes gateway PATH drop-ins during service refresh
date: 2026-07-09
category: docs/solutions/incidents
module: hermes-gateway
problem_type: incident
component: gateway-service-manager
severity: medium
applies_when:
  - hermes-gateway.service is managed by user systemd
  - the service has drop-ins under hermes-gateway.service.d
  - a drop-in PATH references a retired Hermes checkout node_modules/.bin
symptoms:
  - "systemctl --user cat hermes-gateway.service shows a current ExecStart but a stale PATH"
  - "systemctl --user show hermes-gateway.service -p Environment includes /home/hermes/.hermes/hermes-agent/node_modules/.bin"
  - "the live gateway process can resolve helper binaries from a retired checkout"
root_cause: stale-systemd-dropin-path
resolution_type: source-fix
related_components:
  - hermes-01
  - hermes-gateway.service
  - hermes_cli.gateway
tags:
  - hermes
  - systemd
  - deploy-drift
  - rollback
---

## Summary

During the live node sweep, `hermes-01` had a current Doppler-wrapped
`ExecStart` for `/home/hermes/hermes-agent-v31`, but the same drop-in still
set `PATH` with `/home/hermes/.hermes/hermes-agent/node_modules/.bin`.
That retired directory contained an `agent-browser` shim, so any gateway
subprocess lookup could resolve a helper from the old checkout.

## Root Cause

The service refresh path reconciled the base unit and stale gateway
`ExecStart` drop-ins, but it did not inspect current drop-ins for stale
`Environment=PATH` entries. A drop-in can be correct for process launch while
still injecting retired project tooling into the service environment.

## Source Fix

`refresh_systemd_unit_if_needed()` now scans the current service drop-in
directory for `Environment=PATH` entries that include project-root
`node_modules/.bin` paths. If an entry belongs to a project root outside the
current Hermes roots, the refresh removes only that PATH entry, preserves
current venv/system/HERMES_HOME entries, writes a `.path-bak-<timestamp>`
backup, and reloads systemd.

The cleanup is reversible and narrow:

- it only inspects the current service's `.service.d` directory
- it only edits PATH entries ending in `node_modules/.bin`
- it preserves `HERMES_HOME/node_modules/.bin` because that path is profile
  state rather than a retired project checkout
- it backs up the original drop-in before writing the sanitized copy

## Verification

Source verification:

```bash
scripts/run_tests.sh tests/hermes_cli/test_gateway_service.py -k test_refresh_sanitizes_stale_gateway_path_dropin_when_execstart_current -q
scripts/run_tests.sh tests/hermes_cli/test_gateway_service.py -q
uv run --extra dev ruff check hermes_cli/gateway.py tests/hermes_cli/test_gateway_service.py
```

Live verification:

```bash
systemctl --user cat hermes-gateway.service
systemctl --user show hermes-gateway.service -p Environment
pid="$(systemctl --user show hermes-gateway.service -p MainPID --value)"
tr '\0' '\n' < "/proc/$pid/environ" | grep '^PATH='
hermes gateway restart
```

Expected result: no active gateway unit or live process `PATH` references the
retired checkout's `node_modules/.bin`; the current venv and system paths
remain; any edited drop-in has a timestamped `.path-bak-*` copy.

## Rollback

Restore the matching `.path-bak-<timestamp>` file over the active drop-in,
then run:

```bash
systemctl --user daemon-reload
systemctl --user restart hermes-gateway.service
```

Only do this as a temporary rollback. Restoring the backup also restores the
risk that gateway subprocesses resolve helper binaries from the retired
checkout.

## Durable Lesson

ExecStart identity is not the whole service contract. A gateway can launch
from the right checkout while its environment still prefers retired helper
binaries, so production verification must inspect the effective service
environment and the live process environment.
