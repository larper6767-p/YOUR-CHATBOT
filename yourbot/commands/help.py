"""Help command for prefix commands."""
from __future__ import annotations

import discord

from ..config import bot


@bot.command(name="bothelp")
async def bot_help(ctx):
    embed = discord.Embed(title="📖 Bot Commands", color=0x5865F2)

    basic_cmds = [
        ("@bot <message>", "Chat with the bot"),
        (".verify", "Confirm you're 18+ to unlock the bot"),
        (".profile", "View your profile, mood, and facts"),
        (".forgetme", "Delete your profile and history"),
        (".resetconvo", "Clear your conversation history"),
        (".export", "Export your conversation history"),
    ]

    character_cmds = [
        (".character list", "List all characters"),
        (".character switch <key>", "Switch active character"),
        (".character add", "Create a new character"),
        (".character edit <key>", "Edit a character"),
        (".character remove <key>", "Delete a character"),
        (".character view <key>", "View character details"),
    ]

    settings_cmds = [
        (".timezone <hours>", "Set UTC offset (e.g. 5.5)"),
        (".contextinfo", "Show token usage"),
        (".narration [first|third]", "Switch narration mode"),
    ]

    wardrobe_scene_cmds = [
        (".wardrobe [list|change|add|edit|remove]", "Manage outfits"),
        (".scene [list|change|add|edit|remove]", "Manage scenes"),
        (".narration [first|third]", "Switch narration mode"),
    ]

    mod_cmds = [
        (".personality", "View personality settings"),
        (".editpersonality", "Edit personality interactively"),
        (".setpersonality", "Update system prompt"),
        (".setname", "Change bot's name"),
        (".settokens", "Set max response length"),
        (".resetall", "Clear all histories"),
        (".stats", "Show bot statistics"),
    ]

    embed.add_field(name="💬 Basic Commands", value="\n".join([f"`{n}` {d}" for n, d in basic_cmds]), inline=False)
    embed.add_field(name="🎭 Character Management", value="\n".join([f"`{n}` {d}" for n, d in character_cmds]), inline=False)
    embed.add_field(name="⚙️ Settings", value="\n".join([f"`{n}` {d}" for n, d in settings_cmds]), inline=False)
    embed.add_field(name="👗 Wardrobe & Scenes", value="\n".join([f"`{n}` {d}" for n, d in wardrobe_scene_cmds]), inline=False)
    embed.add_field(name="🛡️ Moderator Commands", value="\n".join([f"`{n}` {d}" for n, d in mod_cmds]), inline=False)
    embed.set_footer(text="Use /help for slash command list")
    await ctx.send(embed=embed)
