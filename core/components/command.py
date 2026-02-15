"""Command component for Twitch bot.

This component provides basic commands for the bot, such as displaying version information
and attaching/detaching components.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from twitchio.ext import commands

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["BotCommandManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class BotCommandManager(ComponentBase):
    """Command class to manage bot commands.

    This component provides basic commands for the bot, such as displaying version information
    and attaching/detaching components.
    """

    depends: ClassVar[list[str]] = ["ChatEventsManager"]

    async def component_load(self) -> None:
        """Load the component. No setup required for this component."""
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component. No teardown required for this component."""
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    @staticmethod
    def _get_removable_component_classes() -> list[type[ComponentBase]]:
        """Return removable component classes registered in the component registry.

        Returns:
           list[type[ComponentBase]]: List of removable component classes.
        """
        return [comp_cfg.component for comp_cfg in ComponentBase.component_registry.values() if comp_cfg.is_removable]

    @classmethod
    def _find_removable_component_class(cls, name: str) -> type[ComponentBase] | None:
        for comp_cls in cls._get_removable_component_classes():
            if comp_cls.__name__.lower() == name.lower():
                return comp_cls
        return None

    @commands.command()
    async def ver(self, context: commands.Context) -> None:
        """Display the version

        Args:
            context (commands.Context): The object passed when processing the command
        """
        logger.debug("Command 'ver' invoked by user: %s", context.author.name)
        await context.send(f"Current version is '{self.config.GENERAL.SCRIPT_NAME} ver.{self.config.GENERAL.VERSION}'")

    @commands.command()
    @commands.is_broadcaster()
    async def attach(self, context: commands.Context, *args) -> None:
        """Attach a removable component to the bot.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Component name to attach.
        """
        logger.debug("Command 'attach' invoked by user: %s", context.author.name)

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
    @commands.is_broadcaster()
    async def detach(self, context: commands.Context, *args) -> None:
        """Detach a removable component from the bot.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Component name to detach.
        """
        logger.debug("Command 'detach' invoked by user: %s", context.author.name)

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

    @commands.command()
    async def help(self, context: commands.Context, *args) -> None:
        """Display available commands or help for a specific command.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Optional command name to get help for.
        """
        logger.debug("Command 'help' invoked by user: %s", context.author.name)

        bot_commands: dict[str, commands.Command] = context.bot.commands

        def show_command_list() -> str:
            command_names: list[str] = sorted(bot_commands.keys())
            return f"Available commands: {', '.join([f'!{cmd}' for cmd in command_names])}"

        if not args or len(args) == 0:  # Redundant due to linter countermeasures
            await context.send(show_command_list())
            return

        if len(args) > 1:
            await context.send(show_command_list())
            return

        command_name: str = args[0].lower()
        if command_name in bot_commands:
            cmd_obj: commands.Command = bot_commands[command_name]
            help_text: str | None = cmd_obj.callback.__doc__
            if help_text:
                first_line: str = help_text.strip().split("\n")[0]
                await context.send(f"!{command_name}: {first_line}")
            else:
                await context.send(f"!{command_name}: No description available.")
        else:
            await context.send(show_command_list())
