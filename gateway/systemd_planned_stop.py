"""Mark systemd-managed gateway stops as intentional before SIGTERM.

Systemd's ExecStop runs before it sends KillSignal=SIGTERM to the main
process.  The gateway already distinguishes intentional stops from crash-like
signals via the planned-stop marker, so this helper is intentionally tiny:
parse systemd's $MAINPID and write that marker.
"""

from __future__ import annotations

import sys
from collections import defaultdict, deque
from collections.abc import Sequence
from pathlib import Path

from gateway.status import write_planned_stop_marker

_PROC_ROOT = Path("/proc")


def _iter_proc_pids() -> list[int]:
    pids: list[int] = []
    try:
        entries = list(_PROC_ROOT.iterdir())
    except OSError:
        return pids
    for entry in entries:
        if entry.name.isdigit():
            pids.append(int(entry.name))
    return pids


def _read_proc_ppid(pid: int) -> int | None:
    try:
        with (_PROC_ROOT / str(pid) / "status").open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("PPid:"):
                    return int(line.split(":", 1)[1].strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    return None


def _read_proc_cmdline(pid: int) -> str | None:
    try:
        data = (_PROC_ROOT / str(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, OSError):
        return None
    if not data:
        return None
    return data.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()


def _is_gateway_run_cmdline(cmdline: str | None) -> bool:
    if not cmdline:
        return False
    tokens = cmdline.split()
    if not tokens or not Path(tokens[0]).name.startswith("python"):
        return False
    return "-m" in tokens and "hermes_cli.main" in tokens and "gateway" in tokens and "run" in tokens


def _resolve_gateway_marker_pid(main_pid: int) -> int:
    if _is_gateway_run_cmdline(_read_proc_cmdline(main_pid)):
        return main_pid

    children_by_parent: dict[int, list[int]] = defaultdict(list)
    for pid in _iter_proc_pids():
        ppid = _read_proc_ppid(pid)
        if ppid is not None:
            children_by_parent[ppid].append(pid)

    queue: deque[int] = deque(children_by_parent.get(main_pid, []))
    seen: set[int] = set()
    while queue:
        pid = queue.popleft()
        if pid in seen:
            continue
        seen.add(pid)
        if _is_gateway_run_cmdline(_read_proc_cmdline(pid)):
            return pid
        queue.extend(children_by_parent.get(pid, []))

    return main_pid


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or not str(args[0]).strip():
        print("systemd-planned-stop: missing MAINPID", file=sys.stderr)
        return 1

    try:
        main_pid = int(args[0])
    except (TypeError, ValueError):
        print(f"systemd-planned-stop: invalid MAINPID: {args[0]!r}", file=sys.stderr)
        return 1

    if main_pid <= 0:
        print(f"systemd-planned-stop: invalid MAINPID: {main_pid}", file=sys.stderr)
        return 1

    marker_pid = _resolve_gateway_marker_pid(main_pid)
    if marker_pid != main_pid:
        print(
            f"systemd-planned-stop: resolved gateway child PID {marker_pid} from MAINPID {main_pid}",
            file=sys.stderr,
        )

    if not write_planned_stop_marker(marker_pid):
        print(
            f"systemd-planned-stop: failed to mark planned stop for PID {marker_pid}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
