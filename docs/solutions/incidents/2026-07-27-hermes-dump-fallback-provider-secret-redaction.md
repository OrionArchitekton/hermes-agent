---
title: Sanitize fallback-provider diagnostics before rendering them
date: 2026-07-27
category: docs/solutions/incidents
module: hermes-cli
problem_type: incident
component: dump-diagnostics
severity: high
applies_when:
  - fallback_providers contains inline or nested credential material
  - hermes dump renders config_overrides
  - hermes debug share captures the dump header for a support bundle
symptoms:
  - "hermes dump prints a fallback_providers representation containing an inline credential"
  - "hermes dump without --show-keys exposes nested fallback-provider secret fields"
  - "a debug-share report inherits raw fallback-provider config from its dump header"
root_cause: unsafe-stringification
resolution_type: source-fix
related_components:
  - hermes_cli.dump
  - hermes_cli.debug
  - fallback_providers
tags:
  - hermes
  - diagnostics
  - secret-redaction
  - fallback-providers
---

## What happened

On 2026-07-27, source review of the Hermes Agent v0.19.0 deployment found
that the dump formatter converted the complete `fallback_providers` value with
`str()`. Inline credentials and nested secret-bearing provider options
therefore bypassed the command's normal API-key display policy and could reach
standard output even when `--show-keys` was absent.

The same formatter feeds the dump header captured by `hermes debug share`, so
the unsafe representation could also enter a support report before upload.
No credential value is recorded in this artifact.

## Root cause

The API-key summary had an explicit safe display path: the default showed only
`set` or `not set`, and `--show-keys` permitted a masked fingerprint. The
fallback-provider override path did not use that policy. It flattened an
arbitrarily nested configuration object directly, which also allowed custom
object `repr` implementations to expose their fields.

## Source fix

The dump formatter now converts fallback-provider diagnostics into a JSON-safe
structure before rendering it. The diagnostic schema is intentionally
narrower than the permissive runtime mapping:

- it retains only the runtime-relevant `provider`, `model`, `base_url`,
  `api_mode`, `transport`, `key_env`, `api_key_env`, and `api_key` fields;
- it removes URL userinfo, query strings, fragments, and arbitrary path
  segments while retaining the endpoint host and common API routing paths;
- it reports only whether an environment reference is configured, never the
  reference bytes, because a credential can be shaped like an environment
  variable name;
- it omits all other fields without traversing or naming them and reports only
  a fixed `omitted_fields` count;
- it never calls `str()`, `repr()`, or `vars()` on unsupported objects; and
- it applies the existing `--show-keys` first/last-four masked fingerprint
  rather than introducing another disclosure flag.

The allowlist is the disclosure authorization rule. Credential-pattern
redaction remains defense in depth for the allowed scalar fields, not the
mechanism trusted to classify arbitrary nested data.

This source change does not by itself change the deployed Hermes runtime or any
credential.

## Verification

The source regression suite uses synthetic values only:

```bash
scripts/run_tests.sh tests/hermes_cli/test_dump_fallback_redaction.py -q
scripts/run_tests.sh \
  tests/hermes_cli/test_debug.py \
  tests/hermes_cli/test_dump_env_visibility.py \
  tests/hermes_cli/test_dump_git_commit.py \
  tests/hermes_cli/test_dump_terminal_backend.py \
  tests/hermes_cli/test_dump_fallback_redaction.py \
  tests/hermes_cli/test_fallback_config.py \
  tests/hermes_cli/test_fallback_cmd.py -q
ruff check hermes_cli/dump.py tests/hermes_cli/test_dump_fallback_redaction.py
python scripts/check-windows-footguns.py --all
```

The regression asserts that nested mapping, list, object, header, and
credential-pattern cases are omitted without traversal, while the provider,
model, sanitized endpoint, routing mode, and environment-reference presence
remain useful. A temp-`HERMES_HOME` test exercises `config.yaml` loading through
`run_dump` under both default and `--show-keys` modes and proves that no complete
synthetic credential reaches standard output or standard error.

## Remaining operator gates

The incident is not runtime-closed until all of these separate planes are
verified:

1. A maintainer reviews and merges the source PR.
2. An operator explicitly authorizes materializing the merged commit on
   `hermes-01` and restarting or replacing the affected Hermes runtime.
3. Runtime verification proves the deployed commit and exercises the formatter
   against a temporary synthetic configuration, not the live credential store.
4. An operator explicitly authorizes rotation and revocation of the affected
   fallback-provider credential. Rotation must not print the old or replacement
   value; verification should use provider success plus names-only/set-state
   evidence.

Until those gates complete, deployed v0.19.0 remains vulnerable even though the
source branch is fixed.

## Rollback

If deployment of the fixed build causes an unrelated diagnostic regression,
prefer a forward repair. Rolling back to the previous build restores the
secret-disclosure path, so the dump and debug-share surfaces must remain
disabled or receive the same patch before that version is used.

## Prevention

Support output is a security boundary. Structured configuration must be
projected through an explicit diagnostic allowlist before formatting; arbitrary
extras and objects must not be traversed, named, or stringified. Every future
diagnostic that includes provider configuration should reuse the same
explicit-display policy and carry a synthetic no-plaintext egress test.
