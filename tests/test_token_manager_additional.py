import asyncio
import inspect
import json
import time
from pathlib import Path
from typing import Any

import pytest

from core.token_manager import TokenManager, TwitchBotToken, UserIDs


def test_init_missing_env_vars_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Remove env vars set by autouse fixture and ensure constructor raises
    monkeypatch.delenv("TWITCH_API_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_API_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        TokenManager(Path("cache.json"))


def test_context_managers_are_noop(tmp_path: Path) -> None:
    cache: Path = tmp_path / "tokens.json"
    manager = TokenManager(cache)
    # sync context manager returns self
    with manager as m:
        assert m is manager

    # async context manager is a no-op (ensure it's awaitable and returns self)
    async def _check_async() -> None:
        async with manager as m2:
            assert m2 is manager

    asyncio.run(_check_async())  # small helper to run the coroutine synchronously in tests


def test_is_expired_boundary() -> None:
    manager = TokenManager(Path("does-not-matter.json"))
    now: float = time.time()
    # Set expires_in so that (obtained + expires - 60) is just in the future -> not expired
    tokens_not_expired = {"obtained_at": now, "expires_in": 120}
    assert manager._is_expired(tokens_not_expired) is False  # noqa: SLF001
    # Now make it so refresh threshold is already passed -> expired
    # obtained = now - (expires_in - 59) => obtained + expires - 60 = now -1 -> expired
    tokens_expired = {"obtained_at": now - (120 - 59), "expires_in": 120}
    assert manager._is_expired(tokens_expired) is True  # noqa: SLF001


@pytest.mark.asyncio
async def test_start_authorization_flow_uses_cached_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "tokens.json"
    # Write a valid, non-expired token into cache
    tokens = {
        "access_token": "cached_a",
        "refresh_token": "cached_r",
        "expires_in": 3600,
        "obtained_at": time.time(),
    }
    cache.write_text(json.dumps(tokens))
    manager = TokenManager(cache)

    # If exchange_code_for_tokens or _get_authorization_code_via_browser is called, the test should fail
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
    # Ensure cache was not overwritten in this path
    saved = json.loads(cache.read_text())
    assert saved["access_token"] == "cached_a"


@pytest.mark.asyncio
async def test_start_authorization_flow_refreshes_expired_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "tokens.json"
    # Write an expired token into cache
    tokens = {
        "access_token": "old_a",
        "refresh_token": "old_r",
        "expires_in": 3600,
        "obtained_at": time.time() - 7200,
    }
    cache.write_text(json.dumps(tokens))
    manager = TokenManager(cache)

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
    saved = json.loads(cache.read_text())
    assert saved["access_token"] == "new_a"


def test_signature_names_for_dunder_exit_methods() -> None:
    # Small assertion to show signature contains exception params (these can be renamed to _ to silence linters)
    sig_sync: inspect.Signature = inspect.signature(TokenManager.__exit__)
    sig_async: inspect.Signature = inspect.signature(TokenManager.__aexit__)
    # Ensure they accept three parameters besides self (typical for context managers)
    assert len(sig_sync.parameters) >= 4
    assert len(sig_async.parameters) >= 4
