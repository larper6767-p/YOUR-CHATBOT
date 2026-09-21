"""Model calls and the shared chat-turn pipeline."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import cast

from openai.types.chat import ChatCompletionMessageParam

from .config import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    MEMORY_SUMMARY_INTERVAL,
    agnes_client,
)
from .memory import extract_memory_facts, summarize_conversation, update_mood
from .prompts import build_system_prompt
from .storage import (
    conversation_histories,
    get_or_create_profile,
    get_relationship_stage,
    save_history,
    update_profile,
)
from .utils import detect_and_fix_repetition, trim_conversation


async def agnes_chat_create(messages: list, settings: dict, char: dict, max_retries: int = 2) -> str | None:
    """Call the chat completion API with exponential-backoff retries."""
    model_name = char.get("settings", {}).get("model", {}).get("name", "agnes-3.0-flash")

    for attempt in range(max_retries + 1):
        try:
            response = await agnes_client.chat.completions.create(
                model=model_name,
                messages=cast(list[ChatCompletionMessageParam], messages),
                max_tokens=settings.get("max_tokens", 8000),
                temperature=settings.get("temperature", 0.85),
                top_p=settings.get("top_p", 0.95),
                frequency_penalty=settings.get("frequency_penalty", 0.7),
                presence_penalty=settings.get("presence_penalty", 0.7),
            )
            reply = response.choices[0].message.content or ""
            if not reply.strip():
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                return None
            return reply
        except Exception:
            if attempt < max_retries:
                await asyncio.sleep(1.0 * (2 ** attempt))
                continue
            raise


async def process_chat_turn(
    cid: str,
    user_id: int,
    user_text: str,
    char: dict,
    char_key: str,
    activity_name: str | None = None,
) -> str | None:
    """Record a user message, refresh memory, and generate a reply.

    Shared by the ``on_message`` listener and the ``/chat`` slash command.
    Returns the assistant reply (already appended to history) or ``None`` when
    the model produced an empty response. Exceptions from the API propagate to
    the caller, matching the original single-file behaviour.
    """
    if cid not in conversation_histories:
        conversation_histories[cid] = []
    conversation_histories[cid].append({"role": "user", "content": user_text})

    profile = get_or_create_profile(user_id)
    new_count = profile.get("message_count", 0) + 1
    update_profile(
        user_id,
        message_count=new_count,
        last_interaction=datetime.now(timezone.utc).isoformat(),
        relationship_stage=get_relationship_stage(new_count, char),
    )

    if new_count % MEMORY_SUMMARY_INTERVAL == 0:
        await summarize_conversation(cid, user_id, char)
        await update_mood(cid, user_id, char)
        await extract_memory_facts(cid, user_id, char)

    # refresh profile after potential updates
    profile = get_or_create_profile(user_id)
    system_prompt = build_system_prompt(char, profile, user_text, cid, char_key)

    if activity_name:
        system_prompt += f"\n\n[NOTE: user's Discord status shows activity '{activity_name}']"

    max_ctx = char.get("settings", {}).get("generation", {}).get("max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS)
    trimmed = trim_conversation(conversation_histories[cid], system_prompt, max_ctx)
    messages = [{"role": "system", "content": system_prompt}] + trimmed

    settings = char.get("settings", {}).get("generation", {})
    reply = await agnes_chat_create(messages, settings, char)
    if reply is None:
        return None

    reply = detect_and_fix_repetition(reply)
    conversation_histories[cid].append({"role": "assistant", "content": reply})
    save_history(conversation_histories)
    return reply
