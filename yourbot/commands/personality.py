"""Personality and moderator commands.

Covers the interactive personality editor, token/name settings, and bot-wide
statistics used by moderators.
"""
from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from ..config import bot
from ..storage import (
    characters,
    conversation_histories,
    get_character_key,
    save_character,
    save_history,
)
from ..utils import scope_key_from_message


@bot.command(name="personality")
@commands.has_permissions(manage_messages=True)
async def show_personality(ctx):
    """Display current personality configuration for this scope."""
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    p = characters[key]
    embed = discord.Embed(title=f"🤖 Current Character: {p.get('name', key)}", color=0x5865F2)
    settings = p.get("settings", {}).get("generation", {})
    embed.add_field(name="Temperature", value=settings.get("temperature", "N/A"), inline=True)
    embed.add_field(name="Max Tokens", value=settings.get("max_tokens", "N/A"), inline=True)
    embed.add_field(name="Model", value=p.get("settings", {}).get("model", {}).get("name", "N/A"), inline=True)
    embed.add_field(name="Key", value=f"`{key}`", inline=True)
    preview = p.get("system_prompt", p.get("systemPrompt", "N/A"))[:500]
    embed.add_field(name="System Prompt (preview)", value=f"```{preview}...```", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="setpersonality")
@commands.has_permissions(manage_messages=True)
async def set_personality(ctx, *, new_prompt: str):
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    char = characters[key]
    char["systemPrompt"] = new_prompt
    char["system_prompt"] = new_prompt
    save_character(key, char)
    conversation_histories.clear()
    save_history(conversation_histories)
    await ctx.send(f"✅ Personality updated for **{char.get('name', key)}**! All conversation history cleared.")


@bot.command(name="setname")
@commands.has_permissions(manage_messages=True)
async def set_name(ctx, *, new_name: str):
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    char = characters[key]
    char["name"] = new_name
    save_character(key, char)
    await ctx.send(f"✅ Name updated to **{new_name}**!")


@bot.command(name="settokens")
@commands.has_permissions(manage_messages=True)
async def set_tokens(ctx, *, amount: str):
    try:
        amount_int = int(amount)
    except ValueError:
        await ctx.send("⚠️ Invalid amount. Use a number between 100 and 30000.")
        return
    if not 100 <= amount_int <= 30000:
        await ctx.send("⚠️  Please choose a value between 100 and 30000.")
        return
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    char = characters[key]
    char.setdefault("settings", {}).setdefault("generation", {})["max_tokens"] = amount_int
    save_character(key, char)
    await ctx.send(f"✅ Max tokens set to **{amount_int}**.")


@bot.command(name="resetall")
@commands.has_permissions(manage_messages=True)
async def reset_all(ctx):
    conversation_histories.clear()
    save_history(conversation_histories)
    await ctx.send("🔄 All conversation histories cleared.")


@bot.command(name="setcontextlimit")
@commands.has_permissions(manage_messages=True)
async def set_context_limit(ctx, new_limit: int):
    if new_limit < 1000:
        await ctx.send("⚠️  Please set a limit of at least 1000.")
        return
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    char = characters[key]
    char.setdefault("settings", {}).setdefault("generation", {})["max_context_tokens"] = new_limit
    save_character(key, char)
    await ctx.send(f"✅ Context limit set to **{new_limit:,}** tokens.")


@bot.command(name="stats")
@commands.has_permissions(manage_messages=True)
async def bot_stats(ctx):
    total_conversations = len(conversation_histories)
    total_messages = sum(len(hist) for hist in conversation_histories.values())
    embed = discord.Embed(title="📈 Bot Statistics", color=0x00FF00)
    embed.add_field(name="Active Conversations", value=total_conversations, inline=True)
    embed.add_field(name="Total Messages", value=total_messages, inline=True)
    embed.add_field(name="Servers", value=len(bot.guilds), inline=True)
    embed.add_field(name="Characters Loaded", value=len(characters), inline=True)
    await ctx.send(embed=embed)


