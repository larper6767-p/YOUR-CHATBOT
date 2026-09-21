"""Per-user commands: profiles, memory, verification, timezone, narration, export."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import discord

from ..config import (
    BASE_DIR,
    DEFAULT_MAX_CONTEXT_TOKENS,
    RESPONSE_TOKEN_BUDGET,
    bot,
)
from ..storage import (
    characters,
    conversation_histories,
    get_character_key,
    get_or_create_profile,
    save_character,
    save_history,
    save_profiles,
    update_profile,
    user_profiles,
)
from ..utils import count_tokens_for_messages, scope_key_from_message


@bot.command(name="resetconvo")
async def reset_convo(ctx):
    cid = f"{ctx.channel.id}_{ctx.author.id}"
    if cid in conversation_histories:
        del conversation_histories[cid]
        save_history(conversation_histories)
        await ctx.send("🔄 Your conversation history has been cleared.")
    else:
        await ctx.send("ℹ️  You don't have any conversation history yet.")


@bot.command(name="verify")
async def verify_cmd(ctx):
    user_id = ctx.author.id
    profile = get_or_create_profile(user_id)
    profile["verified"] = True
    save_profiles(user_profiles)
    await ctx.send("✅ Thanks! You're verified — we're officially getting to know each other now.")
    print(f"🔞  User {user_id} verified 18+ (prefix)")


@bot.command(name="profile")
async def profile_cmd(ctx):
    profile = get_or_create_profile(ctx.author.id)
    scope = scope_key_from_message(ctx.message)
    char = characters[get_character_key(scope)]

    embed = discord.Embed(title=f"👤 Your Profile: {ctx.author}", color=0x5865F2)
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
    embed.add_field(
        name="Memory Summary",
        value=profile.get("memory_summary") or "_(nothing remembered yet)_",
        inline=False,
    )
    await ctx.send(embed=embed)


@bot.command(name="forgetme")
async def forgetme_cmd(ctx):
    user_id_str = str(ctx.author.id)
    user_profiles.pop(user_id_str, None)
    save_profiles(user_profiles)
    removed = [cid for cid in list(conversation_histories) if user_id_str in cid]
    for cid in removed:
        del conversation_histories[cid]
    save_history(conversation_histories)
    await ctx.send(f"🧹 Done — your profile and {len(removed)} conversation thread(s) have been deleted.")
    print(f"🧹  User {user_id_str} requested full data removal (prefix)")


@bot.command(name="timezone")
async def timezone_cmd(ctx, offset: str = None):
    """Set your UTC offset in hours, e.g. `.timezone 5.5` for IST."""
    if offset is None:
        p = get_or_create_profile(ctx.author.id)
        await ctx.send(f"🕒 Your UTC offset: **{p.get('timezone_offset', 0) / 60:+.1f}h**\nUse `.timezone <hours>` to change (e.g. `.timezone 5.5`).")
        return
    try:
        hours = float(offset)
        if not -12 <= hours <= 14:
            raise ValueError
    except ValueError:
        await ctx.send("⚠️ Use a number between -12 and 14, e.g. `.timezone 5.5`")
        return
    update_profile(ctx.author.id, timezone_offset=int(hours * 60))
    await ctx.send(f"✅ Timezone set to UTC{hours:+.1f}.")


@bot.command(name="narration")
async def narration_cmd(ctx, mode: str | None = None):
    scope = scope_key_from_message(ctx.message)
    key = get_character_key(scope)
    char = characters[key]

    cid = f"{ctx.channel.id}_{ctx.author.id}"
    if cid not in conversation_histories:
        conversation_histories[cid] = []

    user_prefs = char.setdefault("user_prefs", {})
    pref = user_prefs.get(cid, char.get("advanced", {}).get("narration_style", "first_person"))
    current_label = "first_person" if "first" in pref else "third_person"

    if mode is None:
        emoji = "📖" if current_label == "third_person" else "✨"
        desc = "Third-person (e.g. *She walks to the window...*)" if current_label == "third_person" else "First-person (e.g. *I walk to the window...*)"
        await ctx.send(f"{emoji} **Narration Mode:** {current_label.replace('_', ' ').title()}\n📝 {desc}\n\nUse `.narration first` or `.narration third` to switch.")
        return

    mode = mode.lower().replace("-", "_").replace(" ", "_")
    if mode not in ("first", "first_person", "third", "third_person"):
        await ctx.send("⚠️ Invalid mode. Use `.narration first` or `.narration third`.")
        return

    if mode.startswith("first"):
        new_label, emoji, norm_pref = "First-person", "✨", "first_person"
    else:
        new_label, emoji, norm_pref = "Third-person", "📖", "third_person"

    user_prefs[cid] = norm_pref
    save_character(key, char)

    hint = f"[NARRATION MODE: {new_label}]"
    conversation_histories[cid].insert(0, {"role": "system", "content": hint})
    save_history(conversation_histories)
    await ctx.send(f"{emoji} Narration switched to **{new_label}**!")


@bot.command(name="contextinfo")
async def context_info(ctx):
    cid = f"{ctx.channel.id}_{ctx.author.id}"
    history = conversation_histories.get(cid, [])
    if not history:
        await ctx.send("ℹ️  You don't have any conversation history yet.")
        return
    scope = scope_key_from_message(ctx.message)
    char = characters[get_character_key(scope)]
    system_prompt = char.get("system_prompt", char.get("systemPrompt", ""))
    max_ctx = char.get("settings", {}).get("generation", {}).get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS)
    full = [{"role": "system", "content": system_prompt}] + history
    token_count = count_tokens_for_messages(full)

    embed = discord.Embed(title="📊 Context Information", color=0x5865F2)
    embed.add_field(name="Messages", value=len(history), inline=True)
    embed.add_field(name="Tokens Used", value=f"{token_count:,}", inline=True)
    embed.add_field(name="Max Tokens", value=f"{max_ctx - RESPONSE_TOKEN_BUDGET:,}", inline=True)
    percentage = (token_count / (max_ctx - RESPONSE_TOKEN_BUDGET)) * 100
    embed.add_field(name="Usage", value=f"{percentage:.1f}%", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="export")
async def export_history(ctx):
    cid = f"{ctx.channel.id}_{ctx.author.id}"
    history = conversation_histories.get(cid, [])
    if not history:
        await ctx.send("ℹ️  You don't have any conversation history to export.")
        return
    export_data = {
        "user": str(ctx.author),
        "channel": str(ctx.channel),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "messages": history,
    }
    filename = f"chat_export_{ctx.author.id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(BASE_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    await ctx.send(file=discord.File(filepath))
    os.remove(filepath)
