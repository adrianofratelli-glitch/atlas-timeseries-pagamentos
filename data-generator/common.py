"""Base do gerador: conexão, ids determinísticos e a curva de carga.

A curva é a parte que decide se a demo sobrevive a um engenheiro de distribuidora
na sala. Uma senoide genérica é reconhecida como falsa em segundos; o que se
espera é ombro matinal, ponta noturna, fim de semana deslocado e ruído que não
some quando se soma o transformador inteiro.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

NS = uuid.UUID("6f9b1c2e-0a4d-4f3b-9c11-2f7d5a8e4b60")

SEED = int(os.getenv("SEED", "42"))
INTERVAL_MIN = int(os.getenv("READING_INTERVAL_MINUTES", "15"))
PER_DAY = (24 * 60) // INTERVAL_MIN


def det_id(kind: str, *parts) -> str:
    """uuid5 sobre as chaves de negócio: rodar duas vezes reescreve o mesmo documento."""
    return str(uuid.uuid5(NS, kind + "|" + "|".join(str(p) for p in parts)))


_CLIENT: MongoClient | None = None


def client() -> MongoClient:
    """Cliente único por processo.

    Abrir um MongoClient por chamada re-resolve o registro SRV toda vez; o
    experimento de bucket derrubou o DNS local ("resolution lifetime expired")
    antes de carregar a primeira variante.
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = MongoClient(os.environ["MONGODB_URI"], retryWrites=True, w="majority",
                              serverSelectionTimeoutMS=30000)
    return _CLIENT


def db(name: str | None = None):
    return client()[name or os.getenv("MONGODB_DB", "energia_medicao")]


# ---------------------------------------------------------------- classes de consumo
# kwh_dia: consumo médio diário; perfil: forma horária normalizada (soma = 1).
CLASSES = {
    "residencial_b1": {"share": 0.72, "kwh_dia": (4.0, 12.0)},
    "residencial_b1_alta": {"share": 0.10, "kwh_dia": (14.0, 30.0)},
    "comercial_b3": {"share": 0.14, "kwh_dia": (25.0, 90.0)},
    "industrial_a4": {"share": 0.04, "kwh_dia": (120.0, 400.0)},
}

# Forma da curva por hora do dia (0..23), antes de normalizar.
_SHAPES = {
    "residencial_b1": [
        0.45, 0.38, 0.34, 0.32, 0.33, 0.42, 0.70, 0.95, 0.88, 0.72, 0.65, 0.68,
        0.72, 0.68, 0.64, 0.66, 0.78, 1.05, 1.55, 1.90, 1.75, 1.30, 0.90, 0.60,
    ],
    "residencial_b1_alta": [
        0.60, 0.52, 0.48, 0.46, 0.47, 0.55, 0.80, 1.00, 0.95, 0.85, 0.82, 0.85,
        0.90, 0.88, 0.85, 0.88, 0.98, 1.20, 1.60, 1.85, 1.70, 1.35, 1.00, 0.75,
    ],
    # Comércio: abre às 8, almoço marcado, fecha às 19, domingo quase nada.
    "comercial_b3": [
        0.22, 0.20, 0.19, 0.19, 0.20, 0.25, 0.45, 0.90, 1.55, 1.75, 1.80, 1.78,
        1.60, 1.70, 1.80, 1.78, 1.70, 1.55, 1.20, 0.70, 0.40, 0.30, 0.26, 0.24,
    ],
    # Indústria: dois turnos, base alta, pouca variação.
    "industrial_a4": [
        0.70, 0.68, 0.68, 0.68, 0.70, 0.85, 1.20, 1.45, 1.50, 1.50, 1.48, 1.45,
        1.30, 1.45, 1.50, 1.50, 1.45, 1.30, 1.05, 0.90, 0.82, 0.78, 0.74, 0.72,
    ],
}

# Multiplicador do dia da semana (0=segunda). Comércio e indústria caem no domingo.
_WEEKDAY = {
    "residencial_b1": [1.00, 1.00, 1.00, 1.00, 1.02, 1.12, 1.15],
    "residencial_b1_alta": [1.00, 1.00, 1.00, 1.00, 1.02, 1.12, 1.15],
    "comercial_b3": [1.00, 1.00, 1.00, 1.00, 1.03, 0.80, 0.30],
    "industrial_a4": [1.00, 1.00, 1.00, 1.00, 0.98, 0.72, 0.55],
}


def mean_weekday(klass: str) -> float:
    """Fator médio de dia da semana da classe.

    A energia de um medidor comercial cai a 30% no domingo e a de um residencial
    sobe 15%. Ponderar a verdade de terra só pelo consumo médio diário fez o gap
    esperado do cenário divergir 11 pontos do gap medido em um dia isolado, e
    inverteu a ordem entre "severo" e "moderado". O peso correto é semanal.
    """
    return float(np.mean(_WEEKDAY[klass]))


def _interp_to_interval(shape24: list[float]) -> np.ndarray:
    """Interpola a forma horária para o passo de leitura, fechando o ciclo em 24 h."""
    hours = np.arange(24)
    fine = np.linspace(0, 24, PER_DAY, endpoint=False)
    wrapped = np.concatenate([shape24, shape24[:1]])
    return np.interp(fine, np.concatenate([hours, [24]]), wrapped)


_PROFILE = {k: _interp_to_interval(v) for k, v in _SHAPES.items()}


def day_curve(rng: np.random.Generator, klass: str, kwh_dia: float, weekday: int,
              temp_factor: float) -> np.ndarray:
    """kWh por intervalo para um dia. Soma ≈ kwh_dia × sazonalidade × dia da semana."""
    base = _PROFILE[klass]
    base = base / base.sum()
    total = kwh_dia * _WEEKDAY[klass][weekday] * temp_factor
    # Ruído multiplicativo por intervalo + um deslocamento suave do horário de ponta.
    noise = rng.lognormal(mean=0.0, sigma=0.18, size=PER_DAY)
    shift = int(rng.integers(-2, 3))  # até ±30 min de variação no pico
    return np.roll(base, shift) * total * noise


def temperature_factor(day: datetime, rng: np.random.Generator) -> float:
    """Sazonalidade simples do hemisfério sul: verão puxa ar-condicionado."""
    doy = day.timetuple().tm_yday
    seasonal = 1.0 + 0.18 * np.cos(2 * np.pi * (doy - 15) / 365.0)
    return float(seasonal * rng.normal(1.0, 0.04))


def slots(day: datetime) -> list[datetime]:
    return [day + timedelta(minutes=INTERVAL_MIN * i) for i in range(PER_DAY)]


def utc_midnight(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
