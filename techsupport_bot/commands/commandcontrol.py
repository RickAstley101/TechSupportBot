"""
Commands which allow control over what commands are allowed to be run
The cog in the file is named:
    CommandControl

This file contains 2 commands:
    .command disable
    .command enable
"""

from base import auxiliary, cogs, extension
from discord.ext import commands


async def setup(bot):
    """Registers the CommandControl Cog"""
    await bot.add_cog(CommandControl(bot=bot))


class CommandControl(cogs.BaseCog):
    """
    The class that holds the command control commands
    """

    ADMIN_ONLY = True

    @commands.group(
        name="command",
        brief="Executes a commands bot command",
        description="Executes a commands bot command",
    )
    async def command_group(self, ctx):
        """The bare .command command. This does nothing but generate the help message

        Args:
            ctx (commands.Context): The context in which the command was run in
        """

        # Executed if there are no/invalid args supplied
        await extension.extension_help(self, ctx, self.__module__[9:])

    @auxiliary.with_typing
    @command_group.command(
        name="enable", description="Enables a command by name", usage="[command-name]"
    )
    async def enable_command(self, ctx, *, command_name: str):
        """Enables a command by name.

        This is a command and should be accessed via Discord.

        parameters:
            ctx (discord.ext.Context): the context object for the message
            command_name (str): the name of the command
        """
        command_ = ctx.bot.get_command(command_name)
        if not command_:
            await auxiliary.send_deny_embed(
                message=f"No such command: `{command_name}`", channel=ctx.channel
            )
            return

        if command_.enabled:
            await auxiliary.send_deny_embed(
                message=f"Command `{command_name}` is already enabled!",
                channel=ctx.channel,
            )
            return

        command_.enabled = True
        await auxiliary.send_confirm_embed(
            message=f"Successfully enabled command: `{command_name}`",
            channel=ctx.channel,
        )

    @auxiliary.with_typing
    @command_group.command(
        name="disable", description="Disables a command by name", usage="[command-name]"
    )
    async def disable_command(self, ctx, *, command_name: str):
        """Disables a command by name.

        This is a command and should be accessed via Discord.

        parameters:
            ctx (discord.ext.Context): the context object for the message
            command_name (str): the name of the command
        """
        command_ = ctx.bot.get_command(command_name)
        if not command_:
            await auxiliary.send_deny_embed(
                message=f"No such command: `{command_name}`", channel=ctx.channel
            )
            return

        if not command_.enabled:
            await auxiliary.send_deny_embed(
                message=f"Command: `{command_name}` is already disabled!",
                channel=ctx.channel,
            )
            return

        command_.enabled = False
        await auxiliary.send_confirm_embed(
            message=f"Successfully disabled command: `{command_name}`",
            channel=ctx.channel,
        )
