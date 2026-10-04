"""Module 10: SQLite Storage Engine Implementation.

Provides robust connection management, foreign key enforcement, WAL mode,
transaction context managers, and parameterized query execution.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Dict, Any, List, Optional, Tuple, Iterator

from .base import StorageEngine
from .migrations import SchemaMigrator, CURRENT_SCHEMA_VERSION

logger = logging.getLogger(__name__)


def dict_factory(cursor: sqlite3.Cursor, row: Tuple[Any, ...]) -> Dict[str, Any]:
    """Convert SQLite row to dictionary keyed by column name."""
    fields = [col[0] for col in cursor.description]
    return {col: val for col, val in zip(fields, row)}


class SQLiteStore(StorageEngine):
    """SQLite implementation of the StorageEngine abstraction."""

    def __init__(self, db_path: str = "aarogya.db", auto_init: bool = True):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False
        self._closed = False

        if auto_init:
            self.initialize()

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create the underlying SQLite connection with safety pragmas."""
        with self._lock:
            if self._closed:
                raise sqlite3.OperationalError("Cannot operate on a closed database connection.")
            if self._conn is None:
                # Ensure directory exists if path contains directories
                dirname = os.path.dirname(self.db_path)
                if dirname:
                    os.makedirs(dirname, exist_ok=True)

                conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=10.0,
                )
                conn.row_factory = dict_factory
                # Mandatory database safety pragmas
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.execute("PRAGMA busy_timeout = 5000;")
                try:
                    conn.execute("PRAGMA journal_mode = WAL;")
                except sqlite3.OperationalError:
                    pass  # In-memory databases or some environments may not support WAL
                self._conn = conn
            return self._conn

    def initialize(self) -> None:
        """Run schema migrations and initialize tables."""
        with self._lock:
            if self._initialized:
                return
            conn = self._get_connection()
            migrator = SchemaMigrator(conn)
            version = migrator.apply_migrations()
            logger.info("Initialized SQLiteStore at '%s' (schema version %d)", self.db_path, version)
            self._initialized = True

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager yielding a transactional cursor with commit/rollback."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error("Transaction rolled back due to error: %s", str(e))
                raise
            finally:
                cursor.close()

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> Any:
        """Execute a parameterized query and commit immediately."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                conn.commit()
                return cursor.rowcount
            except Exception as e:
                conn.rollback()
                logger.error("Execute query failed: %s | query: %s", str(e), query)
                raise
            finally:
                cursor.close()

    def fetchone(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single record as a dict."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchone()
            finally:
                cursor.close()

    def fetchall(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        """Fetch all records as a list of dicts."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchall()
            finally:
                cursor.close()

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self._closed = True
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception as e:
                    logger.warning("Error closing SQLite connection: %s", str(e))
                finally:
                    self._conn = None
                    self._initialized = False
