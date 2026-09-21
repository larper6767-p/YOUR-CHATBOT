"""Small cross-cutting helpers: scope keys, token budgeting, reply cleanup."""
from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from typing import Awaitable, Callable

import discord

from .config import ENCODER, RESPONSE_TOKEN_BUDGET

DISCORD_MESSAGE_LIMIT = 1900


# ─────────────────────────────────────────────
#  Scope keys
# ─────────────────────────────────────────────

def scope_key_from_message(msg: discord.Message) -> str:
    """Return the activation scope (a DM user or a whole guild) for a message."""
    if isinstance(msg.channel, discord.DMChannel):
        return f"dm_{msg.author.id}"
    return f"guild_{msg.guild.id}" if msg.guild else f"dm_{msg.author.id}"


def scope_key_from_interaction(ix: discord.Interaction) -> str:
    """Return the activation scope (a DM user or a whole guild) for an interaction."""
    if isinstance(ix.channel, discord.DMChannel):
        return f"dm_{ix.user.id}"
    return f"guild_{ix.guild.id}" if ix.guild else f"dm_{ix.user.id}"


# ─────────────────────────────────────────────
#  Token budgeting
# ─────────────────────────────────────────────

def count_tokens_for_messages(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += len(ENCODER.encode(msg.get("content", "")))
    total += len(messages) * 4
    return total


def trim_conversation(history: list[dict], system_prompt: str, max_tokens: int) -> list[dict]:
    """Drop the oldest messages until the prompt fits within the token budget."""
    if not history:
        return history
    full = [{"role": "system", "content": system_prompt}] + history
    if count_tokens_for_messages(full) <= max_tokens - RESPONSE_TOKEN_BUDGET:
        return history
    trimmed = history.copy()
    while trimmed:
        test = [{"role": "system", "content": system_prompt}] + trimmed
        if count_tokens_for_messages(test) <= max_tokens - RESPONSE_TOKEN_BUDGET:
            break
        trimmed.pop(0)
    return trimmed


# ─────────────────────────────────────────────
#  Sending
# ─────────────────────────────────────────────

async def send_reply(reply_fn: Callable[[str], Awaitable], chunk_fn: Callable[[str], Awaitable], reply: str):
    """Send a reply, splitting it into chunks if it exceeds Discord's limit.

    Short replies use ``reply_fn`` (a threaded reply); long ones are split and
    sent through ``chunk_fn`` to avoid re-pinging on every chunk.
    """
    if len(reply) > DISCORD_MESSAGE_LIMIT:
        for i in range(0, len(reply), DISCORD_MESSAGE_LIMIT):
            await chunk_fn(reply[i:i + DISCORD_MESSAGE_LIMIT])
            await asyncio.sleep(0.5)
    else:
        await reply_fn(reply)


# ─────────────────────────────────────────────
#  Content helpers
# ─────────────────────────────────────────────

def check_safeword(text: str, char: dict) -> bool:
    safeword = char.get("consent", {}).get("safeword", "starlight")
    return safeword.lower() in text.lower()


def get_scene_detail(scene: dict) -> str:
    variants = scene.get("detail_variants", [])
    if not variants:
        return ""
    return random.choice(variants)


def detect_and_fix_repetition(text: str, window_size: int = 50, threshold: int = 8) -> str:
    """Trim degenerate repetition produced by the model."""
    words = text.split()
    if len(words) < window_size:
        return text
    last_words = words[-window_size:]
    word_counts = defaultdict(int)
    for word in last_words:
        clean_word = word.lower().strip('.,!?;:"\'-')
        if clean_word:
            word_counts[clean_word] += 1
    if not word_counts:
        return text
    max_count = max(word_counts.values())
    if max_count > threshold:
        for i in range(len(words) - window_size, max(0, len(words) - 200), -1):
            check_words = words[i:]
            check_counts = defaultdict(int)
            for word in check_words:
                clean = word.lower().strip('.,!?;:"\'-')
                if clean:
                    check_counts[clean] += 1
            if check_counts and max(check_counts.values()) < threshold // 2:
                truncated = ' '.join(words[:i])
                if truncated:
                    return truncated
        cutoff = int(len(words) * 0.75)
        return ' '.join(words[:cutoff])
    return text
