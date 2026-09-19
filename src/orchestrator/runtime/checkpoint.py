"""Checkpointer factory: Postgres in production, SQLite or in-memory for local/test."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from orchestrator.config import Settings


def create_checkpointer(settings: Settings) -> tuple[BaseCheckpointSaver[Any], Callable[[], None]]:
    """Return a ready-to-use checkpointer and a close callback."""
    kind = settings.resolved_checkpointer
    if kind == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        pool: ConnectionPool[Any] = ConnectionPool(
            conninfo=settings.postgres_conninfo,
            max_size=10,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=True,
        )
        saver = PostgresSaver(pool)
        saver.setup()
        return saver, pool.close

    if kind == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver

        path = Path(settings.checkpoint_sqlite_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False)
        sqlite_saver = SqliteSaver(conn)
        sqlite_saver.setup()
        return sqlite_saver, conn.close

    return InMemorySaver(), lambda: None
