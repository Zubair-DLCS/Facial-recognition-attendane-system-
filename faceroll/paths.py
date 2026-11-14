"""Locations of bundled models and of the user's data folder."""

import os
import sys
from pathlib import Path

from . import APP_NAME


def resource_dir() -> Path:
    """Folder holding bundled resources (works from source and from a PyInstaller build)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def models_dir() -> Path:
    return resource_dir() / "models"


def data_dir() -> Path:
    """Per-user data folder: %APPDATA%\\FaceRoll on Windows, ~/.faceroll elsewhere.

    Set FACEROLL_DATA to override (useful for a portable USB install or for tests).
    """
    override = os.environ.get("FACEROLL_DATA")
    if override:
        path = Path(override)
    elif os.name == "nt" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / APP_NAME
    else:
        path = Path.home() / f".{APP_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "faceroll.db"
