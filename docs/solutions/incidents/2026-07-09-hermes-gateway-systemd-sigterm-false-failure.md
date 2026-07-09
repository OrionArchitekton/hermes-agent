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
  - generated systemd unit writes a planned-stop marker in ExecStop
  - ExecStart may be wrapped by a process supervisor such as doppler
  - systemd sends SIGTERM after ExecStop during a controlled restart or stop
symptoms:
  - "journalctl records Main process exited, code=exited, status=1/FAILURE"
  - "journalctl records Failed with result 'exit-code' during controlled restart"
  - "the gateway immediately restarts and remains healthy"
root_cause: systemd-stop-lacked-planned-stop-marker-before-sigterm
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

`start_gateway()` correctly treated unmarked SIGTERM as an unexpected external
kill. That preserves crash recovery for bare `kill -TERM`, container/runtime
interruption, and other unexpected process-manager signals. The missing piece
was in the generated systemd unit: direct `systemctl --user restart
hermes-gateway.service` did not write the existing planned-stop marker before
systemd sent SIGTERM, so a controlled service-manager stop looked identical to
an unexpected kill.

## Source Fix

The generated systemd unit now runs a shell-wrapped
`python -m gateway.systemd_planned_stop "$MAINPID"` in `ExecStop`, so systemd's
`MAINPID` value is expanded at stop time. The helper writes the planned-stop
marker for that PID, or for the Python gateway child when `MAINPID` is a wrapper
such as `doppler`. The existing signal handler then drains and exits cleanly.
An unmarked SIGTERM, even when the gateway is launched by systemd, still stays
on the existing nonzero crash-recovery path.

## Verification

Source verification:

```bash
uv run --extra dev pytest -q tests/gateway/test_runner_startup_failures.py::test_start_gateway_exits_cleanly_on_systemd_sigterm_with_planned_marker tests/gateway/test_runner_startup_failures.py::test_unmarked_systemd_sigterm_remains_signal_initiated_shutdown
scripts/run_tests.sh tests/gateway/test_runner_startup_failures.py -q
scripts/run_tests.sh tests/gateway/test_systemd_planned_stop.py tests/hermes_cli/test_gateway_service.py -q
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

Do not infer intent from systemd ancestry. A supervised process can receive
manual SIGTERM too, so controlled service-manager lifecycle must be marked
explicitly before the runtime treats it as a clean stop.
