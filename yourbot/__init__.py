"""Yourchatbot — a personal AI chatbot Discord bot.

The package is split by responsibility:

- :mod:`yourbot.config`   — paths, environment, API clients, constants
- :mod:`yourbot.storage`  — in-memory state and JSON persistence
- :mod:`yourbot.utils`    — scope keys, token budgeting, reply cleanup
- :mod:`yourbot.memory`   — mood, long-term facts, summaries, time awareness
- :mod:`yourbot.prompts`  — system-prompt assembly
- :mod:`yourbot.llm`      — model calls and the shared chat-turn pipeline
- :mod:`yourbot.events`   — Discord gateway listeners and error handlers
- :mod:`yourbot.commands` — prefix and slash command definitions

Run the bot with ``python bot.py`` from the project root.
"""
