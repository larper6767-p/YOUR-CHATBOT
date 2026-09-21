"""Slash command definitions (``/chat``, ``/character``, ``/profile``, ...)."""
from __future__ import annotations

from typing import cast

import discord
from discord import app_commands

from ..config import AGE_VERIFY_PROMPT, bot
from ..llm import process_chat_turn
from ..storage import (
    _save_active,
    active_characters,
    characters,
    conversation_histories,
    get_character_key,
    get_or_create_profile,
    is_verified,
    load_scenes,
    load_wardrobe,
    save_character,
    save_history,
    save_profiles,
    update_profile,
    user_profiles,
)
from ..utils import scope_key_from_interaction, send_reply


@bot.tree.command(name="chat", description="Chat with the bot")
async def slash_chat(interaction: discord.Interaction, message: str):
    user_text = message.strip()
    if not user_text:
        await interaction.response.send_message("⚠️ Please provide a message.", ephemeral=True)
        return
    if not is_verified(interaction.user.id):
        await interaction.response.send_message(AGE_VERIFY_PROMPT, ephemeral=True)
        return

    scope = scope_key_from_interaction(interaction)
    char_key = get_character_key(scope)
    char = characters[char_key]

    inter_user = interaction.user
    activity_name = None
    if isinstance(inter_user, discord.Member) and inter_user.activity and inter_user.activity.name:
        activity_name = inter_user.activity.name

    async with cast(discord.abc.Messageable, interaction.channel).typing():
        cid = f"{interaction.channel.id}_{interaction.user.id}"
        try:
            reply = await process_chat_turn(cid, interaction.user.id, user_text, char, char_key, activity_name)

            if reply is None:
                fallback = "...hmm, I zoned out for a second there. Can you say that again?"
                conversation_histories[cid].append({"role": "assistant", "content": fallback})
                save_history(conversation_histories)
                await interaction.followup.send(fallback)
                return

            await send_reply(interaction.followup.send, interaction.followup.send, reply)
        except Exception as e:
            await interaction.followup.send(f"⚠️  Something went wrong: `{str(e)[:100]}`")
            print(f"❌  Error: {e}")


