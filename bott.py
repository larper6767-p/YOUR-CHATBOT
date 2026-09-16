
import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
import json
import os
import io
from dotenv import load_dotenv
import tiktoken
import asyncio
import aiohttp
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import cast

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

#  Load personality config

def load_personality():
    personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
    try:
        with open(personality_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"✅  Loaded personality: {data.get('name', 'Unknown')}")
            return data
    except FileNotFoundError:
        print("⚠️  personality.json not found – bot may not work correctly.")
        return {
            "name": "Bot",
            "systemPrompt": "You are a helpful assistant.",
            "settings": {
                "generation": {
                    "temperature": 0.7,
                    "max_tokens": 2000
                }
            }
        }
    except json.JSONDecodeError as e:
        print(f"❌  Error parsing personality.json: {e}")
        raise

personality = load_personality()

#  Clients

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


#  Context management

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "conversation_history.json")
BACKUP_FILE = os.path.join(os.path.dirname(__file__), "conversation_history_backup.json")

# Maximum tokens for the whole context - load from personality.json or use defaults
MAX_CONTEXT_TOKENS = personality.get("settings", {}).get("generation", {}).get("max_context_tokens", 60000)
RESPONSE_TOKEN_BUDGET = 1000

ENCODER = tiktoken.get_encoding("cl100k_base")

# Rate limiting - load from personality.json or use defaults
user_last_message = defaultdict(lambda: datetime.min.replace(tzinfo=timezone.utc))
COOLDOWN_SECONDS = personality.get("settings", {}).get("discord_bot", {}).get("cooldown_seconds", 2)

def count_tokens_for_messages(messages: list[dict]) -> int:
    """Count tokens for a list of messages."""
    total = 0
    for msg in messages:
        total += len(ENCODER.encode(msg.get("content", "")))
    total += len(messages) * 4  # overhead
    return total

def trim_conversation(history: list[dict], system_prompt: str, max_tokens: int = MAX_CONTEXT_TOKENS) -> list[dict]:
    """Drop oldest messages until system + history fits within max_tokens."""
    if not history:
        return history

    full = [{"role": "system", "content": system_prompt}] + history
    current = count_tokens_for_messages(full)

    if current <= max_tokens - RESPONSE_TOKEN_BUDGET:
        return history

    trimmed = history.copy()
    while trimmed:
        test = [{"role": "system", "content": system_prompt}] + trimmed
        if count_tokens_for_messages(test) <= max_tokens - RESPONSE_TOKEN_BUDGET:
            break
        trimmed.pop(0)
    return trimmed

def load_history() -> dict:
    """Load saved conversation histories."""
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
    """Save conversation histories to disk with backup."""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(BACKUP_FILE, "w", encoding="utf-8") as f:
                with open(HISTORY_FILE, "r", encoding="utf-8") as original:
                    f.write(original.read())
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(histories, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"❌  Error saving history: {e}")


conversation_histories = load_history()

# ─────────────────────────────────────────────
#  Wardrobe & Scene Management
# ─────────────────────────────────────────────
WARDROBE_FILE = os.path.join(os.path.dirname(__file__), "wardrobe.json")
SCENES_FILE = os.path.join(os.path.dirname(__file__), "scenes.json")

def load_wardrobe() -> dict:
    """Load wardrobe data."""
    if os.path.exists(WARDROBE_FILE):
        try:
            with open(WARDROBE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Error loading wardrobe: {e}")
    # Default wardrobe
    return {
        "outfits": {
            "poolside_bikini": {
                "name": "Poolside Bikini",
                "description": "Shiny black micro bikini with red flame patterns",
                "emoji": "👙",
                "appearance": "Black micro bikini with red flame patterns, body glistening with water",
                "scene": "poolside"
            }
        },
        "current_outfit": "poolside_bikini"
    }

def save_wardrobe(wardrobe: dict):
    """Save wardrobe data."""
    try:
        with open(WARDROBE_FILE, "w", encoding="utf-8") as f:
            json.dump(wardrobe, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"❌  Error saving wardrobe: {e}")

def load_scenes() -> dict:
    """Load scenes data."""
    if os.path.exists(SCENES_FILE):
        try:
            with open(SCENES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Error loading scenes: {e}")
    # Default scenes
    return {
        "scenes": {
            "poolside": {
                "name": "Poolside",
                "description": "A sunny pool area with lounge chairs and sparkling water",
                "emoji": "🏊",
                "atmosphere": "The sparkling blue pool glistens under the sunlight. Lounge chairs are scattered around. The scent of chlorine mixes with sunscreen. It's warm and inviting.",
                "tags": ["outdoor", "water", "summer"]
            }
        },
        "current_scene": "poolside"
    }

def save_scenes(scenes: dict):
    """Save scenes data."""
    try:
        with open(SCENES_FILE, "w", encoding="utf-8") as f:
            json.dump(scenes, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"❌  Error saving scenes: {e}")

wardrobe = load_wardrobe()
scenes = load_scenes()

# ─────────────────────────────────────────────
#  Per-User Profile Store
# ─────────────────────────────────────────────
PROFILES_FILE = os.path.join(os.path.dirname(__file__), "user_profiles.json")
DEFAULT_PROFILE_SCHEMA = {
    "nickname": None,
    "relationship_stage": "new",
    "tone_preference": "default",
    "recurring_topics": [],
    "last_scene": None,
    "memory_summary": "",
    "message_count": 0,
    "last_interaction": "",
    "verified": False
}
# Relationship stage thresholds (configurable via personality.json settings.relationship)
_RELATIONSHIP_THRESHOLDS = personality.get("settings", {}).get("relationship", {
    "familiar_at": 20,
    "close_at": 100
})


def load_profiles() -> dict:
    """Load per-user profiles."""
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Error loading user profiles: {e}")
    return {}


def save_profiles(profiles: dict):
    """Save per-user profiles to disk."""
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"❌  Error saving user profiles: {e}")


user_profiles = load_profiles()


def get_or_create_profile(user_id: int) -> dict:
    """Get the profile for a user, creating it if it doesn't exist."""
    key = str(user_id)
    if key not in user_profiles:
        user_profiles[key] = dict(DEFAULT_PROFILE_SCHEMA)
        user_profiles[key]["last_interaction"] = datetime.now(timezone.utc).isoformat()
        save_profiles(user_profiles)
    profile = user_profiles[key]
    # Fill in any missing keys (schema evolution)
    for field, default in DEFAULT_PROFILE_SCHEMA.items():
        if field not in profile:
            profile[field] = default
    return profile


def update_profile(user_id: int, **fields):
    """Update specific fields on a user's profile and save."""
    profile = get_or_create_profile(user_id)
    for field, value in fields.items():
        if field in DEFAULT_PROFILE_SCHEMA:
            profile[field] = value
    save_profiles(user_profiles)


def get_relationship_stage(message_count: int) -> str:
    """Determine relationship stage from message count thresholds."""
    familiar_at = _RELATIONSHIP_THRESHOLDS.get("familiar_at", 20)
    close_at = _RELATIONSHIP_THRESHOLDS.get("close_at", 100)
    if message_count >= close_at:
        return "close"
    elif message_count >= familiar_at:
        return "familiar"
    return "new"


MEMORY_SUMMARY_INTERVAL = 15
MEMORY_SUMMARY_MAX_CHARS = 500


async def summarize_conversation(cid: str, user_id: int):
    """Summarize the conversation history for a cid, merging with existing memory_summary."""
    history = conversation_histories.get(cid, [])
    if not history:
        return

    profile = get_or_create_profile(user_id)
    existing_summary = profile.get("memory_summary", "")

    # Build a transcript from recent history
    transcript_parts = []
    for msg in history[-30:]:  # cap the input to avoid huge prompts
        role = msg.get("role", "")
        content = (msg.get("content") or "")[:300]
        if role in ("user", "assistant"):
            transcript_parts.append(f"{role}: {content}")
    transcript = "\n".join(transcript_parts)
    if not transcript.strip():
        return

    model_name = personality.get("settings", {}).get("model", {}).get("name", "agnes-3.0-flash")

    summary_prompt_parts = []
    if existing_summary:
        summary_prompt_parts.append(f"PREVIOUS SUMMARY:\n{existing_summary}")
    summary_prompt_parts.append(f"NEW CONVERSATION EXCERPT:\n{transcript}")
    summary_prompt_parts.append(
        "Write a 2-4 sentence factual summary of the conversation so far. "
        "Include interests mentioned, ongoing bits, and user preferences expressed. "
        "Be concise, under 300 words."
    )

    try:
        response = await agnes_client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": "You are a memory summarizer. " + "\n".join(summary_prompt_parts)}],
            max_tokens=600,
            temperature=0.3,
        )
        new_summary = (response.choices[0].message.content or "").strip()
        if new_summary:
            # Cap to MEMORY_SUMMARY_MAX_CHARS
            if len(new_summary) > MEMORY_SUMMARY_MAX_CHARS:
                new_summary = new_summary[:MEMORY_SUMMARY_MAX_CHARS]
            update_profile(user_id, memory_summary=new_summary)
            print(f"🧠  Memory summary updated for user {user_id} ({cid})")
    except Exception as e:
        print(f"❌  Memory summarization failed for user {user_id}: {e}")


