from __future__ import annotations

import json
import os
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Self

import aiohttp
from twitchio import Client, Scopes

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

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
        cache_file (Path): The path to the cache file where tokens will be stored.
        client_id (str): The Twitch API client ID.
        client_secret (str): The Twitch API client secret.
        bot_id (str): The unique identifier for the bot user.
        owner_id (str): The unique identifier for the bot owner.
        user_access_token (str): The access token for the bot user.
        refresh_token (str): The refresh token for the bot user.
    """

    def __init__(self, cache_file: str | Path) -> None:
        """Initialize the TokenManager with the path to the cache file.

        This cache file is used to store access and refresh tokens for the Twitch API.

        Args:
            cache_file (str | Path): The path to the cache file where tokens will be stored.
        Raises:
            RuntimeError: If the cache file path is empty or if required environment variables are not set.
        """

        def _require_env_var(name: str) -> str:
            """Check if an environment variable is set and return its value."""
            value: str | None = os.getenv(name)
            if not value:
                msg: str = f"The '{name}' environment variable has not been set."
                raise RuntimeError(msg)
            return value

        logger.debug("Initializing %s", self.__class__.__name__)

        cache_file = Path(cache_file)
        if str(cache_file).strip() == "":
            msg: str = "The cache file path is empty."
            raise RuntimeError(msg)
        self.cache_file: Path = cache_file
        logger.debug("Cache file set to: %s", self.cache_file)

        # Load client ID and secret from environment variables
        # These should be set in your environment before running the bot.
        # If not set, a RuntimeError will be raised.
        # Ensure these variables are set in your environment or pass them directly.
        #
        # Example: export TWITCH_API_CLIENT_ID="your_client_id"
        #          export TWITCH_API_CLIENT_SECRET="your_client_secret"
        #
        # Note: These environment variables are required for OAuth2 authentication with Twitch API.
        #       Make sure to set them in your environment or pass them directly.
        #       If you are running this code in a production environment, consider using a secure method
        #       to store and retrieve these sensitive values.
        #       For example, you can use environment variables, a configuration file, or a secret management service.
        #       Ensure that these values are kept secure and not hard-coded in your source code.
        #       The client ID and secret are used to authenticate your application with the Twitch API.
        #       They are essential for making API requests and accessing user data.
        self.client_id: str = _require_env_var("TWITCH_API_CLIENT_ID")
        self.client_secret: str = _require_env_var("TWITCH_API_CLIENT_SECRET")

        # Initialize instance variables for storing bot and owner IDs, access token, and refresh token.
        # These will be set during the OAuth authorization flow.
        # The bot ID is the unique identifier for the bot user,
        # and the owner ID is the unique identifier for the bot owner.
        # The access token is used to authenticate API requests,
        # and the refresh token is used to obtain a new access token when the current one expires.
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
    def _load_tokens(self) -> dict[str, Any]:
        """Load tokens from the cache file."""
        try:
            with self.cache_file.open(encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError:
            logger.warning("Token cache '%s' is corrupted; ignoring.", self.cache_file)
            return {}

    def _save_tokens(self, data: dict[str, Any]) -> None:
        """Save tokens to the cache file."""
        # Ensure parent exists and write atomically to avoid corruption
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp: Path = self.cache_file.with_suffix(self.cache_file.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.cache_file)

    def _is_expired(self, tokens: dict[str, Any]) -> bool:
        """Check if the access token is expired."""
        obtained = float(tokens.get("obtained_at", 0))
        expires = float(tokens.get("expires_in", 0))
        expiry: float = obtained + expires
        return time.time() >= (expiry - 60.0)  # refresh 1 minute before expiry

    # -----------------------------------
    # OAuth Authorization Code Flow
    # -----------------------------------
    def _get_authorization_code_via_browser(self) -> str:
        """Open a web browser to get the authorization code."""
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
        redirected: str = input("Paste the full redirect URL here: ")
        query: str = urllib.parse.urlparse(redirected).query
        code: str | None = dict(urllib.parse.parse_qsl(query)).get("code")
        if not code:
            msg: str = "Authorization code not found in redirect URL."
            raise RuntimeError(msg)
        return code

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

        async with aiohttp.ClientSession(raise_for_status=True) as session:
            # OAuth token endpoints expect form data.
            async with session.post(url, data=params) as resp:
                data = await resp.json()
            if "access_token" not in data:
                msg: str = f"Token exchange failed: {data}"
                raise RuntimeError(msg)
            data["obtained_at"] = time.time()
            return data

    async def _refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token using the refresh token."""
        url: str = "https://id.twitch.tv/oauth2/token"
        params: dict[str, str] = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        async with aiohttp.ClientSession(raise_for_status=True) as session:
            # OAuth token endpoints expect form data.
            async with session.post(url, data=params) as resp:
                data = await resp.json()
            if "access_token" not in data:
                msg: str = f"Token refresh failed: {data}"
                raise RuntimeError(msg)
            data["obtained_at"] = time.time()
            return data

    # -----------------------------------
    # Twitch API helpers
    # -----------------------------------
    async def _get_id_by_name(self, owner_name: str, bot_name: str) -> UserIDs:
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
            # If the order of the return values of fetch_users were guaranteed, processing could be simplified.
            # However, it is not explicitly stated that the order is guaranteed.
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
            msg: str = f"Owner '{owner_name}' not found."
            raise RuntimeError(msg)
        if not bot_id:
            msg: str = f"Bot '{bot_name}' not found."
            raise RuntimeError(msg)

        logger.debug("Owner ID: %s, Bot ID: %s", owner_id, bot_id)
        # Return the user IDs as a UserIDs instance
        return UserIDs(owner_id=owner_id, bot_id=bot_id)

    async def start_authorization_flow(self, owner_name: str, bot_name: str) -> TwitchBotToken:
        """Start the Twitch API authorization flow to obtain access and refresh tokens.

        This method will check for existing tokens, refresh them if necessary, and retrieve the bot and owner IDs.

        Args:
            owner_name (str): The Twitch username of the bot owner.
            bot_name (str): The Twitch username of the bot account.

        Notes:
            This method is interactive: it may open a browser and prompt for a redirect URL.
            It raises RuntimeError on missing env vars, token exchange failures, or if users are not found.
        """
        logger.info("Starting Twitch API authorization flow.")
        tokens: dict[str, Any] = self._load_tokens()
        if not tokens:
            logger.info("No tokens found, starting authorization flow.")
            code: str = self._get_authorization_code_via_browser()
            tokens = await self._exchange_code_for_tokens(code)
            self._save_tokens(tokens)
        elif self._is_expired(tokens):
            logger.info("Access token expired, refreshing tokens.")
            tokens = await self._refresh_access_token(tokens["refresh_token"])
            self._save_tokens(tokens)
        else:
            logger.info("Using cached tokens.")

        # Set the instance variables with the tokens
        self.user_access_token = tokens["access_token"]
        self.refresh_token = tokens["refresh_token"]

        logger.info("Retrieving bot and owner IDs.")
        user_id: UserIDs = await self._get_id_by_name(owner_name, bot_name)
        self.owner_id = user_id.owner_id
        self.bot_id = user_id.bot_id
        logger.info("Authorization flow completed successfully.")

        return TwitchBotToken(
            client_id=self.client_id,
            client_secret=self.client_secret,
            bot_id=self.bot_id,
            owner_id=self.owner_id,
            access_token=self.user_access_token,
            refresh_token=self.refresh_token,
        )
