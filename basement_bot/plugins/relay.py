import datetime
import json
import logging
import re
import uuid

from discord import Embed
from discord.ext import commands
from munch import Munch

from cogs import LoopPlugin, MatchPlugin, MqPlugin
from utils.helpers import *
from utils.logger import get_logger

log = get_logger("Relay Plugin")


def setup(bot):
    bot.add_cog(DiscordRelay(bot))
    bot.add_cog(IRCReceiver(bot))


class DiscordRelay(LoopPlugin, MatchPlugin, MqPlugin):

    PLUGIN_NAME = __name__
    WAIT_KEY = "publish_seconds"

    async def preconfig(self):
        self.channels = list(self.config.channel_map.values())
        self.bot.plugin_api.plugins["relay"]["memory"]["send_buffer"] = []

    def match(self, ctx, content):
        if ctx.channel.id in self.channels:
            if not content.startswith(self.bot.command_prefix):
                if (
                    content.startswith(self.bot.config.plugins.factoids.prefix)
                    and self.bot.plugin_api.plugins.get("factoids") is None
                ):
                    ctx.content = content
                    ctx.factoid = True
                return True
        return False

    async def response(self, ctx, content):
        type_ = "factoid" if getattr(ctx, "factoid", None) else "message"

        # subs in actual mentions if possible
        ctx.content = re.sub(r"<@?!?(\d+)>", self._get_nick_from_id_match, content)
        self.bot.plugin_api.plugins["relay"]["memory"]["send_buffer"].append(
            self.serialize(type_, ctx)
        )

    # main looper
    async def execute(self):
        # grab from buffer
        bodies = [
            body
            for idx, body in enumerate(
                self.bot.plugin_api.plugins["relay"]["memory"]["send_buffer"]
            )
            if idx + 1 <= self.config.send_limit
        ]
        if bodies:
            self.publish(bodies)
            if self.mq_error_state and self.config.notice_errors:
                # just send to first channel on the map
                channel = self.bot.get_channel(
                    self.config.channel_map.get(list(self.config.channel_map.keys())[0])
                )
                if channel:
                    await channel.send(
                        "**ERROR**: Unable to connect to relay event queue"
                    )
            else:
                # remove from buffer
                self.bot.plugin_api.plugins["relay"]["memory"][
                    "send_buffer"
                ] = self.bot.plugin_api.plugins["relay"]["memory"]["send_buffer"][
                    len(bodies) :
                ]

    @staticmethod
    def serialize(type_, ctx):
        data = Munch()

        # event data
        data.event = Munch()
        data.event.id = str(uuid.uuid4())
        data.event.type = type_
        data.event.time = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )
        data.event.content = getattr(ctx, "content", None)
        data.event.command = getattr(ctx, "irc_command", None)
        data.event.attachments = [
            attachment.url for attachment in ctx.message.attachments
        ]

        # author data
        data.author = Munch()
        data.author.username = ctx.author.name
        data.author.id = ctx.author.id
        data.author.nickname = ctx.author.display_name
        data.author.discriminator = ctx.author.discriminator
        data.author.is_bot = ctx.author.bot
        data.author.top_role = str(ctx.author.top_role)
        # permissions data
        data.author.permissions = Munch()
        discord_permissions = ctx.author.permissions_in(ctx.channel)
        data.author.permissions.kick = discord_permissions.kick_members
        data.author.permissions.ban = discord_permissions.ban_members
        data.author.permissions.unban = discord_permissions.ban_members
        data.author.permissions.admin = discord_permissions.administrator

        # server data
        data.server = Munch()
        data.server.name = ctx.author.guild.name
        data.server.id = ctx.author.guild.id

        # channel data
        data.channel = Munch()
        data.channel.name = ctx.channel.name
        data.channel.id = ctx.channel.id

        # non-lossy
        as_json = data.toJSON()
        log.debug(f"Serialized data: {as_json}")
        return as_json

    def _get_nick_from_id_match(self, match):
        id = int(match.group(1))
        user = self.bot.get_user(id)
        return f"@{user.name}" if user else "@user"

    @commands.command(
        name="irc",
        brief="Commands for IRC relay",
        descrption="Run a command (eg. kick/ban) on the relayed IRC",
        usage="<command> <arg>",
    )
    async def irc_command(self, ctx, *args):
        if not self.config.commands_allowed:
            await priv_response(ctx, "Relay cross-chat commands are disabled on my end")
            return

        if ctx.channel.id not in self.channels:
            log.warning(f"IRC command issued outside of allowed channels")
            await priv_response(
                ctx, "That command can only be used from the IRC relay channels"
            )
            return

        permissions = ctx.author.permissions_in(ctx.channel)

        if len(args) == 0:
            await priv_response(ctx, "No IRC command provided. Try `.help irc`")
            return

        command = args[0]
        if len(args) == 1:
            await priv_response(ctx, f"No target provided for IRC command {command}")
            return

        target = " ".join(args[1:])

        ctx.irc_command = command
        ctx.content = target

        await priv_response(
            ctx, f"Sending **{command}** command with target `{target}` to IRC bot...",
        )
        self.bot.plugin_api.plugins["relay"]["memory"]["send_buffer"].append(
            self.serialize("command", ctx)
        )


