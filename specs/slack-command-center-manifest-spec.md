# Slack Command Center Manifest Spec

## Purpose

Operators need Hermes Slack setup to support command-center deployments where
slash-command and interactivity URLs are owned by a routed app endpoint instead
of the default Socket Mode placeholder. Manifest generation must keep the
existing Socket Mode defaults while allowing explicit URLs when the operator
has an HTTP ingress for Slack commands or Block Kit actions.

## Boundaries

- Hermes continues to run Slack through the existing gateway adapter and
  command registry.
- This change does not edit Slack credentials, write Hermes config, restart the
  gateway, or send Slack messages.
- Socket Mode remains the default manifest posture.
- Custom URLs are command invocation inputs, not new `.env` or `config.yaml`
  settings.

## Scenarios

### Scenario 1 - Routed slash-command manifest

When an operator runs `hermes slack manifest --request-url <url>`, every native
Slack slash command in the generated manifest uses that URL.

Acceptance:
- Full manifests and `--slashes-only` output both use the supplied URL.
- The default URL remains unchanged when no override is supplied.
- Command registry ordering and Slack command filtering remain unchanged.

### Scenario 2 - Routed interactivity manifest

When an operator runs `hermes slack manifest --interactivity-request-url <url>`,
the full manifest enables Slack interactivity and includes the supplied request
URL for Block Kit actions.

Acceptance:
- Full manifests include the interactivity request URL only when supplied.
- `--slashes-only` output remains a slash-command array and does not grow
  interactivity fields.
- Existing assistant, app-home, OAuth scope, and Socket Mode settings remain
  present.

## Test Seam

The feature is exercised at the manifest builder and CLI command seam:
`hermes_cli.slack_cli._build_full_manifest()` and
`hermes_cli.slack_cli.slack_manifest_command()`. This verifies the generated
operator artifact without requiring live Slack network calls or Hermes gateway
runtime state.
