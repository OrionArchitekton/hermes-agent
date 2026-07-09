---
title: Hermes disk cleanup missed untracked temp manifest trees
date: 2026-07-09
category: docs/solutions/incidents
module: disk-cleanup
problem_type: incident
component: plugins/disk-cleanup
severity: medium
applies_when:
  - "the bundled `disk-cleanup` plugin is enabled"
  - "Hermes commands create `/tmp/hermes-*` files or manifest directories"
  - "the paths were not written through a hook shape the plugin auto-tracked"
symptoms:
  - "`/tmp/hermes-slack-command-center-manifest-YYYYMMDD` remains on disk"
  - "`/disk-cleanup quick` reports nothing useful because `tracked.json` does not include the path"
  - "safe `/tmp/hermes-*` probe files accumulate across sessions"
root_cause: disk-cleanup-quick-only-processed-tracked-state-and-hermes-home-empty-dirs
resolution_type: source-fix
related_components:
  - disk-cleanup
  - hermes-gateway
  - tmp-hygiene
tags:
  - hermes
  - disk-cleanup
  - tmp
  - disk-waste
---

## Summary

On `hermes-01`, the live `disk-cleanup` plugin was enabled, but `/tmp` still
held a 123 MB source snapshot at
`/tmp/hermes-slack-command-center-manifest-20260709` plus several stale
`/tmp/hermes-*` probe files. The plugin state had not tracked those paths, so
the existing `quick()` cleanup path ignored them.

## Root Cause

The plugin advertised strict scope over `$HERMES_HOME` and `/tmp/hermes-*`, but
`quick()` only processed paths already present in `tracked.json` and then swept
empty directories under `$HERMES_HOME`. It never discovered safe untracked
direct children of `/tmp`, so artifacts created outside the `write_file` /
`terminal` hook parsing path accumulated indefinitely.

## Source Fix

- Add a bounded untracked `/tmp/hermes-*` sweep to `quick()`.
- Delete only direct temp-root children owned by the current user.
- Never follow symlinks.
- Delete untracked manifest directories with `manifest` in the name only after
  they are older than 12 hours.
- Delete untracked `/tmp/hermes-*` files only after they are older than 24
  hours.
- Preserve live active-session marker files and any manifest directory that
  contains a still-tracked child path.
- Include reclaimed bytes in the normal quick-cleanup summary.

## Verification

Source verification:

```bash
python3 -m pytest -q tests/plugins/test_disk_cleanup_plugin.py
python3 -m pytest -q tests/plugins/test_disk_cleanup_plugin.py::TestTrackForgetQuick::test_quick_deletes_stale_untracked_tmp_manifest_dir
git diff --check
```

Live closure after deploy:

```bash
ssh hermes-01 'du -sh /tmp/hermes-* 2>/dev/null | sort -h'
ssh hermes-01 'cd /home/hermes/hermes-agent-v31 && \
  HERMES_HOME=/home/hermes/.hermes ./venv/bin/python - <<'"'"'PY'"'"'
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    "disk_cleanup_live",
    Path("plugins/disk-cleanup/disk_cleanup.py"),
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.quick())
PY'
ssh hermes-01 'du -sh /tmp/hermes-* 2>/dev/null | sort -h'
```

Expected result: stale untracked Hermes temp roots are removed, fresh
`/tmp/hermes-*` roots are preserved, and Hermes gateway/user units remain
healthy.

## Rollback

Revert the plugin change and restart/reload Hermes from the previous deployed
checkout. During rollback, untracked `/tmp/hermes-*` manifest trees must be
removed manually after verifying they are not active.

## Durable Lesson

A cleanup plugin cannot rely only on its own tracking ledger when its safety
contract explicitly includes a temp namespace. If hook parsing misses a path,
bounded discovery inside that namespace must still prevent predictable disk
waste.
