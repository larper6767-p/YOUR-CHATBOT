"""Character management: list, switch, add, edit, remove, view, reload."""
from __future__ import annotations

import asyncio
import os

import discord

from ..config import CHARACTERS_DIR, bot
from ..storage import (
    _save_active,
    active_characters,
    characters,
    get_character_key,
    load_all_characters,
    save_character,
)
from ..utils import scope_key_from_message


@bot.command(name="character")
async def character_cmd(ctx, action: str = None, *, name: str = None):
    """List, switch, add, edit, or remove characters."""
    is_dm = isinstance(ctx.channel, discord.DMChannel)
    is_mod = (not is_dm) and ctx.author.guild_permissions.manage_messages
    scope = f"dm_{ctx.author.id}" if is_dm else scope_key_from_message(ctx.message)

    # LIST
    if action is None or action.lower() == "list":
        cur = get_character_key(scope)
        embed = discord.Embed(title="🎭 Available Characters", color=0x9B59B6)
        for key, data in characters.items():
            emoji = "✅ " if key == cur else ""
            embed.add_field(
                name=f"{emoji}{data.get('name', key)}",
                value=f"`{key}` — {data.get('title', 'no title')}",
                inline=False,
            )
        embed.set_footer(text="Use .character switch <key> to change | .character add to create new")
        await ctx.send(embed=embed)
        return

    # SWITCH
    if action.lower() in ("switch", "set"):
        if not name:
            await ctx.send("⚠️ Usage: `.character switch <key>`")
            return
        key = name.lower().strip().replace(" ", "_")

        if is_dm:
            target_scope = f"dm_{ctx.author.id}"
        else:
            if not is_mod:
                await ctx.send("⛔ Only moderators can switch the character in a server.")
                return
            target_scope = scope

        if key not in characters:
            await ctx.send(f"⚠️ Unknown character `{key}`. Use `.character list`.")
            return

        active_characters[target_scope] = key
        _save_active()
        await ctx.send(
            f"✅ Character switched to **{characters[key].get('name', key)}** "
            f"for this {'DM' if is_dm else 'server'}."
        )
        return

    # RELOAD
    if action.lower() == "reload":
        if not is_mod and not is_dm:
            await ctx.send("⛔ Only moderators can reload characters.")
            return
        characters.clear()
        characters.update(load_all_characters())
        await ctx.send(f"🔄 Reloaded {len(characters)} character(s) from disk.")
        return

    # ADD NEW CHARACTER
    if action.lower() == "add":
        if not is_mod and not is_dm:
            await ctx.send("⛔ Only moderators can add characters.")
            return

        await ctx.send("🎭 Let's create a new character! Please answer the following questions.\nType `cancel` at any time to stop.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            await ctx.send("**1/6** What's the character ID? (lowercase, use underscores, e.g., `alice_wonderland`)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            if msg.content.lower() == "cancel":
                await ctx.send("❌ Character creation cancelled.")
                return
            char_id = msg.content.lower().strip().replace(" ", "_")

            if char_id in characters:
                await ctx.send(f"⚠️ Character `{char_id}` already exists. Use `.character edit` instead.")
                return

            await ctx.send("**2/6** What's the character's name? (e.g., `Alice`)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            if msg.content.lower() == "cancel":
                await ctx.send("❌ Character creation cancelled.")
                return
            char_name = msg.content.strip()

            await ctx.send("**3/6** What's the character's title/tagline? (e.g., `The Curious Explorer`)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            if msg.content.lower() == "cancel":
                await ctx.send("❌ Character creation cancelled.")
                return
            char_title = msg.content.strip()

            await ctx.send("**4/6** Brief description (2-3 sentences about the character)")
            msg = await bot.wait_for('message', check=check, timeout=300.0)
            if msg.content.lower() == "cancel":
                await ctx.send("❌ Character creation cancelled.")
                return
            char_description = msg.content.strip()

            await ctx.send("**5/6** System prompt (the AI's personality instructions). This can be long and detailed.")
            msg = await bot.wait_for('message', check=check, timeout=600.0)
            if msg.content.lower() == "cancel":
                await ctx.send("❌ Character creation cancelled.")
                return
            system_prompt = msg.content.strip()

            await ctx.send("**6/6** Temperature (0.1-2.0, recommended 0.7-0.95). Higher = more creative, Lower = more consistent")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            if msg.content.lower() == "cancel":
                await ctx.send("❌ Character creation cancelled.")
                return
            try:
                temperature = float(msg.content.strip())
                if not 0.1 <= temperature <= 2.0:
                    temperature = 0.85
                    await ctx.send(f"⚠️ Temperature out of range. Using default: {temperature}")
            except ValueError:
                temperature = 0.85
                await ctx.send(f"⚠️ Invalid temperature. Using default: {temperature}")

            # Create new character
            new_character = {
                "name": char_name,
                "title": char_title,
                "description": char_description,
                "systemPrompt": system_prompt,
                "system_prompt": system_prompt,
                "settings": {
                    "model": {"name": "agnes-3.0-flash"},
                    "generation": {
                        "temperature": temperature,
                        "max_tokens": 2000,
                        "frequency_penalty": 0.7,
                        "presence_penalty": 0.7,
                    },
                    "discord_bot": {
                        "cooldown_seconds": 2,
                        "status_message": f"Playing as {char_name}"
                    },
                    "relationship": {
                        "familiar_at": 20,
                        "close_at": 100
                    }
                }
            }

            save_character(char_id, new_character)
            characters[char_id] = new_character

            embed = discord.Embed(title="✅ Character Created!", color=0x00FF00)
            embed.add_field(name="ID", value=char_id, inline=True)
            embed.add_field(name="Name", value=char_name, inline=True)
            embed.add_field(name="Title", value=char_title, inline=False)
            embed.add_field(name="Temperature", value=str(temperature), inline=True)
            embed.set_footer(text=f"Use .character switch {char_id} to activate")
            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Character creation cancelled.")
        return

    # EDIT CHARACTER
    if action.lower() == "edit":
        if not is_mod and not is_dm:
            await ctx.send("⛔ Only moderators can edit characters.")
            return

        if not name:
            await ctx.send("⚠️ Usage: `.character edit <key>`\nUse `.character list` to see available characters.")
            return

        key = name.lower().strip().replace(" ", "_")
        if key not in characters:
            await ctx.send(f"⚠️ Character `{key}` not found.")
            return

        char = characters[key]
        embed = discord.Embed(title=f"📝 Editing: {char.get('name', key)}", color=0xFFAA00)
        embed.add_field(name="What to edit?", value=(
            "`name` — Character's display name\n"
            "`title` — Character's tagline\n"
            "`description` — Brief description\n"
            "`prompt` — System prompt/personality\n"
            "`temperature` — AI temperature (0.1-2.0)\n"
            "`cancel` — Cancel editing"
        ), inline=False)
        await ctx.send(embed=embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            field = msg.content.lower().strip()

            if field == "cancel":
                await ctx.send("❌ Edit cancelled.")
                return

            if field == "name":
                await ctx.send(f"Current name: **{char.get('name', 'N/A')}**\nEnter new name:")
                msg = await bot.wait_for('message', check=check, timeout=120.0)
                char["name"] = msg.content.strip()
                save_character(key, char)
                await ctx.send(f"✅ Name updated to: **{char['name']}**")

            elif field == "title":
                await ctx.send(f"Current title: **{char.get('title', 'N/A')}**\nEnter new title:")
                msg = await bot.wait_for('message', check=check, timeout=120.0)
                char["title"] = msg.content.strip()
                save_character(key, char)
                await ctx.send(f"✅ Title updated to: **{char['title']}**")

            elif field == "description":
                await ctx.send(f"Current description: {char.get('description', 'N/A')[:200]}...\nEnter new description:")
                msg = await bot.wait_for('message', check=check, timeout=300.0)
                char["description"] = msg.content.strip()
                save_character(key, char)
                await ctx.send("✅ Description updated!")

            elif field == "prompt":
                await ctx.send("Enter new system prompt (this can be long):")
                msg = await bot.wait_for('message', check=check, timeout=600.0)
                char["systemPrompt"] = msg.content.strip()
                char["system_prompt"] = msg.content.strip()
                save_character(key, char)
                await ctx.send("✅ System prompt updated!")

            elif field == "temperature":
                current_temp = char.get("settings", {}).get("generation", {}).get("temperature", 0.85)
                await ctx.send(f"Current temperature: **{current_temp}**\nEnter new temperature (0.1-2.0):")
                msg = await bot.wait_for('message', check=check, timeout=60.0)
                try:
                    temp = float(msg.content.strip())
                    if 0.1 <= temp <= 2.0:
                        char.setdefault("settings", {}).setdefault("generation", {})["temperature"] = temp
                        save_character(key, char)
                        await ctx.send(f"✅ Temperature updated to: **{temp}**")
                    else:
                        await ctx.send("⚠️ Temperature must be between 0.1 and 2.0")
                except ValueError:
                    await ctx.send("⚠️ Invalid number")

            else:
                await ctx.send("⚠️ Unknown field. Edit cancelled.")

        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Edit cancelled.")
        return

    # REMOVE CHARACTER
    if action.lower() in ("remove", "delete"):
        if not is_mod and not is_dm:
            await ctx.send("⛔ Only moderators can remove characters.")
            return

        if not name:
            await ctx.send("⚠️ Usage: `.character remove <key>`")
            return

        key = name.lower().strip().replace(" ", "_")
        if key not in characters:
            await ctx.send(f"⚠️ Character `{key}` not found.")
            return

        if len(characters) <= 1:
            await ctx.send("⚠️ Cannot remove the last character. Add another character first.")
            return

        char_name = characters[key].get("name", key)

        # Remove from memory
        del characters[key]

        # Remove file
        char_file = os.path.join(CHARACTERS_DIR, f"{key}.json")
        if os.path.exists(char_file):
            os.remove(char_file)

        # Update active characters that were using this one
        for scope_k in list(active_characters.keys()):
            if active_characters[scope_k] == key:
                active_characters[scope_k] = next(iter(characters.keys()))
        _save_active()

        await ctx.send(f"✅ Removed character: **{char_name}** (`{key}`)")
        return

    # VIEW CHARACTER DETAILS
    if action.lower() in ("view", "info", "show"):
        if not name:
            await ctx.send("⚠️ Usage: `.character view <key>`")
            return

        key = name.lower().strip().replace(" ", "_")
        if key not in characters:
            await ctx.send(f"⚠️ Character `{key}` not found.")
            return

        char = characters[key]
        embed = discord.Embed(title=f"🎭 {char.get('name', key)}", color=0x9B59B6)
        embed.add_field(name="ID", value=f"`{key}`", inline=True)
        embed.add_field(name="Title", value=char.get("title", "N/A"), inline=True)

        temp = char.get("settings", {}).get("generation", {}).get("temperature", "N/A")
        embed.add_field(name="Temperature", value=str(temp), inline=True)

        desc = char.get("description", "N/A")
        if len(desc) > 1024:
            desc = desc[:1021] + "..."
        embed.add_field(name="Description", value=desc, inline=False)

        prompt_preview = char.get("systemPrompt", char.get("system_prompt", "N/A"))[:300]
        embed.add_field(name="System Prompt (preview)", value=f"```{prompt_preview}...```", inline=False)

        await ctx.send(embed=embed)
        return

    await ctx.send("⚠️ Usage: `.character [list | switch | add | edit | remove | view | reload]`")
