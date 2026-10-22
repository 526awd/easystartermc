"""Local settings and Minecraft directory discovery."""
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

if getattr(sys, "frozen", False) and platform.system() == "Darwin":
    APP_DIR = Path.home() / "Library" / "Application Support" / "MC TUI"
else:
    APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
               else Path(__file__).resolve().parent.parent)
CONFIG_PATH = APP_DIR / "launcher.json"


def default_game_dir() -> Path:
    if os.environ.get("MINECRAFT_DIR"):
        return Path(os.environ["MINECRAFT_DIR"]).expanduser()
    if platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", Path.home())) / ".minecraft"
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/minecraft"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "minecraft"


def load() -> dict[str, Any]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def game_dir(config: dict[str, Any]) -> Path:
    return Path(config.get("minecraft_dir") or default_game_dir()).expanduser()
