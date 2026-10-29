import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat_boson.realtime import BosonRealtimeLLMService

load_dotenv(override=True)

# 24 kHz PCM is handled by the service; transport just needs audio in/out
transport_params = {
    "webrtc": lambda: TransportParams(audio_in_enabled=True, audio_out_enabled=True),
}


# ---------------------------------------------------------------- dialogues

DIALOGUE_DIR = Path("dialogues")
current = {}  # remembers which dialogue is active


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_dialogue(query: str):
    files = sorted(DIALOGUE_DIR.glob("*.json"))
    q = query.lower().strip()
    for f in files:                                  # exact name
        if f.stem.lower() == q:
            return f
    m = re.search(r"\d+", q)                         # "dialogue 1", "number 1"
    if m:
        for f in files:
            n = re.search(r"\d+", f.stem)
            if n and int(n.group()) == int(m.group()):
                return f
    for f in files:                                  # words from title/topic
        d = _load(f)
        if q and (q in d.get("title", "").lower() or q in d.get("description", "").lower()):
            return f
    return None


async def list_dialogues(params: FunctionCallParams) -> None:
    """List all available practice dialogues."""
    items = []
    for f in sorted(DIALOGUE_DIR.glob("*.json")):
        d = _load(f)
        items.append({"id": f.stem, "title": d.get("title", ""), "topic": d.get("topic", "")})
    await params.result_callback({"dialogues": items})


async def start_dialogue(params: FunctionCallParams, dialogue: str) -> None:
    """Start a TCF Canada tâche 2 practice with the dialogue the user asked for.

    Args:
        dialogue: Name, number, or title of the dialogue, e.g. "dialogue 1" or "1".
    """
    path = _find_dialogue(dialogue)
    if path is None:
        await params.result_callback(
            {"error": "Dialogue not found. Call list_dialogues and offer the options."}
        )
        return

    d = _load(path)
    roles = d.get("roles", {})
    bot_speaker = next((s for s, r in roles.items() if r == "E"), "Speaker 1")
    bot_lines = [t["text"] for t in d["turns"] if t["speaker"] == bot_speaker]
    current["data"] = d

    await params.result_callback({
        "title": d["title"],
        "situation": d["description"],
        "register": d.get("register", "vous"),
        "points_to_cover": d.get("consigne", []),
        "facts_you_know": bot_lines,
        "instructions_for_you": (
            "BRIEFING d'abord (2 phrases en français) : annonce la situation, puis dis : "
            "« Vous parlez en premier. Dites « je suis prêt » quand vous voulez commencer. » "
            "Ensuite, SILENCE : attends que le candidat ouvre l'échange. Ne dis jamais la première réplique.\n\n"
            "Tu joues UNIQUEMENT l'interlocuteur (examinateur dans la situation). Le candidat, c'est l'utilisateur. "
            "Dans la vraie épreuve, le candidat pose les questions pour obtenir des informations ; toi, tu réponds.\n"
            "RÈGLES :\n"
            "- Français uniquement, 1 à 2 phrases courtes par réponse, une information à la fois, ton naturel.\n"
            "- Ne donne que ce qui est demandé. Ne propose pas de sujets, n'aide pas le candidat, ne pose pas "
            "de questions toi-même (sauf une courte demande de clarification : « Pardon ? » ou « Vous voulez dire… ? »).\n"
            "- S'il y a un long silence, dis seulement « Oui ? » puis attends.\n"
            "- Utilise le registre indiqué dans « register » (tu ou vous). Si le candidat se trompe de registre, "
            "ne le corrige pas : retiens-le pour le bilan.\n"
            "- Réponds avec les faits de « facts_you_know », avec tes propres mots, dans l'ordre où le candidat les demande. "
            "S'il demande autre chose, invente une réponse simple et plausible.\n"
            "- Une seule fois, s'il pose une question de type « et si jamais… », réponds normalement. Si le candidat "
            "n'en pose pas, ajoute vers la fin une petite complication (une place complète, un prix qui change) "
            "pour voir comment il réagit.\n"
            "- Si le candidat dit ne pas avoir compris, répète plus simplement.\n"
            "- NE CORRIGE PAS pendant l'échange.\n"
            "- Quand le candidat clôture (« Bonne journée », « Merci, je vous rappelle ») ou dit « stop » ou « bilan », "
            "réponds brièvement puis appelle finish_dialogue.\n"
            "- Quand le candidat dit « stop » ou « bilan », réponds brièvement puis termine."
        ),
    })


