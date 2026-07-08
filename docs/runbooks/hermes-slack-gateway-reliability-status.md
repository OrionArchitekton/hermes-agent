---
title: Hermes Slack Gateway Reliability Status
verified: 2026-07-07
review_after: 2026-10-07
topics: [hermes-agent, slack, gateway, cron, status, observability]
references:
  - hermes_cli/gateway.py
  - gateway/status.py
  - cron/jobs.py
  - tests/hermes_cli/test_gateway_runtime_health.py
---

# Hermes Slack Gateway Reliability Status

This runbook covers the read-only Slack reliability warnings shown by
`hermes gateway status`.

## What It Reports

- Slack adapter disconnects recorded in `gateway_state.json`.
- Slack cron delivery failures recorded as `last_delivery_error` on jobs that
  target Slack directly or through a Slack origin.

It does not restart `hermes-gateway.service`, edit config, rotate tokens, or
send Slack messages.

## Validate

Run:

```bash
hermes gateway status
```

If Slack is disconnected or Slack-targeted cron jobs are failing, the output
contains a "Recent gateway health" section with warning lines.

For source validation:

```bash
pytest tests/hermes_cli/test_gateway_runtime_health.py -q
```

## Monitor

- `hermes gateway status` for live operator checks.
- `hermes cron list --all` for per-job delivery errors and schedules.
- `journalctl --user -u hermes-gateway -n 100 -l` when the status summary points
  at adapter or delivery failures.

## Rollout

Ship the code with the normal Hermes agent deploy path for the target host. No
config migration is required. The status warnings appear only when existing
runtime or cron state contains a relevant failure.

## Rollback

Revert the code change that adds Slack reliability summary lines to
`hermes_cli/gateway.py` and redeploy the previous Hermes agent build. No runtime
state or Slack credentials need rollback.
