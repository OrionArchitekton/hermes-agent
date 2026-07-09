from gateway import systemd_planned_stop


def test_systemd_planned_stop_writes_marker_for_main_pid(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        systemd_planned_stop,
        "write_planned_stop_marker",
        lambda pid: calls.append(pid) or True,
    )

    assert systemd_planned_stop.main(["1234"]) == 0
    assert calls == [1234]
    assert capsys.readouterr().err == ""


def test_systemd_planned_stop_targets_gateway_child_under_wrapper(monkeypatch, capsys):
    calls = []
    parents = {2001: 2000, 2002: 2001}
    cmdlines = {
        2000: "/usr/bin/doppler run -- python -m hermes_cli.main gateway run --replace",
        2001: "/home/hermes/hermes-agent-v31/venv/bin/python -m hermes_cli.main gateway run --replace",
        2002: "sleep 60",
    }
    monkeypatch.setattr(systemd_planned_stop, "_iter_proc_pids", lambda: [2000, 2001, 2002])
    monkeypatch.setattr(systemd_planned_stop, "_read_proc_ppid", lambda pid: parents.get(pid))
    monkeypatch.setattr(systemd_planned_stop, "_read_proc_cmdline", lambda pid: cmdlines.get(pid))
    monkeypatch.setattr(
        systemd_planned_stop,
        "write_planned_stop_marker",
        lambda pid: calls.append(pid) or True,
    )

    assert systemd_planned_stop.main(["2000"]) == 0
    assert calls == [2001]
    assert "resolved gateway child PID 2001 from MAINPID 2000" in capsys.readouterr().err


def test_systemd_planned_stop_fails_closed_without_main_pid(capsys):
    assert systemd_planned_stop.main([]) == 1
    assert "missing MAINPID" in capsys.readouterr().err


def test_systemd_planned_stop_fails_closed_for_non_numeric_main_pid(capsys):
    assert systemd_planned_stop.main(["not-a-pid"]) == 1
    assert "invalid MAINPID" in capsys.readouterr().err