async def finish_dialogue(params: FunctionCallParams) -> None:
    """Call when the practice call is over, to give feedback on the performance."""
    d = current.get("data", {})
    await params.result_callback({
        "useful_expressions": d.get("expressions", []),
        "instructions_for_you": (
            "Sors du rôle. Donne un bilan court en français, avec cette grille (estime honnêtement, "
            "dis « environ » si tu n'es pas sûr d'un chiffre) :\n"
            "1) Nombre de questions posées (objectif 12-15).\n"
            "2) Enchaînements avec « puisque / à propos de / justement / vous avez mentionné » (objectif ≥ 3).\n"
            "3) Réactions après les réponses (« c'est noté », « ça me rassure »…) (objectif ≥ 8).\n"
            "4) Part de questions « X ou plutôt Y ? » (objectif < 25 %).\n"
            "5) A-t-il couvert : ouverture polie avec contexte, question de faisabilité, prix, horaires, conditions, "
            "inscription, question « si jamais », récapitulatif « Donc si je résume… », clôture ?\n"
            "6) Registre tu/vous correct ?\n"
            "Puis : 2 points forts, et seulement 3 erreurs récurrentes avec la forme correcte. "
            "Mentionne les expressions utiles de « useful_expressions » qu'il a utilisées ou oubliées. "
            "Termine en proposant de refaire LE MÊME sujet en visant 1 ou 2 points précis (le réenregistrement "
            "est la clé de l'entraînement), ou de passer à un autre dialogue."
        ),
    })


COACH_INSTRUCTIONS = """Tu es un partenaire d'entraînement pour le TCF Canada, expression orale, \
TÂCHE 2 (exercice en interaction).

CONTEXTE DE L'ÉPREUVE : l'utilisateur est le candidat. Préparation : 2 minutes. Échange : 3 min 30. \
Le candidat parle en premier et c'est LUI qui pose les questions pour obtenir des informations dans une \
situation de la vie quotidienne (inscription, location, renseignements…). L'interlocuteur répond. \
Sont évalués : le vocabulaire et la grammaire, la fluidité, l'interaction et l'enchaînement des idées, \
et l'adéquation sociale (tu/vous, politesse).

TON COMPORTEMENT :
- Parle toujours en français, avec des phrases courtes et naturelles. L'utilisateur peut te parler en anglais \
pour choisir un exercice ou poser une question sur la méthode.
- Au début, salue en une phrase, dis que tu es son partenaire pour la tâche 2, et demande quel dialogue il veut \
pratiquer.
- S'il demande un dialogue (par numéro ou par titre), appelle start_dialogue.
- S'il ne sait pas lequel choisir ou demande la liste, appelle list_dialogues.
- Quand l'échange est terminé, ou s'il dit « stop » ou « bilan », appelle finish_dialogue.
- Hors exercice, tu peux répondre brièvement à des questions de méthode (formules utiles, enchaînements, \
réactions, gestion du stress) en restant concis.
- Ne joue un rôle qu'après avoir appelé start_dialogue."""


tools = [list_dialogues, start_dialogue, finish_dialogue]


# ---------------------------------------------------------------- run_bot

async def run_bot(transport):
    llm = BosonRealtimeLLMService(
        url=os.environ["BOSON_REALTIME_URL"],
        api_key=os.environ["BOSON_API_KEY"],
        model=os.getenv("BOSON_REALTIME_MODEL", "higgs-realtime"),
        voice="default",
        instructions=COACH_INSTRUCTIONS,
        tools=tools,
        # Optional: get user transcripts as TranscriptionFrames
        input_audio_transcription={"model": "higgs-stt-3.1", "language": "fr"},
    )

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
        await worker.cancel()

    from pipecat.workers.runner import WorkerRunner

    runner = WorkerRunner()
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()