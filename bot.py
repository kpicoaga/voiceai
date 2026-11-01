"""TCF Canada Tâche 2 voice coach, configured from instructions.json.

The coach prompt, tool descriptions, per-tool briefings, and runtime settings
(model, voice, transcription, transport) all come from ``instructions.json``;
this file only implements the behaviour the tools need.
"""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.workers.runner import WorkerRunner
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat_boson.realtime import BosonRealtimeLLMService

from instructions_loader import (
    get_coach_instructions,
    get_runtime_config,
    get_tool_config,
    get_tool_instructions,
)

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------- config

COACH_INSTRUCTIONS = get_coach_instructions()
TOOL_CONFIG = {tool["name"]: tool for tool in get_tool_config()}
TOOL_INSTRUCTIONS = get_tool_instructions()
RUNTIME = get_runtime_config()

DIALOGUE_DIR = Path(os.getenv("DIALOGUES_DIR", BASE_DIR / "dialogues"))

# 24 kHz PCM is handled by the service; transport just needs audio in/out
transport_params = {
    RUNTIME.get("transport", "webrtc"): lambda: TransportParams(
        audio_in_enabled=RUNTIME.get("audio_in_enabled", True),
        audio_out_enabled=RUNTIME.get("audio_out_enabled", True),
    ),
}


# ---------------------------------------------------------------- dialogues

current = {}  # remembers which dialogue is active


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_dialogue(query: str):
    files = sorted(DIALOGUE_DIR.glob("*.json"))
    q = (query or "").lower().strip()
    if not q:
        return None
    for f in files:                                  # exact name
        if f.stem.lower() == q:
            return f
    m = re.search(r"\d+", q)                         # "dialogue 1", "number 1"
    if m:
        for f in files:
            n = re.search(r"\d+", f.stem)
            if n and int(n.group()) == int(m.group()):
                return f
    for f in files:                                  # words from title/topic/description
        d = _load(f)
        haystack = " ".join(
            str(d.get(k, "")) for k in ("title", "topic", "description")
        ).lower()
        if q in haystack:
            return f
    return None


async def list_dialogues(params: FunctionCallParams) -> None:
    """List all available practice dialogues."""
    items = []
    for f in sorted(DIALOGUE_DIR.glob("*.json")):
        d = _load(f)
        items.append(
            {
                "id": f.stem,
                "title": d.get("title", ""),
                "topic": d.get("topic", ""),
                "situation": d.get("description", ""),
            }
        )
    await params.result_callback(
        {
            "dialogues": items,
            "instructions_for_you": TOOL_INSTRUCTIONS.get("list_dialogues") or "",
        }
    )


async def start_dialogue(params: FunctionCallParams, dialogue: str) -> None:
    """Start a TCF Canada tâche 2 practice with the dialogue the user asked for.

    Args:
        dialogue: Name, number, or title of the dialogue, e.g. "dialogue 1" or "1".
    """
    path = _find_dialogue(dialogue)
    if path is None:
        await params.result_callback(
            {
                "error": f"No dialogue matches {dialogue!r}.",
                "instructions_for_you": (
                    "Tell the user that dialogue was not found, then call "
                    "list_dialogues and ask them to choose one."
                ),
            }
        )
        return

    d = _load(path)
    roles = d.get("roles", {})
    bot_speaker = next((s for s, r in roles.items() if r == "E"), "Speaker 1")
    current["data"] = d
    current["id"] = path.stem

    # Pair every answer of the character with the candidate question it responds
    # to, so the model can pick the one fact that was actually asked for instead
    # of reciting the whole list. The hint comes from the candidate turn's note.
    facts = []
    question = None
    for turn in d["turns"]:
        if turn["speaker"] == bot_speaker:
            facts.append(
                {
                    "if_asked_about": (
                        question["text"]
                        if question
                        else "(you are the one being called - do not say this until the user greets you)"
                    ),
                    "answer_with": turn["text"],
                    "note": turn.get("note", ""),
                }
            )
            question = None
        else:
            question = turn

    await params.result_callback(
        {
            "id": path.stem,
            "title": d.get("title", ""),
            "situation": d.get("description", ""),
            "topic": d.get("topic", ""),
            "register": d.get("register", "vous"),
            "points_to_cover": d.get("consigne", []),
            "facts_you_know": facts,
            "useful_expressions": d.get("expressions", []),
            "instructions_for_you": TOOL_INSTRUCTIONS.get("start_dialogue") or "",
        }
    )


