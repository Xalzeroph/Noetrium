from __future__ import annotations

import sqlite3


def rollback_data_writer(db: sqlite3.Connection, primary: BaseException) -> None:
    """Rollback an active Data transaction without replacing its primary failure."""

    if not db.in_transaction:
        return
    try:
        db.rollback()
    except BaseException as rollback_exc:
        primary.add_note(
            "data sqlite rollback failed: "
            f"{type(rollback_exc).__name__}"
        )


__all__ = ["rollback_data_writer"]
