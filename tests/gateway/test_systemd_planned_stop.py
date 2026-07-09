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


def test_systemd_planned_stop_fails_closed_without_main_pid(capsys):
    assert systemd_planned_stop.main([]) == 1
    assert "missing MAINPID" in capsys.readouterr().err


def test_systemd_planned_stop_fails_closed_for_non_numeric_main_pid(capsys):
    assert systemd_planned_stop.main(["not-a-pid"]) == 1
    assert "invalid MAINPID" in capsys.readouterr().err
