"""Mark systemd-managed gateway stops as intentional before SIGTERM.

Systemd's ExecStop runs before it sends KillSignal=SIGTERM to the main
process.  The gateway already distinguishes intentional stops from crash-like
signals via the planned-stop marker, so this helper is intentionally tiny:
parse systemd's $MAINPID and write that marker.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from gateway.status import write_planned_stop_marker


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

    if not write_planned_stop_marker(main_pid):
        print(
            f"systemd-planned-stop: failed to mark planned stop for PID {main_pid}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
