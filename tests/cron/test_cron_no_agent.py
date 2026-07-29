"""Tests for cronjob no_agent mode — script-driven jobs that skip the LLM.

Covers:

* ``create_job(no_agent=True)`` shape, validation, and serialization.
* ``cronjob(action='create', no_agent=True)`` tool-level validation.
* ``cronjob(action='update')`` flipping no_agent on/off.
* ``scheduler.run_job`` short-circuit path: success/silent/failure.
* Shell script support in ``_run_job_script`` (.sh runs via bash).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def hermes_env(tmp_path, monkeypatch):
    """Isolate HERMES_HOME for each test so jobs/scripts don't leak."""
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "scripts").mkdir()
    (home / "cron").mkdir()

    monkeypatch.setenv("HERMES_HOME", str(home))

    # Reload modules that cache get_hermes_home() at import time.
    import importlib
    import hermes_constants
    importlib.reload(hermes_constants)
    import cron.jobs
    importlib.reload(cron.jobs)
    import cron.scheduler
    importlib.reload(cron.scheduler)

    return home


# ---------------------------------------------------------------------------
# create_job / update_job: data-layer semantics
# ---------------------------------------------------------------------------


def test_create_job_no_agent_requires_script(hermes_env):
    from cron.jobs import create_job

    with pytest.raises(ValueError, match="no_agent=True requires a script"):
        create_job(prompt=None, schedule="every 5m", no_agent=True)


def test_create_job_no_agent_stores_field(hermes_env):
    from cron.jobs import create_job

    script_path = hermes_env / "scripts" / "watchdog.sh"
    script_path.write_text("#!/bin/bash\necho hi\n")

    job = create_job(
        prompt=None,
        schedule="every 5m",
        script="watchdog.sh",
        no_agent=True,
        deliver="local",
    )
    assert job["no_agent"] is True
    assert job["script"] == "watchdog.sh"
    # Prompt can be empty/None for no_agent jobs.
    assert job["prompt"] in {None, ""}


def test_create_job_default_is_not_no_agent(hermes_env):
    from cron.jobs import create_job

    job = create_job(prompt="say hi", schedule="every 5m", deliver="local")
    assert job.get("no_agent") is False


def test_update_job_roundtrips_no_agent_flag(hermes_env):
    from cron.jobs import create_job, update_job, get_job

    script_path = hermes_env / "scripts" / "w.sh"
    script_path.write_text("echo hi\n")
    job = create_job(prompt=None, schedule="every 5m", script="w.sh", no_agent=True, deliver="local")

    update_job(job["id"], {"no_agent": False})
    reloaded = get_job(job["id"])
    assert reloaded["no_agent"] is False

    update_job(job["id"], {"no_agent": True})
    reloaded = get_job(job["id"])
    assert reloaded["no_agent"] is True


# ---------------------------------------------------------------------------
# cronjob tool: API-layer validation
# ---------------------------------------------------------------------------


def test_cronjob_tool_create_no_agent_without_script_errors(hermes_env):
    from tools.cronjob_tools import cronjob

    result = json.loads(
        cronjob(action="create", schedule="every 5m", no_agent=True, deliver="local")
    )
    assert result.get("success") is False
    assert "no_agent=True requires a script" in result.get("error", "")


def test_cronjob_tool_create_no_agent_with_script_succeeds(hermes_env):
    from tools.cronjob_tools import cronjob

    script_path = hermes_env / "scripts" / "alert.sh"
    script_path.write_text("#!/bin/bash\necho alert\n")

    result = json.loads(
        cronjob(
            action="create",
            schedule="every 5m",
            script="alert.sh",
            no_agent=True,
            deliver="local",
        )
    )
    assert result.get("success") is True
    assert result["job"]["no_agent"] is True
    assert result["job"]["script"] == "alert.sh"


def test_cronjob_tool_update_toggles_no_agent(hermes_env):
    from tools.cronjob_tools import cronjob

    script_path = hermes_env / "scripts" / "w.sh"
    script_path.write_text("echo hi\n")

    created = json.loads(
        cronjob(
            action="create",
            schedule="every 5m",
            script="w.sh",
            no_agent=True,
            deliver="local",
        )
    )
    job_id = created["job_id"]

    off = json.loads(cronjob(action="update", job_id=job_id, no_agent=False, prompt="run"))
    assert off["success"] is True
    assert off["job"].get("no_agent") in {False, None}

    on = json.loads(cronjob(action="update", job_id=job_id, no_agent=True))
    assert on["success"] is True
    assert on["job"]["no_agent"] is True


