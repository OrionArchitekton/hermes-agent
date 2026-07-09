# Slack Gateway Reliability Status Spec

## Purpose

Dan needs Slack to act as an operations command center without guessing whether
Hermes is actually reachable through Slack. The gateway status surface must make
Slack reliability failures visible from existing local state, without adding
Slack transport code or mutating the running service.

## Boundaries

- Hermes remains the messaging gateway and scheduler owner for Slack delivery.
- Slack app and command-center state stay outside this repo.
- This feature is read-only: it does not restart services, edit config, change
  Slack credentials, or send Slack messages.
- Runtime state comes from the existing gateway runtime status record.
- Scheduled-delivery state comes from the existing cron jobs database.

## Scenarios

### Scenario 1 - Slack adapter disconnected

When the gateway runtime status records Slack as disconnected, `hermes gateway
status` shows a warning in the existing "Recent gateway health" section. If the
runtime record carries an error message, the warning includes the compact error.

Acceptance:
- A nonfatal Slack disconnect is visible without requiring `--deep`.
- Fatal platform warnings continue to render as before.
- Connected platforms do not produce warning noise.

### Scenario 2 - Slack scheduled delivery failing

When one or more cron jobs target Slack and have a `last_delivery_error`,
`hermes gateway status` shows the count and latest failing job in the existing
"Recent gateway health" section.

Acceptance:
- Jobs with `deliver=slack`, `deliver=slack:<target>`, or `deliver=origin` from
  a Slack origin are counted.
- Jobs with `deliver=all` are not inferred from error text; they need an
  explicit Slack delivery target or Slack origin to count.
- Non-Slack delivery failures are not included in the Slack summary.
- Cron storage read failures do not break gateway status output.

## Test Seam

The feature is exercised at the status formatter seam:
`hermes_cli.gateway._runtime_health_lines()`. That seam reads the same persisted
state used by `hermes gateway status`, while avoiding live service or Slack
network dependencies in tests.
