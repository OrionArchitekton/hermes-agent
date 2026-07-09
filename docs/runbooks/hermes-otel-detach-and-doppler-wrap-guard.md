---
title: Hermes Gateway — OTel detach guard + Doppler-wrap durability guard
verified: 2026-06-20
review_after: 2026-09-20
topics: [hermes-agent, hermes-01, langfuse, opentelemetry, doppler, systemd, observability]
references:
  - /home/hermes/.hermes/hermes-agent/plugins/observability/langfuse/__init__.py
  - /home/hermes/.config/systemd/user/hermes-gateway.service.d/90-doppler-wrap.conf
  - /home/hermes/.config/systemd/user/hermes-doppler-wrap-guard.path
  - /home/hermes/.config/systemd/user/hermes-doppler-wrap-guard.service
  - /home/hermes/.hermes-runtimelab/bin/doppler-wrap-guard.sh
  - /home/hermes/.hermes-runtimelab/doppler-wrap.canonical.conf
  - /home/hermes/.hermes-runtimelab/phase1-baseline-20260620/
---

# Hermes Gateway Phase-1 Stabilization (2026-06-20)

Two estate-local patches to the Nous Hermes Agent fork deployment on **hermes-01**
(`hermes-gateway.service`, user `hermes`). Phase-1 of the C1 "stabilize" plan.
The v0.17 cutover is now live; this runbook covers the estate-local OTel
detach guard and Doppler wrapper durability guard that remain applied on top of
that fork release.

## 1a - OpenTelemetry cross-context detach guard

Symptom: `ERROR opentelemetry.context: Failed to detach context` +
`ValueError: <Token ...> was created in a different Context` in
~/.hermes/logs/errors.log (26 events) and the journal, emitted when the langfuse
plugin ends spans / flushes during async teardown (GeneratorExit). Known
cross-framework bug (langfuse#8780/#8316; google/adk-python#860).
NOTE: this is log/teardown NOISE. It is not the cause of gateway restart exit
status. Older Hermes builds emitted nonzero restart exits for systemd-managed
SIGTERM, but that behavior was corrected on 2026-07-09; see
`docs/runbooks/hermes-gateway-systemd-sigterm-exit.md`.

Fix: plugins/observability/langfuse/__init__.py installs
`_install_otel_detach_guard()` at import — wraps
`opentelemetry.context._RUNTIME_CONTEXT.detach` to swallow ONLY the
"was created in a different Context" ValueError (DEBUG) and re-raise everything
else. Idempotent, fail-open.

Validate: `cd ~/.hermes/hermes-agent && venv/bin/python -m py_compile plugins/observability/langfuse/__init__.py`
+ import check; then before/after reproduction (BEFORE>=1, AFTER=0). Live:
`grep -c "different Context" ~/.hermes/logs/errors.log` stays flat across restarts.

Rollback: restore
~/.hermes-runtimelab/phase1-baseline-20260620/langfuse__init__.py.bak over the
plugin, then `systemctl --user restart hermes-gateway`.

## 1b - Doppler-wrap durability guard

Risk: the doppler-run ExecStart wrapper lives ONLY in 90-doppler-wrap.conf. It
survives override.conf rewrites today only because override.conf (lane-manifest
owned) sets Environment-only (no ExecStart) — fragile (override.conf loads LAST).
If the wrapper is ever stripped and the gateway restarts, it loses Slack tokens.

Fix: hermes-doppler-wrap-guard.path watches the drop-in dir + override.conf; on
change it runs hermes-doppler-wrap-guard.service ->
~/.hermes-runtimelab/bin/doppler-wrap-guard.sh, which restores the wrapper from
the canonical copy if missing/altered, daemon-reloads, and restarts the gateway
ONLY if the RUNNING process is actually unwrapped. Never edits override.conf.

Monitor: ~/.hermes/logs/doppler-wrap-guard.log;
`systemctl --user status hermes-doppler-wrap-guard.path`.

Validate: simulate an atomic override.conf rewrite -> effective ExecStart still
`doppler run`; strip the wrapper -> guard restores it (no restart while the
running process is wrapped).

Rollback: `systemctl --user disable --now hermes-doppler-wrap-guard.path`; remove
the .path + .service units; `systemctl --user daemon-reload`. 90-doppler-wrap.conf
stays in place.

## Deploy path
Native: edit fork plugin in place (editable venv) + `systemctl --user daemon-reload
&& systemctl --user restart hermes-gateway`. 90-* drop-in only, NEVER override.conf
(lane-manifest rewrites it). Doppler values stay in project hermes-agent/config prd.

## Later cutover note
The fork cutover to v0.17 has since landed. Keep this runbook scoped to the
local OTel detach guard and Doppler wrapper durability guard; estate recall /
MCP memory access remains a separate access-gated workstream.
