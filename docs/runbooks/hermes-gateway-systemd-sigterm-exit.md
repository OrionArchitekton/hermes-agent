---
verified: 2026-07-09
review_after: 2026-10-09
topics: [hermes-agent, hermes-01, gateway, systemd, restart, runbooks]
references:
  - gateway/run.py
  - gateway/shutdown_forensics.py
  - tests/gateway/test_runner_startup_failures.py
---

# Hermes Gateway Systemd SIGTERM Exit

Hermes gateway runs on hermes-01 as the user systemd service
`hermes-gateway.service`. During `systemctl --user restart`, systemd sends
SIGTERM to the process it owns. That stop is intentional and must drain
cleanly instead of returning a process failure.

## Expected Behavior

- SIGTERM with shutdown context `under_systemd=yes` exits cleanly after drain.
- SIGTERM without a systemd shutdown context remains a signal-initiated
  shutdown and exits nonzero unless a planned-stop or takeover marker exists.
- Planned takeover, explicit gateway stop, Ctrl+C, and restart-request paths
  keep their existing behavior.

## Validation

Source validation:

```bash
scripts/run_tests.sh tests/gateway/test_runner_startup_failures.py -q
uv run --extra dev ruff check gateway/run.py tests/gateway/test_runner_startup_failures.py
```

Runtime validation on hermes-01:

```bash
systemctl --user restart hermes-gateway.service
journalctl --user -u hermes-gateway.service --since -2m --no-pager
systemctl --user status hermes-gateway.service --no-pager
```

Expected result: the service restarts and remains active without a new
`status=1/FAILURE` or `Failed with result 'exit-code'` line for the controlled
restart window.

## Rollback

Deploy the previous Hermes Agent release and restart `hermes-gateway.service`.
If a rollback reintroduces nonzero controlled-restart exits, treat those journal
lines as known restart-noise only for the rollback window and restore this fix
before relying on gateway failure counts.

## Durable Lesson

Failure semantics belong to the supervisor boundary. Once systemd owns a stop
or restart, the process should not convert that same signal into a crash signal.
