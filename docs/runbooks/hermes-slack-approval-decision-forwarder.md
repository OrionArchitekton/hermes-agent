---
verified: 2026-07-09
review_after: 2026-10-09
topics: [hermes-agent, hermes-01, slack, approvals, gateway, runbooks]
references:
  - plugins/platforms/slack/adapter.py
  - tests/gateway/test_slack.py
  - tests/gateway/test_slack_approval_buttons.py
---

# Hermes Slack Approval Decision Forwarder

Hermes Slack Socket Mode receives Block Kit button actions for lane approval
cards. Approval-card actions use `approval_decision:approve` and
`approval_decision:reject`; Hermes must ACK those actions and forward a bounded
decision payload to the approvals-store receiver.

## Required Runtime Configuration

Set these in the gateway runtime secret/config source:

- `SLACK_APPROVAL_DECISION_URL`: approvals-store decision endpoint, for example
  `http://approvals-store:8091/decision` when Hermes runs on the same compose
  network, or the routed production endpoint when it does not.
- `SLACK_APPROVAL_DECISION_TOKEN`: shared receiver token sent as
  `X-Trigger-Token`.

Optional:

- `SLACK_APPROVAL_ACTION_PREFIX`: defaults to `approval_decision:`.
- `SLACK_APPROVAL_DECISION_TIMEOUT_MS`: defaults to `5000`.

## Validation

Source validation:

```bash
scripts/run_tests.sh tests/gateway/test_slack_approval_buttons.py tests/gateway/test_slack.py -q
uv run --extra dev ruff check plugins/platforms/slack/adapter.py tests/gateway/test_slack.py tests/gateway/test_slack_approval_buttons.py
```

Runtime validation on `hermes-01`:

```bash
journalctl --user -u hermes-gateway.service --since -30m --no-pager | grep -F 'approval_decision:'
```

Expected result after a button click:

- No `slack_bolt.AsyncApp: Unhandled request` line for
  `approval_decision:approve` or `approval_decision:reject`.
- Hermes logs either `Forwarded approval decision ...` or a bounded fail-closed
  configuration/receiver error.
- The approvals-store records the decision exactly once.

## Rollback

1. Remove or unset `SLACK_APPROVAL_DECISION_URL` and
   `SLACK_APPROVAL_DECISION_TOKEN` to stop forwarding while keeping Slack ACKs
   fail-closed.
2. If code rollback is required, deploy the prior `hermes-agent` release and
   restart `hermes-gateway.service`.
3. Re-test with a synthetic approval card before re-enabling operator approval
   traffic.

## Durable Lesson

Slack Socket Mode handlers must be registered in the receiving gateway, even
when another edge service also handles the signed HTTP path. Without the handler,
Slack retries and logs an unhandled action before the approval-store receiver
can ever see the operator's decision.