def test_cronjob_tool_update_no_agent_without_script_errors(hermes_env):
    """Flipping no_agent=True on a job that has no script must fail."""
    from tools.cronjob_tools import cronjob

    created = json.loads(
        cronjob(action="create", schedule="every 5m", prompt="do a thing", deliver="local")
    )
    job_id = created["job_id"]

    result = json.loads(cronjob(action="update", job_id=job_id, no_agent=True))
    assert result.get("success") is False
    assert "without a script" in result.get("error", "")


def test_cronjob_tool_create_does_not_require_prompt_when_no_agent(hermes_env):
    """The 'prompt or skill required' rule is relaxed for no_agent jobs."""
    from tools.cronjob_tools import cronjob

    script_path = hermes_env / "scripts" / "w.sh"
    script_path.write_text("echo hi\n")

    result = json.loads(
        cronjob(
            action="create",
            schedule="every 5m",
            script="w.sh",
            no_agent=True,
            deliver="local",
        )
    )
    assert result.get("success") is True


def test_cron_script_path_validation_accepts_normalized_internal_path(hermes_env):
    from tools.cronjob_tools import _validate_cron_script_path

    assert _validate_cron_script_path("nested/../probe.hermes-isolated.sh") is None
    assert _validate_cron_script_path("../probe.hermes-isolated.sh") is not None


# ---------------------------------------------------------------------------
# scheduler.run_job: short-circuit behavior
# ---------------------------------------------------------------------------


def test_run_job_no_agent_success_returns_script_stdout(hermes_env):
    """Happy path: script exits 0 with output, delivered verbatim."""
    from cron.jobs import create_job
    from cron.scheduler import run_job

    script_path = hermes_env / "scripts" / "alert.sh"
    script_path.write_text("#!/bin/bash\necho 'RAM 92% on host'\n")

    job = create_job(
        prompt=None, schedule="every 5m", script="alert.sh", no_agent=True, deliver="local"
    )
    success, doc, final_response, error = run_job(job)
    assert success is True
    assert error is None
    assert "RAM 92% on host" in final_response
    assert "RAM 92% on host" in doc


def test_run_job_no_agent_empty_output_is_silent(hermes_env):
    """Empty stdout → SILENT_MARKER, which suppresses delivery downstream."""
    from cron.jobs import create_job
    from cron.scheduler import run_job, SILENT_MARKER

    script_path = hermes_env / "scripts" / "quiet.sh"
    script_path.write_text("#!/bin/bash\n# nothing to say\n")

    job = create_job(
        prompt=None, schedule="every 5m", script="quiet.sh", no_agent=True, deliver="local"
    )
    success, doc, final_response, error = run_job(job)
    assert success is True
    assert error is None
    assert final_response == SILENT_MARKER


def test_run_job_no_agent_wake_gate_is_silent(hermes_env):
    """wakeAgent=false gate in stdout triggers a silent run."""
    from cron.jobs import create_job
    from cron.scheduler import run_job, SILENT_MARKER

    script_path = hermes_env / "scripts" / "gated.sh"
    script_path.write_text('#!/bin/bash\necho \'{"wakeAgent": false}\'\n')

    job = create_job(
        prompt=None, schedule="every 5m", script="gated.sh", no_agent=True, deliver="local"
    )
    success, doc, final_response, error = run_job(job)
    assert success is True
    assert final_response == SILENT_MARKER


def test_run_job_no_agent_script_failure_delivers_error(hermes_env):
    """Non-zero exit → success=False, error alert is the delivered message."""
    from cron.jobs import create_job
    from cron.scheduler import run_job

    script_path = hermes_env / "scripts" / "broken.sh"
    script_path.write_text("#!/bin/bash\necho oops >&2\nexit 3\n")

    job = create_job(
        prompt=None, schedule="every 5m", script="broken.sh", no_agent=True, deliver="local"
    )
    success, doc, final_response, error = run_job(job)
    assert success is False
    assert error is not None
    assert "oops" in final_response or "exited with code 3" in final_response
    assert "Cron watchdog" in final_response  # alert header


