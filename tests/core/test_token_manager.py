from __future__ import annotations

import builtins
import time
from pathlib import Path
from typing import Any, Self

import pytest

import core.token_manager as tm
from core.token_manager import TokenManager, TwitchBotToken, UserIDs


@pytest.fixture(autouse=True)
def set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWITCH_API_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("TWITCH_API_CLIENT_SECRET", "test-client-secret")


def test_load_tokens_file_not_found(tmp_path: Path) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    assert manager._load_tokens() == {}  # noqa: SLF001


def test_load_tokens_empty_when_missing(tmp_path: Path) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    assert manager._load_tokens() == {}  # noqa: SLF001


def test_save_and_load_tokens_atomic(tmp_path: Path) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    data = {"access_token": "a", "refresh_token": "r"}
    manager._save_tokens(data)  # noqa: SLF001
    loaded = manager._load_tokens()  # noqa: SLF001
    assert loaded["access_token"] == "a"
    assert loaded["refresh_token"] == "r"


def test_is_expired_true_false(tmp_path: Path) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    now: builtins.float = time.time()
    tokens_not_expired = {"obtained_at": now, "expires_in": 3600}
    tokens_expired = {"obtained_at": now - 7200, "expires_in": 3600}
    assert manager._is_expired(tokens_not_expired) is False  # noqa: SLF001
    assert manager._is_expired(tokens_expired) is True  # noqa: SLF001


def test_get_authorization_code_via_browser_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda _url: None)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "http://localhost?code=abc123")
    manager = TokenManager(Path("tokens.db"))
    assert manager._get_authorization_code_via_browser() == "abc123"  # noqa: SLF001


def test_get_authorization_code_via_browser_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("webbrowser.open", lambda _url: None)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "http://localhost?error=denied")
    manager = TokenManager(Path("tokens.db"))
    with pytest.raises(RuntimeError):
        manager._get_authorization_code_via_browser()  # noqa: SLF001


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fake aiohttp client/session/response
    class FakeResp:
        def __init__(self, payload) -> None:
            self._payload = payload

        async def json(self) -> Any:
            return self._payload

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSession:
        def __init__(self, payload) -> None:
            self._payload = payload

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, *_args, **_kwargs) -> FakeResp:
            return FakeResp(self._payload)

    # failure case: no access_token
    monkeypatch.setattr(tm.aiohttp, "ClientSession", lambda **_kwargs: FakeSession({}))
    manager = TokenManager(Path("tokens.db"))
    with pytest.raises(RuntimeError):
        await manager._exchange_code_for_tokens("code")  # noqa: SLF001

    # success case
    payload = {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
    monkeypatch.setattr(tm.aiohttp, "ClientSession", lambda **_kwargs: FakeSession(payload))
    res = await manager._exchange_code_for_tokens("code")  # noqa: SLF001
    assert res["access_token"] == "a"
    assert "obtained_at" in res


@pytest.mark.asyncio
async def test_refresh_access_token_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResp:
        def __init__(self, payload) -> None:
            self._payload = payload

        async def json(self) -> Any:
            return self._payload

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakeSession:
        def __init__(self, payload) -> None:
            self._payload = payload

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, *_args, **_kwargs) -> FakeResp:
            return FakeResp(self._payload)

    manager = TokenManager(Path("tokens.db"))
    # failure
    monkeypatch.setattr(tm.aiohttp, "ClientSession", lambda **_kwargs: FakeSession({}))
    with pytest.raises(RuntimeError):
        await manager._refresh_access_token("refresh")  # noqa: SLF001

    # success
    payload = {"access_token": "a", "refresh_token": "r", "expires_in": 3600}
    monkeypatch.setattr(tm.aiohttp, "ClientSession", lambda **_kwargs: FakeSession(payload))
    res = await manager._refresh_access_token("refresh")  # noqa: SLF001
    assert res["access_token"] == "a"
    assert "obtained_at" in res


@pytest.mark.asyncio
async def test_get_id_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fake twitchio Client
    class FakeUser:
        def __init__(self, name, uid) -> None:
            self.name = name
            self.id = uid

    class FakeClient:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def login(self) -> None:
            return None

        async def fetch_users(self, logins) -> builtins.list[FakeUser]:
            # return for mixed-case check
            _ = logins
            return [FakeUser("OwnerUser", "owner-id"), FakeUser("BotUser", "bot-id")]

    monkeypatch.setattr(tm, "Client", lambda *_args, **_kwargs: FakeClient())
    manager = TokenManager(Path("tokens.db"))
    ids: UserIDs = await manager._get_id_by_name("OwnerUser", "BotUser")  # noqa: SLF001
    assert isinstance(ids, UserIDs)
    assert ids.owner_id == "owner-id"
    assert ids.bot_id == "bot-id"

    # not found case should raise
    async def async_fetch_users(_self, logins) -> builtins.list[FakeUser]:
        _ = logins
        return [FakeUser("OnlyOne", "only-id")]

    monkeypatch.setattr(FakeClient, "fetch_users", async_fetch_users)
    with pytest.raises(RuntimeError):
        await manager._get_id_by_name("OwnerUser", "BotUser")  # noqa: SLF001


@pytest.mark.asyncio
async def test_start_authorization_flow_full(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)

    # stub interactive and network parts
    monkeypatch.setattr(manager, "_get_authorization_code_via_browser", lambda: "code")
    monkeypatch.setattr(
        manager,
        "_exchange_code_for_tokens",
        lambda _code: pytest.mark.asyncio(lambda: {"access_token": "a", "refresh_token": "r", "expires_in": 3600})(),
    )

    async def async_exchange(_code):
        return {"access_token": "a", "refresh_token": "r", "expires_in": 3600}

    async def async_refresh(_refresh):
        return {"access_token": "a2", "refresh_token": "r2", "expires_in": 3600}

    async def async_get_id(_owner, _bot) -> UserIDs:
        return UserIDs(owner_id="owner-id", bot_id="bot-id")

    monkeypatch.setattr(manager, "_exchange_code_for_tokens", async_exchange)
    monkeypatch.setattr(manager, "_refresh_access_token", async_refresh)
    monkeypatch.setattr(manager, "_get_id_by_name", async_get_id)

    token: TwitchBotToken = await manager.start_authorization_flow("owner", "bot")
    assert isinstance(token, TwitchBotToken)
    assert token.access_token == "a"
    assert token.refresh_token == "r"
    saved = manager._load_tokens()  # noqa: SLF001
    assert saved["access_token"] == "a"
