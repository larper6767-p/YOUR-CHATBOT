"""Scene management: view, list, change, add, edit, remove scenes."""
from __future__ import annotations

import asyncio

import discord

from ..config import bot
from ..storage import (
    get_character_key,
    is_verified,
    load_scenes,
    save_scenes,
    update_profile,
)
from ..utils import scope_key_from_message


@bot.command(name="scene")
async def scene_cmd(ctx, action: str | None = None, *, scene_id: str | None = None):
    scope = scope_key_from_message(ctx.message)
    char_key = get_character_key(scope)
    scenes = load_scenes(char_key)

    if action is None:
        current = scenes.get("current_scene", "poolside")
        scene = scenes.get("scenes", {}).get(current, {})
        embed = discord.Embed(title=f"🎬 Current Scene: {scene.get('name', 'Unknown')}", color=0x00CED1)
        embed.add_field(name="Description", value=scene.get("description", "No description"), inline=False)
        embed.add_field(name="Atmosphere", value=scene.get("atmosphere", "No details")[:1024], inline=False)
        embed.set_footer(text=f"Scene ID: {current}")
        await ctx.send(embed=embed)
        return

    if action.lower() == "list":
        all_scenes = scenes.get("scenes", {})
        current = scenes.get("current_scene", "")
        embed = discord.Embed(title="🎬 Available Scenes", color=0x00CED1)
        for sid, scene in all_scenes.items():
            emoji = scene.get("emoji", "🎬")
            name = scene.get("name", sid)
            desc = scene.get("description", "No description")
            is_current = "✅ " if sid == current else ""
            embed.add_field(name=f"{is_current}{emoji} {name}", value=f"`{sid}` - {desc}", inline=False)
        embed.set_footer(text="Use .scene change <scene_id> to change scene")
        await ctx.send(embed=embed)
        return

    if action.lower() == "change":
        if not scene_id:
            await ctx.send("⚠️ Please specify a scene ID. Use `.scene list` to see available scenes.")
            return
        scene_id = scene_id.lower().replace(" ", "_")
        if scene_id not in scenes.get("scenes", {}):
            await ctx.send(f"⚠️ Scene '{scene_id}' not found. Use `.scene list` to see available scenes.")
            return
        scenes["current_scene"] = scene_id
        save_scenes(char_key, scenes)
        scene = scenes["scenes"][scene_id]
        if is_verified(ctx.author.id):
            update_profile(ctx.author.id, last_scene=scene_id)
        embed = discord.Embed(title="✅ Scene Changed!", color=0x00FF00)
        embed.add_field(name="Now At", value=f"{scene.get('emoji', '🎬')} {scene.get('name', scene_id)}", inline=False)
        embed.add_field(name="Description", value=scene.get('description', 'No description'), inline=False)
        await ctx.send(embed=embed)
        return

    if action.lower() == "add":
        await ctx.send("📝 Let's create a new scene! Please answer the following questions.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            await ctx.send("**1/5** What's the scene ID? (lowercase, underscores)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            new_id = msg.content.lower().replace(" ", "_")
            if new_id in scenes.get("scenes", {}):
                await ctx.send(f"⚠️ Scene '{new_id}' already exists. Use `.scene edit` instead.")
                return
            await ctx.send("**2/5** What's the scene name?")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            name = msg.content
            await ctx.send("**3/5** Choose an emoji for this scene")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            emoji = msg.content
            await ctx.send("**4/5** Brief description (one line)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            description = msg.content
            await ctx.send("**5/5** Full atmosphere description (what do you see, hear, smell?)")
            msg = await bot.wait_for('message', check=check, timeout=300.0)
            atmosphere = msg.content

            scenes.setdefault("scenes", {})[new_id] = {
                "name": name,
                "emoji": emoji,
                "description": description,
                "atmosphere": atmosphere,
            }
            save_scenes(char_key, scenes)
            embed = discord.Embed(title="✅ Scene Added!", color=0x00FF00)
            embed.add_field(name="ID", value=new_id, inline=True)
            embed.add_field(name="Name", value=f"{emoji} {name}", inline=True)
            embed.add_field(name="Description", value=description, inline=False)
            await ctx.send(embed=embed)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Scene creation cancelled.")
        return

    if action.lower() == "remove":
        if not scene_id:
            await ctx.send("⚠️ Please specify a scene ID to remove.")
            return
        scene_id = scene_id.lower().replace(" ", "_")
        if scene_id not in scenes.get("scenes", {}):
            await ctx.send(f"⚠️ Scene '{scene_id}' not found.")
            return
        scene_name = scenes["scenes"][scene_id].get("name", scene_id)
        del scenes["scenes"][scene_id]
        if scenes.get("current_scene") == scene_id:
            scenes["current_scene"] = list(scenes["scenes"].keys())[0] if scenes["scenes"] else "default"
        save_scenes(char_key, scenes)
        await ctx.send(f"✅ Removed scene: {scene_name}")
        return

    if action.lower() == "edit":
        if not scene_id:
            await ctx.send("⚠️ Please specify a scene ID to edit.")
            return
        scene_id = scene_id.lower().replace(" ", "_")
        if scene_id not in scenes.get("scenes", {}):
            await ctx.send(f"⚠️ Scene '{scene_id}' not found.")
            return
        scene = scenes["scenes"][scene_id]
        embed = discord.Embed(title=f"📝 Editing: {scene.get('name', scene_id)}", color=0xFFAA00)
        embed.add_field(name="What to edit?", value="Reply with:\n`name` `emoji` `description` `atmosphere` or `cancel`", inline=False)
        await ctx.send(embed=embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            field = msg.content.lower()
            if field == "cancel":
                await ctx.send("❌ Edit cancelled.")
                return
            if field not in ["name", "emoji", "description", "atmosphere"]:
                await ctx.send("⚠️ Invalid field. Edit cancelled.")
                return
            await ctx.send(f"Enter new value for **{field}**:")
            msg = await bot.wait_for('message', check=check, timeout=300.0)
            scene[field] = msg.content
            save_scenes(char_key, scenes)
            await ctx.send(f"✅ Updated {field} for scene: {scene.get('name', scene_id)}")
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Edit cancelled.")
        return

    await ctx.send("⚠️ Invalid action. Use: `list`, `change`, `add`, `remove`, or `edit`")
