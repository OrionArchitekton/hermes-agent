from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="CLI wrapper is only supported on Unix-like systems",
)


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "install-cli-wrapper.sh"


def _write_executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def test_install_cli_wrapper_creates_path_visible_current_cli(tmp_path: Path) -> None:
    real = tmp_path / "active" / "venv" / "bin" / "hermes"
    link = tmp_path / "bin" / "hermes"
    _write_executable(
        real,
        "#!/usr/bin/env bash\n"
        "printf 'real=%s args=%s\\n' \"$0\" \"$*\"\n",
    )

    install = subprocess.run(
        [str(SCRIPT), "--hermes-bin", str(real), "--link", str(link)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert link.is_file()
    assert os.access(link, os.X_OK)

    run = subprocess.run(
        ["hermes", "cron", "list"],
        env={"PATH": f"{link.parent}:/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert f"real={real}" in run.stdout
    assert "args=cron list" in run.stdout


def test_install_cli_wrapper_refuses_unrelated_existing_file(tmp_path: Path) -> None:
    real = tmp_path / "active" / "venv" / "bin" / "hermes"
    link = tmp_path / "bin" / "hermes"
    _write_executable(real, "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(link, "#!/usr/bin/env bash\n# unrelated operator file\n")

    proc = subprocess.run(
        [str(SCRIPT), "--hermes-bin", str(real), "--link", str(link)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "refusing to overwrite" in proc.stderr
    assert "unrelated operator file" in link.read_text(encoding="utf-8")


def test_install_cli_wrapper_refuses_directory_target(tmp_path: Path) -> None:
    real = tmp_path / "active" / "venv" / "bin" / "hermes"
    link = tmp_path / "bin" / "hermes"
    _write_executable(real, "#!/usr/bin/env bash\nexit 0\n")
    link.mkdir(parents=True)

    proc = subprocess.run(
        [str(SCRIPT), "--force", "--hermes-bin", str(real), "--link", str(link)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 1
    assert "target path is a directory" in proc.stderr
    assert list(link.iterdir()) == []


def test_install_cli_wrapper_force_replaces_existing_wrapper(tmp_path: Path) -> None:
    real = tmp_path / "active" / "venv" / "bin" / "hermes"
    link = tmp_path / "bin" / "hermes"
    _write_executable(real, "#!/usr/bin/env bash\nprintf 'current\\n'\n")
    _write_executable(link, "#!/usr/bin/env bash\n# old Hermes wrapper\nexit 127\n")

    proc = subprocess.run(
        [str(SCRIPT), "--force", "--hermes-bin", str(real), "--link", str(link)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "Managed by Hermes install-cli-wrapper.sh" in link.read_text(encoding="utf-8")

    run = subprocess.run(
        [str(link)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0
    assert run.stdout == "current\n"


def test_install_cli_wrapper_preserves_optional_slack_doppler_route(tmp_path: Path) -> None:
    real = tmp_path / "active" / "venv" / "bin" / "hermes"
    doppler = tmp_path / "bin" / "doppler"
    env_file = tmp_path / "doppler.env"
    link = tmp_path / "bin" / "hermes"
    record = tmp_path / "doppler_args.txt"
    _write_executable(real, "#!/usr/bin/env bash\nprintf 'direct %s\\n' \"$*\"\n")
    _write_executable(
        doppler,
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" > {record}\n"
        "while [ \"$#\" -gt 0 ] && [ \"$1\" != \"--\" ]; do shift; done\n"
        "[ \"$#\" -gt 0 ] && shift\n"
        "exec \"$@\"\n",
    )
    env_file.write_text("SLACK_BOT_TOKEN=x-test\n", encoding="utf-8")

    proc = subprocess.run(
        [
            str(SCRIPT),
            "--hermes-bin",
            str(real),
            "--link",
            str(link),
            "--slack-doppler-env-file",
            str(env_file),
            "--doppler-bin",
            str(doppler),
            "--slack-doppler-project",
            "hermes-agent",
            "--slack-doppler-config",
            "prd",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    run = subprocess.run(
        [str(link), "send", "--to", "slack:#ops", "hello"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert run.returncode == 0
    assert "direct send --to slack:#ops hello" in run.stdout
    doppler_args = record.read_text(encoding="utf-8")
    assert "run --project hermes-agent --config prd --" in doppler_args

    record.unlink()
    run_with_profile = subprocess.run(
        [str(link), "--profile", "prod", "send", "-t=slack:#ops", "hello"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert run_with_profile.returncode == 0
    assert "direct --profile prod send -t=slack:#ops hello" in run_with_profile.stdout
    doppler_args = record.read_text(encoding="utf-8")
    assert "run --project hermes-agent --config prd --" in doppler_args