class IRCReceiver(LoopPlugin, MqPlugin):

    PLUGIN_NAME = __name__
    WAIT_KEY = "consume_seconds"
    IRC_LOGO = "\U0001F4E8"  # emoji

    async def preconfig(self):
        self.channels = list(self.config.channel_map.values())
        self.error_count = 0

    # main looper
    async def execute(self):
        responses = self.consume()
        if self.mq_error_state and self.config.notice_errors and self.error_count < 5:
            channel = self.bot.get_channel(
                self.config.channel_map.get(list(self.config.channel_map.keys())[0])
            )
            await channel.send("**ERROR**: Unable to connect to relay event queue")
            self.error_count += 1
            return

        for response in responses:
            await self.handle_event(response)

    async def handle_event(self, response):
        data = self.deserialize(response)
        if not data:
            log.warning("Unable to deserialize data! Aborting!")
            return

        # handle message event
        if data.event.type in [
            "message",
            "join",
            "part",
            "quit",
            "kick",
            "action",
            "other",
            "factoid",
        ]:
            if data.event.target == "factoid_request":
                log.debug("Ignoring factoid request event")
                return

            message = self.process_message(data)
            if message:
                message = re.sub(
                    r"\B\{0}\w+".format(self.config.irc_tag_prefix),
                    self._get_mention_from_irc_tag,
                    message,
                )

                channel = self._get_channel(data)
                if not channel:
                    log.warning("Unable to find channel to send command alert")
                    return
                await channel.send(message)

            else:
                log.warning(f"Unable to format message for event: {response}")

        # handle command event
        elif data.event.type == "command":
            await self.process_command(data)

        elif data.event.type == "response":
            await self.process_response(data)

        else:
            log.warning(f"Unable to handle event: {response}")

    async def process_command(self, data):
        if not self.config.commands_allowed:
            log.debug(
                f"Blocking incoming {data.event.command} request due to disabled config"
            )
            return

        if data.event.command in ["kick", "ban", "unban"]:
            await self._process_user_command(data)
        else:
            log.warning(f"Received unroutable command: {data.event.command}")

    async def process_response(self, data):
        response = data.event.content
        if not response:
            log.warning("Received empty response")
            return

        if response.type == "whois":
            await self._process_whois_response(data)
            requester = self.bot.get_user(response.request.author)

    async def _process_whois_response(self, data):
        response = data.event.content
        author_id = response.request.author
        requester = self.bot.get_user(author_id)
        if not requester:
            log.warning(
                f"Unable to find user with ID {author_id} associated with response"
            )
            return
        dm_channel = await requester.create_dm()

        embed = Embed(title=f"WHOIS Response for {response.payload.nick}")
        embed.add_field(
            name="User", value=response.payload.user or "Not found", inline=False
        )
        embed.add_field(
            name="Host", value=response.payload.host or "Not found", inline=False
        )
        embed.add_field(
            name="Realname",
            value=response.payload.realname or "Not found",
            inline=False,
        )
        embed.add_field(
            name="Server", value=response.payload.server or "Not found", inline=False
        )

        await dm_channel.send(embed=embed)

    @staticmethod
    def _data_has_op(data):
        if "o" not in data.author.permissions:
            return False
        return True

    def _get_channel(self, data):
        for channel_id in self.channels:
            if channel_id == self.config.channel_map.get(data.channel.name):
                return self.bot.get_channel(channel_id)

    async def _process_user_command(self, data):
        if not self._data_has_op(data):
            log.warning(
                f"Blocking incoming {data.event.command} request due to permissions"
            )
            return

        channel = self._get_channel(data)
        if not channel:
            log.warning("Unable to find channel to send command alert")
            return

        await channel.send(
            f"Executing IRC **{data.event.command}** command from `{data.author.mask}` on target `{data.event.content}`"
        )

        target_guild = get_guild_from_channel_id(self.bot, channel.id)
        if not target_guild:
            await channel.send(f"> Critical error! Aborting command")
            log.warning(
                f"Unable to find guild associated with relay channel (this is unusual)"
            )
            return

        target_user = target_guild.get_member_named(data.event.content)
        if not target_user:
            await channel.send(
                f"Unable to locate target `{data.event.content}`! Aborting command"
            )
            return

        # very likely this will raise an exception :(
        try:
            if data.event.command == "kick":
                await target_guild.kick(target_user)
            elif data.event.command == "ban":
                await target_guild.ban(target_user, self.config.discord_ban_days)
            elif data.event.command == "unban":
                await target_guild.unban(target_user)
        except Exception as e:
            log.warning(f"Unable to send command: {e}")

    def deserialize(self, body):
        try:
            deserialized = Munch.fromJSON(body)
        except Exception as e:
            log.warning(f"Unable to Munch-deserialize incoming data: {e}")
            log.warning(f"Full body: {body}")
            return

        time = deserialized.event.time
        if not time:
            log.warning(f"Unable to retrieve time object from incoming data")
            return
        if self._time_stale(time):
            log.warning(
                f"Incoming data failed stale check ({self.config.stale_seconds} seconds)"
            )
            return

        log.debug(f"Deserialized data: {body})")
        return deserialized

    def _time_stale(self, time):
        time = datetime.datetime.strptime(time, "%Y-%m-%d %H:%M:%S.%f")
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        if (now - time).total_seconds() > self.config.stale_seconds:
            return True
        return False

    def _get_mention_from_irc_tag(self, match):
        tagged = match.group(0)
        guild = get_guild_from_channel_id(self.bot, self.config.channel)
        if not guild:
            return tagged
        name = tagged.replace(self.config.irc_tag_prefix, "")
        member = guild.get_member_named(name)
        if not member:
            return tagged
        return member.mention

    def process_message(self, data):
        if data.event.type == "message":
            return self._format_chat_message(data)
        else:
            return self._format_event_message(data)

    def _format_chat_message(self, data):
        return f"{self.IRC_LOGO} `{self._get_permissions_label(data.author.permissions)}{data.author.nickname}` {data.event.content}"

    def _format_event_message(self, data):
        permissions_label = self._get_permissions_label(data.author.permissions)
        if data.event.type == "join":
            return f"{self.IRC_LOGO} `{permissions_label}{data.author.mask}` has joined {data.channel.name}!"
        elif data.event.type == "part":
            return f"{self.IRC_LOGO} `{permissions_label}{data.author.mask}` left {data.channel.name}!"
        elif data.event.type == "quit":
            return f"{self.IRC_LOGO} `{permissions_label}{data.author.mask}` quit ({data.event.content})"
        elif data.event.type == "kick":
            return f"{self.IRC_LOGO} `{permissions_label}{data.author.mask}` kicked `{data.event.target}` from {data.channel.name}! (reason: *{data.event.content}*)."
        elif data.event.type == "action":
            # this isnt working well right now
            return f"{self.IRC_LOGO} `{permissions_label}{data.author.nickname}` {data.event.content}"
        elif data.event.type == "other":
            if data.event.irc_command.lower() == "mode":
                return f"{self.IRC_LOGO} `{permissions_label}{data.author.nickname}` sets mode **{data.event.irc_paramlist[1]}** on `{data.event.irc_paramlist[2]}`"
            else:
                return f"{self.IRC_LOGO} `{data.author.mask}` did some configuration on {data.channel.name}..."
        elif data.event.type == "factoid":
            return f"{self.IRC_LOGO} {data.event.content}"

    @staticmethod
    def _get_permissions_label(permissions):
        label = ""
        if permissions:
            if "v" in permissions:
                label += "+"
            if "o" in permissions:
                label += "@"
        return label