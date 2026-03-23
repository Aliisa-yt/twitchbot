from __future__ import annotations

import asyncio
import os
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Self

import aiohttp
from aiohttp import web
from twitchio import Client, Scopes

from core.token_storage import TokenStorage
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from twitchio.user import User


__all__: list[str] = ["TokenManager", "TwitchBotToken"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# OAuth2 redirect URI for Twitch API
# This should match the redirect URI set in your Twitch application settings.
# It is used to receive the authorization code after user login.
REDIRECT_URI: Final[str] = "http://localhost"
# REDIRECT_URI: Final[str] = "http://localhost:4343/oauth/callback"

# List of access scopes required for the bot
# These scopes define the permissions the bot will request from the user.
# Adjust the scopes based on your bot's functionality and requirements.
ACCESS_SCOPES: Scopes = Scopes(
    chat_read=True,
    chat_edit=True,
    user_read_chat=True,
    user_write_chat=True,
    user_bot=True,
    user_manage_chat_color=True,
    channel_bot=True,
)


@dataclass(frozen=True)
class TwitchBotToken:
    """Data class to hold Twitch bot token information.

    This class is used to store the OAuth2 tokens and other related information for the Twitch bot.

    Attributes:
        client_id (str): The Twitch API client ID.
        client_secret (str): The Twitch API client secret.
        bot_id (str): The unique identifier for the bot user.
        owner_id (str): The unique identifier for the bot owner.
        access_token (str): The access token for the bot user.
        refresh_token (str): The refresh token for the bot user.
    """

    client_id: str = ""
    client_secret: str = ""
    bot_id: str = ""
    owner_id: str = ""
    access_token: str = ""
    refresh_token: str = ""


@dataclass(frozen=True)
class UserIDs:
    """Data class to hold user IDs.

    This is used to store the owner ID and bot ID of the Twitch bot.

    Attributes:
        owner_id (str): The unique identifier for the bot owner.
        bot_id (str): The unique identifier for the bot user.
    """

    owner_id: str = ""
    bot_id: str = ""


class TokenManager:
    """Manager for Twitch API tokens.

    Handles the OAuth2 authorization code flow, token storage, and token refreshing
    for the Twitch API. Exposes synchronous helpers and asynchronous methods to
    interact with Twitch (for example fetching user IDs or exchanging/refreshing
    tokens).

    Convenience context manager methods are provided so this object can be used
    with either ``with`` or ``async with``. These are no-op helpers and do not
    automatically manage or close network clients; resource management must be
    handled by the caller when required.

    Attributes:
        storage (TokenStorage): The token storage backend using SQLite3.
        client_id (str): The Twitch API client ID.
        client_secret (str): The Twitch API client secret.
        bot_id (str): The unique identifier for the bot user.
        owner_id (str): The unique identifier for the bot owner.
        user_access_token (str): The access token for the bot user.
        refresh_token (str): The refresh token for the bot user.
    """

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the TokenManager with the path to the database file.

        This database file is used to store access and refresh tokens for the Twitch API.

        Args:
            db_path (str | Path): The path to the SQLite database file where tokens will be stored.
        Raises:
            RuntimeError: If the database path is empty or if required environment variables are not set.
        """

        def _require_env_var(name: str) -> str:
            """Check if an environment variable is set and return its value."""
            value: str | None = os.getenv(name)
            if not value:
                msg: str = f"The '{name}' environment variable has not been set."
                raise RuntimeError(msg)
            return value

        logger.debug("Initializing %s", self.__class__.__name__)

        # Initialize the token storage backend
        self.storage: TokenStorage = TokenStorage(db_path)
        logger.debug("Token storage initialized")

        # Load client ID and secret from environment variables.
        # These are required for OAuth2 authentication with the Twitch API.
        # Example:
        #   export TWITCH_API_CLIENT_ID="your_client_id"
        #   export TWITCH_API_CLIENT_SECRET="your_client_secret"
        self.client_id: str = _require_env_var("TWITCH_API_CLIENT_ID")
        self.client_secret: str = _require_env_var("TWITCH_API_CLIENT_SECRET")

        # Initialize IDs and tokens; populated during the OAuth authorization flow.
        self.bot_id: str = ""
        self.owner_id: str = ""
        self.user_access_token: str = ""
        self.refresh_token: str = ""

    def __enter__(self) -> Self:
        """Enter sync context; no-op convenience helper."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit sync context; no resources are managed by TokenManager itself."""
        _ = exc_type, exc_val, exc_tb

    async def __aenter__(self) -> Self:
        """Enter async context; no-op convenience helper."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context; no resources are managed by TokenManager itself."""
        _ = exc_type, exc_val, exc_tb

    # -----------------------------------
    # Token storage and management
    # -----------------------------------
    def load_tokens(self) -> dict[str, Any]:
        """Load tokens from the storage."""
        with self.storage:
            return self.storage.load_tokens()

    def save_tokens(self, data: dict[str, Any]) -> None:
        """Save tokens to the storage."""
        with self.storage:
            self.storage.save_tokens(data)

    # -----------------------------------
    # OAuth Authorization Code Flow
    # -----------------------------------
    def _get_authorization_code_via_browser(self) -> str:
        """Open a web browser and prompt the user to paste the redirect URL manually.

        Fallback method used when the local callback server is unavailable
        (e.g., port conflict or timeout).  Opens the Twitch authorization URL in the
        default browser and waits for the user to paste back the full redirect URL.

        Returns:
            str: The authorization code extracted from the pasted redirect URL.

        Raises:
            RuntimeError: If input is unavailable or the redirect URL contains no code.
        """
        # Build OAuth authorization parameters
        params: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(ACCESS_SCOPES.selected),
        }
        url: str = f"https://id.twitch.tv/oauth2/authorize?{urllib.parse.urlencode(params)}"

        # Attempt to open the authorization URL in default browser
        print("Opening browser to get authorization code...")
        if not webbrowser.open(url):
            logger.warning("Failed to open web browser automatically.")
            print(f"Please open the following URL in your browser:\n{url}")

        # Prompt user to paste the redirect URL containing authorization code
        try:
            redirected: str = input("Paste the full redirect URL here: ")
        except EOFError as err:
            # Raised when input is unavailable (e.g., non-interactive terminal, forced termination)
            msg = "forced termination or input unavailable; cannot obtain authorization code."
            raise RuntimeError(msg) from err

        # Extract authorization code from redirect URL query parameters
        query: str = urllib.parse.urlparse(redirected).query
        code: str | None = dict(urllib.parse.parse_qsl(query)).get("code")
        if not code:
            msg = "Authorization code not found in redirect URL."
            raise RuntimeError(msg)
        return code

    async def _get_authorization_code_via_local_server(self, timeout: float = 60.0) -> str:  # noqa: ASYNC109
        """Start a temporary local HTTP server to receive the OAuth callback automatically.

        Opens the Twitch authorization URL in the default browser, waits for the redirect
        containing ``?code=...``, then shuts down the server.  Accepts exactly one request.

        Args:
            timeout (float): Maximum seconds to wait before raising ``TimeoutError``.

        Returns:
            str: The authorization code extracted from the redirect callback.

        Raises:
            TimeoutError: If no callback is received within *timeout* seconds.
            RuntimeError: If the callback contains no ``code`` (e.g. user denied access).
            OSError: If the server cannot bind to the port derived from ``REDIRECT_URI``.
        """
        parsed: urllib.parse.ParseResult = urllib.parse.urlparse(REDIRECT_URI)
        host: str = parsed.hostname or "localhost"
        port: int = parsed.port or (443 if parsed.scheme == "https" else 80)
        path: str = parsed.path or "/"

        code_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

        async def _handle(request: web.Request) -> web.Response:
            query: dict[str, str] = dict(request.rel_url.query)
            code: str | None = query.get("code")
            if not code_future.done():
                if code:
                    code_future.set_result(code)
                    return web.Response(text="Authorization successful. You can close this tab.")
                error: str = query.get("error", "unknown error")
                msg: str = f"Authorization denied: {error}"
                code_future.set_exception(RuntimeError(msg))
            return web.Response(text="Authorization failed. Please check the bot logs.", status=400)

        app: web.Application = web.Application()
        app.router.add_get(path, _handle)
        runner: web.AppRunner = web.AppRunner(app)
        await runner.setup()
        try:
            site: web.TCPSite = web.TCPSite(runner, host, port)
            await site.start()
            logger.debug("Local OAuth callback server started on %s:%d%s", host, port, path)
            params: dict[str, str] = {
                "client_id": self.client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(ACCESS_SCOPES.selected),
            }
            url: str = f"https://id.twitch.tv/oauth2/authorize?{urllib.parse.urlencode(params)}"
            print("Opening browser to get authorization code...")
            if not webbrowser.open(url):
                logger.warning("Failed to open web browser automatically.")
                print(f"Please open the following URL in your browser:\n{url}")
            async with asyncio.timeout(timeout):
                return await code_future
        finally:
            await runner.cleanup()
            logger.debug("Local OAuth callback server stopped.")

    async def _exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        """Exchange the authorization code for access and refresh tokens."""
        url: str = "https://id.twitch.tv/oauth2/token"
        params: dict[str, str] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }

        async with aiohttp.ClientSession(raise_for_status=True) as session, session.post(url, data=params) as resp:
            # OAuth token endpoints expect form data.
            data: dict[str, Any] = await resp.json()
        if "access_token" not in data:
            msg: str = "Token exchange failed: API did not return access_token."
            raise RuntimeError(msg)
        data["obtained_at"] = time.time()  # It seems that this data isn't being used.
        return data

    async def _refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using the stored refresh token.

        Args:
            refresh_token (str): The refresh token to exchange for a new access token.

        Returns:
            dict[str, Any]: The new token data containing at minimum access_token and refresh_token.

        Raises:
            RuntimeError: If the API does not return an access_token.
            aiohttp.ClientResponseError: If the HTTP request fails (e.g. the refresh token is invalid).
        """
        url: str = "https://id.twitch.tv/oauth2/token"
        params: dict[str, str] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        async with aiohttp.ClientSession(raise_for_status=True) as session, session.post(url, data=params) as resp:
            data: dict[str, Any] = await resp.json()
        if "access_token" not in data:
            msg: str = "Token refresh failed: API did not return access_token."
            raise RuntimeError(msg)
        data["obtained_at"] = time.time()
        return data

    async def _validate_access_token_user_id(self, access_token: str) -> str:
        """Validate an access token and return the associated Twitch user ID.

        Args:
            access_token (str): The user access token to validate.

        Returns:
            str: The Twitch user ID associated with the token.

        Raises:
            RuntimeError: If validation fails or the token is not a user access token.
        """
        url: str = "https://id.twitch.tv/oauth2/validate"
        headers: dict[str, str] = {"Authorization": f"OAuth {access_token}"}
        async with aiohttp.ClientSession() as session, session.get(url, headers=headers) as resp:
            if resp.status != 200:
                msg: str = f"Token validation failed with status {resp.status}."
                raise RuntimeError(msg)
            data: dict[str, Any] = await resp.json()
        user_id: str = data.get("user_id", "")
        if not user_id:
            msg = "Token validation returned no user_id. The token may be an app token, not a user access token."
            raise RuntimeError(msg)
        return user_id

    # -----------------------------------
    # Twitch API helpers
    # -----------------------------------
    async def _get_id_by_name(self, owner_name: str, bot_name: str) -> UserIDs:
        """Get user IDs for the owner and bot by their Twitch usernames.

        Args:
            owner_name (str): The Twitch username of the bot owner.
            bot_name (str): The Twitch username of the bot account.

        Returns:
            UserIDs: A dataclass containing the owner ID and bot ID.

        Raises:
            RuntimeError: If either user is not found.
        """
        owner_id: str = ""
        bot_id: str = ""
        owner_name = owner_name.strip().lower()
        bot_name = bot_name.strip().lower()
        if not owner_name or not bot_name:
            msg: str = "Owner name and bot name must be provided."
            raise RuntimeError(msg)
        logger.debug("Fetching IDs for owner '%s' and bot '%s'", owner_name, bot_name)
        async with Client(client_id=self.client_id, client_secret=self.client_secret) as client:
            await client.login()
            users: list[User] = await client.fetch_users(logins=[owner_name, bot_name])
            # The order of fetch_users results is not guaranteed.
            for user in users:
                name: str | None = getattr(user, "name", None)
                if name is None:
                    msg = f"User missing 'name' field: {user}"
                    raise RuntimeError(msg)
                uid: str | None = getattr(user, "id", None)
                if uid is None:
                    msg = f"User '{name}' has no ID."
                    raise RuntimeError(msg)
                logger.debug("User '%s' has ID '%s'", name, uid)
                uname: str = name.lower()
                if uname == owner_name:
                    owner_id = uid
                elif uname == bot_name:
                    bot_id = uid

        # If either owner_id or bot_id is not found, raise an error.
        if not owner_id:
            msg = f"Owner '{owner_name}' not found."
            raise RuntimeError(msg)
        if not bot_id:
            msg = f"Bot '{bot_name}' not found."
            raise RuntimeError(msg)

        logger.debug("Owner ID: %s, Bot ID: %s", owner_id, bot_id)
        # Return the user IDs as a UserIDs instance
        return UserIDs(owner_id=owner_id, bot_id=bot_id)

    async def _run_oauth_for_bot(
        self,
        bot_name: str,
        expected_bot_id: str,
    ) -> dict[str, Any]:
        """Run the OAuth authorization flow and validate the resulting token.

        Prompts the user to log in with the bot account, exchanges the
        authorization code for tokens, then verifies the token user ID matches
        *expected_bot_id* before persisting the tokens.

        Args:
            bot_name (str): Display name used in user-facing messages.
            expected_bot_id (str): The Twitch user ID the token must belong to.

        Returns:
            dict[str, Any]: The token data returned from the token exchange.

        Raises:
            RuntimeError: If the obtained token does not belong to *expected_bot_id*.
        """
        logger.info("No valid bot token found. Starting OAuth authorization flow.")
        print(f"\nIMPORTANT: Please log in to Twitch with the BOT account ({bot_name}),")
        print("           NOT the channel owner account!")
        try:
            code: str = await self._get_authorization_code_via_local_server()
        except (TimeoutError, OSError) as exc:
            logger.warning("Local server callback unavailable (%s); falling back to manual input.", exc)
            code = self._get_authorization_code_via_browser()
        tokens: dict[str, Any] = await self._exchange_code_for_tokens(code)

        # Validate that the newly obtained token actually belongs to the bot account.
        new_access_token: str = tokens.get("access_token", "")
        if new_access_token:
            token_user_id: str = await self._validate_access_token_user_id(new_access_token)
            if token_user_id != expected_bot_id:
                msg: str = (
                    f"Authorization error: expected bot account '{bot_name}' (ID: {expected_bot_id}), "
                    f"but the authorised account has ID '{token_user_id}'. "
                    f"Please run setup_tokens again and log in with the bot account."
                )
                raise RuntimeError(msg)

        self.save_tokens(tokens)
        return tokens

    async def start_authorization_flow(self, owner_name: str, bot_name: str) -> TwitchBotToken:
        """Start the Twitch API authorization flow to obtain access and refresh tokens.

        This method retrieves bot and owner IDs first (using an App Token), then checks
        for a valid cached bot token. If the cached token belongs to a different user
        (e.g. the channel owner), it is discarded and a new OAuth flow is started so
        the bot account can re-authorise. The resulting token is always validated
        against the expected bot ID before being persisted.

        Args:
            owner_name (str): The Twitch username of the bot owner.
            bot_name (str): The Twitch username of the bot account.

        Notes:
            This method is interactive: it may open a browser and prompt for a redirect URL.
            It raises RuntimeError on missing env vars, token exchange failures, or if users are not found.
        """
        logger.info("Starting Twitch API authorization flow.")

        # Retrieve bot/owner IDs first so we can validate the token owner below.
        logger.info("Retrieving bot and owner IDs.")
        user_id: UserIDs = await self._get_id_by_name(owner_name, bot_name)
        self.owner_id = user_id.owner_id
        self.bot_id = user_id.bot_id

        tokens: dict[str, Any] = self.load_tokens()
        if tokens:
            logger.info("Using cached tokens.")
            cached_access_token: str = tokens.get("access_token", "")
            cached_refresh_token: str = tokens.get("refresh_token", "")
            if cached_access_token:
                try:
                    token_user_id: str = await self._validate_access_token_user_id(cached_access_token)
                    if token_user_id != self.bot_id:
                        logger.warning(
                            "Cached token belongs to user '%s', but expected bot '%s' (%s). "
                            "Discarding cached token and re-authorizing.",
                            token_user_id,
                            bot_name,
                            self.bot_id,
                        )
                        tokens = {}
                except RuntimeError as exc:
                    logger.warning("Cached token validation failed (%s). Attempting token refresh.", exc)
                    tokens = {}
                    if cached_refresh_token:
                        try:
                            refreshed_tokens: dict[str, Any] = await self._refresh_access_token(cached_refresh_token)
                            refreshed_user_id: str = await self._validate_access_token_user_id(
                                refreshed_tokens["access_token"]
                            )
                            if refreshed_user_id == self.bot_id:
                                self.save_tokens(refreshed_tokens)
                                tokens = refreshed_tokens
                                logger.info("Token refreshed successfully.")
                            else:
                                logger.warning(
                                    "Refreshed token belongs to user '%s', not bot '%s'. Re-authorizing.",
                                    refreshed_user_id,
                                    self.bot_id,
                                )
                        except (RuntimeError, aiohttp.ClientResponseError) as refresh_exc:
                            logger.warning("Token refresh failed (%s). Re-authorizing.", refresh_exc)

        if not tokens:
            tokens = await self._run_oauth_for_bot(bot_name, self.bot_id)

        # Set the instance variables with the tokens
        access_token: str | None = tokens.get("access_token")
        refresh_token: str | None = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            msg: str = "Access token or refresh token is missing. Please reauthorize."
            raise RuntimeError(msg)
        self.user_access_token = access_token
        self.refresh_token = refresh_token

        logger.info("Authorization flow completed successfully.")

        return TwitchBotToken(
            client_id=self.client_id,
            client_secret=self.client_secret,
            bot_id=self.bot_id,
            owner_id=self.owner_id,
            access_token=self.user_access_token,
            refresh_token=self.refresh_token,
        )
