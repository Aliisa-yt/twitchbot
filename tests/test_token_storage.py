from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from core.token_storage import TokenStorage

if TYPE_CHECKING:
    from pathlib import Path


def test_token_storage_load_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "tokens.db"
    storage = TokenStorage(db_path)
    with storage:
        tokens = storage.load_tokens()
    assert tokens == {}


def test_token_storage_save_and_load_with_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "tokens.db"
    storage = TokenStorage(db_path)
    data = {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_in": 3600,
        "obtained_at": time.time(),
        "scope": ["chat:read", "chat:edit"],
        "token_type": "bearer",
    }
    with storage:
        storage.save_tokens(data)
        loaded = storage.load_tokens()
    assert loaded["access_token"] == "access"
    assert loaded["refresh_token"] == "refresh"
    assert loaded["scope"] == ["chat:read", "chat:edit"]


def test_token_storage_delete_tokens(tmp_path: Path) -> None:
    db_path = tmp_path / "tokens.db"
    storage = TokenStorage(db_path)
    data = {"access_token": "a", "refresh_token": "r", "expires_in": 3600, "obtained_at": time.time()}
    with storage:
        storage.save_tokens(data)
        storage.delete_tokens()
        loaded = storage.load_tokens()
    assert loaded == {}


def test_token_storage_is_expired_empty_tokens(tmp_path: Path) -> None:
    db_path = tmp_path / "tokens.db"
    storage = TokenStorage(db_path)
    with storage:
        assert storage.is_expired({}) is True


def test_token_storage_rejects_empty_path() -> None:
    with pytest.raises(RuntimeError):
        TokenStorage("   ")
