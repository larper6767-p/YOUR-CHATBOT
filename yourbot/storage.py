"""In-memory state and JSON persistence.

All mutable runtime state lives here. Other modules import the dict objects
directly (e.g. ``from .storage import conversation_histories``) and mutate them
in place — nothing ever rebinds these names, so the shared references stay valid.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from .config import (
    ACTIVE_FILE,
    BACKUP_FILE,
    CHARACTERS_DIR,
    DEFAULT_PROFILE_SCHEMA,
    DEFAULT_SCENES,
    DEFAULT_WARDROBE,
    HISTORY_FILE,
    PROFILES_FILE,
)


# ─────────────────────────────────────────────
#  Character paths (one folder per character)
# ─────────────────────────────────────────────

def _char_dir(key: str) -> str:
    """Return the path to a character's own folder."""
    return os.path.join(CHARACTERS_DIR, key)


def _char_file(key: str, suffix: str = "") -> str:
    """Return the path to a character file, e.g. marin.json or marin_wardrobe.json."""
    return os.path.join(_char_dir(key), f"{key}{suffix}.json")


# ─────────────────────────────────────────────
#  Characters
# ─────────────────────────────────────────────

def _default_character() -> dict:
    return {
        "name": "Bot",
        "title": "Assistant",
        "systemPrompt": "You are a helpful assistant.",
        "settings": {
            "model": {"name": "agnes-3.0-flash"},
            "generation": {"temperature": 0.7, "max_tokens": 2000},
            "discord_bot": {"cooldown_seconds": 2, "status_message": "Ready!"},
            "relationship": {"familiar_at": 20, "close_at": 100},
        },
    }


