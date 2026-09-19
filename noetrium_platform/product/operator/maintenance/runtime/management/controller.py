from __future__ import annotations

import signal
import threading

from .context import ManagementCommandContext

GROUP = "controller"


def register(groups) -> None:
    parser = groups.add_parser(GROUP)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("--interval-seconds", type=float, default=10.0)
    run.add_argument("--max-cycles", type=int)


def dispatch(args, context: ManagementCommandContext):
    controller = context.models.controller
    if args.action == "status":
        return controller.snapshot()
    if args.action != "run":
        raise ValueError(f"unsupported controller management action: {args.action}")

    stop = threading.Event()
    previous = {}

    def request_stop(signum, frame):
        del signum, frame
        stop.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    try:
        return controller.run(
            interval_seconds=args.interval_seconds,
            stop=stop,
            max_cycles=args.max_cycles,
        )
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


__all__ = ["GROUP", "dispatch", "register"]
