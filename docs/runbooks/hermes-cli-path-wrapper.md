---
verified: 2026-07-09
review_after: 2026-10-09
topics: [hermes-agent, hermes-01, cli, path, deployment]
references:
  - scripts/install-cli-wrapper.sh
  - tests/test_install_cli_wrapper.py
---

# Hermes CLI Path Wrapper

Hermes service hosts often run non-login SSH commands and systemd probes with a
minimal PATH such as `/usr/local/bin:/usr/bin:/bin`. A user-local
`~/.local/bin/hermes` launcher is not enough for those probes, and it can also
point at an older checkout than the running gateway.

Use `scripts/install-cli-wrapper.sh` to install explicit launchers that exec
the active venv binary.

## Install

```bash
scripts/install-cli-wrapper.sh \
  --force \
  --hermes-bin /home/hermes/hermes-agent-v31/venv/bin/hermes \
  --link /home/hermes/.local/bin/hermes

sudo scripts/install-cli-wrapper.sh \
  --force \
  --hermes-bin /home/hermes/hermes-agent-v31/venv/bin/hermes \
  --link /usr/local/bin/hermes
```

If the launcher must preserve Slack sends through Doppler, include the optional
Slack route arguments:

```bash
scripts/install-cli-wrapper.sh \
  --force \
  --hermes-bin /home/hermes/hermes-agent-v31/venv/bin/hermes \
  --link /home/hermes/.local/bin/hermes \
  --slack-doppler-env-file /home/hermes/.hermes-runtimelab/doppler.env \
  --doppler-bin /usr/bin/doppler \
  --slack-doppler-project hermes-agent \
  --slack-doppler-config prd

sudo scripts/install-cli-wrapper.sh \
  --force \
  --hermes-bin /home/hermes/hermes-agent-v31/venv/bin/hermes \
  --link /usr/local/bin/hermes \
  --slack-doppler-env-file /home/hermes/.hermes-runtimelab/doppler.env \
  --doppler-bin /usr/bin/doppler \
  --slack-doppler-project hermes-agent \
  --slack-doppler-config prd
```

The installer refuses to overwrite non-managed launchers unless `--force` is
present. Use `--force` only after verifying the existing file belongs to Hermes.
Run the user-local install without `sudo`; otherwise
`/home/hermes/.local/bin/hermes` can become root-owned and block later
non-privileged updates.

## Validation

```bash
ssh hermes-01 'hermes --version'
ssh hermes-01 'hermes cron list'
ssh hermes-01 'bash --noprofile --norc -c "command -v hermes && hermes --version"'
```

Expected result:

- `command -v hermes` resolves to the intended launcher.
- `hermes --version` reports the deployed checkout currently serving the
  gateway.
- `hermes cron list` reads the live cron registry without requiring a login
  shell or user-local PATH.

## Rollback

Remove the managed launchers, or reinstall them to the prior executable:

```bash
sudo rm -f /usr/local/bin/hermes
rm -f /home/hermes/.local/bin/hermes
```

Then restore the previous user wrapper from backup or rerun the older install
command. Removing the `/usr/local/bin` launcher returns non-login SSH probes to
the previous `command not found` behavior but does not stop the already running
gateway service.

## Durable Lesson

Operator commands must resolve to the same deployed Hermes checkout as the
running gateway. A user-local launcher is not a production PATH contract, and a
stale launcher can make runbook probes inspect the wrong code.
