"""SQLite test connection helpers with explicit close-on-context-exit semantics."""

import sqlite3


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(database, *args, **kwargs):
    """Return a normal sqlite connection whose context manager also closes it."""
    if "factory" in kwargs:
        raise TypeError("sqlite_test_support.connect owns the connection factory")
    return sqlite3.connect(database, *args, factory=ClosingConnection, **kwargs)