# ─────────────────────────────────────────────
#  LLM Call with Retry
# ─────────────────────────────────────────────


async def agnes_chat_create(messages: list, settings: dict, max_retries: int = 2) -> str | None:
    """Call agnes_client with exponential-backoff retry. Returns reply string or None."""
    model_name = personality.get("settings", {}).get("model", {}).get("name", "agnes-3.0-flash")

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
            # Retry once if reply is empty/whitespace
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


# ─────────────────────────────────────────────
#  Scene Detail Variants
# ─────────────────────────────────────────────

def get_scene_detail(scene: dict) -> str:
    """Pick a random detail variant for the scene, if any."""
    variants = scene.get("detail_variants", [])
    if not variants:
        return ""
    return random.choice(variants)


# ─────────────────────────────────────────────
#  Age-Verification Gate
# ─────────────────────────────────────────────

AGE_VERIFY_PROMPT = (
    "🔞 **Age verification required**\n\n"
    "I need you to confirm you are 18+ before we continue.\n"
    "Run `/verify` (or `.verify`) to confirm your age and unlock the bot."
)


def is_verified(user_id: int) -> bool:
    """Check whether a user has completed age verification."""
    profile = user_profiles.get(str(user_id))
    return bool(profile and profile.get("verified"))


async def require_verification_prefix(interaction: discord.Interaction):
    """Send an age-verification prompt for slash commands. Returns True if verified."""
    if is_verified(interaction.user.id):
        return True
    await interaction.response.send_message(AGE_VERIFY_PROMPT, ephemeral=True)
    return False

# ─────────────────────────────────────────────
#  Image Generation (Pollinations.ai)
# ─────────────────────────────────────────────
IMAGE_CACHE_FILE = os.path.join(os.path.dirname(__file__), "image_cache.json")
CHARACTER_SEED = 42

