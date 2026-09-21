# Yourchatbot

A personal AI chatbot for Discord. Give it a character, a wardrobe, and a set of
scenes, and it stays in character while remembering who it's talking to.

- **Multiple characters** — switch per DM or per server
- **Wardrobe & scenes** — the character's current outfit and setting are woven into every reply
- **Long-term memory** — rolling summaries, extracted facts, and mood that drifts over time
- **Time awareness** — the bot knows the user's local time and how long it's been since you talked
- **Prefix and slash commands** — everything works with both `.command` and `/command`

## Requirements

- Python 3.11+ (developed on 3.13)
- A Discord bot token and any OpenAI-compatible API key (the default config points at agnes.ai)

## Setup

1. Create and activate a virtual environment, then install dependencies:

   ```sh
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   # source .venv/bin/activate # macOS / Linux
   pip install -r requirements.txt
   ```

2. Copy `.example.env` to `.env` and fill in your credentials:

   ```sh
   copy .example.env .env      # Windows
   # cp .example.env .env      # macOS / Linux
   ```

   ```
   DISCORD_TOKEN=your-discord-bot-token
   AGNES_API_KEY=your-api-key
   ```

3. Enable the **Message Content** intent for your bot in the Discord Developer
   Portal (the bot reads messages to reply when mentioned or DM'd).

4. Start the bot from the project root:

   ```sh
   python bot.py
   ```

## Project structure

```
Yourchatbot/
├── bot.py                  # entry point — wires modules together and runs the bot
├── requirements.txt
├── yourbot/                # application package
│   ├── config.py           # paths, environment, API clients, constants, default schemas
│   ├── storage.py          # in-memory state + JSON persistence (characters, history, profiles)
│   ├── utils.py            # scope keys, token budgeting, chunked sending, reply cleanup
│   ├── memory.py           # mood, long-term facts, summaries, time awareness
│   ├── prompts.py          # system-prompt assembly
│   ├── llm.py              # model calls + the shared chat-turn pipeline
│   ├── events.py           # on_ready / on_message / error handlers
│   └── commands/           # command definitions, grouped by domain
│       ├── character.py    # .character
│       ├── wardrobe.py     # .wardrobe
│       ├── scene.py        # .scene
│       ├── personality.py  # .personality, .editpersonality, .setname, .settokens, .status, ...
│       ├── user.py         # .profile, .verify, .forgetme, .timezone, .narration, .export, ...
│       ├── help.py         # .bothelp
│       └── slash.py        # all slash commands (/chat, /character, ...)
└── data/                   # everything mutable lives here
    ├── characters/         # one JSON file per character (e.g. marin.json)
    ├── histories/          # conversation_history.json (+ rolling backup)
    ├── profiles/           # user_profiles.json
    └── legacy/             # old single-file data, kept for backward compatibility
```

### How it fits together

`bot.py` imports `yourbot.config` (which builds the shared Discord client and API
clients), then the command modules (which register themselves on that client),
then `yourbot.events` (which registers the gateway listeners). All mutable state
is owned by `yourbot.storage`, and the chat request pipeline lives in
`yourbot.llm.process_chat_turn`, so the message listener and the `/chat` slash
command share one implementation.

## Adding a character

Characters live in `data/characters/<key>.json`. The easiest way to add one is in
Discord:

```
.character add      # interactive prompt for id, name, title, description, and system prompt
.character switch <key>
```

Per-character wardrobe and scene overrides are stored alongside as
`data/characters/<key>_wardrobe.json` and `<key>_scenes.json`.

## Commands

### Everyone

| Command | Description |
| --- | --- |
| `@bot <message>` / `/chat <message>` | Chat with the bot |
| `.verify` / `/verify` | Confirm you're 18+ to unlock the bot |
| `.profile` / `/profile` | View your profile, mood, and remembered facts |
| `.forgetme` / `/forgetme` | Delete your profile and conversation history |
| `.resetconvo` | Clear your conversation history |
| `.export` | Export your conversation history as JSON |
| `.timezone <hours>` / `/timezone <hours>` | Set your UTC offset |
| `.narration [first\|third]` | Switch narration mode |
| `.contextinfo` | Show current token usage |

### Characters, wardrobe & scenes

| Command | Description |
| --- | --- |
| `.character list \| switch <key> \| add \| edit <key> \| remove <key> \| view <key> \| reload` | Manage characters |
| `/character list \| switch <key>` | Manage characters (slash) |
| `.wardrobe [list \| change <id> \| add \| edit <id> \| remove <id>]` | Manage outfits |
| `.scene [list \| change <id> \| add \| edit <id> \| remove <id>]` | Manage scenes |

### Moderators (requires *Manage Messages*)

| Command | Description |
| --- | --- |
| `.personality` | View the active character's settings |
| `.editpersonality` | Interactively edit the active character |
| `.setpersonality <prompt>` | Replace the system prompt (clears history) |
| `.setname <name>` | Change the character's display name |
| `.settokens <amount>` | Set the max response length |
| `.setcontextlimit <tokens>` | Set the context window size |
| `.status <type> <message>` | Change the bot's Discord status |
| `.resetall` | Clear every conversation history |
| `.stats` | Show bot statistics |

## Notes on data & privacy

Conversation history and user profiles are written to `data/histories/` and
`data/profiles/` and are git-ignored so private chat data isn't committed. Delete
them (or run `/forgetme`) to reset all stored state.
