"""Entry point for the Yourchatbot Discord bot.

Run from the project root with::

    python bot.py
"""
from __future__ import annotations

import os

# Importing these modules wires the application together: ``config`` builds the
# shared clients, the command modules register prefix and slash commands, and
# ``events`` registers the gateway listeners and error handlers.
from yourbot import config, events  # noqa: F401
from yourbot.commands import (  # noqa: F401
    character,
    help as help_commands,
    personality,
    scene,
    slash,
    user,
    wardrobe,
)
from yourbot.config import (
    CHARACTERS_DIR,
    DISCORD_TOKEN,
    HISTORY_FILE,
    PROFILES_FILE,
    bot,
)


if __name__ == "__main__":
    print(f"🚀  Starting bot from: {os.path.abspath(__file__)}")
    print(f"📁  Characters dir: {CHARACTERS_DIR}")
    print(f"📁  History file: {HISTORY_FILE}")
    print(f"📁  Profiles file: {PROFILES_FILE}")
    bot.run(DISCORD_TOKEN)
