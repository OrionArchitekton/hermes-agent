from hermes_cli.gateway import _runtime_health_lines


def test_runtime_health_lines_include_fatal_platform_and_startup_reason(monkeypatch):
    monkeypatch.setattr(
        "gateway.status.read_runtime_status",
        lambda: {
            "gateway_state": "startup_failed",
            "exit_reason": "telegram conflict",
            "platforms": {
                "telegram": {
                    "state": "fatal",
                    "error_message": "another poller is active",
                }
            },
        },
    )

    lines = _runtime_health_lines()

    assert "⚠ telegram: another poller is active" in lines
    assert "⚠ Last startup issue: telegram conflict" in lines


def test_runtime_health_lines_include_nonfatal_slack_disconnect(monkeypatch):
    monkeypatch.setattr(
        "gateway.status.read_runtime_status",
        lambda: {
            "gateway_state": "running",
            "platforms": {
                "slack": {
                    "state": "disconnected",
                    "error_message": "socket mode reconnect failed",
                }
            },
        },
    )

    lines = _runtime_health_lines()

    assert "⚠ slack: disconnected (socket mode reconnect failed)" in lines


def test_runtime_health_lines_include_slack_cron_delivery_failures(monkeypatch):
    monkeypatch.setattr(
        "gateway.status.read_runtime_status",
        lambda: {"gateway_state": "running", "platforms": {}},
    )
    monkeypatch.setattr(
        "cron.jobs.load_jobs",
        lambda: [
            {
                "id": "slack-digest",
                "name": "ops digest",
                "deliver": "slack:C123",
                "last_run_at": "2026-07-07T20:00:00Z",
                "last_delivery_error": "delivery to slack:C123 failed: timeout",
            },
            {
                "id": "telegram-digest",
                "name": "telegram digest",
                "deliver": "telegram",
                "last_run_at": "2026-07-07T20:01:00Z",
                "last_delivery_error": "delivery to telegram failed",
            },
            {
                "id": "broadcast-digest",
                "name": "broadcast digest",
                "deliver": "all",
                "last_run_at": "2026-07-07T20:01:30Z",
                "last_delivery_error": "delivery to slack failed in broadcast fanout",
            },
            {
                "id": "slack-origin",
                "name": "approval loop",
                "deliver": "origin",
                "origin": {"platform": "slack", "chat_id": "C999"},
                "last_run_at": "2026-07-07T20:02:00Z",
                "last_delivery_error": "delivery to slack:C999 failed: missing channel",
            },
        ],
    )

    lines = _runtime_health_lines()

    assert (
        "⚠ Slack cron delivery: 2 job(s) failing; latest approval loop: "
        "delivery to slack:C999 failed: missing channel"
    ) in lines
    assert not any("telegram digest" in line for line in lines)


def test_runtime_health_lines_ignores_cron_storage_failures(monkeypatch):
    monkeypatch.setattr(
        "gateway.status.read_runtime_status",
        lambda: {"gateway_state": "running", "platforms": {}},
    )

    def _raise_load_error():
        raise RuntimeError("jobs database unreadable")

    monkeypatch.setattr("cron.jobs.load_jobs", _raise_load_error)

    assert _runtime_health_lines() == []


def test_runtime_status_running_pid_validates_live_gateway_record(monkeypatch):
    from gateway import status as status_mod

    runtime = {
        "pid": 12345,
        "kind": "hermes-gateway",
        "argv": ["/opt/hermes/hermes_cli/main.py", "gateway", "run", "--replace"],
        "start_time": None,
        "gateway_state": "running",
    }
    monkeypatch.setattr(status_mod, "_pid_exists", lambda pid: pid == 12345)
    monkeypatch.setattr(status_mod, "_get_process_start_time", lambda pid: None)
    monkeypatch.setattr(status_mod, "_looks_like_gateway_process", lambda pid: False)

    assert status_mod.get_runtime_status_running_pid(runtime) == 12345


def test_runtime_status_running_pid_rejects_stopped_record(monkeypatch):
    from gateway import status as status_mod

    runtime = {
        "pid": 12345,
        "kind": "hermes-gateway",
        "argv": ["/opt/hermes/hermes_cli/main.py", "gateway", "run", "--replace"],
        "gateway_state": "stopped",
    }
    monkeypatch.setattr(status_mod, "_pid_exists", lambda pid: True)

    assert status_mod.get_runtime_status_running_pid(runtime) is None
