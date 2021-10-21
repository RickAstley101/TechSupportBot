import asyncio

import base
import discord
import util
from discord.ext import commands


def setup(bot):
    config = bot.PluginConfig()
    config.add(
        key="channel",
        datatype="int",
        title="Server Gate Channel ID",
        description="The ID of the channel the gate is in",
        default=None,
    )
    config.add(
        key="roles",
        datatype="list",
        title="Roles to add",
        description="The list of roles to add after user is verified",
        default=[],
    )
    config.add(
        key="intro_message",
        datatype="str",
        title="Server Gate intro message",
        description="The message that's sent when running the intro message command",
        default="Welcome to our server! 👋 Please read the rules then type agree below to verify yourself",
    )
    config.add(
        key="welcome_message",
        datatype="str",
        title="Server Gate welcome message",
        description="The message to send to the user after they are verified",
        default="You are now verified! Welcome to the server!",
    )
    config.add(
        key="delete_wait",
        datatype="int",
        title="Welcome message delete time",
        description="The amount of time to wait (in seconds) before deleting the welcome message",
        default=60,
    )
    config.add(
        key="verify_text",
        datatype="str",
        title="Verification text",
        description="The case-insensitive text the user should type to verify themselves",
        default="agree",
    )

    bot.process_plugin_setup(cogs=[ServerGate], config=config)


class ServerGate(base.MatchCog):
    async def match(self, config, ctx, _):
        if not config.plugins.gate.channel.value:
            return False

        return ctx.channel.id == int(config.plugins.gate.channel.value)

    async def response(self, config, ctx, content, _):
        prefix = await self.bot.get_prefix(ctx.message)

        is_admin = await self.bot.is_bot_admin(ctx)

        if content.startswith(prefix) and is_admin:
            return

        await ctx.message.delete()

        if content.lower() == config.plugins.gate.verify_text.value:
            roles = await self.get_roles(config, ctx)
            if not roles:
                await self.bot.guild_log(
                    ctx.guild,
                    "logging_channel",
                    "warning",
                    f"No roles to give user in gate plugin channel - ignoring message",
                    send=True,
                )
                return

            await ctx.author.add_roles(*roles)

            welcome_message = config.plugins.gate.welcome_message.value
            delete_wait = config.plugins.gate.delete_wait.value

            await util.send_with_mention(
                ctx,
                f"{welcome_message} (this message will delete in {delete_wait} seconds)",
                delete_after=float(delete_wait),
            )

    async def get_roles(self, config, ctx):
        roles = []
        for role_name in config.plugins.gate.roles.value:
            role = discord.utils.get(ctx.guild.roles, name=role_name)

            if role in ctx.author.roles:
                continue

            if role:
                roles.append(role)

        return roles

    @commands.group(
        name="gate",
        brief="Executes a gate command",
        description="Executes a gate command",
    )
    async def gate_command(self, ctx):
        pass

    @commands.has_permissions(manage_messages=True)
    @commands.guild_only()
    @gate_command.command(
        name="intro",
        brief="Generates a gate intro message",
        description="Generates the configured gate intro message",
        usage="[query]",
    )
    async def intro_message(self, ctx):
        config = await self.bot.get_context_config(ctx)

        if ctx.channel.id != int(config.plugins.gate.channel.value):
            await util.send_with_mention(
                ctx, "That command is only usable in the gate channel"
            )
            return

        await ctx.channel.send(config.plugins.gate.intro_message.value)
