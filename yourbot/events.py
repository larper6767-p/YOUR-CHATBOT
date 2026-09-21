"""Discord gateway listeners and global error handlers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import discord
from discord.ext import commands

from .config import AGE_VERIFY_PROMPT, bot
from .llm import process_chat_turn
from .storage import (
    characters,
    conversation_histories,
    get_character_key,
    is_verified,
    save_history,
    user_last_message,
)
from .utils import scope_key_from_message, send_reply


async def sync_slash_commands():
    await bot.tree.sync()
    print(f"📝 Slash commands synced globally for {bot.user}")


@bot.event
async def on_ready():
    print(f"✅  Logged in as {bot.user} (ID: {cast(discord.ClientUser, bot.user).id})")
    print(f"🎭  Loaded {len(characters)} character(s): {', '.join(characters.keys())}")
    print(f"📚  Loaded history for {len(conversation_histories)} channels")

    default_key = get_character_key("default")
    status_msg = characters[default_key].get("settings", {}).get("discord_bot", {}).get("status_message", "Ready!")
    await bot.change_presence(activity=discord.Game(name=status_msg))
    print("─" * 40)

    await sync_slash_commands()


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

    bot_mentioned = bot.user in message.mentions
    is_dm = isinstance(message.channel, discord.DMChannel)
    if not (bot_mentioned or is_dm):
        return

    if not is_verified(message.author.id):
        await message.channel.send(AGE_VERIFY_PROMPT)
        return

    scope = scope_key_from_message(message)
    char_key = get_character_key(scope)
    char = characters[char_key]

    cooldown = char.get("settings", {}).get("discord_bot", {}).get("cooldown_seconds", 2)

    user_id = message.author.id
    now = datetime.now(timezone.utc)
    last_time = user_last_message[user_id]
    if (now - last_time).total_seconds() < cooldown:
        await message.add_reaction("⏱️")
        return
    user_last_message[user_id] = now

    user_text = message.content.replace(f"<@{cast(discord.ClientUser, bot.user).id}>", "").strip()
    if not user_text:
        await message.channel.send(f"Hey! I'm **{char.get('name', 'Bot')}**. How can I help?")
        return

    author = message.author
    activity_name = None
    if isinstance(author, discord.Member) and author.activity and author.activity.name:
        activity_name = author.activity.name

    async with message.channel.typing():
        cid = f"{message.channel.id}_{message.author.id}"
        try:
            reply = await process_chat_turn(cid, user_id, user_text, char, char_key, activity_name)

            if reply is None:
                fallback = "...hmm, I zoned out for a second there. Can you say that again?"
                conversation_histories[cid].append({"role": "assistant", "content": fallback})
                save_history(conversation_histories)
                await message.reply(fallback)
                print("⚠️  Empty reply from agnes; sent fallback message")
                return

            await send_reply(message.reply, message.channel.send, reply)
        except Exception as e:
            await message.channel.send(f"⚠️  Something went wrong: `{str(e)[:100]}`")
            print(f"❌  Error: {e}")


@bot.tree.error
async def on_slash_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    try:
        if isinstance(error, discord.app_commands.MissingPermissions):
            await interaction.response.send_message("⛔ You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, discord.app_commands.MissingAnyRole):
            await interaction.response.send_message("⛔ You need a specific role to use this command.", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ An error occurred: `{str(error)[:100]}`", ephemeral=True)
            print(f"❌  Slash command error: {error}")
    except Exception:
        pass


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ You don't have permission to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️  Invalid arguments. Use `.bothelp` for command usage.")
    else:
        await ctx.send(f"⚠️  An error occurred: `{str(error)[:100]}`")
        print(f"❌  Command error: {error}")
