---
title: Hermes Cron Isolated Launcher
verified: 2026-07-28
review_after: 2026-10-28
topics: [hermes-agent, hermes-01, cron, scheduler, shell, isolation, runbooks]
references:
  - specs/cron-isolated-launcher-spec.md
  - cron/scheduler.py
  - cron/jobs.py
  - tools/cronjob_tools.py
  - tests/cron/test_cron_no_agent.py
  - website/docs/guides/cron-script-only.md
  - website/docs/user-guide/features/cron.md
---

# Hermes Cron Isolated Launcher

Hermes reserves the `*.hermes-isolated.sh` suffix for POSIX cron scripts that
must start without ambient shell or language-loading variables. The scheduler
opens the canonical scripts-directory anchor component-by-component from a held
root descriptor, then opens the selected regular file and its parent without
following symlinks. It uses `/bin/bash --noprofile --norc` with inherited
`/dev/fd` references for the held script and working directory. The
descriptors are normalized above standard input, output, and error before
subprocess stdio is configured, including on detached hosts with closed
standard descriptors. The
scheduler-supplied exec environment is exactly `PATH=/usr/bin:/bin`; Bash may
synthesize its own internal variables after exec.

Ordinary `.sh`, `.bash`, and Python-selected scripts retain their existing
launcher behavior.

## Source Rollout

1. Review the source diff and the feature spec.
2. Run the focused source validation below.
3. Merge through the normal repository review path.
4. Before deployment, enumerate all jobs through the supported cron list
   interface with disabled jobs included. Record every job whose selected
   `script` has an exact, case-sensitive basename ending in
   `.hermes-isolated.sh`.
5. If the inventory is non-empty, treat deployment as activation for every
   recorded job. Do not deploy until each runnable job has separate runtime
   authority and the artifact, job snapshot, and validation evidence required
   by **Activation Validation**. Preserve the complete inventory as rollout and
   rollback evidence.
6. Deploy the merged Hermes source through the existing controlled deployment
   path for the target runtime.

A merge is not an activation. Deployment is an activation for any existing job
that already selects the reserved suffix. Other jobs do not gain the isolated
launcher until their selected script name ends in `.hermes-isolated.sh`.

Live bind-mount changes, script creation or renaming, and cron job mutation on
`hermes-01` remain separate operator-gated actions. Do not perform them as part
of source rollout.

## Source Validation

Run:

```bash
scripts/run_tests.sh tests/cron/test_cron_no_agent.py -q
scripts/run_tests.sh tests/cron/test_cron_no_agent.py tests/cron/test_cron_script.py -q
```

Also run the repository's Python lint and diff whitespace checks for the
changed source and tests.

The isolated-launcher tests prove:

- fixed Bash path and startup flags;
- exact scheduler-supplied exec environment and absence of named ambient
  variables in a real Bash child;
- rejection on non-POSIX;
- scripts-directory containment and rejection of isolated symlinks or
  indirection;
- held-inode execution and pinned parent cwd across deterministic pathname
  swaps;
- exact script and parent-cwd execution with each standard descriptor closed;
- no process-global cwd change for a no-agent job that carries `workdir`;
- unchanged legacy shell and Python dispatch.

## Activation Validation

Perform these steps only after explicit authority to mutate the target runtime
and the named cron job:

1. Record the target job ID and a full pre-change snapshot of its stored job
   definition. Preserve this snapshot as the rollback receipt.
2. Record an activation audit receipt with:
   - deployed Hermes source revision;
   - artifact SHA-256;
   - artifact source revision;
   - bind-mount source and target, when a bind mount is used;
   - numeric owner and group, permission mode, modification time, and audit
     time in UTC;
   - the intended relative script selection.
3. Confirm the deployed checkout contains the reviewed isolated-launcher source.
4. Review the candidate script for dependencies on ambient variables or
   commands outside `/usr/bin:/bin`.
5. Prove the artifact and every replacement-capable parent are not writable by
   the Hermes runtime identity. A read-only bind mount or equivalent
   runtime-unwritable source is required; descriptor retention prevents
   pathname replacement but does not freeze a writable inode's bytes.
6. Place or bind the reviewed artifact under the active Hermes scripts
   directory with an exact, case-sensitive basename ending in
   `.hermes-isolated.sh`. The selection must contain no symlink component.
7. Recompute SHA-256 and ownership/mode evidence from the live selected
   artifact and match it to the activation receipt.
8. Update only the recorded job ID to select that relative script name.
9. Trigger one controlled run or wait for the next scheduled run.
10. Confirm the expected stdout or silent result, the job status, and the saved
    cron output. Append the result and observation time to the receipt.

Do not infer activation from a green source test, merged commit, deployed
checkout, or presence of an isolated script that no job selects.

## Monitoring

Monitor:

- cron job status and saved output for the activated job;
- scheduler logs for `requires a POSIX platform`, missing `/bin/bash`,
  missing `/dev/fd`, blocked symlink or indirection, `command not found`,
  non-zero exit, or timeout errors;
- expected deliveries and expected silent ticks;
- unexpected failures caused by absent `HOME`, locale, temporary-directory,
  proxy, application, credential, Python, or loader variables.
- periodic artifact SHA-256, owner, mode, mount-source, and runtime-write
  checks against the activation receipt.

Legacy cron jobs should show no launcher change. Treat failures on an unrelated
legacy job as a regression rather than expected isolation behavior.

## Rollback

Source rollback and live-job rollback are separate operations.

1. Enumerate all jobs through the supported cron list interface with disabled
   jobs included. Record every job whose selected `script` has an exact,
   case-sensitive basename ending in `.hermes-isolated.sh`.
2. Retrieve the rollout inventory and activation receipt for every matching job.
   Reconcile that receipt set with the live inventory; do not continue while a
   matching job lacks a pre-change snapshot or while a receipt names a job that
   cannot be accounted for.
3. Pause every runnable matching job before deploying source that lacks this
   contract. Older source may interpret each reserved name as an ordinary
   `.sh` script and restore inherited environment behavior. Re-enumerate the
   jobs and do not continue while any matching job remains runnable.
4. Restore every matching job's pre-change snapshot fields with `enabled`
   forced to `false`. Do not restore a recorded `enabled: true` value yet; keep
   all affected jobs paused throughout source and artifact rollback.
5. Revert the isolated-launcher source change and deploy the previous reviewed
   Hermes version through the normal controlled path.
6. Restore each pre-change artifact or bind-mount state recorded in the receipts
   only when separately authorized.
7. Validate every restored job definition, the source revision, artifact
   digests, and expected behavior while all affected jobs remain paused.
8. Only after every validation succeeds, restore each receipt's recorded
   `enabled` state as the final operation for that job ID. A job that was
   previously disabled remains disabled; any rollback or validation failure
   leaves every affected job paused.

Do not rename scripts, change bind mounts, edit jobs, or restart live services
as an implicit part of rollback. Those remain separately gated runtime
mutations.