def load_all_characters() -> dict:
    """Load every character from its own folder in characters/."""
    out: dict = {}
    os.makedirs(CHARACTERS_DIR, exist_ok=True)

    if os.path.isdir(CHARACTERS_DIR):
        for entry in sorted(os.listdir(CHARACTERS_DIR)):
            # skip non-directories (back-compat for old flat files)
            if not os.path.isdir(os.path.join(CHARACTERS_DIR, entry)):
                continue
            char_file = os.path.join(CHARACTERS_DIR, entry, f"{entry}.json")
            if not os.path.exists(char_file):
                continue
            try:
                with open(char_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                out[entry] = data
                print(f"✅  Loaded character: {entry} ({data.get('name', '?')})")
            except Exception as e:
                print(f"⚠️  Failed to load character {entry}: {e}")

    if not out:
        print("⚠️  No characters found — using built-in default.")
        out["default"] = _default_character()
    return out


characters: dict = load_all_characters()


def _load_active() -> dict:
    if os.path.exists(ACTIVE_FILE):
        try:
            with open(ACTIVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_active():
    try:
        with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(active_characters, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌  Could not save active_characters: {e}")


active_characters: dict = _load_active()  # scope_key -> character key


def get_character_key(scope_key: str) -> str:
    key = active_characters.get(scope_key)
    if key and key in characters:
        return key
    key = active_characters.get("default")
    if key and key in characters:
        return key
    return next(iter(characters.keys()))


def get_character(scope_key: str) -> dict:
    return characters[get_character_key(scope_key)]


def save_character(key: str, data: dict):
    characters[key] = data
    os.makedirs(_char_dir(key), exist_ok=True)
    try:
        with open(_char_file(key), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌  Failed to save character {key}: {e}")


# ─────────────────────────────────────────────
#  Conversation history
# ─────────────────────────────────────────────

def load_history() -> dict:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("⚠️  Corrupted history file, trying backup...")
            if os.path.exists(BACKUP_FILE):
                try:
                    with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
    return {}


def save_history(histories: dict):
    try:
        if os.path.exists(HISTORY_FILE):
            with open(BACKUP_FILE, "w", encoding="utf-8") as f:
                with open(HISTORY_FILE, "r", encoding="utf-8") as original:
                    f.write(original.read())
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(histories, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌  Error saving history: {e}")


conversation_histories: dict = load_history()


# ─────────────────────────────────────────────
#  Per-character wardrobe & scenes
# ─────────────────────────────────────────────

_wardrobe_cache: dict[str, dict] = {}
_scenes_cache: dict[str, dict] = {}


def load_wardrobe(key: str) -> dict:
    if key in _wardrobe_cache:
        return _wardrobe_cache[key]
    path = _char_file(key, "_wardrobe")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _wardrobe_cache[key] = data
            return data
        except Exception as e:
            print(f"⚠️  Error loading wardrobe for {key}: {e}")
    data = json.loads(json.dumps(DEFAULT_WARDROBE))
    _wardrobe_cache[key] = data
    return data


def save_wardrobe(key: str, wardrobe: dict):
    _wardrobe_cache[key] = wardrobe
    os.makedirs(_char_dir(key), exist_ok=True)
    try:
        with open(_char_file(key, "_wardrobe"), "w", encoding="utf-8") as f:
            json.dump(wardrobe, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"❌  Error saving wardrobe for {key}: {e}")


def load_scenes(key: str) -> dict:
    if key in _scenes_cache:
        return _scenes_cache[key]
    path = _char_file(key, "_scenes")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _scenes_cache[key] = data
            return data
        except Exception as e:
            print(f"⚠️  Error loading scenes for {key}: {e}")
    data = json.loads(json.dumps(DEFAULT_SCENES))
    _scenes_cache[key] = data
    return data


def save_scenes(key: str, scenes: dict):
    _scenes_cache[key] = scenes
    os.makedirs(_char_dir(key), exist_ok=True)
    try:
        with open(_char_file(key, "_scenes"), "w", encoding="utf-8") as f:
            json.dump(scenes, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"❌  Error saving scenes for {key}: {e}")


# ─────────────────────────────────────────────
#  Per-user profiles
# ─────────────────────────────────────────────

def load_profiles() -> dict:
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Error loading user profiles: {e}")
    return {}


def save_profiles(profiles: dict):
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"❌  Error saving user profiles: {e}")


user_profiles: dict = load_profiles()


def get_or_create_profile(user_id: int) -> dict:
    key = str(user_id)
    if key not in user_profiles:
        user_profiles[key] = json.loads(json.dumps(DEFAULT_PROFILE_SCHEMA))
        user_profiles[key]["last_interaction"] = datetime.now(timezone.utc).isoformat()
        save_profiles(user_profiles)
    profile = user_profiles[key]
    for field, default in DEFAULT_PROFILE_SCHEMA.items():
        if field not in profile:
            profile[field] = json.loads(json.dumps(default))
    # ensure nested mood dict is complete
    mood = profile.setdefault("mood", {})
    for field, default in DEFAULT_PROFILE_SCHEMA["mood"].items():
        if field not in mood:
            mood[field] = default
    return profile


def update_profile(user_id: int, **fields):
    profile = get_or_create_profile(user_id)
    for field, value in fields.items():
        if field in DEFAULT_PROFILE_SCHEMA:
            profile[field] = value
    save_profiles(user_profiles)


def get_relationship_stage(message_count: int, char: dict) -> str:
    thresholds = char.get("settings", {}).get("relationship", {}) or {}
    familiar_at = thresholds.get("familiar_at", 20)
    close_at = thresholds.get("close_at", 100)
    if message_count >= close_at:
        return "close"
    elif message_count >= familiar_at:
        return "familiar"
    return "new"


def is_verified(user_id: int) -> bool:
    profile = user_profiles.get(str(user_id))
    return bool(profile and profile.get("verified"))


# ─────────────────────────────────────────────
#  Runtime-only state
# ─────────────────────────────────────────────

# Per-user cooldown tracking (not persisted).
user_last_message = defaultdict(lambda: datetime.min.replace(tzinfo=timezone.utc))