async def finish_dialogue(params: FunctionCallParams) -> None:
    """Call when the practice call is over, to give feedback on the performance."""
    d = current.get("data", {})
    await params.result_callback(
        {
            "title": d.get("title", ""),
            "situation": d.get("description", ""),
            "useful_expressions": d.get("expressions", []),
            "instructions_for_you": TOOL_INSTRUCTIONS.get("finish_dialogue") or "",
        }
    )


# ---------------------------------------------------------------- tools

TOOL_HANDLERS = {
    "list_dialogues": lambda params: list_dialogues(params),
    "start_dialogue": lambda params: start_dialogue(
        params, dialogue=str(params.arguments.get("dialogue", ""))
    ),
    "finish_dialogue": lambda params: finish_dialogue(params),
}


def _build_tool_schemas() -> list[FunctionSchema]:
    """Build tool schemas from instructions.json, wired to the handlers above.

    The JSON file is the single source of truth for names, descriptions, and
    parameter descriptions; ``TOOL_HANDLERS`` only supplies the behaviour.
    """
    missing = sorted(set(TOOL_CONFIG) - set(TOOL_HANDLERS))
    if missing:
        raise RuntimeError(
            f"instructions.json defines tools with no implementation: {missing}"
        )

    schemas = []
    for name, config in TOOL_CONFIG.items():
        properties = {}
        required = []
        for arg in config.get("args", []):
            properties[arg["name"]] = {
                "type": "string",
                "description": arg.get("desc", ""),
            }
            required.append(arg["name"])
        schemas.append(
            FunctionSchema(
                name=name,
                description=config.get("description", ""),
                properties=properties,
                required=required,
                handler=TOOL_HANDLERS[name],
            )
        )
    return schemas


# Wrapped so the set satisfies LLMContext's ``ToolsSchema`` parameter type;
# the service and the context then advertise the exact same tool set.
tools = ToolsSchema(standard_tools=_build_tool_schemas())


# ---------------------------------------------------------------- run_bot

def _create_llm() -> BosonRealtimeLLMService:
    missing = [
        key
        for key in ("BOSON_REALTIME_URL", "BOSON_API_KEY")
        if not os.environ.get(key)
    ]
    if missing:
        raise RuntimeError(
            f"Missing environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your Boson credentials."
        )

    kwargs = {
        "url": os.environ["BOSON_REALTIME_URL"],
        "api_key": os.environ["BOSON_API_KEY"],
        "model": os.getenv(
            "BOSON_REALTIME_MODEL", RUNTIME.get("model", "higgs-realtime")
        ),
        "voice": RUNTIME.get("voice", "default"),
        "instructions": COACH_INSTRUCTIONS,
        "tools": tools,
    }
    # Optional: get user transcripts as TranscriptionFrames
    transcription = RUNTIME.get("input_audio_transcription")
    if transcription:
        kwargs["input_audio_transcription"] = transcription
    # Optional sampling temperature (lower = follows the instructions more strictly)
    temperature = RUNTIME.get("temperature")
    if temperature is not None:
        kwargs["temperature"] = temperature
    return BosonRealtimeLLMService(**kwargs)


async def run_bot(transport, runner_args: RunnerArguments | None = None):
    llm = _create_llm()

    context = LLMContext(tools=tools)  # same tool list as the service
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        realtime_service_mode=True,  # required for realtime services
    )

    pipeline = Pipeline(
        [
            transport.input(),
            user_aggregator,
            llm,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        # Make the assistant speak first
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await worker.cancel(reason="client disconnected")

    runner = WorkerRunner(
        handle_sigint=runner_args.handle_sigint if runner_args else True
    )
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
