"""Tests for core.token_manager.TokenManager.

These tests focus on the internal logic of TokenManager, especially around token caching and refreshing.
They use monkeypatching to isolate the code under test and avoid real network calls or user interaction.

Normal-case test content:
- Test loading tokens when the file does not exist or is empty.
- Test saving and loading tokens to ensure data integrity.
- Test the token expiration logic with various timestamps.
- Test the interactive authorization flow, including handling of user input and token exchange.

Abnormal-case test content:
- Test that missing environment variables cause initialization to fail.
- Test that the interactive flow raises when the user does not provide an authorization code.
- Test that the interactive flow raises when the user inputs an error redirect.
- Test that the flow raises when cached token data is missing required fields.
"""

from __future__ import annotations

import asyncio
import builtins
import inspect
import time
import types
from pathlib import Path
from typing import Any, Self

import aiohttp.web
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


def test_init_missing_env_vars_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWITCH_API_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_API_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        TokenManager(Path("tokens.db"))


def test_context_managers_are_noop(tmp_path: Path) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    with manager as m:
        assert m is manager

    async def _check_async() -> None:
        async with manager as m2:
            assert m2 is manager

    asyncio.run(_check_async())


def test_is_expired_boundary(tmp_path: Path) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    now: float = time.time()
    tokens_not_expired = {"obtained_at": now, "expires_in": 120}
    assert manager._is_expired(tokens_not_expired) is False  # noqa: SLF001
    tokens_expired = {"obtained_at": now - (120 - 59), "expires_in": 120}
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

    # stub local server to succeed directly, avoiding real network
    async def fake_local_server(_timeout: float = 60.0) -> str:
        return "code"

    monkeypatch.setattr(manager, "_get_authorization_code_via_local_server", fake_local_server)
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


@pytest.mark.asyncio
async def test_start_authorization_flow_uses_cached_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    tokens = {
        "access_token": "cached_a",
        "refresh_token": "cached_r",
        "expires_in": 3600,
        "obtained_at": time.time(),
    }
    manager._save_tokens(tokens)  # noqa: SLF001

    def fail_exchange(*_args, **_kwargs):
        msg = "Exchange should not be called when cached token is valid"
        raise AssertionError(msg)

    monkeypatch.setattr(manager, "_exchange_code_for_tokens", fail_exchange)
    monkeypatch.setattr(
        manager,
        "_get_authorization_code_via_browser",
        lambda: (_ for _ in ()).throw(AssertionError("Interactive flow should not run")),
    )

    async def fake_get_id(_owner, _bot) -> UserIDs:
        return UserIDs(owner_id="owner-id", bot_id="bot-id")

    monkeypatch.setattr(manager, "_get_id_by_name", fake_get_id)

    token: TwitchBotToken = await manager.start_authorization_flow("owner", "bot")
    assert token.access_token == "cached_a"
    assert token.refresh_token == "cached_r"
    saved = manager._load_tokens()  # noqa: SLF001
    assert saved["access_token"] == "cached_a"


@pytest.mark.asyncio
async def test_start_authorization_flow_refreshes_expired_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    tokens = {
        "access_token": "old_a",
        "refresh_token": "old_r",
        "expires_in": 3600,
        "obtained_at": time.time() - 7200,
    }
    manager._save_tokens(tokens)  # noqa: SLF001

    async def fake_refresh(refresh_token: str) -> dict[str, Any]:
        assert refresh_token == "old_r"
        return {"access_token": "new_a", "refresh_token": "new_r", "expires_in": 3600, "obtained_at": time.time()}

    async def fake_get_id(_owner, _bot) -> UserIDs:
        return UserIDs(owner_id="owner-id", bot_id="bot-id")

    monkeypatch.setattr(manager, "_refresh_access_token", fake_refresh)
    monkeypatch.setattr(manager, "_get_id_by_name", fake_get_id)

    token: TwitchBotToken = await manager.start_authorization_flow("owner", "bot")
    assert token.access_token == "new_a"
    assert token.refresh_token == "new_r"
    saved = manager._load_tokens()  # noqa: SLF001
    assert saved["access_token"] == "new_a"