def test_run_job_no_agent_never_invokes_aiagent(hermes_env):
    """no_agent jobs must NOT import/construct the AIAgent."""
    from cron.jobs import create_job

    script_path = hermes_env / "scripts" / "alert.sh"
    script_path.write_text("#!/bin/bash\necho alert\n")

    job = create_job(
        prompt=None, schedule="every 5m", script="alert.sh", no_agent=True, deliver="local"
    )

    with patch("run_agent.AIAgent") as ai_mock:
        from cron.scheduler import run_job

        run_job(job)

    ai_mock.assert_not_called()


def test_run_job_no_agent_workdir_never_changes_process_cwd(hermes_env, tmp_path):
    """A no-agent workdir must not leak through process-global chdir."""
    from cron.jobs import create_job
    from cron.scheduler import run_job

    script_path = hermes_env / "scripts" / "cwd-probe.sh"
    started = tmp_path / "started"
    release = tmp_path / "release"
    workdir = tmp_path / "configured-workdir"
    workdir.mkdir()
    script_path.write_text(
        f"touch {shlex.quote(str(started))}\n"
        f"while [[ ! -e {shlex.quote(str(release))} ]]; do sleep 0.01; done\n"
        "pwd -P\n"
    )
    job = create_job(
        prompt=None,
        schedule="every 5m",
        script=script_path.name,
        no_agent=True,
        deliver="local",
        workdir=str(workdir),
    )
    result = []
    runner = threading.Thread(target=lambda: result.append(run_job(job)))
    original_cwd = os.getcwd()
    observed_cwd = None

    runner.start()
    try:
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "script did not start"
        observed_cwd = os.getcwd()
    finally:
        release.write_text("")
        runner.join(timeout=5)

    assert not runner.is_alive()
    assert observed_cwd == original_cwd
    assert os.getcwd() == original_cwd
    success, _doc, final_response, error = result[0]
    assert success is True
    assert error is None
    assert final_response == str(script_path.parent.resolve())


# ---------------------------------------------------------------------------
# _run_job_script: shell-script support
# ---------------------------------------------------------------------------


def test_run_job_script_shell_script_runs_via_bash(hermes_env):
    """.sh files should execute under /bin/bash even without a shebang line."""
    from cron.scheduler import _run_job_script

    script_path = hermes_env / "scripts" / "shelly.sh"
    # No shebang — relies on the interpreter-by-extension rule.
    script_path.write_text('echo "shell: $BASH_VERSION" | head -c 7\n')

    ok, output = _run_job_script("shelly.sh")
    assert ok is True
    assert output.startswith("shell:")


def test_run_job_script_bash_extension_also_runs_via_bash(hermes_env):
    from cron.scheduler import _run_job_script

    script_path = hermes_env / "scripts" / "thing.bash"
    script_path.write_text('printf "via bash\\n"\n')

    ok, output = _run_job_script("thing.bash")
    assert ok is True
    assert output == "via bash"


def test_run_job_script_hermes_isolated_shell_uses_fixed_bash_minimal_env(
    hermes_env, monkeypatch
):
    """The opt-in suffix must not trust PATH, bash startup hooks, or loader env."""
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    script_path = hermes_env / "scripts" / "probe.hermes-isolated.sh"
    script_path.write_text("printf isolated\n")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="isolated\n", stderr="")

    for name in ("BASH_ENV", "PYTHONPATH", "LD_PRELOAD"):
        monkeypatch.setenv(name, f"/ambient/{name.lower()}")
    monkeypatch.setenv("PATH", "/ambient/bin")
    monkeypatch.setattr(sched_mod.subprocess, "run", fake_run)

    ok, output = _run_job_script(script_path.name)

    assert ok is True
    assert output == "isolated"
    assert captured["argv"][:3] == [
        "/bin/bash",
        "--noprofile",
        "--norc",
    ]
    assert captured["argv"][3].startswith("/dev/fd/")
    assert captured["kwargs"]["cwd"].startswith("/dev/fd/")
    assert set(captured["kwargs"]["pass_fds"]) == {
        int(captured["argv"][3].removeprefix("/dev/fd/")),
        int(captured["kwargs"]["cwd"].removeprefix("/dev/fd/")),
    }
    assert all(fd >= 3 for fd in captured["kwargs"]["pass_fds"])
    assert captured["kwargs"]["env"] == {"PATH": "/usr/bin:/bin"}
    for fd in captured["kwargs"]["pass_fds"]:
        with pytest.raises(OSError):
            sched_mod.os.fstat(fd)


