---
title: Disable stale Hermes gateway ExecStart drop-ins during service refresh
date: 2026-07-09
category: docs/solutions/incidents
module: hermes-gateway
problem_type: incident
component: gateway-service-manager
severity: medium
applies_when:
  - hermes-gateway.service is managed by user systemd
  - the service has drop-ins under hermes-gateway.service.d
  - a drop-in ExecStart points at a retired Hermes checkout
symptoms:
  - "systemctl --user cat hermes-gateway.service shows an older ExecStart before the current override"
  - "a lower-priority drop-in references /home/hermes/.hermes/hermes-agent/venv/bin/python"
  - "removing a later override would revive a retired Hermes checkout"
root_cause: stale-systemd-dropin
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

During the live node sweep, `hermes-01` still carried
`90-doppler-wrap.conf` under `hermes-gateway.service.d`. A later
`95-upgrade-v31.conf` made the effective `ExecStart` use
`/home/hermes/hermes-agent-v31`, but the older drop-in still pointed at the
retired `/home/hermes/.hermes/hermes-agent` checkout.

## Root Cause

The service refresh path repaired the main `hermes-gateway.service` file but
did not inspect current-service drop-ins. A stale drop-in can be masked by a
later override and still remain dangerous: if the later file is removed or
rewritten, systemd falls back to the older `ExecStart`.

## Source Fix

`refresh_systemd_unit_if_needed()` now scans the current service drop-in
directory for `ExecStart` lines that launch the Hermes gateway from a Python
virtualenv rooted outside the current `PROJECT_ROOT`. Matching drop-ins are
renamed to `.disabled-<timestamp>` and systemd is daemon-reloaded. Current-root
drop-ins are preserved.

The cleanup is reversible and narrow:

- it only inspects the current service's `.service.d` directory
- it only targets gateway `ExecStart` drop-ins
- it preserves the file content by renaming, not deleting
- it does not touch environment-only drop-ins or current-checkout wrappers

## Verification

Source verification:

```bash
uv run --extra dev pytest -q tests/hermes_cli/test_gateway_service.py::TestSystemdServiceRefresh::test_refresh_disables_stale_gateway_execstart_dropin_when_unit_current tests/hermes_cli/test_gateway_service.py::TestSystemdServiceRefresh::test_refresh_keeps_current_gateway_execstart_dropin
uv run --extra dev pytest -q tests/hermes_cli/test_gateway_service.py
uv run --extra dev ruff check hermes_cli/gateway.py tests/hermes_cli/test_gateway_service.py
```

Live verification:

```bash
systemctl --user cat hermes-gateway.service
hermes gateway restart
systemctl --user cat hermes-gateway.service
systemctl --user status hermes-gateway.service --no-pager
```

Expected result: the retired-checkout drop-in is renamed to
`*.disabled-<timestamp>`, the effective `ExecStart` points at the current
checkout, and the gateway remains active after restart.

## Rollback

Rename the disabled drop-in back to its original `.conf` name, then run:

```bash
systemctl --user daemon-reload
systemctl --user restart hermes-gateway.service
```

Only do this as a temporary rollback. Restoring a stale drop-in also restores
the risk that a later override removal will revive a retired checkout.

## Durable Lesson

The effective unit can be correct while masked drop-ins still preserve a stale
future fallback. Service refresh must reconcile the current unit and its
drop-in stack, not just the base unit file.
