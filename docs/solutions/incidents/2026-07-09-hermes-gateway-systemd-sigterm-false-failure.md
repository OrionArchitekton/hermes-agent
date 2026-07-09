---
title: Hermes gateway systemd restart recorded as process failure
date: 2026-07-09
category: docs/solutions/incidents
module: hermes-gateway
problem_type: incident
component: gateway-runner
severity: medium
applies_when:
  - hermes-gateway.service is managed by user systemd
  - systemd sends SIGTERM during a controlled restart or stop
  - gateway shutdown context reports under_systemd=yes
symptoms:
  - "journalctl records Main process exited, code=exited, status=1/FAILURE"
  - "journalctl records Failed with result 'exit-code' during controlled restart"
  - "the gateway immediately restarts and remains healthy"
root_cause: systemd-sigterm-classified-as-unexpected-kill
resolution_type: source-fix
related_components:
  - hermes-01
  - hermes-gateway.service
  - gateway.shutdown_forensics
tags:
  - hermes
  - false-remediation
  - systemd
  - restart
---

## Summary

During the live node sweep, hermes-01 showed controlled
`hermes-gateway.service` restarts that logged `status=1/FAILURE` and
`Failed with result 'exit-code'` even though the service immediately restarted
and stayed active.

## Root Cause

`start_gateway()` treated any unmarked SIGTERM as an unexpected external kill.
That was correct for bare process kills and container/runtime interruption, but
wrong for the user systemd service path: systemd already owns the stop/restart
decision and sends SIGTERM as part of normal service lifecycle.

## Source Fix

The signal handler now classifies SIGTERM with shutdown context
`under_systemd=yes` as a managed service-manager stop. It drains and exits
cleanly without setting the signal-initiated failure flag. Non-systemd SIGTERM
still stays on the existing nonzero crash-recovery path.

## Verification

Source verification:

```bash
uv run --extra dev pytest -q tests/gateway/test_runner_startup_failures.py::test_start_gateway_exits_cleanly_on_systemd_sigterm tests/gateway/test_runner_startup_failures.py::test_non_systemd_sigterm_is_not_classified_as_managed_restart
scripts/run_tests.sh tests/gateway/test_runner_startup_failures.py -q
```

Live verification:

```bash
ssh hermes-01 'systemctl --user restart hermes-gateway.service'
ssh hermes-01 'journalctl --user -u hermes-gateway.service --since -2m --no-pager'
ssh hermes-01 'systemctl --user is-active hermes-gateway.service'
```

## Rollback

Deploy the previous Hermes Agent release and restart the user service. Rollback
restores the false-failure journal lines for controlled restarts, so alerting
based on gateway failure count should be treated as noisy until the fix is
redeployed.

## Durable Lesson

Do not infer failure solely from receipt of SIGTERM. The shutdown classifier
must include supervisor context so controlled service-manager lifecycle events
do not become false remediation signals.
