"""Module for the translate extension for the discord bot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from core import auxiliary, cogs
from discord.ext import commands

if TYPE_CHECKING:
    import bot


async def setup(bot: bot.TechSupportBot) -> None:
    """Loading the Translate plugin into the bot

    Args:
        bot (bot.TechSupportBot): The bot object to register the cogs to
    """
    await bot.add_cog(Translator(bot=bot))


class Translator(cogs.BaseCog):
    """Class to set up the translate extension.

    Attributes:
        API_URL (str): The translated API URL

    """

    API_URL: str = "https://api.mymemory.translated.net/get?q={}&langpair={}|{}"

    @auxiliary.with_typing
    @commands.command(
        brief="Translates a message",
        description="Translates a given input message to another language",
        usage=(
            '"[message (in quotes)]" [src language code (en)] [dest language code (es)]'
        ),
    )
    async def translate(
        self: Self, ctx: commands.Context, message: str, src: str, dest: str
    ) -> None:
        """Translates user input into another language

        Args:
            ctx (commands.Context): The context generated by running this command
            message (str): The string to translate
            src (str): The language the message is currently in
            dest (str): The target language to translate to
        """
        response = await self.bot.http_functions.http_call(
            "get",
            self.API_URL.format(message, src, dest),
        )
        translated = response.get("responseData", {}).get("translatedText")

        if not translated:
            await auxiliary.send_deny_embed(
                message="I could not translate your message", channel=ctx.channel
            )
            return

        await auxiliary.send_confirm_embed(message=translated, channel=ctx.channel)
