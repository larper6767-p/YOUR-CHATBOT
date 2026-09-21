"""System-prompt assembly for chat requests."""
from __future__ import annotations

from .config import MOOD_DESCRIPTORS
from .memory import retrieve_relevant_facts, time_context
from .storage import load_scenes, load_wardrobe
from .utils import get_scene_detail


def _describe(val: float, buckets) -> str:
    label = buckets[0][1]
    for threshold, desc in buckets:
        if val >= threshold:
            label = desc
    return label


def mood_to_prompt(mood: dict) -> str:
    if not mood:
        return ""
    return (
        "\n\n[YOUR CURRENT MOOD]\n"
        f"- Affection: {_describe(mood.get('affection', 0.6), MOOD_DESCRIPTORS['affection'])}\n"
        f"- Energy: {_describe(mood.get('energy', 0.7), MOOD_DESCRIPTORS['energy'])}\n"
        f"- Playfulness: {_describe(mood.get('playfulness', 0.7), MOOD_DESCRIPTORS['playfulness'])}\n"
        "Let these subtly shape your tone. Don't announce them."
    )


def build_system_prompt(char: dict, profile: dict, user_text: str, scope_cid: str, char_key: str) -> str:
    """Assemble the full system prompt (character + outfit + scene + memory)."""
    system_prompt = char.get("system_prompt", char.get("systemPrompt", ""))

    wardrobe = load_wardrobe(char_key)
    scenes = load_scenes(char_key)

    current_outfit_id = wardrobe.get("current_outfit", "poolside_bikini")
    current_outfit = wardrobe.get("outfits", {}).get(current_outfit_id, {})
    current_scene_id = scenes.get("current_scene", "poolside")
    current_scene = scenes.get("scenes", {}).get(current_scene_id, {})

    outfit_context = f"\n\n[CURRENT OUTFIT: {current_outfit.get('name', 'Unknown')}]\n{current_outfit.get('appearance', '')}"
    scene_detail = get_scene_detail(current_scene)
    scene_context = f"\n\n[CURRENT SCENE: {current_scene.get('name', 'Unknown')}]\n{current_scene.get('atmosphere', '')}"
    if scene_detail:
        scene_context += f"\n{scene_detail}"

    prompt = system_prompt + outfit_context + scene_context

    user_prefs = char.get("user_prefs", {})
    narration_pref = user_prefs.get(scope_cid, char.get("advanced", {}).get("narration_style", "first_person"))
    if "first" in narration_pref:
        prompt += "\n\n[NARRATION MODE: First-person]"

    if profile.get("memory_summary"):
        prompt += f"\n\n[RELATIONSHIP SUMMARY]\n{profile['memory_summary']}"
    prompt += retrieve_relevant_facts(profile, user_text)
    prompt += f"\n\n[RELATIONSHIP STAGE: {profile.get('relationship_stage', 'new')}]"
    prompt += mood_to_prompt(profile.get("mood", {}))
    prompt += time_context(profile)

    return prompt
