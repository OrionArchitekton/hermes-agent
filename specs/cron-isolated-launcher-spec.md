# Cron Isolated Launcher Spec

## Purpose

Operators need an opt-in cron script launcher that does not trust the scheduler's
ambient shell or language-loading environment. A script selects this launcher by
using the reserved `*.hermes-isolated.sh` suffix. Existing cron scripts retain
their current behavior.

## Boundaries

- The isolated launcher is available to both script-only jobs and pre-run
  scripts because both use the existing cron script execution interface.
- Scripts remain confined to the active Hermes scripts directory. Tool-created
  job definitions reject absolute paths and paths that escape after
  normalization; internal forms such as `nested/../script` remain valid.
- An isolated selection rejects symlinks in the selected file or any relative
  path component. Legacy lexical names do not opt in based on a target name.
- The launcher is POSIX-only and requires `/bin/bash`, `O_NOFOLLOW`,
  `O_DIRECTORY`, `F_DUPFD_CLOEXEC`, and `/dev/fd`.
- This feature does not create, rename, pause, resume, or run any cron job.
- Merging the source does not activate isolation. Deploying it activates
  isolation for every existing job that already selects a script whose name
  ends in `.hermes-isolated.sh`; all other existing jobs require an operator to
  select the reserved suffix.
- Existing `.sh`, `.bash`, and Python-selected scripts keep their current
  interpreter and environment behavior.

## Scenarios

### Scenario 1 - Run an isolated cron script

Given a cron job selects a contained regular file whose lexical basename ends in
`.hermes-isolated.sh`, when the scheduler executes the script on a POSIX host,
it opens the canonical scripts-directory anchor component-by-component from a
held root descriptor, then opens the selected relative components without
following symlinks. It retains descriptors for the verified regular-file inode
and its parent, and launches the held script bytes with fixed `/bin/bash` while
disabling Bash profile and rc loading.

Acceptance:

- The launcher command is `/bin/bash --noprofile --norc <held-script-fd>`.
- Bash receives an inherited `/dev/fd` reference to the opened script instead
  of reopening the selected pathname.
- The child working directory is pinned through an inherited descriptor for the
  opened script parent.
- Held script and parent descriptors are normalized above standard input,
  output, and error before subprocess stdio is configured, so detached hosts
  with any closed standard descriptor still execute the intended script and
  working directory.
- Replacing an intermediate absolute anchor component with a symlink cannot
  redirect the scripts directory.
- The scheduler-supplied exec environment contains exactly one entry:
  `PATH=/usr/bin:/bin`.
- Ambient `PATH`, `BASH_ENV`, `PYTHONPATH`, and `LD_PRELOAD` values do not reach
  the child. Bash may synthesize its own internal variables after exec.
- Swapping the selected file or parent pathname after validation cannot redirect
  the script bytes or relative-file working directory.
- Normal stdout, stderr, timeout, redaction, exit-status, and delivery semantics
  continue through the existing cron script result path.

### Scenario 2 - Refuse unsupported isolated execution

Given a selected isolated script is executed on a non-POSIX host, the fixed
`/bin/bash` interpreter is unavailable, the required descriptor primitives are
unavailable, or the isolated selection contains a symlink, the cron run fails
with a clear operator-facing error instead of falling back to another launcher.

Acceptance:

- A non-POSIX host reports that the isolated suffix requires POSIX.
- A POSIX host without `/bin/bash` reports the missing fixed interpreter.
- A selected-file or intermediate-directory symlink reports blocked
  indirection.
- No unsupported or blocked condition falls through to the legacy shell or
  Python launcher.

### Scenario 3 - Preserve existing cron script compatibility

Given a cron job references a script without the reserved suffix, when the
scheduler executes it, the existing extension-based launcher and sanitized
inherited environment remain unchanged.

Acceptance:

- Ordinary `.sh` and `.bash` scripts continue to use the legacy dynamically
  resolved Bash path.
- Python-selected scripts continue to use the current Python interpreter,
  including the existing Windows compatibility path.
- Existing scripts are not opted into the minimal environment by a source
  merge or deployment.
- Suffix matching is case-sensitive and uses the selected lexical basename.
- A legacy lexical name that resolves to a target with the reserved suffix
  remains a legacy selection.
- Existing legacy containment behavior remains unchanged.

## Compatibility Constraints

- Isolated scripts cannot depend on ambient `HOME`, locale, temporary-directory,
  proxy, virtual-environment, Python, dynamic-loader, credential, or
  application variables. They must establish any required non-secret values
  explicitly and obtain secrets through an approved mechanism outside this
  launcher contract.
- Commands available only through a custom ambient `PATH` are unavailable.
- The launcher does not honor a script shebang.
- The child working directory is the selected script's parent, even when a cron
  job carries a separate project work directory.
- Internal normalized selections such as `nested/../script.hermes-isolated.sh`
  are accepted when the result remains inside the scripts directory.
- Runtime activation requires a reviewed artifact that the Hermes runtime
  identity cannot modify; retaining an inode descriptor prevents pathname
  replacement but does not make a writable inode immutable.
- Deploying while an existing job already selects the reserved suffix,
  renaming an existing script to that suffix, or changing a live job to select
  it is an activation action. Each requires the runtime authority and validation
  evidence described by the operator runbook.

## Test Seam

The highest test seam is the existing cron script execution interface,
`_run_job_script(script_path)`. It is the same seam used by script-only jobs and
pre-run scripts, and it exposes launcher success plus captured output without
introducing another interface.

At this seam, tests use real child processes to prove ambient environment
poisoning is absent and deterministic file/parent pathname swaps cannot redirect
execution. Detached-host subprocesses close each standard descriptor in turn to
prove descriptor/stdin/stdout/stderr remapping cannot redirect or hang the
launcher. A focused subprocess substitution verifies the descriptor launcher,
scheduler-supplied exec environment, and pinned working directory. Existing
no-agent tests exercise the surrounding scheduled-job result and delivery
behavior, including that a configured project work directory never changes the
scheduler process cwd.
