"""Command component for Twitch bot.

Provides chat commands for bot control including playback management,
version display, translation engine switching, and usage statistics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast

from twitchio.ext import commands

from core.components.base import ComponentBase
from core.trans.manager import TransManager
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from twitchio import Chatter

    from models.translation_models import CharacterQuota


__all__: list[str] = ["BotCommandManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class BotCommandManager(ComponentBase):
    """Command class to manage bot commands.

    Provides chat commands for bot control including playback management,
    version display, translation engine switching, and usage statistics.
    """

    depends: ClassVar[list[str]] = ["ChatEventsManager", "TranslationServiceComponent", "TTSServiceComponent"]

    async def component_load(self) -> None:
        """Load the component. No setup required for this component."""
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component. No teardown required for this component."""
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    @staticmethod
    def _get_removable_component_classes() -> list[type[ComponentBase]]:
        return [
            comp_cfg.component for comp_cfg in ComponentBase.class_map.values() if comp_cfg.is_removable
        ]

    @classmethod
    def _find_removable_component_class(cls, name: str) -> type[ComponentBase] | None:
        for comp_cls in cls._get_removable_component_classes():
            if comp_cls.__name__.lower() == name.lower():
                return comp_cls
        return None

    @commands.command()
    async def skip(self, context: commands.Context) -> None:
        """Skip the current playback.

        Args:
            context (commands.Context): The object passed when processing the command
        """
        logger.debug("Command 'skip' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        if self.shared is None:
            return

        if self.tts_manager.playback_manager.is_playing:
            await self.tts_manager.playback_manager.cancel_playback()
            logger.debug("Current playback cancelled.")
            await context.send("Current playback cancelled.")

    @commands.command()
    async def ver(self, context: commands.Context) -> None:
        """Display the version

        Args:
            context (commands.Context): The object passed when processing the command
        """
        logger.debug("Command 'ver' invoked by user: %s", context.author.name)
        await context.send(f"Current version is '{self.config.GENERAL.SCRIPT_NAME} ver.{self.config.GENERAL.VERSION}'")

    @commands.command()
    async def attach(self, context: commands.Context, *args) -> None:
        """Attach a removable component to the bot.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Component name to attach.
        """
        logger.debug("Command 'attach' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        removable_classes: list[type[ComponentBase]] = self._get_removable_component_classes()
        available_components: list[str] = [comp_cls.__name__ for comp_cls in removable_classes]

        def usage_message() -> str:
            return f"Usage: !attach <component name>. Available: {', '.join(available_components)}"

        if not args or len(args) == 0:  # Redundant due to linter countermeasures
            await context.send(usage_message())
            return

        if len(args) > 1:
            await context.send(usage_message())
            return

        component_name: str = str(args[0])
        component_class: type[ComponentBase] | None = self._find_removable_component_class(component_name)

        if component_class is None:
            logger.warning("Attach failed: unknown component '%s'", component_name)
            await context.send(usage_message())
            return

        if any(comp.__class__ is component_class for comp in self.bot.attached_components):
            await context.send(f"Component '{component_class.__name__}' is already attached.")
            return

        component: ComponentBase = component_class(self.bot)
        await self.bot.attach_component(component)
        await context.send(f"Component '{component_class.__name__}' attached.")

    @commands.command()
    async def detach(self, context: commands.Context, *args) -> None:
        """Detach a removable component from the bot.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Component name to detach.
        """
        logger.debug("Command 'detach' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        removable_classes: list[type[ComponentBase]] = self._get_removable_component_classes()
        available_components: list[str] = [comp_cls.__name__ for comp_cls in removable_classes]

        def usage_message() -> str:
            return f"Usage: !detach <component name>. Available: {', '.join(available_components)}"

        if not args or len(args) == 0:  # Redundant due to linter countermeasures
            await context.send(usage_message())
            return

        if len(args) > 1:
            await context.send(usage_message())
            return

        component_name: str = str(args[0])
        component_class: type[ComponentBase] | None = self._find_removable_component_class(component_name)

        if component_class is None:
            logger.warning("Detach failed: unknown component '%s'", component_name)
            await context.send(usage_message())
            return

        component_instance: ComponentBase | None = None
        for comp in self.bot.attached_components:
            if comp.__class__ is component_class:
                component_instance = comp
                break

        if component_instance is None:
            await context.send(f"Component '{component_class.__name__}' is not attached.")
            return

        await self.bot.detach_component(component_instance)
        await context.send(f"Component '{component_class.__name__}' detached.")

    # The command to switch translation engines will only take effect when processing of
    # the next 'event_message' begins.
    # Switching immediately could cause inconsistencies if multiple translation requests
    # are made at the same time.
    @commands.command(name="te")
    async def change_translation_engine(self, context: commands.Context, *args) -> None:
        """Display or change the current translation engine.

        If no arguments are provided, the current engine is displayed.
        If 'google' or 'deepl' is specified as an argument, the translation engine is switched accordingly.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Optional translation engine name to switch to.
        """
        logger.debug("Command 'te' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        available_translation_engines: list[str] = TransManager.get_trans_engine_names().copy()

        def usage_message() -> str:
            return f"Usage: !te [{'|'.join(available_translation_engines)}]"

        if not args or len(args) == 0:  # Redundant due to linter countermeasures
            await context.send(f"The current translation engine is '{available_translation_engines[0]}'.")
            return

        if len(args) > 1:
            await context.send(usage_message())
            return

        selected_engine: str = args[0].lower()
        if selected_engine in available_translation_engines:
            logger.debug("Changing translation engine to '%s'", selected_engine)
            try:
                available_translation_engines.remove(selected_engine)
                available_translation_engines.insert(0, selected_engine)
            except ValueError:
                await context.send(usage_message())
            except IndexError as err:
                logger.error("Error changing translation engine: %s", err)
            else:
                TransManager.set_trans_engine_names(available_translation_engines)
                await context.send(f"Translation engine switched to '{selected_engine}'.")
        else:
            await context.send(usage_message())

    @commands.command()
    async def trans_usage(self, context: commands.Context) -> None:
        """Display the character usage of the translation engine.

        This value is currently meaningful only when using DeepL.

        Args:
            context (commands.Context): The context object provided during command execution.
        """
        logger.debug("Command 'trans_usage' invoked by: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        quota: CharacterQuota = await self.trans_manager.get_usage()

        msg: str
        if quota.is_quota_valid:
            if quota.limit > 0:
                percentage: float = (quota.count / quota.limit) * 100
                msg = f"Character usage: {quota.count:,}/{quota.limit:,} ({percentage:.2f}%)"
            else:
                msg = f"Character usage: {quota.count:,}/{quota.limit:,} (---%)"
        else:
            msg = "The current translation engine is unable to use information about character usage."
        logger.debug("Usage message: %s", msg)
        await context.send(msg)

    @commands.command()
    async def help(self, context: commands.Context, *args) -> None:
        """Display available commands or help for a specific command.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Optional command name to get help for.
        """
        logger.debug("Command 'help' invoked by user: %s", context.author.name)

        # Get all registered commands from the bot
        bot_commands: dict[str, commands.Command] = context.bot.commands

        # Helper function to display all available commands
        def show_command_list() -> str:
            command_names: list[str] = sorted(bot_commands.keys())
            return f"Available commands: {', '.join([f'!{cmd}' for cmd in command_names])}"

        # No arguments - show all commands
        if not args or len(args) == 0:  # Redundant due to linter countermeasures
            await context.send(show_command_list())
            return

        # Multiple arguments - show all commands (invalid usage)
        if len(args) > 1:
            await context.send(show_command_list())
            return

        # Single argument - show help for that specific command
        command_name: str = args[0].lower()
        if command_name in bot_commands:
            cmd_obj: commands.Command = bot_commands[command_name]
            help_text: str | None = cmd_obj.callback.__doc__
            if help_text:
                # Extract first line of docstring as brief description
                first_line: str = help_text.strip().split("\n")[0]
                await context.send(f"!{command_name}: {first_line}")
            else:
                await context.send(f"!{command_name}: No description available.")
        else:
            # Command not found - show all commands
            await context.send(show_command_list())