@bot.tree.command(name="wardrobe", description="View or manage outfits")
@app_commands.describe(action="Action to perform")
async def slash_wardrobe(interaction: discord.Interaction, action: str | None = None):
    scope = scope_key_from_interaction(interaction)
    char_key = get_character_key(scope)
    wardrobe = load_wardrobe(char_key)

    if action == "list":
        outfits = wardrobe.get("outfits", {})
        current = wardrobe.get("current_outfit", "")
        embed = discord.Embed(title="👗 Available Outfits", color=0xFF69B4)
        for oid, outfit in outfits.items():
            emoji = outfit.get("emoji", "👗")
            name = outfit.get("name", oid)
            desc = outfit.get("description", "No description")
            is_current = "✅ " if oid == current else ""
            embed.add_field(name=f"{is_current}{emoji} {name}", value=f"`{oid}` - {desc}", inline=False)
        embed.set_footer(text="Use .wardrobe change <id> to switch")
        await interaction.response.send_message(embed=embed)
    else:
        current = wardrobe.get("current_outfit", "poolside_bikini")
        outfit = wardrobe.get("outfits", {}).get(current, {})
        embed = discord.Embed(title=f"👗 Current Outfit: {outfit.get('name', 'Unknown')}", color=0xFF69B4)
        embed.add_field(name="Description", value=outfit.get("description", "No description"), inline=False)
        embed.add_field(name="Appearance", value=outfit.get("appearance", "No details")[:1024], inline=False)
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="scene", description="View or manage scenes")
@app_commands.describe(action="Action to perform")
async def slash_scene(interaction: discord.Interaction, action: str | None = None):
    scope = scope_key_from_interaction(interaction)
    char_key = get_character_key(scope)
    scenes = load_scenes(char_key)

    if action == "list":
        all_scenes = scenes.get("scenes", {})
        current = scenes.get("current_scene", "")
        embed = discord.Embed(title="🎬 Available Scenes", color=0x00CED1)
        for sid, scene in all_scenes.items():
            emoji = scene.get("emoji", "🎬")
            name = scene.get("name", sid)
            desc = scene.get("description", "No description")
            is_current = "✅ " if sid == current else ""
            embed.add_field(name=f"{is_current}{emoji} {name}", value=f"`{sid}` - {desc}", inline=False)
        embed.set_footer(text="Use .scene change <id> to switch")
        await interaction.response.send_message(embed=embed)
    else:
        current = scenes.get("current_scene", "poolside")
        scene = scenes.get("scenes", {}).get(current, {})
        embed = discord.Embed(title=f"🎬 Current Scene: {scene.get('name', 'Unknown')}", color=0x00CED1)
        embed.add_field(name="Description", value=scene.get("description", "No description"), inline=False)
        embed.add_field(name="Atmosphere", value=scene.get("atmosphere", "No details")[:1024], inline=False)
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="character", description="List or switch the active character")
@app_commands.describe(action="list or switch", name="character key when switching")
async def slash_character(interaction: discord.Interaction, action: str = "list", name: str = ""):
    is_dm = isinstance(interaction.channel, discord.DMChannel)
    is_mod = (not is_dm) and isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages
    scope = f"dm_{interaction.user.id}" if is_dm else scope_key_from_interaction(interaction)

    if action.lower() == "list":
        cur = get_character_key(scope)
        embed = discord.Embed(title="🎭 Available Characters", color=0x9B59B6)
        for key, data in characters.items():
            emoji = "✅ " if key == cur else ""
            embed.add_field(name=f"{emoji}{data.get('name', key)}", value=f"`{key}` — {data.get('title', 'no title')}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if action.lower() == "switch":
        if not name:
            await interaction.response.send_message("⚠️ Provide a character key.", ephemeral=True)
            return
        key = name.lower().strip().replace(" ", "_")
        if not is_dm and not is_mod:
            await interaction.response.send_message("⛔ Only moderators can switch the character in a server.", ephemeral=True)
            return
        if key not in characters:
            await interaction.response.send_message(f"⚠️ Unknown character `{key}`.", ephemeral=True)
            return
        target_scope = f"dm_{interaction.user.id}" if is_dm else scope
        active_characters[target_scope] = key
        _save_active()
        await interaction.response.send_message(f"✅ Character switched to **{characters[key].get('name', key)}**.", ephemeral=True)
        return

    await interaction.response.send_message("⚠️ Usage: `/character list` or `/character switch <key>`", ephemeral=True)


@bot.tree.command(name="timezone", description="Set your UTC offset in hours")
@app_commands.describe(offset="Hours from UTC, e.g. 5.5 for IST")
async def slash_timezone(interaction: discord.Interaction, offset: float):
    if not -12 <= offset <= 14:
        await interaction.response.send_message("⚠️ Offset must be between -12 and 14.", ephemeral=True)
        return
    update_profile(interaction.user.id, timezone_offset=int(offset * 60))
    await interaction.response.send_message(f"✅ Timezone set to UTC{offset:+.1f}.", ephemeral=True)


@bot.tree.command(name="status", description="View or change bot status")
@app_commands.describe(activity_type="Type of activity", message="Status message")
async def slash_status(interaction: discord.Interaction, activity_type: str | None = None, message: str = ""):
    scope = scope_key_from_interaction(interaction)
    key = get_character_key(scope)
    char = characters[key]

    if not activity_type and not message:
        current = char.get("settings", {}).get("discord_bot", {}).get("status_message", "Ready!")
        await interaction.response.send_message(f"📊 Current status: **{current}**", ephemeral=True)
        return
    if not message:
        await interaction.response.send_message("⚠️ Please provide a status message.", ephemeral=True)
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
        await interaction.response.send_message(f"⚠️ Invalid type. Valid: {', '.join(activity_types.keys())}", ephemeral=True)
        return

    await bot.change_presence(activity=activity_types[activity_type])
    d = char.setdefault("settings", {}).setdefault("discord_bot", {})
    d["status_message"] = message
    d["activity_type"] = activity_type
    save_character(key, char)

    emoji_map = {"playing": "🎮", "watching": "👁️", "listening": "🎧", "streaming": "📺"}
    await interaction.response.send_message(f"✅ Status updated! {emoji_map.get(activity_type, '📊')} **{message}**")


@bot.tree.command(name="verify", description="Confirm you are 18+ to unlock the bot")
async def slash_verify(interaction: discord.Interaction):
    user_id = interaction.user.id
    profile = get_or_create_profile(user_id)
    profile["verified"] = True
    save_profiles(user_profiles)
    await interaction.response.send_message(
        f"✅ Thanks, **{interaction.user}**! You're verified. We're officially getting to know each other now.",
        ephemeral=True,
    )
    print(f"🔞  User {user_id} verified 18+")


@bot.tree.command(name="profile", description="Show your stored profile (mood, facts, memory)")
async def slash_profile(interaction: discord.Interaction):
    profile = get_or_create_profile(interaction.user.id)
    scope = scope_key_from_interaction(interaction)
    char = characters[get_character_key(scope)]

    embed = discord.Embed(title=f"👤 Your Profile: {interaction.user}", color=0x5865F2)
    embed.add_field(name="Nickname", value=profile.get("nickname") or "_(not set)_", inline=True)
    embed.add_field(name="Relationship Stage", value=profile.get("relationship_stage", "new"), inline=True)
    embed.add_field(name="Messages", value=str(profile.get("message_count", 0)), inline=True)
    mood = profile.get("mood", {})
    embed.add_field(
        name=f"{char.get('name', 'Character')}'s Mood",
        value=f"affection {mood.get('affection', 0):.2f} · energy {mood.get('energy', 0):.2f} · playfulness {mood.get('playfulness', 0):.2f}",
        inline=False,
    )
    facts = profile.get("memory_facts", []) or []
    facts_text = "\n".join(f"• {f['fact']}" for f in facts[-8:]) or "_(none yet)_"
    embed.add_field(name="Stored Facts", value=facts_text[:1024], inline=False)
    embed.add_field(name="Memory Summary", value=profile.get("memory_summary") or "_(nothing remembered yet)_", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="forgetme", description="Delete your profile and conversation history")
async def slash_forgetme(interaction: discord.Interaction):
    user_id_str = str(interaction.user.id)
    user_profiles.pop(user_id_str, None)
    save_profiles(user_profiles)
    removed = [cid for cid in list(conversation_histories) if user_id_str in cid]
    for cid in removed:
        del conversation_histories[cid]
    save_history(conversation_histories)
    await interaction.response.send_message(
        f"🧹 Done — your profile and {len(removed)} conversation thread(s) have been deleted.",
        ephemeral=True,
    )
    print(f"🧹  User {user_id_str} requested full data removal (profile + {len(removed)} history entries)")


@bot.tree.command(name="help", description="Show help message")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Slash Commands", color=0x5865F2)
    embed.add_field(name="💬 Chat & Info", value="`/chat <message>` — Chat with bot\n`/profile` — View your profile\n`/verify` — Age verification\n`/forgetme` — Delete all data", inline=False)
    embed.add_field(name="🎭 Characters", value="`/character list` — List all characters\n`/character switch <key>` — Switch character", inline=False)
    embed.add_field(name="👗 Wardrobe & Scenes", value="`/wardrobe [list]` — Manage outfits\n`/scene [list]` — Manage scenes", inline=False)
    embed.add_field(name="⚙️ Settings", value="`/timezone <hours>` — Set UTC offset\n`/status` — Bot status", inline=False)
    embed.set_footer(text="Use .bothelp for prefix command list")
    await interaction.response.send_message(embed=embed)
