---
verified: 2026-07-09
review_after: 2026-10-09
topics: [hermes-agent, hermes-01, cli, path, incident]
references:
  - scripts/install-cli-wrapper.sh
  - tests/test_install_cli_wrapper.py
  - docs/runbooks/hermes-cli-path-wrapper.md
---

# Hermes CLI Path Drift

## Symptom

On `hermes-01`, non-login SSH probes such as `ssh hermes-01 'hermes cron list'`
failed with `hermes: command not found` because the minimal SSH PATH did not
include `~/.local/bin`.

The user-local launcher also pointed at an older Hermes checkout while the
running gateway used the newer deployed checkout. That made PATH repair unsafe
unless the launcher was re-rendered to the active venv binary.

## Root Cause

The deployment updated the running Hermes checkout and service, but did not
refresh a PATH-visible operator launcher. The host had no `/usr/local/bin/hermes`
launcher, and the existing `~/.local/bin/hermes` wrapper was not a reliable
deployed-version contract.

## Fix

Add `scripts/install-cli-wrapper.sh`, a small installer that writes managed
Hermes launchers to one or more PATH locations and execs an explicit venv
binary. The installer:

- validates that the target Hermes binary is executable;
- atomically writes the launcher;
- refuses to overwrite non-managed files unless `--force` is passed;
- unsets inherited Python path variables before exec;
- optionally preserves the Slack Doppler route used by Hermes runtime wrappers.

## Verification

Regression tests:

```bash
pytest -q tests/test_install_cli_wrapper.py
```

Runtime proof after deployment:

```bash
ssh hermes-01 'hermes --version'
ssh hermes-01 'hermes cron list'
ssh hermes-01 'bash --noprofile --norc -c "command -v hermes && hermes --version"'
```

## Rollback

Remove the managed launchers or rerun `scripts/install-cli-wrapper.sh` with the
previous executable path. Removing `/usr/local/bin/hermes` is safe for the
gateway process; it only affects operator shell command discovery.

## Durable Lesson

Treat operator CLI launchers as deployed artifacts. Updating the service
checkout without updating PATH-visible wrappers creates a split-brain between
runbook probes and the running gateway.
