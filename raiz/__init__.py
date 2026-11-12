"""Raíz: produto em cima do motor de dados (motor/)."""

from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]
MOTOR_DIR = RAIZ_REPO / "motor"

__version__ = "0.1.0"
