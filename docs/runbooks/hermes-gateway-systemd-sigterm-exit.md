---
verified: 2026-07-09
review_after: 2026-10-09
topics: [hermes-agent, hermes-01, gateway, systemd, restart, runbooks]
references:
  - gateway/run.py
  - gateway/systemd_planned_stop.py
  - gateway/shutdown_forensics.py
  - hermes_cli/gateway.py
  - tests/gateway/test_runner_startup_failures.py
  - tests/hermes_cli/test_gateway_service.py
---

# Hermes Gateway Systemd SIGTERM Exit

Hermes gateway runs on hermes-01 as the user systemd service
`hermes-gateway.service`. During `systemctl --user restart`, systemd sends
SIGTERM to the process it owns. The generated unit runs a shell-wrapped
`python -m gateway.systemd_planned_stop "$MAINPID"` in `ExecStop` before that
signal, writing the same planned-stop marker used by `hermes gateway stop`.
If `MAINPID` is a wrapper such as `doppler`, the helper resolves the Python
gateway child and writes the marker for the process that will run the signal
handler. That stop is intentional and must drain cleanly instead of returning a
process failure.

The service refresh path also reconciles current-service drop-ins:

- stale `ExecStart` drop-ins whose Python virtualenv is rooted outside the
  current Hermes checkout are renamed to `.disabled-<timestamp>`
- stale `Environment=PATH` entries that point at a retired project
  `node_modules/.bin` are removed in place after writing a
  `.path-bak-<timestamp>` backup

Both repairs run before daemon reload and preserve rollback files.

## Expected Behavior

- SIGTERM with a valid planned-stop marker exits cleanly after drain.
- SIGTERM with `under_systemd=yes` but without that marker remains a
  signal-initiated shutdown and exits nonzero unless a takeover marker exists.
- Planned takeover, explicit gateway stop, Ctrl+C, and restart-request paths
  keep their existing behavior.

## Validation

Source validation:

```bash
scripts/run_tests.sh tests/gateway/test_runner_startup_failures.py -q
scripts/run_tests.sh tests/gateway/test_systemd_planned_stop.py tests/hermes_cli/test_gateway_service.py -q
uv run --extra dev ruff check gateway/run.py gateway/systemd_planned_stop.py tests/gateway/test_runner_startup_failures.py tests/gateway/test_systemd_planned_stop.py tests/hermes_cli/test_gateway_service.py
```

Runtime validation on hermes-01:

```bash
systemctl --user restart hermes-gateway.service
journalctl --user -u hermes-gateway.service --since -2m --no-pager
systemctl --user status hermes-gateway.service --no-pager
```

Expected result: the service restarts and remains active without a new
`status=1/FAILURE` or `Failed with result 'exit-code'` line for the controlled
restart window, and the installed unit contains
`ExecStop=-/bin/sh -c 'exec ... -m gateway.systemd_planned_stop "$MAINPID"'`.
The effective unit must not include an active `*.conf` drop-in whose
`ExecStart` points at a retired checkout such as
`/home/hermes/.hermes/hermes-agent/venv/bin/python`, and neither
`systemctl --user show hermes-gateway.service -p Environment` nor the live
gateway process environment should include a retired project
`node_modules/.bin` path such as
`/home/hermes/.hermes/hermes-agent/node_modules/.bin`.

## Rollback

Deploy the previous Hermes Agent release and restart `hermes-gateway.service`.
If a rollback reintroduces nonzero controlled-restart exits, treat those journal
lines as known restart-noise only for the rollback window and restore this fix
before relying on gateway failure counts.

If rollback specifically needs a disabled drop-in, rename the matching
`*.disabled-<timestamp>` file back to `.conf`, run
`systemctl --user daemon-reload`, then restart the gateway.

If rollback specifically needs a sanitized PATH drop-in, restore the matching
`*.path-bak-<timestamp>` file over the active `.conf`, run
`systemctl --user daemon-reload`, then restart the gateway.

## Durable Lesson

Failure semantics must be explicit at the supervisor boundary. Being launched
by systemd does not prove systemd sent a given SIGTERM, so the service unit
must mark controlled stops before the gateway treats them as clean.
