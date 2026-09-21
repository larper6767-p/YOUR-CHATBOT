"""Mood, long-term memory extraction, retrieval, and time awareness."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import MEMORY_SUMMARY_MAX_CHARS, agnes_client
from .storage import conversation_histories, get_or_create_profile, update_profile


# ─────────────────────────────────────────────
#  Mood system
# ─────────────────────────────────────────────

async def update_mood(cid: str, user_id: int, char: dict):
    history = conversation_histories.get(cid, [])
    if not history:
        return
    profile = get_or_create_profile(user_id)
    old_mood = profile.get("mood", {})

    transcript = "\n".join(
        f"{m.get('role')}: {(m.get('content') or '')[:200]}"
        for m in history[-16:] if m.get("role") in ("user", "assistant")
    )
    if not transcript.strip():
        return

    prompt = (
        f"Current mood scores: affection={old_mood.get('affection')}, "
        f"energy={old_mood.get('energy')}, playfulness={old_mood.get('playfulness')}.\n\n"
        f"Recent conversation:\n{transcript}\n\n"
        "Update the character's mood on three axes (affection, energy, playfulness), each 0.0-1.0. "
        "Move scores gradually (max ±0.25). If the user was kind, raise affection. "
        "If they were distant or left a gap, lower it slightly. "
        "Return ONLY compact JSON: {\"affection\": x, \"energy\": y, \"playfulness\": z}"
    )

    model_name = char.get("settings", {}).get("model", {}).get("name", "agnes-3.0-flash")
    try:
        resp = await agnes_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=120,
            temperature=0.3,
        )
        raw = (resp.choices[0].message.content or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1]) if start != -1 else {}
        new_mood = {
            "affection": float(max(0.0, min(1.0, data.get("affection", old_mood.get("affection", 0.6))))),
            "energy": float(max(0.0, min(1.0, data.get("energy", old_mood.get("energy", 0.7))))),
            "playfulness": float(max(0.0, min(1.0, data.get("playfulness", old_mood.get("playfulness", 0.7))))),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        update_profile(user_id, mood=new_mood)
        print(f"💗  Mood updated for {user_id}: {new_mood}")
    except Exception as e:
        print(f"⚠️  Mood update failed: {e}")


# ─────────────────────────────────────────────
#  Structured long-term memory
# ─────────────────────────────────────────────

async def extract_memory_facts(cid: str, user_id: int, char: dict):
    history = conversation_histories.get(cid, [])
    if not history:
        return
    transcript = "\n".join(
        f"{m.get('role')}: {(m.get('content') or '')[:250]}"
        for m in history[-20:] if m.get("role") in ("user", "assistant")
    )
    if not transcript.strip():
        return

    profile = get_or_create_profile(user_id)
    existing = profile.get("memory_facts", []) or []
    existing_facts_text = "\n".join(f"- {f.get('fact', '')}" for f in existing[-30:]) or "(none)"

    prompt = (
        f"Facts already stored:\n{existing_facts_text}\n\n"
        f"New transcript:\n{transcript}\n\n"
        "Extract 0-3 NEW durable facts about the user (preferences, life details, "
        "recurring topics, things they told you about themselves). "
        "Skip ephemeral chit-chat, and skip facts already stored. "
        "Return ONLY JSON: {\"facts\": [{\"fact\": \"...\", \"tags\": [\"...\"]}]}. "
        "If nothing new, return {\"facts\": []}."
    )

    model_name = char.get("settings", {}).get("model", {}).get("name", "agnes-3.0-flash")
    try:
        resp = await agnes_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": prompt}],
            max_tokens=400,
            temperature=0.2,
        )
        raw = (resp.choices[0].message.content or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1]) if start != -1 else {"facts": []}

        new_items = []
        for f in data.get("facts", [])[:3]:
            fact = (f.get("fact") or "").strip()
            if not fact:
                continue
            new_items.append({
                "fact": fact[:300],
                "tags": [t.lower()[:24] for t in f.get("tags", [])][:6],
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        if new_items:
            existing.extend(new_items)
            update_profile(user_id, memory_facts=existing[-200:])
            print(f"🧩  +{len(new_items)} facts stored for {user_id}")
    except Exception as e:
        print(f"⚠️  Fact extraction failed: {e}")


def retrieve_relevant_facts(profile: dict, user_text: str, k: int = 8) -> str:
    facts = profile.get("memory_facts", []) or []
    if not facts:
        return ""
    tokens = {w.lower().strip(".,!?;:\"'") for w in user_text.split() if len(w) > 2}

    def score(f):
        tag_hits = sum(1 for t in f.get("tags", []) if t in tokens)
        fact_hits = sum(1 for w in tokens if w in f.get("fact", "").lower())
        return tag_hits * 2 + fact_hits

    ranked = sorted(facts, key=score, reverse=True)[:k]
    if not any(score(f) > 0 for f in ranked):
        ranked = facts[-k:]
    lines = "\n".join(f"- {f['fact']}" for f in ranked)
    return f"\n\n[THINGS YOU REMEMBER ABOUT THIS PERSON]\n{lines}"


# ─────────────────────────────────────────────
#  Time awareness
# ─────────────────────────────────────────────

def time_context(profile: dict) -> str:
    parts = []

    offset_min = profile.get("timezone_offset", 0) or 0
    user_now = datetime.now(timezone.utc) + timedelta(minutes=offset_min)
    hour = user_now.hour
    if 5 <= hour < 12:
        tod = "morning"
    elif 12 <= hour < 17:
        tod = "afternoon"
    elif 17 <= hour < 22:
        tod = "evening"
    else:
        tod = "late night"
    parts.append(f"It's {tod} ({user_now.strftime('%H:%M')}) for the user.")
    if hour >= 23 or hour < 5:
        parts.append("They're up very late — maybe comment on it.")

    last = profile.get("last_interaction", "")
    if last:
        try:
            dt = datetime.fromisoformat(last)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            secs = (datetime.now(timezone.utc) - dt).total_seconds()
            if secs > 60 * 60 * 24 * 3:
                parts.append(f"It's been {int(secs // 86400)} days since you last talked.")
            elif secs > 60 * 60 * 24:
                parts.append(f"It's been about {int(secs // 86400)} day(s) since you last talked.")
            elif secs > 60 * 60 * 6:
                parts.append(f"It's been about {int(secs // 3600)} hours since you last talked.")
            elif secs > 60 * 90:
                parts.append("It's been a couple of hours since your last exchange.")
        except Exception:
            pass

    if not parts:
        return ""
    return "\n\n[TIME CONTEXT]\n" + "\n".join(f"- {p}" for p in parts)


# ─────────────────────────────────────────────
#  Rolling summary
# ─────────────────────────────────────────────

async def summarize_conversation(cid: str, user_id: int, char: dict):
    history = conversation_histories.get(cid, [])
    if not history:
        return

    profile = get_or_create_profile(user_id)
    existing_summary = profile.get("memory_summary", "")

    transcript_parts = []
    for msg in history[-30:]:
        role = msg.get("role", "")
        content = (msg.get("content") or "")[:300]
        if role in ("user", "assistant"):
            transcript_parts.append(f"{role}: {content}")
    transcript = "\n".join(transcript_parts)
    if not transcript.strip():
        return

    model_name = char.get("settings", {}).get("model", {}).get("name", "agnes-3.0-flash")

    prompt_parts = []
    if existing_summary:
        prompt_parts.append(f"PREVIOUS SUMMARY:\n{existing_summary}")
    prompt_parts.append(f"NEW CONVERSATION EXCERPT:\n{transcript}")
    prompt_parts.append(
        "Write a 2-4 sentence factual summary of the conversation so far. "
        "Include interests mentioned, ongoing bits, and user preferences expressed. "
        "Be concise, under 300 words."
    )

    try:
        response = await agnes_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": "You are a memory summarizer. " + "\n".join(prompt_parts)}],
            max_tokens=600,
            temperature=0.3,
        )
        new_summary = (response.choices[0].message.content or "").strip()
        if new_summary:
            if len(new_summary) > MEMORY_SUMMARY_MAX_CHARS:
                new_summary = new_summary[:MEMORY_SUMMARY_MAX_CHARS]
            update_profile(user_id, memory_summary=new_summary)
            print(f"🧠  Memory summary updated for user {user_id} ({cid})")
    except Exception as e:
        print(f"❌  Memory summarization failed for user {user_id}: {e}")