@pytest.mark.asyncio
async def test_start_authorization_flow_raises_when_user_does_not_input_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)

    # Simulate local server being unavailable so the fallback path is exercised
    async def fail_local_server(_timeout: float = 60.0) -> str:
        msg = "port unavailable"
        raise OSError(msg)

    monkeypatch.setattr(manager, "_get_authorization_code_via_local_server", fail_local_server)
    monkeypatch.setattr("webbrowser.open", lambda _url: True)

    def raise_eof(_prompt: str = "") -> str:
        msg = "input unavailable"
        raise EOFError(msg)

    monkeypatch.setattr(builtins, "input", raise_eof)

    with pytest.raises(RuntimeError, match="cannot obtain authorization code"):
        await manager.start_authorization_flow("owner", "bot")


@pytest.mark.asyncio
async def test_start_authorization_flow_raises_when_user_inputs_error_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)

    # Simulate local server being unavailable so the fallback path is exercised
    async def fail_local_server(_timeout: float = 60.0) -> str:
        msg = "port unavailable"
        raise OSError(msg)

    monkeypatch.setattr(manager, "_get_authorization_code_via_local_server", fail_local_server)
    monkeypatch.setattr("webbrowser.open", lambda _url: True)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "http://localhost?error=access_denied")

    with pytest.raises(RuntimeError, match="Authorization code not found"):
        await manager.start_authorization_flow("owner", "bot")


@pytest.mark.asyncio
async def test_start_authorization_flow_raises_when_cached_access_token_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    tokens = {
        "refresh_token": "cached_r",
        "expires_in": 3600,
        "obtained_at": time.time(),
    }
    manager._save_tokens(tokens)  # noqa: SLF001

    async def fail_get_id(_owner: str, _bot: str) -> UserIDs:
        msg = "_get_id_by_name should not be called when token data is invalid"
        raise AssertionError(msg)

    monkeypatch.setattr(manager, "_get_id_by_name", fail_get_id)

    with pytest.raises(RuntimeError, match="Access token or refresh token is missing"):
        await manager.start_authorization_flow("owner", "bot")


@pytest.mark.asyncio
async def test_start_authorization_flow_raises_when_cached_refresh_token_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)
    tokens = {
        "access_token": "cached_a",
        "expires_in": 3600,
        "obtained_at": time.time(),
    }
    manager._save_tokens(tokens)  # noqa: SLF001

    async def fail_get_id(_owner: str, _bot: str) -> UserIDs:
        msg = "_get_id_by_name should not be called when token data is invalid"
        raise AssertionError(msg)

    monkeypatch.setattr(manager, "_get_id_by_name", fail_get_id)

    with pytest.raises(RuntimeError, match="Access token or refresh token is missing"):
        await manager.start_authorization_flow("owner", "bot")


def test_signature_names_for_dunder_exit_methods() -> None:
    sig_sync: inspect.Signature = inspect.signature(TokenManager.__exit__)
    sig_async: inspect.Signature = inspect.signature(TokenManager.__aexit__)
    assert len(sig_sync.parameters) >= 4
    assert len(sig_async.parameters) >= 4


# ---------------------------------------------------------------------------
# _get_authorization_code_via_local_server tests
# ---------------------------------------------------------------------------


