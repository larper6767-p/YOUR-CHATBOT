"""Wardrobe management: view, list, change, add, edit, remove outfits."""
from __future__ import annotations

import asyncio

import discord

from ..config import bot
from ..storage import get_character_key, load_wardrobe, save_wardrobe
from ..utils import scope_key_from_message


@bot.command(name="wardrobe")
async def wardrobe_cmd(ctx, action: str | None = None, *, outfit_id: str | None = None):
    scope = scope_key_from_message(ctx.message)
    char_key = get_character_key(scope)
    wardrobe = load_wardrobe(char_key)

    if action is None:
        current = wardrobe.get("current_outfit", "poolside_bikini")
        outfit = wardrobe.get("outfits", {}).get(current, {})
        embed = discord.Embed(title=f"👗 Current Outfit: {outfit.get('name', 'Unknown')}", color=0xFF69B4)
        embed.add_field(name="Description", value=outfit.get("description", "No description"), inline=False)
        embed.add_field(name="Appearance", value=outfit.get("appearance", "No details")[:1024], inline=False)
        if "scene" in outfit:
            embed.add_field(name="Scene", value=outfit["scene"], inline=True)
        embed.set_footer(text=f"Outfit ID: {current}")
        await ctx.send(embed=embed)
        return

    if action.lower() == "list":
        outfits = wardrobe.get("outfits", {})
        current = wardrobe.get("current_outfit", "")
        embed = discord.Embed(title="👗 Available Outfits", color=0xFF69B4)
        for oid, outfit in outfits.items():
            emoji = outfit.get("emoji", "👗")
            name = outfit.get("name", oid)
            desc = outfit.get("description", "No description")
            is_current = "✅ " if oid == current else ""
            embed.add_field(name=f"{is_current}{emoji} {name}", value=f"`{oid}` - {desc}", inline=False)
        embed.set_footer(text="Use .wardrobe change <outfit_id> to change outfit")
        await ctx.send(embed=embed)
        return

    if action.lower() == "change":
        if not outfit_id:
            await ctx.send("⚠️ Please specify an outfit ID. Use `.wardrobe list` to see available outfits.")
            return
        outfit_id = outfit_id.lower().replace(" ", "_")
        if outfit_id not in wardrobe.get("outfits", {}):
            await ctx.send(f"⚠️ Outfit '{outfit_id}' not found. Use `.wardrobe list` to see available outfits.")
            return
        wardrobe["current_outfit"] = outfit_id
        save_wardrobe(char_key, wardrobe)
        outfit = wardrobe["outfits"][outfit_id]
        embed = discord.Embed(title="✅ Outfit Changed!", color=0x00FF00)
        embed.add_field(name="Now Wearing", value=f"{outfit.get('emoji', '👗')} {outfit.get('name', outfit_id)}", inline=False)
        embed.add_field(name="Description", value=outfit.get('description', 'No description'), inline=False)
        await ctx.send(embed=embed)
        return

    if action.lower() == "add":
        await ctx.send("📝 Let's create a new outfit! Please answer the following questions.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            await ctx.send("**1/6** What's the outfit ID? (e.g., `casual_jeans`, `evening_dress`) - lowercase, use underscores")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            new_id = msg.content.lower().replace(" ", "_")
            if new_id in wardrobe.get("outfits", {}):
                await ctx.send(f"⚠️ Outfit '{new_id}' already exists. Use `.wardrobe edit` instead.")
                return
            await ctx.send("**2/6** What's the outfit name?")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            name = msg.content
            await ctx.send("**3/6** Choose an emoji for this outfit (e.g., 👗, 👙, 👔)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            emoji = msg.content
            await ctx.send("**4/6** Brief description (one line)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            description = msg.content
            await ctx.send("**5/6** Full appearance description (be detailed!)")
            msg = await bot.wait_for('message', check=check, timeout=300.0)
            appearance = msg.content
            await ctx.send("**6/6** What scene is this outfit for?")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            scene = msg.content

            wardrobe.setdefault("outfits", {})[new_id] = {
                "name": name,
                "emoji": emoji,
                "description": description,
                "appearance": appearance,
                "scene": scene,
            }
            save_wardrobe(char_key, wardrobe)

            embed = discord.Embed(title="✅ Outfit Added!", color=0x00FF00)
            embed.add_field(name="ID", value=new_id, inline=True)
            embed.add_field(name="Name", value=f"{emoji} {name}", inline=True)
            embed.add_field(name="Description", value=description, inline=False)
            await ctx.send(embed=embed)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Outfit creation cancelled.")
        return

    if action.lower() == "remove":
        if not outfit_id:
            await ctx.send("⚠️ Please specify an outfit ID to remove.")
            return
        outfit_id = outfit_id.lower().replace(" ", "_")
        if outfit_id not in wardrobe.get("outfits", {}):
            await ctx.send(f"⚠️ Outfit '{outfit_id}' not found.")
            return
        outfit_name = wardrobe["outfits"][outfit_id].get("name", outfit_id)
        del wardrobe["outfits"][outfit_id]
        if wardrobe.get("current_outfit") == outfit_id:
            wardrobe["current_outfit"] = list(wardrobe["outfits"].keys())[0] if wardrobe["outfits"] else "default"
        save_wardrobe(char_key, wardrobe)
        await ctx.send(f"✅ Removed outfit: {outfit_name}")
        return

    if action.lower() == "edit":
        if not outfit_id:
            await ctx.send("⚠️ Please specify an outfit ID to edit.")
            return
        outfit_id = outfit_id.lower().replace(" ", "_")
        if outfit_id not in wardrobe.get("outfits", {}):
            await ctx.send(f"⚠️ Outfit '{outfit_id}' not found.")
            return
        outfit = wardrobe["outfits"][outfit_id]
        embed = discord.Embed(title=f"📝 Editing: {outfit.get('name', outfit_id)}", color=0xFFAA00)
        embed.add_field(name="What to edit?", value="Reply with:\n`name` `emoji` `description` `appearance` `scene` or `cancel`", inline=False)
        await ctx.send(embed=embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            field = msg.content.lower()
            if field == "cancel":
                await ctx.send("❌ Edit cancelled.")
                return
            if field not in ["name", "emoji", "description", "appearance", "scene"]:
                await ctx.send("⚠️ Invalid field. Edit cancelled.")
                return
            await ctx.send(f"Enter new value for **{field}**:")
            msg = await bot.wait_for('message', check=check, timeout=300.0)
            outfit[field] = msg.content
            save_wardrobe(char_key, wardrobe)
            await ctx.send(f"✅ Updated {field} for outfit: {outfit.get('name', outfit_id)}")
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Edit cancelled.")
        return

    await ctx.send("⚠️ Invalid action. Use: `list`, `change`, `add`, `remove`, or `edit`")
