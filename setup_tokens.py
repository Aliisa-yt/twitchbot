"""Setup tokens for Twitchbot.

This script is used to obtain and store Twitch OAuth tokens in the tokens.db database.
Run this script before first use or when tokens need to be reset.

This is a console-only application; no log file is created.
All output is sent to stdout/stderr for immediate user feedback.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Final, NoReturn

from config.loader import Config, ConfigLoader, ConfigLoaderError
from core.token_manager import TokenManager, TwitchBotToken
from utils.file_utils import FileUtils

CFG_FILE: Final[str] = "twitchbot.ini"
TOKEN_DB_FILE: Final[str] = "tokens.db"


def check_python_version() -> None:
    """Check if Python version is 3.13 or later.

    Raises:
        RuntimeError: If Python version is below 3.13.
    """
    if sys.version_info < (3, 13):
        msg = "Python 3.13 or later is required"
        raise RuntimeError(msg)


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print(f"\n{message}\n", file=sys.stderr)
        self.print_help(sys.stderr)
        raise SystemExit(2)


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for owner and bot names.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = _ArgumentParser(
        description="Setup Twitch OAuth tokens for twitchbot",
        epilog="Example: python setup_tokens.py --owner myname --bot mybotname",
    )
    parser.add_argument("--owner", dest="owner", metavar="OWNER_NAME", help="Override channel owner name")
    parser.add_argument("--bot", dest="bot", metavar="BOT_NAME", help="Override bot user name")
    return parser.parse_args()


def load_config(args: argparse.Namespace) -> Config:
    """Load configuration file and apply CLI overrides.

    Args:
        args: Command-line arguments.

    Returns:
        Config: Configuration object.

    Raises:
        ConfigLoaderError: If configuration file cannot be loaded.
    """
    script_name: str = Path(sys.argv[0]).stem
    return ConfigLoader(config_filename=CFG_FILE, script_name=script_name, **vars(args)).config


def resolve_usernames(config: Config) -> tuple[str, str]:
    """Resolve owner and bot usernames from configuration.

    Raises:
        ValueError: If required usernames are missing.
    """
    owner_name: str = config.TWITCH.OWNER_NAME
    bot_name: str = config.BOT.BOT_NAME

    if not owner_name or not bot_name:
        msg = "Owner name and bot name must be provided via CLI or config."
        raise ValueError(msg)

    return owner_name, bot_name


async def main() -> None:
    """Main entry point for token setup.

    Performs the following steps:
    1. Check Python version
    2. Parse command-line arguments
    3. Load configuration
    4. Display target users
    5. Check environment variables
    6. Execute OAuth authorization flow
    7. Save tokens to database
    """
    check_python_version()
    print("=" * 50)
    print("Twitch Token Setup Utility")
    print("=" * 50)

    # Parse arguments and load configuration
    args: argparse.Namespace = parse_arguments()
    try:
        config: Config = load_config(args)
    except ConfigLoaderError as err:
        print("\nError: Failed to load configuration file.", file=sys.stderr)
        print(f"Details: {err}", file=sys.stderr)
        return

    # Resolve usernames
    owner_name, bot_name = resolve_usernames(config)

    # Display target users
    print(f"\nChannel Owner: {owner_name}")
    print(f"Bot User: {bot_name}")
    print("-" * 50)

    # Check environment variables
    if not os.getenv("TWITCH_API_CLIENT_ID"):
        print("\nError: TWITCH_API_CLIENT_ID environment variable is not set.", file=sys.stderr)
        print("Please set it before running this script.", file=sys.stderr)
        return

    if not os.getenv("TWITCH_API_CLIENT_SECRET"):
        print("\nError: TWITCH_API_CLIENT_SECRET environment variable is not set.", file=sys.stderr)
        print("Please set it before running this script.", file=sys.stderr)
        return

    # Initialize token manager and start authorization flow
    token_db_path: Path = FileUtils.resolve_path(TOKEN_DB_FILE)
    try:
        print("\nStarting OAuth authorization flow...")
        token_manager: TokenManager = TokenManager(token_db_path)
        token_data: TwitchBotToken = await token_manager.start_authorization_flow(owner_name, bot_name)

        print("\n" + "=" * 50)
        print("✓ Token setup completed successfully!")
        print("=" * 50)
        print(f"Owner ID: {token_data.owner_id}")
        print(f"Bot ID: {token_data.bot_id}")
        print(f"Tokens saved to: {token_db_path}")
        print("\nYou can now run twitchbot.py")

    except RuntimeError as err:
        print(f"\nError: {err}", file=sys.stderr)
        return
    except (OSError, ValueError, TypeError) as err:
        print("\nUnexpected error occurred during token setup.", file=sys.stderr)
        print(f"Details: {err}", file=sys.stderr)
        return


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        print("\n\nSetup cancelled by user.", file=sys.stderr)
    except (OSError, RuntimeError, ValueError) as err:
        print(f"\nFatal error: {err}", file=sys.stderr)
    finally:
        # Pause before exit to allow user to read the output
        with suppress(KeyboardInterrupt, EOFError):
            input("\nPress Enter to exit...")