@bot.command(name="editpersonality")
@commands.has_permissions(manage_messages=True)
async def edit_personality(ctx):
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    char = characters[key]

    embed = discord.Embed(title=f"🎨 Personality Editor — {char.get('name', key)}", color=0x9B59B6)
    embed.add_field(name="What would you like to edit?", value=(
        "`name` - Bot's display name\n"
        "`system_prompt` - Full system prompt\n"
        "`temperature` - AI temperature (0.0-2.0)\n"
        "`max_tokens` - Max response length\n"
        "`frequency_penalty` - Repetition penalty (0.0-2.0)\n"
        "`presence_penalty` - Topic diversity (0.0-2.0)\n"
        "`status` - Bot's Discord status\n"
        "`cancel` - Cancel editing"
    ), inline=False)
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        msg = await bot.wait_for('message', check=check, timeout=60.0)
        field = msg.content.lower()

        if field == "cancel":
            await ctx.send("❌ Edit cancelled.")
            return

        if field == "name":
            await ctx.send("Enter new bot name:")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            char["name"] = msg.content

        elif field == "system_prompt":
            await ctx.send("Enter new system prompt:")
            msg = await bot.wait_for('message', check=check, timeout=600.0)
            char["systemPrompt"] = msg.content
            char["system_prompt"] = msg.content

        elif field == "temperature":
            await ctx.send("Enter temperature value (0.0-2.0):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                temp = float(msg.content)
                if not 0.0 <= temp <= 2.0:
                    await ctx.send("⚠️ Temperature must be between 0.0 and 2.0")
                    return
                char.setdefault("settings", {}).setdefault("generation", {})["temperature"] = temp
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "max_tokens":
            await ctx.send("Enter max tokens (100-30000):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                tokens = int(msg.content)
                if not 100 <= tokens <= 30000:
                    await ctx.send("⚠️ Max tokens must be between 100 and 30000")
                    return
                char.setdefault("settings", {}).setdefault("generation", {})["max_tokens"] = tokens
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "frequency_penalty":
            await ctx.send("Enter frequency penalty (0.0-2.0):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                penalty = float(msg.content)
                if not 0.0 <= penalty <= 2.0:
                    await ctx.send("⚠️ Must be between 0.0 and 2.0")
                    return
                char.setdefault("settings", {}).setdefault("generation", {})["frequency_penalty"] = penalty
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "presence_penalty":
            await ctx.send("Enter presence penalty (0.0-2.0):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                penalty = float(msg.content)
                if not 0.0 <= penalty <= 2.0:
                    await ctx.send("⚠️ Must be between 0.0 and 2.0")
                    return
                char.setdefault("settings", {}).setdefault("generation", {})["presence_penalty"] = penalty
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "status":
            await ctx.send("Enter new Discord status message:")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            char.setdefault("settings", {}).setdefault("discord_bot", {})["status_message"] = msg.content
            await bot.change_presence(activity=discord.Game(name=msg.content))

        else:
            await ctx.send("⚠️ Unknown field. Edit cancelled.")
            return

        save_character(key, char)
        await ctx.send(f"✅ Updated **{field}** successfully!")

    except asyncio.TimeoutError:
        await ctx.send("⏱️ Timed out. Edit cancelled.")


@bot.command(name="status")
@commands.has_permissions(manage_messages=True)
async def status_cmd(ctx, activity_type: str | None = None, *, message: str = ""):
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    char = characters[key]

    if not activity_type and not message:
        current = char.get("settings", {}).get("discord_bot", {}).get("status_message", "Ready!")
        await ctx.send(f"📊 Current status: **{current}**\n\nUsage: `.status <type> <message>`\nTypes: `playing`, `watching`, `listening`, `streaming`")
        return
    if not message:
        await ctx.send("⚠️ Please provide a status message. Example: `.status playing with you`")
        return

    activity_type = activity_type.lower() if activity_type else "playing"
    message = message.strip()

    activity_types = {
        "playing": discord.Game(name=message),
        "watching": discord.Activity(type=discord.ActivityType.watching, name=message),
        "listening": discord.Activity(type=discord.ActivityType.listening, name=message),
        "streaming": discord.Streaming(url="", name=message),
    }
    if activity_type not in activity_types:
        await ctx.send(f"⚠️ Invalid activity type. Valid: {', '.join(activity_types.keys())}")
        return

    await bot.change_presence(activity=activity_types[activity_type])
    d = char.setdefault("settings", {}).setdefault("discord_bot", {})
    d["status_message"] = message
    d["activity_type"] = activity_type
    save_character(key, char)

    emoji_map = {"playing": "🎮", "watching": "👁️", "listening": "🎧", "streaming": "📺"}
    await ctx.send(f"✅ Status updated! {emoji_map.get(activity_type, '📊')} **{message}** ({activity_type})")
