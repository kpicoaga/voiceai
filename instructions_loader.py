"""Instructions loader for AI coach configuration."""
import json
from pathlib import Path

# Path to the instructions JSON file, resolved next to this module so the bot
# works no matter which directory it is launched from.
INSTRUCTIONS_PATH = Path(__file__).resolve().parent / "instructions.json"


def load_instructions():
    """Load coach instructions from JSON file.

    Returns:
        dict: Parsed instructions containing coach_instructions, tools, and runtime config.

    Raises:
        FileNotFoundError: If the instructions JSON file doesn't exist.
        json.JSONDecodeError: If the JSON file is malformed.
    """
    if not INSTRUCTIONS_PATH.exists():
        raise FileNotFoundError(f"Instructions file not found: {INSTRUCTIONS_PATH}")

    with open(INSTRUCTIONS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_coach_instructions():
    """Get coach instructions from JSON file.

    Returns:
        str: The coach instructions text.

    Raises:
        FileNotFoundError: If the instructions JSON file doesn't exist.
        json.JSONDecodeError: If the JSON file is malformed.
        KeyError: If the expected keys are not present in the JSON.
    """
    instructions = load_instructions()
    return instructions["coach_instructions"]["text"]


def get_tool_config():
    """Get the tool definitions (name, description, args) from the JSON file.

    Returns:
        list[dict]: Tool definitions in the order they appear in the file.
    """
    return load_instructions().get("tools", [])


def get_tool_instructions():
    """Get tool-specific instructions from JSON file.

    Returns:
        dict[str, str | None]: Mapping of tool name to its ``instructions_for_you``
        text, e.g. ``{"start_dialogue": "...", "finish_dialogue": "..."}``.

    Raises:
        FileNotFoundError: If the instructions JSON file doesn't exist.
        json.JSONDecodeError: If the JSON file is malformed.
    """
    return {
        tool.get("name"): tool.get("instructions_for_you")
        for tool in get_tool_config()
        if tool.get("name")
    }


def get_runtime_config():
    """Get runtime configuration from JSON file.

    Returns:
        dict: Runtime configuration including model, voice, and transcription settings.

    Raises:
        FileNotFoundError: If the instructions JSON file doesn't exist.
        json.JSONDecodeError: If the JSON file is malformed.
    """
    instructions = load_instructions()
    return instructions.get("runtime", {})
