---
title: Hermes Cron - Pre-run script failure status
verified: 2026-07-05
review_after: 2026-10-05
topics: [hermes-agent, hermes-01, cron, scheduler, runbooks]
references:
  - cron/scheduler.py
  - tests/cron/test_scheduler.py
  - tests/cron/test_cron_script.py
---

# Hermes Cron Pre-run Script Failure Status

Hermes cron jobs may use a pre-run script to collect data before the agent
generates a report. If the script exits non-zero, or exits zero while the first
non-empty output line emits explicit machine-shaped failure evidence such as
`rc=124`, `exited 1`, `script timed out`, or `timeout after 100s`, the job must
preserve a failed cron status even when the agent successfully reports the
script failure to the operator.

## Symptom

A scheduled job delivers an alert or timeout report but `cron/jobs.json` records
`last_status: ok`. Dashboards and downstream status checks then show a false
green run even though no usable script data was produced.

## Root Cause

The default LLM cron path treated "the agent produced a response" as the job
success condition. That allowed a wrapper script to report its own failure in
stdout, especially after formatting a short operator alert and exiting zero,
while the scheduler still returned success.

## Rollout

1. Deploy the `hermes-agent` scheduler change to the Hermes runtime checkout.
2. Restart the Hermes gateway or cron runner through the existing service
   manager for the target host.
3. Do not edit job definitions or credentials for this rollout.

## Validation

1. Run the source tests:
   `scripts/run_tests.sh tests/cron/test_scheduler.py tests/cron/test_cron_script.py -q`
2. After deployment, trigger or wait for a cron job whose pre-run script emits a
   controlled failure marker such as `rc=124`.
3. Confirm the saved cron output still contains the agent's report.
4. Confirm the corresponding job has `last_status: error` and a `last_error`
   beginning with `pre-run script output reported failure` or
   `pre-run script failed`.

## Monitoring

Watch Hermes cron output files, `cron/jobs.json`, dashboard panels that read
cron status, and scheduler logs for the warning:
`completed agent reporting after pre-run script failure`.

## Rollback

Revert the scheduler change and restart the Hermes gateway or cron runner. A
rollback restores the previous behavior where delivery success can mark a
script-failure report as `ok`, so keep dashboard-side failure-output detection
enabled until a replacement source fix is live.
