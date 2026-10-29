"""Instructions loader for AI coach configuration."""
import json
import os
from pathlib import Path

# Path to the instructions JSON file
INSTRUCTIONS_PATH = Path("instructions.json")


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


def get_tool_instructions():
    """Get tool-specific instructions from JSON file.

    Returns:
        tuple: (start_briefing, finish_briefing) instructions.

    Raises:
        FileNotFoundError: If the instructions JSON file doesn't exist.
        json.JSONDecodeError: If the JSON file is malformed.
        KeyError: If the expected keys are not present in the JSON.
    """
    instructions = load_instructions()
    tools = instructions.get("tools", [])

    # start_dialogue is typically at index 1
    start_briefing = tools[1]["instructions_for_you"] if len(tools) > 1 else None

    # finish_dialogue is typically at index 2
    finish_briefing = tools[2]["instructions_for_you"] if len(tools) > 2 else None

    return start_briefing, finish_briefing


def get_runtime_config():
    """Get runtime configuration from JSON file.

    Returns:
        dict: Runtime configuration including model, voice, and transcription settings.

    Raises:
        FileNotFoundError: If the instructions JSON file doesn't exist.
        json.JSONDecodeError: If the JSON file is malformed.
        KeyError: If the expected keys are not present in the JSON.
    """
    instructions = load_instructions()
    return instructions.get("runtime", {})