"""Regression coverage for task-local gateway identity in terminal children."""

from __future__ import annotations

import os

from gateway.session_context import (
    _VAR_MAP,
    clear_session_vars,
    set_session_vars,
)
from tools.environments.local import _make_run_env


def test_cleared_gateway_context_overrides_stale_process_identity(
    monkeypatch,
) -> None:
    """A finished turn must not leak a prior process-global user identity."""
    saved_context = {name: var.get() for name, var in _VAR_MAP.items()}
    saved_env = os.environ.get("HERMES_SESSION_USER_ID")
    monkeypatch.setenv("HERMES_SESSION_USER_ID", "FOREIGN-USER")

    tokens = set_session_vars(
        platform="slack",
        chat_id="C-MINE",
        user_id="U-MINE",
    )
    clear_session_vars(tokens)
    try:
        child_env = _make_run_env({})
    finally:
        for name, var in _VAR_MAP.items():
            var.set(saved_context[name])
        if saved_env is None:
            os.environ.pop("HERMES_SESSION_USER_ID", None)
        else:
            os.environ["HERMES_SESSION_USER_ID"] = saved_env

    assert child_env.get("HERMES_SESSION_USER_ID", "") == ""
