"""Persistent one-time nonce registry for replay protection."""
import sqlite3
from contextlib import closing
from pathlib import Path

class NonceRegistry:
    def __init__(self, database_path):
        self.database_path = str(database_path)
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as db:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS consumed_nonces (nonce TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")

    def consume_once(self, nonce, expires_at, now):
        # SQLite distinguishes TEXT from BLOB primary-key values.  Accepting
        # bytes here would let the same nonce bytes be consumed once as text
        # and again as a BLOB, so the registry boundary is string-only.
        if not isinstance(nonce, str) or not nonce or len(nonce) > 256:
            return False
        if type(expires_at) is not int or expires_at <= now:
            return False
        db = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM consumed_nonces WHERE expires_at < ?", (int(now),))
            try:
                db.execute("INSERT INTO consumed_nonces(nonce,expires_at) VALUES(?,?)", (nonce, expires_at))
            except sqlite3.IntegrityError:
                db.rollback()
                return False
            db.commit()
            return True
        finally:
            db.close()