def _make_aiohttp_web_mocks(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace aiohttp.web server classes with no-op mocks; returns captured routes."""
    captured: dict = {}

    class _MockApp:
        def __init__(self) -> None:
            self.router = self

        def add_get(self, path: str, handler) -> None:
            captured[path] = handler

    class _MockRunner:
        def __init__(self, _app) -> None:
            pass

        async def setup(self) -> None:
            pass

        async def cleanup(self) -> None:
            pass

    class _MockSite:
        def __init__(self, *_a, **_kw) -> None:
            pass

        async def start(self) -> None:
            pass

    class _MockResponse:
        def __init__(self, text: str = "", status: int = 200) -> None:
            pass

    monkeypatch.setattr(aiohttp.web, "Application", _MockApp)
    monkeypatch.setattr(aiohttp.web, "AppRunner", _MockRunner)
    monkeypatch.setattr(aiohttp.web, "TCPSite", _MockSite)
    monkeypatch.setattr(aiohttp.web, "Response", _MockResponse)
    return captured


@pytest.mark.asyncio
async def test_get_authorization_code_via_local_server_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured = _make_aiohttp_web_mocks(monkeypatch)
    monkeypatch.setattr(tm, "REDIRECT_URI", "http://localhost:48888/")
    monkeypatch.setattr("webbrowser.open", lambda _url: True)

    manager = TokenManager(tmp_path / "tokens.db")

    async def _fire_callback() -> None:
        await asyncio.sleep(0)
        handler = captured.get("/")
        assert handler is not None
        await handler(types.SimpleNamespace(rel_url=types.SimpleNamespace(query={"code": "localcode42"})))

    fire_task = asyncio.create_task(_fire_callback(), name="fire_callback")
    code = await manager._get_authorization_code_via_local_server(timeout=5.0)  # noqa: SLF001
    await fire_task
    assert code == "localcode42"


@pytest.mark.asyncio
async def test_get_authorization_code_via_local_server_code_missing_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured = _make_aiohttp_web_mocks(monkeypatch)
    monkeypatch.setattr(tm, "REDIRECT_URI", "http://localhost:48889/")
    monkeypatch.setattr("webbrowser.open", lambda _url: True)

    manager = TokenManager(tmp_path / "tokens.db")

    async def _fire_error_callback() -> None:
        await asyncio.sleep(0)
        handler = captured.get("/")
        assert handler is not None
        await handler(types.SimpleNamespace(rel_url=types.SimpleNamespace(query={"error": "access_denied"})))

    fire_task = asyncio.create_task(_fire_error_callback(), name="fire_error_callback")
    with pytest.raises(RuntimeError, match="Authorization denied"):
        await manager._get_authorization_code_via_local_server(timeout=5.0)  # noqa: SLF001
    await fire_task


@pytest.mark.asyncio
async def test_get_authorization_code_via_local_server_timeout_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _make_aiohttp_web_mocks(monkeypatch)
    monkeypatch.setattr(tm, "REDIRECT_URI", "http://localhost:48890/")
    monkeypatch.setattr("webbrowser.open", lambda _url: True)

    manager = TokenManager(tmp_path / "tokens.db")
    with pytest.raises(TimeoutError):
        await manager._get_authorization_code_via_local_server(timeout=0.05)  # noqa: SLF001


@pytest.mark.asyncio
async def test_start_authorization_flow_local_server_timeout_falls_back_to_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path: Path = tmp_path / "tokens.db"
    manager = TokenManager(db_path)

    async def fake_local_server_timeout(_timeout: float = 60.0) -> str:
        msg = "test timeout"
        raise TimeoutError(msg)

    monkeypatch.setattr(manager, "_get_authorization_code_via_local_server", fake_local_server_timeout)
    monkeypatch.setattr(manager, "_get_authorization_code_via_browser", lambda: "browser_code")

    async def async_exchange(code: str) -> dict[str, Any]:
        assert code == "browser_code"
        return {"access_token": "a", "refresh_token": "r", "expires_in": 3600}

    async def async_get_id(_owner: str, _bot: str) -> UserIDs:
        return UserIDs(owner_id="oid", bot_id="bid")

    monkeypatch.setattr(manager, "_exchange_code_for_tokens", async_exchange)
    monkeypatch.setattr(manager, "_get_id_by_name", async_get_id)

    token: TwitchBotToken = await manager.start_authorization_flow("owner", "bot")
    assert token.access_token == "a"