def test_run_job_script_hermes_isolated_shell_drops_poisoned_ambient_env(
    hermes_env, monkeypatch
):
    """Exercise the real child process to prove ambient code-loading vars are absent."""
    from cron.scheduler import _run_job_script

    script_path = hermes_env / "scripts" / "env.hermes-isolated.sh"
    ambient_names = (
        "BASH_ENV",
        "PYTHONPATH",
        "LD_PRELOAD",
        "HOME",
        "LANG",
        "TMPDIR",
        "HTTPS_PROXY",
    )
    script_path.write_text(
        "for name in " + " ".join(ambient_names) + '; do\n'
        '  if [[ -v "$name" ]]; then printf "LEAK:%s\\n" "$name"; fi\n'
        "done\n"
        'printf "PATH=%s\\n" "$PATH"\n'
    )
    poison = hermes_env / "poison.sh"
    poison.write_text("printf poisoned\n")
    monkeypatch.setenv("PATH", "/ambient/bin")
    monkeypatch.setenv("BASH_ENV", str(poison))
    monkeypatch.setenv("PYTHONPATH", "/ambient/python")
    monkeypatch.setenv("LD_PRELOAD", "/ambient/loader.so")
    monkeypatch.setenv("HOME", "/ambient/home")
    monkeypatch.setenv("LANG", "ambient_LOCALE")
    monkeypatch.setenv("TMPDIR", "/ambient/tmp")
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient.proxy")

    ok, output = _run_job_script(script_path.name)

    assert ok is True
    assert output == "PATH=/usr/bin:/bin"


@pytest.mark.parametrize("closed_fd", [0, 1, 2])
def test_run_job_script_hermes_isolated_shell_survives_closed_standard_fd(
    hermes_env, tmp_path, closed_fd
):
    """Held script/cwd descriptors must never collide with stdio remapping."""
    script_path = hermes_env / "scripts" / "closed-fd.hermes-isolated.sh"
    script_path.write_text('printf "exact\\n%s\\n" "$PWD"\n')
    result_path = tmp_path / f"result-{closed_fd}.json"
    probe = """
import json
import os
from pathlib import Path
from cron.scheduler import _run_job_script

os.close(int(os.environ["CLOSED_STANDARD_FD"]))
ok, output = _run_job_script("closed-fd.hermes-isolated.sh")
Path(os.environ["RESULT_PATH"]).write_text(json.dumps([ok, output]))
"""
    env = os.environ.copy()
    env["HERMES_HOME"] = str(hermes_env)
    env["CLOSED_STANDARD_FD"] = str(closed_fd)
    env["RESULT_PATH"] = str(result_path)

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        timeout=10,
    )

    assert completed.returncode == 0
    ok, output = json.loads(result_path.read_text())
    assert ok is True
    assert output == f"exact\n{script_path.parent.resolve()}"


def test_run_job_script_hermes_isolated_shell_fails_clearly_off_posix(
    hermes_env, monkeypatch
):
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    script_path = hermes_env / "scripts" / "probe.hermes-isolated.sh"
    script_path.write_text("printf isolated\n")
    monkeypatch.setattr(sched_mod, "_IS_POSIX", False)

    ok, output = _run_job_script(script_path.name)

    assert ok is False
    assert "requires a POSIX platform" in output


def test_run_job_script_hermes_isolated_shell_rejects_escaping_symlink(
    hermes_env, tmp_path
):
    from cron.scheduler import _run_job_script

    outside = tmp_path / "outside.hermes-isolated.sh"
    outside.write_text("printf escaped\n")
    link = hermes_env / "scripts" / "linked.hermes-isolated.sh"
    link.symlink_to(outside)

    ok, output = _run_job_script(link.name)

    assert ok is False
    assert "symlink" in output.lower() or "indirection" in output.lower()


def test_run_job_script_hermes_isolated_shell_rejects_contained_symlink(
    hermes_env
):
    """The selected lexical isolated name must never downgrade through a symlink."""
    from cron.scheduler import _run_job_script

    target = hermes_env / "scripts" / "target.sh"
    target.write_text("printf target\n")
    selected = hermes_env / "scripts" / "selected.hermes-isolated.sh"
    selected.symlink_to(target)

    ok, output = _run_job_script(selected.name)

    assert ok is False
    assert "symlink" in output.lower() or "indirection" in output.lower()


