"""Central configuration: paths, environment, API clients, and shared constants.

This module performs import-time setup only (no network calls), so every other
module can import from it without creating circular dependencies.
"""
from __future__ import annotations

import os
import sys

import discord
import tiktoken
from discord.ext import commands
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Windows console fix: force stdout/stderr to UTF-8 so emoji logging (✅ ❌ 🎨)
# doesn't crash with UnicodeEncodeError on cp1252 consoles.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# ─────────────────────────────────────────────
#  Paths
# ─────────────────────────────────────────────
# BASE_DIR is the project root (the parent directory of this package).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CHARACTERS_DIR = os.path.join(DATA_DIR, "characters")
HISTORIES_DIR = os.path.join(DATA_DIR, "histories")
PROFILES_DIR = os.path.join(DATA_DIR, "profiles")

ACTIVE_FILE = os.path.join(DATA_DIR, "active_characters.json")
HISTORY_FILE = os.path.join(HISTORIES_DIR, "conversation_history.json")
BACKUP_FILE = os.path.join(HISTORIES_DIR, "conversation_history_backup.json")
PROFILES_FILE = os.path.join(PROFILES_DIR, "user_profiles.json")

# ─────────────────────────────────────────────
#  Environment & clients
# ─────────────────────────────────────────────
load_dotenv(os.path.join(BASE_DIR, ".env"))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
AGNES_API_KEY = os.getenv("AGNES_API_KEY")

if not DISCORD_TOKEN:
    raise ValueError("Missing DISCORD_TOKEN in .env")
if not AGNES_API_KEY:
    raise ValueError("Missing AGNES_API_KEY in .env")

agnes_client = AsyncOpenAI(
    api_key=AGNES_API_KEY,
    base_url="https://apihub.agnes-ai.com/v1",
)

intents = discord.Intents.default()
intents.message_content = True
intents.presences = True
bot = commands.Bot(command_prefix=".", intents=intents)

# ─────────────────────────────────────────────
#  Context / token settings
# ─────────────────────────────────────────────
ENCODER = tiktoken.get_encoding("cl100k_base")
RESPONSE_TOKEN_BUDGET = 1000
DEFAULT_MAX_CONTEXT_TOKENS = 60000
MEMORY_SUMMARY_INTERVAL = 15
MEMORY_SUMMARY_MAX_CHARS = 500

# ─────────────────────────────────────────────
#  Default data schemas
# ─────────────────────────────────────────────
DEFAULT_PROFILE_SCHEMA = {
    "nickname": None,
    "relationship_stage": "new",
    "tone_preference": "default",
    "recurring_topics": [],
    "last_scene": None,
    "memory_summary": "",
    "memory_facts": [],            # structured long-term memory
    "timezone_offset": 0,          # minutes from UTC
    "mood": {
        "affection": 0.6,
        "energy": 0.7,
        "playfulness": 0.7,
        "last_updated": "",
    },
    "message_count": 0,
    "last_interaction": "",
    "verified": False,
}

MOOD_DESCRIPTORS = {
    "affection": [
        (0.0, "guarded and distant"),
        (0.35, "polite but reserved"),
        (0.6, "warm and familiar"),
        (0.8, "openly affectionate, clingy"),
    ],
    "energy": [
        (0.0, "drained, low-energy"),
        (0.35, "calm and quiet"),
        (0.6, "normal"),
        (0.8, "bubbly and wired"),
    ],
    "playfulness": [
        (0.0, "serious, no teasing"),
        (0.35, "mildly playful"),
        (0.6, "teasing"),
        (0.8, "relentlessly flirty"),
    ],
}

DEFAULT_WARDROBE = {
    "outfits": {
        "poolside_bikini": {
            "name": "Poolside Bikini",
            "description": "Shiny black micro bikini with red flame patterns",
            "emoji": "👙",
            "appearance": "Black micro bikini with red flame patterns, body glistening with water",
            "scene": "poolside",
        }
    },
    "current_outfit": "poolside_bikini",
}

DEFAULT_SCENES = {
    "scenes": {
        "poolside": {
            "name": "Poolside",
            "description": "A sunny pool area with lounge chairs and sparkling water",
            "emoji": "🏊",
            "atmosphere": "The sparkling blue pool glistens under the sunlight. Lounge chairs are scattered around. The scent of chlorine mixes with sunscreen. It's warm and inviting.",
            "tags": ["outdoor", "water", "summer"],
        }
    },
    "current_scene": "poolside",
}

AGE_VERIFY_PROMPT = (
    "🔞 **Age verification required**\n\n"
    "I need you to confirm you are 18+ before we continue.\n"
    "Run `/verify` (or `.verify`) to confirm your age and unlock the bot."
)