def load_image_cache() -> dict:
    if os.path.exists(IMAGE_CACHE_FILE):
        try:
            with open(IMAGE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_image_cache(cache: dict):
    try:
        with open(IMAGE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

image_cache = load_image_cache()

async def generate_ai_image(prompt: str, seed: int | None = None, style: str = "anime") -> bytes | None:
    style_map = {
        "anime": "anime style, high quality, detailed, vibrant colors",
        "realistic": "photorealistic, detailed, 8k, professional photography",
        "artistic": "digital art, fantasy style, painterly, dramatic lighting",
        "chibi": "chibi style, cute, kawaii, small body, big head"
    }

    style_prefix = style_map.get(style, style_map["anime"])
    full_prompt = f"{prompt}, {style_prefix}, best quality, masterpiece"

    image_seed = seed if seed is not None else random.randint(1, 999999)
    cache_key = f"{full_prompt}_{image_seed}"

    try:
        url = image_cache[cache_key]
    except KeyError:
        url = None

    if url is None:
        encoded_prompt = full_prompt.replace(" ", "+")
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?seed={image_seed}&width=512&height=768&nologo=true"
        image_cache[cache_key] = url
        if len(image_cache) > 500:
            keys_to_remove = list(image_cache.keys())[:100]
            for k in keys_to_remove:
                del image_cache[k]
        save_image_cache(image_cache)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.read()
                else:
                    print(f"❌ Image generation failed: HTTP {resp.status}")
                    return None
    except Exception as e:
        print(f"❌ Error fetching image: {e}")
        return None

def get_character_seed(user_id: int) -> int:
    return (CHARACTER_SEED + user_id * 7) % 1000000

# ─────────────────────────────────────────────
#  Safeword detection
# ─────────────────────────────────────────────
def check_safeword(text: str) -> bool:
    """Check if message contains the safeword."""
    safeword = personality.get("consent", {}).get("safeword", "foxfire")
    return safeword.lower() in text.lower()


#  Anti-repetition helper

def detect_and_fix_repetition(text: str, window_size: int = 50, threshold: int = 8) -> str:
    """Detect word repetition loops and truncate if necessary."""
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
        # Find where repetition starts - scan backwards
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

        # Fallback: cut at 75% of original length
        cutoff = int(len(words) * 0.75)
        return ' '.join(words[:cutoff])

    return text


#  Events

@bot.event
async def on_ready():
    print(f"✅  Logged in as {bot.user} (ID: {cast(discord.ClientUser, bot.user).id})")
    print(f"🤖  Personality: {personality['name']}")
    print(f"📚  Loaded history for {len(conversation_histories)} channels")

    # Set bot status
    status_msg = personality.get("settings", {}).get("discord_bot", {}).get("status_message", "Ready!")
    await bot.change_presence(activity=discord.Game(name=status_msg))
    print("─" * 40)

    # Sync slash commands globally
    await sync_slash_commands()

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    await bot.process_commands(message)

    bot_mentioned = bot.user in message.mentions
    is_dm = isinstance(message.channel, discord.DMChannel)

    if not (bot_mentioned or is_dm):
        return

    # Age gate — must verify before any in-character content
    if not is_verified(message.author.id):
        await message.channel.send(AGE_VERIFY_PROMPT)
        return

    # Rate limiting
    user_id = message.author.id
    now = datetime.now(timezone.utc)
    last_time = user_last_message[user_id]

    if (now - last_time).total_seconds() < COOLDOWN_SECONDS:
        await message.add_reaction("⏱️")
        return

    user_last_message[user_id] = now

    user_text = message.content.replace(f"<@{cast(discord.ClientUser, bot.user).id}>", "").strip()
    if not user_text:
        await message.channel.send(f"Hey! I'm **{personality['name']}**. How can I help?")
        return

    async with message.channel.typing():
        # Use per-user history instead of per-channel
        cid = f"{message.channel.id}_{message.author.id}"

        if cid not in conversation_histories:
            conversation_histories[cid] = []

        conversation_histories[cid].append({"role": "user", "content": user_text})

        # ── Update profile (message count, last interaction, relationship stage) ──
        profile = get_or_create_profile(user_id)
        new_count = profile.get("message_count", 0) + 1
        update_profile(
            user_id,
            message_count=new_count,
            last_interaction=now.isoformat(),
            relationship_stage=get_relationship_stage(new_count),
        )

        # ── Memory summarization every N messages, before trimming ──
        if new_count % MEMORY_SUMMARY_INTERVAL == 0:
            await summarize_conversation(cid, user_id)

        system_prompt = personality.get("system_prompt", personality.get("systemPrompt", ""))

        # Add current outfit and scene context to system prompt
        current_outfit_id = wardrobe.get("current_outfit", "poolside_bikini")
        current_outfit = wardrobe.get("outfits", {}).get(current_outfit_id, {})

        current_scene_id = scenes.get("current_scene", "poolside")
        current_scene = scenes.get("scenes", {}).get(current_scene_id, {})

        # Append outfit and scene details to system prompt
        outfit_context = f"\n\n[CURRENT OUTFIT: {current_outfit.get('name', 'Unknown')}]\n{current_outfit.get('appearance', '')}"
        scene_detail = get_scene_detail(current_scene)
        scene_context = f"\n\n[CURRENT SCENE: {current_scene.get('name', 'Unknown')}]\n{current_scene.get('atmosphere', '')}"
        if scene_detail:
            scene_context += f"\n{scene_detail}"

        enhanced_system_prompt = system_prompt + outfit_context + scene_context

        # Inject narration mode hint from user preference (stored in personality.json)
        user_prefs = personality.get("user_prefs", {})
        narration_pref = user_prefs.get(cid, personality.get("advanced", {}).get("narration_style", "first_person"))
        if "first" in narration_pref:
            enhanced_system_prompt += "\n\n[NARRATION MODE: First-person]"

        # ── Inject profile memory + relationship stage ──
        if profile.get("memory_summary"):
            enhanced_system_prompt += f"\n\n[WHAT YOU REMEMBER ABOUT THIS PERSON]\n{profile['memory_summary']}"
        enhanced_system_prompt += f"\n\n[RELATIONSHIP STAGE: {profile.get('relationship_stage', 'new')}]"

        # ── Environment/presence awareness (only in guilds where author is a Member) ──
        author = message.author
        if isinstance(author, discord.Member) and author.activity and author.activity.name:
            enhanced_system_prompt += f"\n\n[NOTE: user's Discord status shows activity '{author.activity.name}']"

        trimmed = trim_conversation(conversation_histories[cid], enhanced_system_prompt)
        messages = [{"role": "system", "content": enhanced_system_prompt}] + trimmed

        try:
            settings = personality.get("settings", {}).get("generation", {})

            reply = await agnes_chat_create(messages, settings)

            if reply is None:
                # Empty reply after retry — send graceful fallback
                fallback = "...hmm, I zoned out for a second there. Can you say that again?"
                conversation_histories[cid].append({"role": "assistant", "content": fallback})
                save_history(conversation_histories)
                await message.reply(fallback)
                print("⚠️  Empty reply from agnes; sent fallback message")
                return

            # Apply anti-repetition filter
            reply = detect_and_fix_repetition(reply)

            conversation_histories[cid].append({"role": "assistant", "content": reply})
            save_history(conversation_histories)

            # Handle long messages
            if len(reply) > 1900:
                chunks = [reply[i:i+1900] for i in range(0, len(reply), 1900)]
                for chunk in chunks:
                    await message.channel.send(chunk)
                    await asyncio.sleep(0.5)  # Prevent rate limiting
            else:
                await message.reply(reply)

        except Exception as e:
            error_msg = f"⚠️  Something went wrong: `{str(e)[:100]}`"
            await message.channel.send(error_msg)
            print(f"❌  Error: {e}")


#  Commands

@bot.command(name="personality")
@commands.has_permissions(manage_messages=True)
async def show_personality(ctx):
    """Display current personality configuration."""
    p = personality
    embed = discord.Embed(title=f"🤖 Current Personality: {p['name']}", color=0x5865F2)

    settings = p.get("settings", {}).get("generation", {})
    embed.add_field(name="Temperature", value=settings.get("temperature", "N/A"), inline=True)
    embed.add_field(name="Max Tokens", value=settings.get("max_tokens", "N/A"), inline=True)
    embed.add_field(name="Model", value="agnes-3.0-flash", inline=True)

    system_preview = p.get("system_prompt", p.get("systemPrompt", "N/A"))[:500]
    embed.add_field(name="System Prompt (preview)", value=f"```{system_preview}...```", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="setpersonality")
@commands.has_permissions(manage_messages=True)
async def set_personality(ctx, *, new_prompt: str):
    """Update the system prompt."""
    global personality
    personality["systemPrompt"] = new_prompt
    personality["system_prompt"] = new_prompt

    personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
    with open(personality_path, "w", encoding="utf-8") as f:
        json.dump(personality, f, indent=2, ensure_ascii=False)

    conversation_histories.clear()
    save_history(conversation_histories)
    await ctx.send(f"✅ Personality updated! All conversation history cleared.")

@bot.command(name="setname")
@commands.has_permissions(manage_messages=True)
async def set_name(ctx, *, new_name: str):
    """Change the bot's display name."""
    global personality
    personality["name"] = new_name

    personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
    with open(personality_path, "w", encoding="utf-8") as f:
        json.dump(personality, f, indent=2, ensure_ascii=False)

    await ctx.send(f"✅ Name updated to **{new_name}**!")

@bot.command(name="settokens")
@commands.has_permissions(manage_messages=True)
async def set_tokens(ctx, *, amount: str):  # type: ignore
    """Set maximum response token length."""
    try:
        amount_int = int(amount)
    except ValueError:
        await ctx.send("⚠️ Invalid amount. Use a number between 100 and 30000.")
        return

    if not 100 <= amount_int <= 30000:
        await ctx.send("⚠️  Please choose a value between 100 and 30000.")
        return

    global personality
    if "settings" not in personality:
        personality["settings"] = {}
    if "generation" not in personality["settings"]:
        personality["settings"]["generation"] = {}

    personality["settings"]["generation"]["max_tokens"] = amount_int

    personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
    with open(personality_path, "w", encoding="utf-8") as f:
        json.dump(personality, f, indent=2, ensure_ascii=False)

    await ctx.send(f"✅ Max tokens set to **{amount_int}**.")

@bot.command(name="resetconvo")
async def reset_convo(ctx):
    """Clear conversation history for current user."""
    cid = f"{ctx.channel.id}_{ctx.author.id}"
    if cid in conversation_histories:
        del conversation_histories[cid]
        save_history(conversation_histories)
        await ctx.send("🔄 Your conversation history has been cleared.")
    else:
        await ctx.send("ℹ️  You don't have any conversation history yet.")

@bot.command(name="verify")
async def verify_cmd(ctx):
    """Confirm you are 18+ to unlock the bot."""
    user_id = ctx.author.id
    profile = get_or_create_profile(user_id)
    profile["verified"] = True
    save_profiles(user_profiles)
    await ctx.send("✅ Thanks! You're verified — we're officially getting to know each other now.")
    print(f"🔞  User {user_id} verified 18+ (prefix)")

@bot.command(name="profile")
async def profile_cmd(ctx):
    """Show your stored profile."""
    profile = get_or_create_profile(ctx.author.id)

    embed = discord.Embed(title=f"👤 Your Profile: {ctx.author}", color=0x5865F2)
    embed.add_field(name="Nickname", value=profile.get("nickname") or "_(not set)_", inline=True)
    embed.add_field(name="Relationship Stage", value=profile.get("relationship_stage", "new"), inline=True)
    embed.add_field(name="Messages", value=str(profile.get("message_count", 0)), inline=True)
    embed.add_field(name="Recurring Topics", value="\n".join(profile.get("recurring_topics", [])) or "_(none yet)_", inline=False)
    embed.add_field(
        name="Memory Summary",
        value=profile.get("memory_summary") or "_(nothing remembered yet)_",
        inline=False,
    )
    await ctx.send(embed=embed)

@bot.command(name="forgetme")
async def forgetme_cmd(ctx):
    """Delete your profile and all conversation history entries for your user_id."""
    user_id_str = str(ctx.author.id)

    user_profiles.pop(user_id_str, None)
    save_profiles(user_profiles)

    removed = [cid for cid in list(conversation_histories) if user_id_str in cid]
    for cid in removed:
        del conversation_histories[cid]
    save_history(conversation_histories)

    await ctx.send(f"🧹 Done — your profile and {len(removed)} conversation thread(s) have been deleted.")
    print(f"🧹  User {user_id_str} requested full data removal (prefix)")

@bot.command(name="narration")
async def narration_cmd(ctx, mode: str | None = None):
    """Toggle narration perspective: third-person or first-person."""
    global personality

    cid = f"{ctx.channel.id}_{ctx.author.id}"
    if cid not in conversation_histories:
        conversation_histories[cid] = []

    # Read per-user prefs from personality.json
    user_prefs = personality.get("user_prefs", {})
    pref = user_prefs.get(cid, personality.get("advanced", {}).get("narration_style", "first_person"))
    # Normalize to short form for display
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
        new_label = "First-person"
        emoji = "✨"
        norm_pref = "first_person"
    else:
        new_label = "Third-person"
        emoji = "📖"
        norm_pref = "third_person"

    # Save preference to personality.json
    if "user_prefs" not in personality:
        personality["user_prefs"] = {}
    personality["user_prefs"][cid] = norm_pref

    personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
    with open(personality_path, "w", encoding="utf-8") as f:
        json.dump(personality, f, indent=2, ensure_ascii=False)

    # Insert a system reminder into the user's history so the AI picks up the new style immediately
    hint = f"[NARRATION MODE: {new_label}]"
    conversation_histories[cid].insert(0, {"role": "system", "content": hint})
    save_history(conversation_histories)

    await ctx.send(f"{emoji} Narration switched to **{new_label}**!")

@bot.command(name="resetall")
@commands.has_permissions(manage_messages=True)
async def reset_all(ctx):
    """Clear all conversation histories (mod only)."""
    conversation_histories.clear()
    save_history(conversation_histories)
    await ctx.send("🔄 All conversation histories cleared.")

@bot.command(name="contextinfo")
async def context_info(ctx):
    """Show token usage for current conversation."""
    cid = f"{ctx.channel.id}_{ctx.author.id}"
    history = conversation_histories.get(cid, [])

    if not history:
        await ctx.send("ℹ️  You don't have any conversation history yet.")
        return

    system_prompt = personality.get("system_prompt", personality.get("systemPrompt", ""))
    full = [{"role": "system", "content": system_prompt}] + history
    token_count = count_tokens_for_messages(full)

    embed = discord.Embed(title="📊 Context Information", color=0x5865F2)
    embed.add_field(name="Messages", value=len(history), inline=True)
    embed.add_field(name="Tokens Used", value=f"{token_count:,}", inline=True)
    embed.add_field(name="Max Tokens", value=f"{MAX_CONTEXT_TOKENS - RESPONSE_TOKEN_BUDGET:,}", inline=True)

    percentage = (token_count / (MAX_CONTEXT_TOKENS - RESPONSE_TOKEN_BUDGET)) * 100
    embed.add_field(name="Usage", value=f"{percentage:.1f}%", inline=True)

    await ctx.send(embed=embed)

@bot.command(name="export")
async def export_history(ctx):
    """Export your conversation history."""
    cid = f"{ctx.channel.id}_{ctx.author.id}"
    history = conversation_histories.get(cid, [])

    if not history:
        await ctx.send("ℹ️  You don't have any conversation history to export.")
        return

    # Create a readable export
    export_data = {
        "user": str(ctx.author),
        "channel": str(ctx.channel),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "messages": history
    }

    # Save to file
    filename = f"chat_export_{ctx.author.id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(os.path.dirname(__file__), filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    await ctx.send(file=discord.File(filepath))
    os.remove(filepath)  # Clean up

@bot.command(name="setcontextlimit")
@commands.has_permissions(manage_messages=True)
async def set_context_limit(ctx, new_limit: int):
    """Set maximum context token limit."""
    global MAX_CONTEXT_TOKENS
    if new_limit < 1000:
        await ctx.send("⚠️  Please set a limit of at least 1000.")
        return
    MAX_CONTEXT_TOKENS = new_limit
    await ctx.send(f"✅ Context limit set to **{new_limit:,}** tokens.")

@bot.command(name="stats")
@commands.has_permissions(manage_messages=True)
async def bot_stats(ctx):
    """Show bot statistics."""
    total_conversations = len(conversation_histories)
    total_messages = sum(len(hist) for hist in conversation_histories.values())

    embed = discord.Embed(title="📈 Bot Statistics", color=0x00FF00)
    embed.add_field(name="Active Conversations", value=total_conversations, inline=True)
    embed.add_field(name="Total Messages", value=total_messages, inline=True)
    embed.add_field(name="Servers", value=len(bot.guilds), inline=True)

    await ctx.send(embed=embed)

@bot.command(name="bothelp")
async def bot_help(ctx):
    """Show all available commands."""
    embed = discord.Embed(title="📖 Bot Commands", color=0x5865F2)

    user_cmds = [
        ("@bot <message>", "Chat with the bot"),
        (".verify", "Confirm you're 18+ to unlock the bot"),
        (".profile", "View your stored profile"),
        (".forgetme", "Delete your profile and all conversation history"),
        (".resetconvo", "Clear your conversation history"),
        (".contextinfo", "Show your token usage"),
        (".wardrobe", "View current outfit or list outfits"),
        (".wardrobe change <id>", "Change outfit"),
        (".wardrobe add", "Add new outfit"),
        (".wardrobe edit <id>", "Edit outfit"),
        (".wardrobe remove <id>", "Remove outfit"),
        (".scene", "View current scene or list scenes"),
        (".scene change <id>", "Change scene"),
        (".scene add", "Add new scene"),
        (".scene edit <id>", "Edit scene"),
        (".scene remove <id>", "Remove scene"),
        (".narration", "Show current narration mode"),
        (".narration first", "Switch to first-person narration"),
        (".narration third", "Switch to third-person narration"),
        (".export", "Export your conversation history"),
        (".bothelp", "Show this help message"),
    ]

    mod_cmds = [
        (".personality", "View personality settings"),
        (".editpersonality", "Interactive personality editor"),
        (".setpersonality <prompt>", "Update system prompt"),
        (".setname <name>", "Change bot's name"),
        (".settokens <100-30000>", "Set max response length"),
        (".setcontextlimit <num>", "Set max context tokens"),
        (".resetconvo", "Clear your conversation history"),
        (".resetall", "Clear all conversation histories"),
        (".stats", "Show bot statistics"),
    ]

    embed.add_field(name="👤 User Commands", value="\n".join([f"`{n}` - {d}" for n, d in user_cmds]), inline=False)
    embed.add_field(name="🛡️ Moderator Commands", value="\n".join([f"`{n}` - {d}" for n, d in mod_cmds]), inline=False)

    await ctx.send(embed=embed)

# ─────────────────────────────────────────────
#  Wardrobe Commands
# ─────────────────────────────────────────────
@bot.command(name="wardrobe")
async def wardrobe_cmd(ctx, action: str | None = None, *, outfit_id: str | None = None):
    """Manage character outfits."""
    global wardrobe, personality

    # View current outfit
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

    # List all outfits
    if action.lower() == "list":
        outfits = wardrobe.get("outfits", {})
        current = wardrobe.get("current_outfit", "")

        embed = discord.Embed(title="👗 Available Outfits", color=0xFF69B4)

        for outfit_id, outfit in outfits.items():
            emoji = outfit.get("emoji", "👗")
            name = outfit.get("name", outfit_id)
            desc = outfit.get("description", "No description")
            is_current = "✅ " if outfit_id == current else ""
            embed.add_field(
                name=f"{is_current}{emoji} {name}",
                value=f"`{outfit_id}` - {desc}",
                inline=False
            )

        embed.set_footer(text=f"Use .wardrobe change <outfit_id> to change outfit")
        await ctx.send(embed=embed)
        return

    # Change outfit
    if action.lower() == "change":
        if not outfit_id:
            await ctx.send("⚠️ Please specify an outfit ID. Use `.wardrobe list` to see available outfits.")
            return

        outfit_id = outfit_id.lower().replace(" ", "_")

        if outfit_id not in wardrobe.get("outfits", {}):
            await ctx.send(f"⚠️ Outfit '{outfit_id}' not found. Use `.wardrobe list` to see available outfits.")
            return

        wardrobe["current_outfit"] = outfit_id
        save_wardrobe(wardrobe)

        outfit = wardrobe["outfits"][outfit_id]

        # Update personality state
        if "state" in personality:
            personality["state"]["clothing_state"] = outfit_id

        embed = discord.Embed(title=f"✅ Outfit Changed!", color=0x00FF00)
        embed.add_field(name="Now Wearing", value=f"{outfit.get('emoji', '👗')} {outfit.get('name', outfit_id)}", inline=False)
        embed.add_field(name="Description", value=outfit.get('description', 'No description'), inline=False)
        await ctx.send(embed=embed)
        return

    # Add new outfit
    if action.lower() == "add":
        await ctx.send("📝 Let's create a new outfit! Please answer the following questions.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            # Get outfit ID
            await ctx.send("**1/6** What's the outfit ID? (e.g., `casual_jeans`, `evening_dress`) - lowercase, use underscores")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            new_outfit_id = msg.content.lower().replace(" ", "_")

            if new_outfit_id in wardrobe.get("outfits", {}):
                await ctx.send(f"⚠️ Outfit '{new_outfit_id}' already exists. Use `.wardrobe edit` instead.")
                return

            # Get name
            await ctx.send("**2/6** What's the outfit name? (e.g., `Casual Jeans`, `Evening Dress`)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            name = msg.content

            # Get emoji
            await ctx.send("**3/6** Choose an emoji for this outfit (e.g., 👗, 👙, 👔)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            emoji = msg.content

            # Get description
            await ctx.send("**4/6** Brief description (one line)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            description = msg.content

            # Get appearance
            await ctx.send("**5/6** Full appearance description (be detailed!)")
            msg = await bot.wait_for('message', check=check, timeout=300.0)
            appearance = msg.content

            # Get scene
            await ctx.send("**6/6** What scene is this outfit for? (e.g., `poolside`, `bedroom`, `school`)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            scene = msg.content

            # Create outfit
            if "outfits" not in wardrobe:
                wardrobe["outfits"] = {}

            wardrobe["outfits"][new_outfit_id] = {
                "name": name,
                "emoji": emoji,
                "description": description,
                "appearance": appearance,
                "scene": scene
            }

            save_wardrobe(wardrobe)

            embed = discord.Embed(title="✅ Outfit Added!", color=0x00FF00)
            embed.add_field(name="ID", value=new_outfit_id, inline=True)
            embed.add_field(name="Name", value=f"{emoji} {name}", inline=True)
            embed.add_field(name="Description", value=description, inline=False)
            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Outfit creation cancelled.")
        return

    # Remove outfit
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

        # If removing current outfit, reset to default
        if wardrobe.get("current_outfit") == outfit_id:
            wardrobe["current_outfit"] = list(wardrobe["outfits"].keys())[0] if wardrobe["outfits"] else "default"

        save_wardrobe(wardrobe)
        await ctx.send(f"✅ Removed outfit: {outfit_name}")
        return

    # Edit outfit
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

            save_wardrobe(wardrobe)
            await ctx.send(f"✅ Updated {field} for outfit: {outfit.get('name', outfit_id)}")

        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Edit cancelled.")
        return

    await ctx.send("⚠️ Invalid action. Use: `list`, `change`, `add`, `remove`, or `edit`")


#  Scene Commands

@bot.command(name="scene")
async def scene_cmd(ctx, action: str | None = None, *, scene_id: str | None = None):
    """Manage character scenes."""
    global scenes, personality

    # View current scene
    if action is None:
        current = scenes.get("current_scene", "poolside")
        scene = scenes.get("scenes", {}).get(current, {})

        embed = discord.Embed(title=f"🎬 Current Scene: {scene.get('name', 'Unknown')}", color=0x00CED1)
        embed.add_field(name="Description", value=scene.get("description", "No description"), inline=False)
        embed.add_field(name="Atmosphere", value=scene.get("atmosphere", "No details")[:1024], inline=False)
        embed.set_footer(text=f"Scene ID: {current}")
        await ctx.send(embed=embed)
        return

    # List all scenes
    if action.lower() == "list":
        all_scenes = scenes.get("scenes", {})
        current = scenes.get("current_scene", "")

        embed = discord.Embed(title="🎬 Available Scenes", color=0x00CED1)

        for scene_id, scene in all_scenes.items():
            emoji = scene.get("emoji", "🎬")
            name = scene.get("name", scene_id)
            desc = scene.get("description", "No description")
            is_current = "✅ " if scene_id == current else ""
            embed.add_field(
                name=f"{is_current}{emoji} {name}",
                value=f"`{scene_id}` - {desc}",
                inline=False
            )

        embed.set_footer(text=f"Use .scene change <scene_id> to change scene")
        await ctx.send(embed=embed)
        return

    # Change scene
    if action.lower() == "change":
        if not scene_id:
            await ctx.send("⚠️ Please specify a scene ID. Use `.scene list` to see available scenes.")
            return

        scene_id = scene_id.lower().replace(" ", "_")

        if scene_id not in scenes.get("scenes", {}):
            await ctx.send(f"⚠️ Scene '{scene_id}' not found. Use `.scene list` to see available scenes.")
            return

        scenes["current_scene"] = scene_id
        save_scenes(scenes)

        scene = scenes["scenes"][scene_id]

        # Update personality state
        if "state" in personality:
            personality["state"]["current_scene"] = scene_id

        # Track last_scene on the calling user's profile
        if is_verified(ctx.author.id):
            update_profile(ctx.author.id, last_scene=scene_id)

        embed = discord.Embed(title=f"✅ Scene Changed!", color=0x00FF00)
        embed.add_field(name="Now At", value=f"{scene.get('emoji', '🎬')} {scene.get('name', scene_id)}", inline=False)
        embed.add_field(name="Description", value=scene.get('description', 'No description'), inline=False)
        await ctx.send(embed=embed)
        return

    # Add new scene
    if action.lower() == "add":
        await ctx.send("📝 Let's create a new scene! Please answer the following questions.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            # Get scene ID
            await ctx.send("**1/5** What's the scene ID? (e.g., `beach`, `bedroom_night`) - lowercase, use underscores")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            new_scene_id = msg.content.lower().replace(" ", "_")

            if new_scene_id in scenes.get("scenes", {}):
                await ctx.send(f"⚠️ Scene '{new_scene_id}' already exists. Use `.scene edit` instead.")
                return

            # Get name
            await ctx.send("**2/5** What's the scene name? (e.g., `Beach`, `Bedroom at Night`)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            name = msg.content

            # Get emoji
            await ctx.send("**3/5** Choose an emoji for this scene (e.g., 🏖️, 🏠, 🌃)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            emoji = msg.content

            # Get description
            await ctx.send("**4/5** Brief description (one line)")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            description = msg.content

            # Get atmosphere
            await ctx.send("**5/5** Full atmosphere description (be detailed! What do you see, hear, smell?)")
            msg = await bot.wait_for('message', check=check, timeout=300.0)
            atmosphere = msg.content

            # Create scene
            if "scenes" not in scenes:
                scenes["scenes"] = {}

            scenes["scenes"][new_scene_id] = {
                "name": name,
                "emoji": emoji,
                "description": description,
                "atmosphere": atmosphere
            }

            save_scenes(scenes)

            embed = discord.Embed(title="✅ Scene Added!", color=0x00FF00)
            embed.add_field(name="ID", value=new_scene_id, inline=True)
            embed.add_field(name="Name", value=f"{emoji} {name}", inline=True)
            embed.add_field(name="Description", value=description, inline=False)
            await ctx.send(embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Scene creation cancelled.")
        return

    # Remove scene
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

        # If removing current scene, reset to default
        if scenes.get("current_scene") == scene_id:
            scenes["current_scene"] = list(scenes["scenes"].keys())[0] if scenes["scenes"] else "default"

        save_scenes(scenes)
        await ctx.send(f"✅ Removed scene: {scene_name}")
        return

    # Edit scene
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

            save_scenes(scenes)
            await ctx.send(f"✅ Updated {field} for scene: {scene.get('name', scene_id)}")

        except asyncio.TimeoutError:
            await ctx.send("⏱️ Timed out. Edit cancelled.")
        return

    await ctx.send("⚠️ Invalid action. Use: `list`, `change`, `add`, `remove`, or `edit`")


#  Enhanced Personality Editor

@bot.command(name="editpersonality")
@commands.has_permissions(manage_messages=True)
async def edit_personality(ctx):
    """Interactive personality editor with menu."""
    embed = discord.Embed(title="🎨 Personality Editor", color=0x9B59B6)
    embed.add_field(name="What would you like to edit?", value=(
        "`name` - Bot's display name\n"
        "`system_prompt` - Full system prompt\n"
        "`temperature` - AI temperature (0.0-2.0)\n"
        "`max_tokens` - Max response length\n"
        "`frequency_penalty` - Repetition penalty (0.0-2.0)\n"
        "`presence_penalty` - Topic diversity (0.0-2.0)\n"
        "`status` - Bot's Discord status\n"
        "`cancel` - Cancel editing"
    ), inline=False)
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        msg = await bot.wait_for('message', check=check, timeout=60.0)
        field = msg.content.lower()

        if field == "cancel":
            await ctx.send("❌ Edit cancelled.")
            return

        global personality

        if field == "name":
            await ctx.send("Enter new bot name:")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            personality["name"] = msg.content

        elif field == "system_prompt":
            await ctx.send("Enter new system prompt (this is the AI's personality instructions):")
            msg = await bot.wait_for('message', check=check, timeout=600.0)
            personality["systemPrompt"] = msg.content
            personality["system_prompt"] = msg.content

        elif field == "temperature":
            await ctx.send("Enter temperature value (0.0 = deterministic, 2.0 = very random):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                temp = float(msg.content)
                if 0.0 <= temp <= 2.0:
                    if "settings" not in personality:
                        personality["settings"] = {}
                    if "generation" not in personality["settings"]:
                        personality["settings"]["generation"] = {}
                    personality["settings"]["generation"]["temperature"] = temp
                else:
                    await ctx.send("⚠️ Temperature must be between 0.0 and 2.0")
                    return
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "max_tokens":
            await ctx.send("Enter max tokens (100-30000):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                tokens = int(msg.content)
                if 100 <= tokens <= 30000:
                    if "settings" not in personality:
                        personality["settings"] = {}
                    if "generation" not in personality["settings"]:
                        personality["settings"]["generation"] = {}
                    personality["settings"]["generation"]["max_tokens"] = tokens
                else:
                    await ctx.send("⚠️ Max tokens must be between 100 and 30000")
                    return
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "frequency_penalty":
            await ctx.send("Enter frequency penalty (0.0-2.0, higher = less repetition):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                penalty = float(msg.content)
                if 0.0 <= penalty <= 2.0:
                    if "settings" not in personality:
                        personality["settings"] = {}
                    if "generation" not in personality["settings"]:
                        personality["settings"]["generation"] = {}
                    personality["settings"]["generation"]["frequency_penalty"] = penalty
                else:
                    await ctx.send("⚠️ Frequency penalty must be between 0.0 and 2.0")
                    return
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "presence_penalty":
            await ctx.send("Enter presence penalty (0.0-2.0, higher = more topic diversity):")
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            try:
                penalty = float(msg.content)
                if 0.0 <= penalty <= 2.0:
                    if "settings" not in personality:
                        personality["settings"] = {}
                    if "generation" not in personality["settings"]:
                        personality["settings"]["generation"] = {}
                    personality["settings"]["generation"]["presence_penalty"] = penalty
                else:
                    await ctx.send("⚠️ Presence penalty must be between 0.0 and 2.0")
                    return
            except ValueError:
                await ctx.send("⚠️ Invalid number")
                return

        elif field == "status":
            await ctx.send("Enter new Discord status message:")
            msg = await bot.wait_for('message', check=check, timeout=120.0)
            if "settings" not in personality:
                personality["settings"] = {}
            if "discord_bot" not in personality["settings"]:
                personality["settings"]["discord_bot"] = {}
            personality["settings"]["discord_bot"]["status_message"] = msg.content
            await bot.change_presence(activity=discord.Game(name=msg.content))

        else:
            await ctx.send("⚠️ Unknown field. Edit cancelled.")
            return

        # Save personality
        personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
        try:
            with open(personality_path, "w", encoding="utf-8") as f:
                json.dump(personality, f, indent=2, ensure_ascii=False)
            await ctx.send(f"✅ Updated **{field}** successfully!")
        except OSError as e:
            await ctx.send(f"❌ Failed to save: {e}")

    except asyncio.TimeoutError:
        await ctx.send("⏱️ Timed out. Edit cancelled.")


#  Status Command

@bot.command(name="status")
@commands.has_permissions(manage_messages=True)
async def status_cmd(ctx, activity_type: str | None = None, *, message: str = ""):
    """Change bot status and activity. Types: playing, watching, listening, streaming"""
    global personality

    if not activity_type and not message:
        current = personality.get("settings", {}).get("discord_bot", {}).get("status_message", "Ready!")
        await ctx.send(f"📊 Current status: **{current}**\n\nUsage: `.status <type> <message>`\nTypes: `playing`, `watching`, `listening`, `streaming`")
        return

    if not message:
        await ctx.send("⚠️ Please provide a status message. Example: `.status playing with you`")
        return

    activity_type = activity_type.lower() if activity_type else "playing"
    message = message.strip()

    activity_types = {
        "playing": discord.Game(name=message),
        "watching": discord.Activity(type=discord.ActivityType.watching, name=message),
        "listening": discord.Activity(type=discord.ActivityType.listening, name=message),
        "streaming": discord.Streaming(url="", name=message)
    }

    if activity_type not in activity_types:
        valid = ", ".join(activity_types.keys())
        await ctx.send(f"⚠️ Invalid activity type. Valid types: {valid}")
        return

    await bot.change_presence(activity=activity_types[activity_type])

    if "settings" not in personality:
        personality["settings"] = {}
    if "discord_bot" not in personality["settings"]:
        personality["settings"]["discord_bot"] = {}
    personality["settings"]["discord_bot"]["status_message"] = message
    personality["settings"]["discord_bot"]["activity_type"] = activity_type

    personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
    with open(personality_path, "w", encoding="utf-8") as f:
        json.dump(personality, f, indent=2, ensure_ascii=False)

    emoji_map = {"playing": "🎮", "watching": "👁️", "listening": "🎧", "streaming": "📺"}
    emoji = emoji_map.get(activity_type, "📊")
    await ctx.send(f"✅ Status updated! {emoji} **{message}** ({activity_type})")

#  Slash Commands

async def sync_slash_commands():
    """Register slash commands globally."""
    await bot.tree.sync()
    print(f"📝 Slash commands synced globally for {bot.user}")

@bot.tree.command(name="chat", description="Chat with the bot")
async def slash_chat(interaction: discord.Interaction, message: str):
    """Chat with the bot via slash command."""
    user_text = message.strip()
    if not user_text:
        await interaction.response.send_message("⚠️ Please provide a message.", ephemeral=True)
        return

    # Age gate
    if not is_verified(interaction.user.id):
        await interaction.response.send_message(AGE_VERIFY_PROMPT, ephemeral=True)
        return

    async with cast(discord.abc.Messageable, interaction.channel).typing():
        cid = f"{interaction.channel.id}_{interaction.user.id}"  # type: ignore[union-attr]
        user_id = interaction.user.id

        if cid not in conversation_histories:
            conversation_histories[cid] = []

        conversation_histories[cid].append({"role": "user", "content": user_text})

        # ── Update profile ──
        profile = get_or_create_profile(user_id)
        new_count = profile.get("message_count", 0) + 1
        update_profile(
            user_id,
            message_count=new_count,
            last_interaction=datetime.now(timezone.utc).isoformat(),
            relationship_stage=get_relationship_stage(new_count),
        )

        # ── Memory summarization every N messages ──
        if new_count % MEMORY_SUMMARY_INTERVAL == 0:
            await summarize_conversation(cid, user_id)

        system_prompt = personality.get("system_prompt", personality.get("systemPrompt", ""))
        current_outfit_id = wardrobe.get("current_outfit", "poolside_bikini")
        current_outfit = wardrobe.get("outfits", {}).get(current_outfit_id, {})
        current_scene_id = scenes.get("current_scene", "poolside")
        current_scene = scenes.get("scenes", {}).get(current_scene_id, {})

        outfit_context = f"\n\n[CURRENT OUTFIT: {current_outfit.get('name', 'Unknown')}]\n{current_outfit.get('appearance', '')}"
        scene_detail = get_scene_detail(current_scene)
        scene_context = f"\n\n[CURRENT SCENE: {current_scene.get('name', 'Unknown')}]\n{current_scene.get('atmosphere', '')}"
        if scene_detail:
            scene_context += f"\n{scene_detail}"

        enhanced_system_prompt = system_prompt + outfit_context + scene_context

        # Inject narration mode hint from user preference
        user_prefs = personality.get("user_prefs", {})
        narration_pref = user_prefs.get(cid, personality.get("advanced", {}).get("narration_style", "first_person"))
        if "first" in narration_pref:
            enhanced_system_prompt += "\n\n[NARRATION MODE: First-person]"

        # ── Inject profile memory + relationship stage ──
        if profile.get("memory_summary"):
            enhanced_system_prompt += f"\n\n[WHAT YOU REMEMBER ABOUT THIS PERSON]\n{profile['memory_summary']}"
        enhanced_system_prompt += f"\n\n[RELATIONSHIP STAGE: {profile.get('relationship_stage', 'new')}]"

        # ── Environment/presence awareness (only in guilds where user is a Member) ──
        inter_user = interaction.user
        if isinstance(inter_user, discord.Member) and inter_user.activity and inter_user.activity.name:
            enhanced_system_prompt += f"\n\n[NOTE: user's Discord status shows activity '{inter_user.activity.name}']"

        trimmed = trim_conversation(conversation_histories[cid], enhanced_system_prompt)
        messages = [{"role": "system", "content": enhanced_system_prompt}] + trimmed

        try:
            settings = personality.get("settings", {}).get("generation", {})

            reply = await agnes_chat_create(messages, settings)

            if reply is None:
                fallback = "...hmm, I zoned out for a second there. Can you say that again?"
                conversation_histories[cid].append({"role": "assistant", "content": fallback})
                save_history(conversation_histories)
                await interaction.followup.send(fallback)
                print("⚠️  Empty reply from agnes; sent fallback message")
                return

            reply = detect_and_fix_repetition(reply)
            conversation_histories[cid].append({"role": "assistant", "content": reply})
            save_history(conversation_histories)

            if len(reply) > 1900:
                chunks = [reply[i:i+1900] for i in range(0, len(reply), 1900)]
                for chunk in chunks:
                    await interaction.followup.send(chunk)
                    await asyncio.sleep(0.5)
            else:
                await interaction.followup.send(reply)
        except Exception as e:
            error_msg = f"⚠️  Something went wrong: `{str(e)[:100]}`"
            await interaction.response.send_message(error_msg, ephemeral=True)
            print(f"❌  Error: {e}")

@bot.tree.command(name="wardrobe", description="View or manage outfits")
@app_commands.describe(action="Action to perform")
async def slash_wardrobe(interaction: discord.Interaction, action: str | None = None):
    """View or list outfits."""
    if action == "list":
        outfits = wardrobe.get("outfits", {})
        current = wardrobe.get("current_outfit", "")

        embed = discord.Embed(title="👗 Available Outfits", color=0xFF69B4)
        for outfit_id, outfit in outfits.items():
            emoji = outfit.get("emoji", "👗")
            name = outfit.get("name", outfit_id)
            desc = outfit.get("description", "No description")
            is_current = "✅ " if outfit_id == current else ""
            embed.add_field(name=f"{is_current}{emoji} {name}", value=f"`{outfit_id}` - {desc}", inline=False)
        embed.set_footer(text="Use .wardrobe change <id> to switch")
        await interaction.response.send_message(embed=embed)
    else:
        current = wardrobe.get("current_outfit", "poolside_bikini")
        outfit = wardrobe.get("outfits", {}).get(current, {})
        embed = discord.Embed(title=f"👗 Current Outfit: {outfit.get('name', 'Unknown')}", color=0xFF69B4)
        embed.add_field(name="Description", value=outfit.get("description", "No description"), inline=False)
        embed.add_field(name="Appearance", value=outfit.get("appearance", "No details")[:1024], inline=False)
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="scene", description="View or manage scenes")
@app_commands.describe(action="Action to perform")
async def slash_scene(interaction: discord.Interaction, action: str | None = None):
    """View or list scenes."""
    if action == "list":
        all_scenes = scenes.get("scenes", {})
        current = scenes.get("current_scene", "")

        embed = discord.Embed(title="🎬 Available Scenes", color=0x00CED1)
        for scene_id, scene in all_scenes.items():
            emoji = scene.get("emoji", "🎬")
            name = scene.get("name", scene_id)
            desc = scene.get("description", "No description")
            is_current = "✅ " if scene_id == current else ""
            embed.add_field(name=f"{is_current}{emoji} {name}", value=f"`{scene_id}` - {desc}", inline=False)
        embed.set_footer(text="Use .scene change <id> to switch")
        await interaction.response.send_message(embed=embed)
    else:
        current = scenes.get("current_scene", "poolside")
        scene = scenes.get("scenes", {}).get(current, {})
        embed = discord.Embed(title=f"🎬 Current Scene: {scene.get('name', 'Unknown')}", color=0x00CED1)
        embed.add_field(name="Description", value=scene.get("description", "No description"), inline=False)
        embed.add_field(name="Atmosphere", value=scene.get("atmosphere", "No details")[:1024], inline=False)
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="status", description="View or change bot status")
@app_commands.describe(activity_type="Type of activity", message="Status message")
async def slash_status(interaction: discord.Interaction, activity_type: str | None = None, message: str = ""):
    """Change bot status and activity."""
    if not activity_type and not message:
        current = personality.get("settings", {}).get("discord_bot", {}).get("status_message", "Ready!")
        await interaction.response.send_message(f"📊 Current status: **{current}**\n\nUse `.status <type> <message>` to change")
        return

    if not message:
        await interaction.response.send_message("⚠️ Please provide a status message.", ephemeral=True)
        return

    activity_type = activity_type.lower() if activity_type else "playing"
    message = message.strip()

    activity_types = {
        "playing": discord.Game(name=message),
        "watching": discord.Activity(type=discord.ActivityType.watching, name=message),
        "listening": discord.Activity(type=discord.ActivityType.listening, name=message),
        "streaming": discord.Streaming(url="", name=message)
    }

    if activity_type not in activity_types:
        valid = ", ".join(activity_types.keys())
        await interaction.response.send_message(f"⚠️ Invalid activity type. Valid types: {valid}", ephemeral=True)
        return

    await bot.change_presence(activity=activity_types[activity_type])

    if "settings" not in personality:
        personality["settings"] = {}
    if "discord_bot" not in personality["settings"]:
        personality["settings"]["discord_bot"] = {}
    personality["settings"]["discord_bot"]["status_message"] = message
    personality["settings"]["discord_bot"]["activity_type"] = activity_type

    personality_path = os.path.join(os.path.dirname(__file__), "personality.json")
    with open(personality_path, "w", encoding="utf-8") as f:
        json.dump(personality, f, indent=2, ensure_ascii=False)

    emoji_map = {"playing": "🎮", "watching": "👁️", "listening": "🎧", "streaming": "📺"}
    emoji = emoji_map.get(activity_type, "📊")
    await interaction.response.send_message(f"✅ Status updated! {emoji} **{message}** ({activity_type})")

@bot.tree.command(name="selfie", description="Generate a selfie image")
@app_commands.describe(description="Optional description")
async def slash_selfie(interaction: discord.Interaction, description: str = ""):
    """Generate a selfie image."""
    if not is_verified(interaction.user.id):
        await interaction.response.send_message(AGE_VERIFY_PROMPT, ephemeral=True)
        return
    await interaction.response.send_message("🎨 Generating your selfie...", ephemeral=True)

    current_outfit = wardrobe.get("outfits", {}).get(wardrobe.get("current_outfit", ""), {})
    current_scene = scenes.get("scenes", {}).get(scenes.get("current_scene", ""), {})

    outfit_desc = current_outfit.get("appearance", "a character")
    scene_desc = current_scene.get("atmosphere", "a nice background")

    if description:
        custom_prompt = f"Selfie of {outfit_desc}, {description}, {scene_desc}, taking a photo, looking at camera, cute pose"
    else:
        custom_prompt = f"Selfie of {outfit_desc}, {scene_desc}, taking a photo, looking at camera, cute pose"

    user_seed = get_character_seed(interaction.user.id)
    image_bytes = await generate_ai_image(custom_prompt, seed=user_seed, style="anime")

    if image_bytes:
        await interaction.followup.send(f"📸 Your selfie! (seed: {user_seed})", file=discord.File(io.BytesIO(image_bytes), filename="selfie.png"))
    else:
        await interaction.followup.send("⚠️ Failed to generate image. Try again later.")

@bot.tree.command(name="pose", description="Generate a pose image")
@app_commands.describe(description="Pose description")
async def slash_pose(interaction: discord.Interaction, description: str = ""):
    """Generate a pose image."""
    if not is_verified(interaction.user.id):
        await interaction.response.send_message(AGE_VERIFY_PROMPT, ephemeral=True)
        return
    await interaction.response.send_message("🎨 Generating your pose...", ephemeral=True)

    current_outfit = wardrobe.get("outfits", {}).get(wardrobe.get("current_outfit", ""), {})
    current_scene = scenes.get("scenes", {}).get(scenes.get("current_scene", ""), {})

    outfit_desc = current_outfit.get("appearance", "a character")
    scene_desc = current_scene.get("atmosphere", "a nice background")

    if description:
        custom_prompt = f"{outfit_desc}, {description}, {scene_desc}, artistic pose, dynamic angle"
    else:
        custom_prompt = f"{outfit_desc}, standing pose, {scene_desc}, artistic, full body shot"

    user_seed = get_character_seed(interaction.user.id)
    image_bytes = await generate_ai_image(custom_prompt, seed=user_seed, style="anime")

    if image_bytes:
        await interaction.followup.send(f"🎨 Your pose! (seed: {user_seed})", file=discord.File(io.BytesIO(image_bytes), filename="pose.png"))
    else:
        await interaction.followup.send("⚠️ Failed to generate image. Try again later.")

@bot.tree.command(name="image", description="Generate a custom AI image")
@app_commands.describe(prompt="Image description")
async def slash_image(interaction: discord.Interaction, prompt: str):
    """Generate a custom AI image."""
    if not is_verified(interaction.user.id):
        await interaction.response.send_message(AGE_VERIFY_PROMPT, ephemeral=True)
        return
    await interaction.response.send_message("🎨 Generating your image...", ephemeral=True)

    user_seed = get_character_seed(interaction.user.id)
    image_bytes = await generate_ai_image(prompt, seed=user_seed, style="anime")

    if image_bytes:
        await interaction.followup.send(f"🖼️ Your image! (seed: {user_seed})", file=discord.File(io.BytesIO(image_bytes), filename="image.png"))
    else:
        await interaction.followup.send("⚠️ Failed to generate image. Try again later.")

@bot.tree.command(name="verify", description="Confirm you are 18+ to unlock the bot")
async def slash_verify(interaction: discord.Interaction):
    """Age-verify the calling user."""
    user_id = interaction.user.id
    profile = get_or_create_profile(user_id)
    profile["verified"] = True
    save_profiles(user_profiles)
    await interaction.response.send_message(
        f"✅ Thanks, **{interaction.user}**! You're verified. We're officially getting to know each other now.",
        ephemeral=True,
    )
    print(f"🔞  User {user_id} verified 18+")


@bot.tree.command(name="profile", description="Show your stored profile (nickname, stage, memory)")
async def slash_profile(interaction: discord.Interaction):
    """Show the calling user's profile."""
    profile = get_or_create_profile(interaction.user.id)

    embed = discord.Embed(title=f"👤 Your Profile: {interaction.user}", color=0x5865F2)
    embed.add_field(name="Nickname", value=profile.get("nickname") or "_(not set)_", inline=True)
    embed.add_field(name="Relationship Stage", value=profile.get("relationship_stage", "new"), inline=True)
    embed.add_field(name="Messages", value=str(profile.get("message_count", 0)), inline=True)
    embed.add_field(name="Recurring Topics", value="\n".join(profile.get("recurring_topics", [])) or "_(none yet)_", inline=False)
    embed.add_field(
        name="Memory Summary",
        value=profile.get("memory_summary") or "_(nothing remembered yet)_",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="forgetme", description="Delete your profile and conversation history")
async def slash_forgetme(interaction: discord.Interaction):
    """Delete the caller's profile and all conversation history entries containing their user_id."""
    user_id_str = str(interaction.user.id)

    # Delete profile
    user_profiles.pop(user_id_str, None)
    save_profiles(user_profiles)

    # Delete conversation history entries containing this user_id
    removed = [cid for cid in list(conversation_histories) if user_id_str in cid]
    for cid in removed:
        del conversation_histories[cid]
    save_history(conversation_histories)

    await interaction.response.send_message(
        f"🧹 Done — your profile and {len(removed)} conversation thread(s) have been deleted.",
        ephemeral=True,
    )
    print(f"🧹  User {user_id_str} requested full data removal (profile + {len(removed)} history entries)")


@bot.tree.command(name="seed", description="Show your character seed")
async def slash_seed(interaction: discord.Interaction):
    """Show character seed."""
    user_seed = get_character_seed(interaction.user.id)
    await interaction.response.send_message(f"🎲 Your character seed: **{user_seed}**\n\nUse this seed with /selfie, /pose, or /image to keep your character consistent.")

@bot.tree.command(name="help", description="Show help message")
async def slash_help(interaction: discord.Interaction):
    """Show help message."""
    embed = discord.Embed(title="📖 Bot Commands", color=0x5865F2)

    embed.add_field(name="💬 Chat Commands", value="`/chat <message>` - Chat with the bot\n`/seed` - Show your character seed\n`/help` - Show this message", inline=False)
    embed.add_field(name="🎨 Image Commands", value="`/selfie [description]` - Generate a selfie\n`/pose [description]` - Generate a pose\n`/image <prompt>` - Generate custom image", inline=False)
    embed.add_field(name="👗 Wardrobe Commands", value="`/wardrobe [view/list]` - View outfits\nUse `!wardrobe change <id>` to switch", inline=False)
    embed.add_field(name="🎬 Scene Commands", value="`/scene [view/list]` - View scenes\nUse `.scene change <id>` to switch", inline=False)
    embed.add_field(name="📊 Status Commands", value="`.status <type> <message>` - Change bot status\nTypes: playing, watching, listening, streaming", inline=False)
    embed.add_field(name="🛡️ Mod Commands", value="`.personality`, `.setpersonality`, `.setname`, `.settokens`\n`.setcontextlimit`, `.editpersonality`\n`.resetconvo`, `.resetall`, `.stats`", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.error
async def on_slash_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Handle slash command errors."""
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("⛔ You don't have permission to use this command.", ephemeral=True)
    elif isinstance(error, discord.app_commands.MissingAnyRole):
        await interaction.response.send_message("⛔ You need a specific role to use this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ An error occurred: `{str(error)[:100]}`", ephemeral=True)
        print(f"❌  Slash command error: {error}")
@bot.event
async def on_command_error(ctx, error):
    """Handle command errors gracefully."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("⛔ You don't have permission to use this command.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands
    elif isinstance(error, commands.BadArgument):
        await ctx.send("⚠️  Invalid arguments. Use `!bothelp` for command usage.")
    else:
        await ctx.send(f"⚠️  An error occurred: `{str(error)[:100]}`")
        print(f"❌  Command error: {error}")


#  Run

if __name__ == "__main__":
    print(f"🚀  Starting bot from: {os.path.abspath(__file__)}")
    print(f"📁  History file: {HISTORY_FILE}")
    bot.run(DISCORD_TOKEN)