def test_run_job_script_hermes_isolated_shell_rejects_intermediate_symlink(
    hermes_env
):
    from cron.scheduler import _run_job_script

    real_parent = hermes_env / "scripts" / "real-parent"
    real_parent.mkdir()
    (real_parent / "probe.hermes-isolated.sh").write_text("printf target\n")
    linked_parent = hermes_env / "scripts" / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    ok, output = _run_job_script(
        "linked-parent/probe.hermes-isolated.sh"
    )

    assert ok is False
    assert "symlink" in output.lower() or "indirection" in output.lower()


def test_run_job_script_hermes_isolated_shell_rejects_anchor_parent_redirect(
    hermes_env, monkeypatch
):
    """Swapping an absolute anchor component cannot redirect scripts_dir."""
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    selected_name = "anchor.hermes-isolated.sh"
    (hermes_env / "scripts" / selected_name).write_text("printf safe\n")
    original_home = hermes_env.with_name(".hermes-original")
    redirect_home = hermes_env.with_name(".hermes-redirect")
    (redirect_home / "scripts").mkdir(parents=True)
    (redirect_home / "scripts" / selected_name).write_text("printf evil\n")
    real_open = sched_mod.os.open
    swapped = False

    def redirect_anchor(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and path == ".hermes":
            swapped = True
            hermes_env.rename(original_home)
            hermes_env.symlink_to(redirect_home, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(sched_mod.os, "open", redirect_anchor)

    ok, output = _run_job_script(selected_name)

    assert swapped is True
    assert ok is False
    assert "symlink" in output.lower() or "indirection" in output.lower()


def test_run_job_script_legacy_symlink_to_isolated_name_stays_legacy(
    hermes_env, monkeypatch
):
    """A legacy lexical selection must not opt in based on its resolved target."""
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    target = hermes_env / "scripts" / "target.hermes-isolated.sh"
    target.write_text("printf target\n")
    selected = hermes_env / "scripts" / "selected.sh"
    selected.symlink_to(target)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="legacy\n", stderr="")

    monkeypatch.setattr(sched_mod.shutil, "which", lambda name: "/legacy/bin/bash")
    monkeypatch.setattr(sched_mod.subprocess, "run", fake_run)

    ok, output = _run_job_script(selected.name)

    assert ok is True
    assert output == "legacy"
    assert captured["argv"] == ["/legacy/bin/bash", str(target.resolve())]
    assert "pass_fds" not in captured["kwargs"]


def test_run_job_script_isolated_suffix_is_case_sensitive(hermes_env, monkeypatch):
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    script = hermes_env / "scripts" / "upper.HERMES-ISOLATED.SH"
    script.write_text("printf legacy\n")
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return SimpleNamespace(returncode=0, stdout="legacy\n", stderr="")

    monkeypatch.setattr(sched_mod.shutil, "which", lambda name: "/legacy/bin/bash")
    monkeypatch.setattr(sched_mod.subprocess, "run", fake_run)

    ok, output = _run_job_script(script.name)

    assert ok is True
    assert output == "legacy"
    assert captured["argv"] == ["/legacy/bin/bash", str(script.resolve())]


def test_run_job_script_hermes_isolated_shell_accepts_normalized_internal_path(
    hermes_env
):
    from cron.scheduler import _run_job_script

    (hermes_env / "scripts" / "nested").mkdir()
    script = hermes_env / "scripts" / "normalized.hermes-isolated.sh"
    script.write_text("printf normalized\n")

    ok, output = _run_job_script("nested/../normalized.hermes-isolated.sh")

    assert ok is True
    assert output == "normalized"


def test_run_job_script_hermes_isolated_shell_executes_held_inode_after_path_swap(
    hermes_env, tmp_path, monkeypatch
):
    """Swapping the selected pathname cannot change the already-opened script."""
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    selected = hermes_env / "scripts" / "swap.hermes-isolated.sh"
    selected.write_text("printf safe\n")
    outside = tmp_path / "outside.sh"
    outside.write_text("printf evil\n")
    original_run = sched_mod.subprocess.run

    def swap_then_run(argv, **kwargs):
        selected.unlink()
        selected.symlink_to(outside)
        return original_run(argv, **kwargs)

    monkeypatch.setattr(sched_mod.subprocess, "run", swap_then_run)

    ok, output = _run_job_script(selected.name)

    assert ok is True
    assert output == "safe"


def test_run_job_script_hermes_isolated_shell_pins_parent_cwd(
    hermes_env, monkeypatch
):
    """Replacing the parent pathname cannot redirect relative file access."""
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    parent = hermes_env / "scripts" / "held"
    parent.mkdir()
    (parent / "marker").write_text("safe\n")
    script = parent / "cwd.hermes-isolated.sh"
    script.write_text("cat marker\n")
    moved = hermes_env / "scripts" / "held-original"
    original_run = sched_mod.subprocess.run

    def swap_parent_then_run(argv, **kwargs):
        parent.rename(moved)
        parent.mkdir()
        (parent / "marker").write_text("evil\n")
        return original_run(argv, **kwargs)

    monkeypatch.setattr(sched_mod.subprocess, "run", swap_parent_then_run)

    ok, output = _run_job_script("held/cwd.hermes-isolated.sh")

    assert ok is True
    assert output == "safe"


def test_run_job_script_hermes_isolated_shell_requires_fixed_bash(
    hermes_env, monkeypatch
):
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    script = hermes_env / "scripts" / "missing.hermes-isolated.sh"
    script.write_text("printf no\n")
    real_isfile = sched_mod.os.path.isfile
    monkeypatch.setattr(
        sched_mod.os.path,
        "isfile",
        lambda value: False if value == "/bin/bash" else real_isfile(value),
    )

    ok, output = _run_job_script(script.name)

    assert ok is False
    assert "required interpreter /bin/bash was not found" in output


def test_run_job_script_hermes_isolated_shell_requires_fd_filesystem(
    hermes_env, monkeypatch
):
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    script = hermes_env / "scripts" / "missing-fd.hermes-isolated.sh"
    script.write_text("printf no\n")
    monkeypatch.setattr(
        sched_mod, "_HERMES_ISOLATED_FD_ROOT", "/definitely-missing-dev-fd"
    )

    ok, output = _run_job_script(script.name)

    assert ok is False
    assert "require /definitely-missing-dev-fd" in output


def test_run_job_script_hermes_isolated_shell_requires_regular_inode(hermes_env):
    from cron.scheduler import _run_job_script

    fifo = hermes_env / "scripts" / "pipe.hermes-isolated.sh"
    fifo.parent.mkdir(exist_ok=True)
    os.mkfifo(fifo)

    ok, output = _run_job_script(fifo.name)

    assert ok is False
    assert "not a regular file" in output


def test_run_job_script_legacy_shell_and_python_dispatch_unchanged(
    hermes_env, monkeypatch
):
    """The opt-in suffix must not alter existing .sh/.bash/.py launch behavior."""
    from cron import scheduler as sched_mod
    from cron.scheduler import _run_job_script

    scripts = {
        "legacy.sh": "printf shell\n",
        "legacy.bash": "printf bash\n",
        "legacy.py": "print('python')\n",
    }
    for name, body in scripts.items():
        (hermes_env / "scripts" / name).write_text(body)

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(sched_mod.shutil, "which", lambda name: "/legacy/bin/bash")
    monkeypatch.setattr(sched_mod.subprocess, "run", fake_run)
    monkeypatch.setenv("BASH_ENV", "/ambient/bash-env")

    for name in scripts:
        ok, output = _run_job_script(name)
        assert ok is True
        assert output == "ok"

    assert calls[0][0][0] == "/legacy/bin/bash"
    assert calls[1][0][0] == "/legacy/bin/bash"
    assert calls[2][0][0] == sched_mod.sys.executable
    assert all(
        call[0][1] == str((hermes_env / "scripts" / name).resolve())
        for call, name in zip(calls, scripts)
    )
    assert all(call[1]["env"] != {"PATH": "/usr/bin:/bin"} for call in calls)


def test_run_job_script_python_still_runs_via_python(hermes_env):
    """Regression: .py files must keep running via sys.executable."""
    from cron.scheduler import _run_job_script

    script_path = hermes_env / "scripts" / "py.py"
    script_path.write_text("import sys\nprint(f'python {sys.version_info.major}')\n")

    ok, output = _run_job_script("py.py")
    assert ok is True
    assert output.startswith("python ")


def test_run_job_script_path_traversal_still_blocked(hermes_env):
    """Security regression: shell-script support must NOT loosen containment."""
    from cron.scheduler import _run_job_script

    # Absolute path outside the scripts dir should be rejected.
    ok, output = _run_job_script("/etc/passwd")
    assert ok is False
    assert "Blocked" in output or "outside" in output
