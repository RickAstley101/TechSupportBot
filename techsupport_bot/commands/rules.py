"""Module for the rules extension of the discord bot."""

from __future__ import annotations

import datetime
import io
import json
from typing import TYPE_CHECKING, Self

import discord
import munch
from core import auxiliary, cogs
from discord.ext import commands

if TYPE_CHECKING:
    import bot


async def setup(bot: bot.TechSupportBot) -> None:
    """Loading the Rules plugin into the bot

    Args:
        bot (bot.TechSupportBot): The bot object to register the cogs to
    """
    await bot.add_cog(Rules(bot=bot))


class Rules(cogs.BaseCog):
    """Class to define the rules for the extension.

    Attributes:
        RULE_ICON_URL (str): The icon to use for the rules

    """

    RULE_ICON_URL: str = (
        "https://cdn.icon-icons.com/icons2/907/PNG"
        "/512/balance-scale-of-justice_icon-icons.com_70554.png"
    )

    @commands.group(name="rule")
    async def rule_group(self: Self, ctx: commands.Context) -> None:
        """The bare .rule command. This does nothing but generate the help message

        Args:
            ctx (commands.Context): The context in which the command was run in
        """

        # Executed if there are no/invalid args supplied
        await auxiliary.extension_help(self, ctx, self.__module__[9:])

    async def get_guild_rules(self: Self, guild: discord.Guild) -> munch.Munch:
        """Gets the munchified rules for a given guild.
        Will create and write to the database if no rules exist

        Args:
            guild (discord.Guild): The guild to get rules for

        Returns:
            munch.Munch: The munchified rules ready to be parsed and shown to the user
        """
        query = await self.bot.models.Rule.query.where(
            self.bot.models.Rule.guild_id == str(guild.id)
        ).gino.first()
        if not query:
            # Handle case where guild doesn't have rules
            rules_data = json.dumps(
                {
                    "rules": [
                        {"description": "No spamming! (this is an example rule)"},
                        {"description": "Keep it friendly! (this is an example rule)"},
                    ],
                }
            )
            new_rules = munch.munchify(json.loads(rules_data))
            await self.write_new_rules(guild=guild, rules=new_rules)
            return munch.munchify(json.loads(rules_data))
        return munch.munchify(json.loads(query.rules))

    async def write_new_rules(
        self: Self, guild: discord.Guild, rules: munch.Munch
    ) -> None:
        """This converts the munchified rules into a string and writes it to the database

        Args:
            guild (discord.Guild): The guild to write the rules for
            rules (munch.Munch): The rules to convert and write
        """
        query = await self.bot.models.Rule.query.where(
            self.bot.models.Rule.guild_id == str(guild.id)
        ).gino.first()
        if not query:
            # Handle case where guild doesn't have rules
            rules_data = json.dumps(rules)
            new_guild_rules = self.bot.models.Rule(
                guild_id=str(guild.id),
                rules=str(json.dumps(rules_data)),
            )
            await new_guild_rules.create()
        else:
            await query.update(rules=str(json.dumps(rules))).apply()

    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @rule_group.command(
        name="edit",
        brief="Edits rules",
        description="Edits rules by uploading JSON",
        usage="|uploaded-json|",
    )
    async def edit_rules(self: Self, ctx: commands.Context) -> None:
        """Replaces existing rule with new rules provided by the user

        Args:
            ctx (commands.Context): The context that was generated by running this command
        """

        uploaded_data = await auxiliary.get_json_from_attachments(ctx.message)
        if uploaded_data:
            uploaded_data["guild_id"] = str(ctx.guild.id)
            await self.write_new_rules(ctx.guild, uploaded_data)
            await auxiliary.send_confirm_embed(
                message="I've updated to those rules", channel=ctx.channel
            )
            return

        rules_data = await self.get_guild_rules(ctx.guild)

        json_file = discord.File(
            io.StringIO(json.dumps(rules_data, indent=4)),
            filename=f"{ctx.guild.id}-rules-{datetime.datetime.utcnow()}.json",
        )

        await ctx.send(content="Re-upload this file to apply new rules", file=json_file)

    @commands.guild_only()
    @rule_group.command(
        name="get",
        brief="Gets a rule",
        description="Gets a rule by number for the current server",
        usage="[number]",
    )
    async def get_rule(self: Self, ctx: commands.Context, content: str) -> None:
        """Gets the list of rules provided by the invoker

        Args:
            ctx (commands.Context): The context generated by running the command
            content (str): The string representing what rules to get
        """
        # A list of all the rule numbers to get. It starts empty
        numbers = []

        # Splits content string, and adds each item to number list
        # Catches ValueError when no number is specified
        try:
            numbers.extend([int(num) for num in content.split(",")])
        except ValueError:
            await auxiliary.send_deny_embed(
                message="Please specify a rule number!", channel=ctx.channel
            )
            return

        # Stort and deduplicate all the numbers
        numbers = sorted(set(numbers))
        # Get the max rule number
        max_rule = await self.get_rule_count(ctx.guild)

        # Ensure that all rules are valid
        if numbers[0] <= 0 or numbers[len(numbers) - 1] > max_rule:
            await auxiliary.send_deny_embed(
                message="Invalid rule numbers", channel=ctx.channel
            )
            return

        # Build an embed that contains all the given rules
        embed = auxiliary.generate_basic_embed(
            title="Server Rules",
            description="",
            color=discord.Color.gold(),
            url=self.RULE_ICON_URL,
        )
        raw_rules = await self.get_guild_rules(ctx.guild)
        guild_rules = raw_rules.get("rules")
        for rule_number in numbers:
            embed.add_field(
                name=f"Rule {rule_number}",
                value=guild_rules[rule_number - 1].get("description", "None"),
                inline=False,
            )

        # Send it, and mention anyone origially mentioned
        await ctx.send(
            content=auxiliary.construct_mention_string(ctx.message.mentions),
            embed=embed,
        )

    @commands.guild_only()
    @rule_group.command(
        name="all",
        brief="Gets all rules",
        description="Gets all the rules for the current server",
    )
    async def get_all_rules(self: Self, ctx: commands.Context) -> None:
        """Prints an embed containing all of the guild rules

        Args:
            ctx (commands.Context): The context that was generated when the command was run
        """
        rules_data = await self.get_guild_rules(ctx.guild)
        if not rules_data or not rules_data.get("rules"):
            await auxiliary.send_confirm_embed(
                message="There are no rules for this server", channel=ctx.channel
            )
            return

        embed = auxiliary.generate_basic_embed(
            title="Server Rules",
            description="By talking on this server, you agree to the following rules",
            color=discord.Color.gold(),
        )

        for index, rule in enumerate(rules_data.get("rules")):
            embed.add_field(
                name=f"Rule {index+1}",
                value=rule.get("description", "None"),
                inline=False,
            )

        embed.set_thumbnail(url=self.RULE_ICON_URL)
        embed.color = discord.Color.gold()

        await ctx.send(embed=embed, mention_author=False)

    async def get_rule_count(self: Self, guild: discord.Guild) -> int:
        """Gets the rule count as an integer for the given guild
        This will create rules should it be called without any rules

        Args:
            guild (discord.Guild): The guild to get the count for

        Returns:
            int: The number of rules in the given guild
        """
        rules_data = await self.get_guild_rules(guild)
        if not rules_data or not rules_data.get("rules"):
            return 0

        return len(rules_data.get("rules"))
