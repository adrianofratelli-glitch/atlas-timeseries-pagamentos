"""Configuração por ambiente. Toda constante que a demo ajusta mora aqui."""
from __future__ import annotations

import os

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT, ".env"))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


MONGODB_URI = os.environ["MONGODB_URI"]
MONGODB_DB = os.getenv("MONGODB_DB", "energia_medicao")

MAX_TIME_MS = _int("TS_MAX_TIME_MS", 15000)
MAX_RANGE_DAYS = _int("TS_MAX_RANGE_DAYS", 90)
MAX_POINTS = _int("TS_MAX_POINTS", 4000)

LOSS_THRESHOLD_PCT = _float("LOSS_THRESHOLD_PCT", 10.0)
LOSS_MIN_WINDOWS = _int("LOSS_MIN_WINDOWS", 6)

READING_INTERVAL_MINUTES = _int("READING_INTERVAL_MINUTES", 15)
ARCHIVE_ENABLED = os.getenv("ARCHIVE_ENABLED", "false").lower() == "true"

KWH_TARIFF = _float("KWH_TARIFF", 0.78)
FIELD_INSPECTION_COST = _float("FIELD_INSPECTION_COST", 180.0)
CURRENCY = os.getenv("CURRENCY", "R$")

BACKEND_PORT = _int("BACKEND_PORT", 8400)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
