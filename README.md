# boson-voice

A real-time French voice conversation coach for the TCF Canada oral exam (Tâche 2: exercice en interaction). The bot plays the role of the interlocutor/examiner while the user practices asking questions to obtain information, then gives structured feedback at the end.

Built on [pipecat-ai](https://github.com/pipecat-ai/pipecat) and the [`pipecat-boson`](https://pypi.org/project/pipecat-boson/) realtime service, using the `higgs-realtime` model for low-latency, spoken, in-language conversation over WebRTC.

## Features

- **TCF Canada oral practice**: the assistant briefs the candidate, plays the interlocutor during the interaction, and delivers a scorecard-style debrief (number of questions asked, linking expressions used, register tu/vous, points covered, strengths and recurring errors).
- **Dialogue selection**: standard practice dialogues live in `dialogues/*.json`. The user asks by name or number, and the assistant starts the matching role-play.
- **Realtime STT**: user audio is transcribed in French (e.g. `higgs-stt-3.1`) so the coach can follow the conversation.

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/)
- A Boson API key (`BOSON_API_KEY`)

## Setup

1. Clone this repository and enter the directory:

   ```sh
   cd boson-voice
   ```

2. Copy the environment template and fill in your Boson API key:

   ```sh
   cp .env.example .env
   # edit .env and set BOSON_API_KEY=...
   ```

   The environment file expects:

   ```sh
   BOSON_API_KEY=bai-xxxx
   BOSON_REALTIME_URL=wss://api.boson.ai/v1/realtime/
   BOSON_REALTIME_MODEL=higgs-realtime
   ```

3. Sync dependencies:

   ```sh
   uv sync
   ```

   This installs `pipecat-ai` and `pipecat-boson[webrtc]` from the lockfile.

4. (Optional) Check that the `instructions.json` coach configuration is valid JSON:

   ```sh
   uv run python -c "import json; json.load(open('instructions.json'))"
   ```

## Run the bot

```sh
uv run python bot.py
```

That starts the Pipecat development runner (a FastAPI server) on
<http://localhost:7860>. Open <http://localhost:7860/client/> in your browser and
click **Connect** to start a voice session.

Useful flags:

```sh
uv run python bot.py --host 0.0.0.0 --port 8080   # bind elsewhere
uv run python bot.py -t webrtc                     # restrict to the WebRTC transport
```

The coach greets you in English, asks which dialogue you want to practice, then
runs the roleplay in French and the debrief in English.

## Project layout

| Path | Purpose |
| --- | --- |
| `bot.py` | Pipecat pipeline: realtime LLM service (`BosonRealtimeLLMService`), dialogue tools (`list_dialogues`, `start_dialogue`, `finish_dialogue`), WebRTC transport |
| `dialogues/*.json` | Practice dialogues (title, description, roles, turns, expressions) |
| `instructions.json` | Single source of truth: coach prompt, tool descriptions/args, per-tool briefings (`instructions_for_you`), and runtime config (model, voice, transcription, transport) |
| `instructions_loader.py` | Loads `instructions.json` for `bot.py` |
| `main.py` | Minimal entry-point stub |
| `.env` | Secrets (Boson API key, realtime URL, model) — never commit |

## How it works

`bot.py` builds a pipecat pipeline: WebRTC audio in → user context aggregator → `BosonRealtimeLLMService` → WebRTC audio out → assistant context aggregator. The coach prompt, the three tool descriptions and arguments, and the runtime settings are all read from `instructions.json`; `bot.py` supplies the behaviour behind `list_dialogues`, `start_dialogue`, and `finish_dialogue`, and each returns its `instructions_for_you` text with its result so the model gets the step-specific briefing. When the user picks a dialogue, `start_dialogue` loads it from `dialogues/`; when the exchange ends, `finish_dialogue` collects the expressions and briefing for the debrief.