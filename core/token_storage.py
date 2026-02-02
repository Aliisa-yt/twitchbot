"""Token storage implementation using SQLite3.

This module provides persistent storage for Twitch API tokens using SQLite3 database.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["TokenStorage"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TokenStorage:
    """SQLite3-based storage for Twitch API tokens.

    This class manages token persistence using SQLite3 database, providing methods
    to save, load, and check token expiration.

    Attributes:
        db_path (Path): Path to the SQLite database file.
        _connection (sqlite3.Connection | None): Active database connection.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the TokenStorage with the path to the database file.

        Args:
            db_path (str | Path): Path to the SQLite database file.

        Raises:
            RuntimeError: If the database path is empty.
        """
        logger.debug("Initializing %s", self.__class__.__name__)

        db_path = Path(db_path)
        if str(db_path).strip() == "":
            msg: str = "The database path is empty."
            raise RuntimeError(msg)

        self.db_path: Path = db_path
        self._connection: sqlite3.Connection | None = None
        logger.debug("Database path set to: %s", self.db_path)

    def __enter__(self) -> Self:
        """Enter context manager; initialize database connection."""
        self._initialize_database()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager; close database connection."""
        _ = exc_type, exc_val, exc_tb
        self.close()

    def _initialize_database(self) -> None:
        """Initialize database connection and create tables if they don't exist."""
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create connection
        self._connection = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,  # Allow usage from different threads
            isolation_level=None,  # Autocommit mode
        )
        self._connection.row_factory = sqlite3.Row

        # Create table if it doesn't exist
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                key TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_in INTEGER NOT NULL,
                obtained_at REAL NOT NULL,
                scope TEXT,
                token_type TEXT
            )
            """
        )
        logger.debug("Database initialized successfully")

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the active database connection.

        Returns:
            sqlite3.Connection: Active database connection.

        Raises:
            RuntimeError: If database is not initialized.
        """
        if self._connection is None:
            msg = "Database connection is not initialized. Use context manager or call _initialize_database()."
            raise RuntimeError(msg)
        return self._connection

    def load_tokens(self, key: str = "twitch_bot") -> dict[str, Any]:
        """Load tokens from the database for the specified key.

        Args:
            key (str): Identifier for the token entry (default: "twitch_bot").

        Returns:
            dict[str, Any]: Token data dictionary, or empty dict if not found.
        """
        if self._connection is None:
            self._initialize_database()

        cursor: sqlite3.Cursor = self.connection.execute(
            "SELECT * FROM tokens WHERE key = ?",
            (key,),
        )
        row = cursor.fetchone()

        if row is None:
            logger.debug("No tokens found for key: %s", key)
            return {}

        # Convert row to dictionary
        tokens: dict[str, Any] = dict(row)
        # Remove the 'key' field from the result
        tokens.pop("key", None)

        # Parse scope from JSON string if present
        if tokens.get("scope"):
            try:
                tokens["scope"] = json.loads(tokens["scope"])
            except json.JSONDecodeError:
                logger.warning("Failed to parse scope JSON; using as-is")

        logger.debug("Loaded tokens for key: %s", key)
        return tokens

    def save_tokens(self, data: dict[str, Any], key: str = "twitch_bot") -> None:
        """Save tokens to the database.

        Args:
            data (dict[str, Any]): Token data to save.
            key (str): Identifier for the token entry (default: "twitch_bot").
        """
        if self._connection is None:
            self._initialize_database()

        # Serialize scope to JSON if it's a list
        scope_value: str | None = None
        if "scope" in data:
            scope_value = json.dumps(data["scope"]) if isinstance(data["scope"], list) else data["scope"]

        # Insert or replace the token entry
        self.connection.execute(
            """
            INSERT OR REPLACE INTO tokens (
                key, access_token, refresh_token, expires_in,
                obtained_at, scope, token_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                data.get("access_token", ""),
                data.get("refresh_token", ""),
                data.get("expires_in", 0),
                data.get("obtained_at", time.time()),
                scope_value,
                data.get("token_type", "bearer"),
            ),
        )
        logger.debug("Saved tokens for key: %s", key)

    def is_expired(self, tokens: dict[str, Any]) -> bool:
        """Check if the access token is expired.

        Args:
            tokens (dict[str, Any]): Token data dictionary.

        Returns:
            bool: True if the token is expired or about to expire, False otherwise.
        """
        if not tokens:
            return True

        obtained = float(tokens.get("obtained_at", 0))
        expires = float(tokens.get("expires_in", 0))
        expiry: float = obtained + expires
        # Refresh 1 minute before expiry
        return time.time() >= (expiry - 60.0)

    def delete_tokens(self, key: str = "twitch_bot") -> None:
        """Delete tokens from the database.

        Args:
            key (str): Identifier for the token entry (default: "twitch_bot").
        """
        if self._connection is None:
            self._initialize_database()

        self.connection.execute(
            "DELETE FROM tokens WHERE key = ?",
            (key,),
        )
        logger.debug("Deleted tokens for key: %s", key)

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            logger.debug("Database connection closed")
