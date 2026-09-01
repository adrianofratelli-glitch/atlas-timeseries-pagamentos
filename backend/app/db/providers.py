"""Saúde do provedor: desvio da própria linha de base, não limiar absoluto.

Um adquirente de crédito com mix de risco recusa 23% das transações e está saudável;
um PSP de PIX que recusa 3% está em incidente. Limiar absoluto acusa o primeiro e
perde o segundo — foi exatamente o que o controle negativo plantado mostra.

O detector compara cada provedor consigo mesmo: `$setWindowFields` calcula média
móvel e desvio padrão sobre a janela anterior e o z-score diz de quantos desvios a
janela atual se afastou. É a mesma matemática de um SPC de chão de fábrica, feita
dentro do banco de dados sobre o evento bruto.
"""
from __future__ import annotations

from datetime import datetime

from ..config import (MAX_POINTS, MAX_TIME_MS, Z_MIN_WINDOWS, Z_SCORE_THRESHOLD)
from .client import db, with_retry
from .ranges import label, resolve


def pipeline(provedor: str, start: datetime | None, end: datetime | None, unit: str,
             size: int, janela: int) -> list[dict]:
    match: dict = {"meta.provedor": provedor}
    if start and end:
        match["ts"] = {"$gte": start, "$lt": end}
    return [
        {"$match": match},
        {"$group": {
            "_id": {"$dateTrunc": {"date": "$ts", "unit": unit, "binSize": size}},
            "eventos": {"$sum": 1},
            "recusados": {"$sum": {"$cond": ["$aprovado", 0, 1]}},
            "volume": {"$sum": "$valor"},
            "lat": {"$percentile": {"input": "$latencia_ms", "p": [0.5, 0.99],
                                    "method": "approximate"}},
        }},
        {"$set": {"ts": "$_id",
                  "p50": {"$arrayElemAt": ["$lat", 0]},
                  "p99": {"$arrayElemAt": ["$lat", 1]},
                  "taxa_recusa": {"$cond": [{"$gt": ["$eventos", 0]},
                                            {"$multiply": [100, {"$divide": [
                                                "$recusados", "$eventos"]}]}, 0]}}},
        {"$setWindowFields": {
            "sortBy": {"ts": 1},
            "output": {
                # A janela termina em -1: a linha de base é o passado do provedor,
                # sem incluir a janela que está sendo julgada. Incluir a própria
                # janela dilui o desvio justamente quando ele importa.
                "recusa_base": {"$avg": "$taxa_recusa",
                                "window": {"documents": [-janela, -1]}},
                "recusa_desvio": {"$stdDevSamp": "$taxa_recusa",
                                  "window": {"documents": [-janela, -1]}},
                "p99_base": {"$avg": "$p99", "window": {"documents": [-janela, -1]}},
                "p99_desvio": {"$stdDevSamp": "$p99",
                               "window": {"documents": [-janela, -1]}},
            }}},
        {"$set": {
            "z_recusa": {"$cond": [
                {"$gt": ["$recusa_desvio", 0]},
                {"$divide": [{"$subtract": ["$taxa_recusa", "$recusa_base"]},
                             "$recusa_desvio"]}, 0]},
            "z_p99": {"$cond": [
                {"$gt": ["$p99_desvio", 0]},
                {"$divide": [{"$subtract": ["$p99", "$p99_base"]}, "$p99_desvio"]}, 0]},
        }},
        {"$set": {"anomalo": {"$or": [{"$gt": ["$z_recusa", Z_SCORE_THRESHOLD]},
                                      {"$gt": ["$z_p99", Z_SCORE_THRESHOLD]}]}}},
        {"$sort": {"ts": 1}},
        {"$project": {"_id": 0, "ts": 1, "eventos": 1, "recusados": 1,
                      "volume": {"$round": ["$volume", 2]},
                      "p50": {"$round": ["$p50", 1]}, "p99": {"$round": ["$p99", 1]},
                      "taxa_recusa": {"$round": ["$taxa_recusa", 3]},
                      "recusa_base": {"$round": ["$recusa_base", 3]},
                      "p99_base": {"$round": ["$p99_base", 1]},
                      "z_recusa": {"$round": ["$z_recusa", 2]},
                      "z_p99": {"$round": ["$z_p99", 2]},
                      "anomalo": 1}},
        {"$limit": MAX_POINTS},
    ]


def saude(provedor: str, hours: float) -> dict:
    start, end, unit, size = resolve(hours)
    janela = Z_MIN_WINDOWS * 4
    pipe = pipeline(provedor, start, end, unit, size, janela)
    linhas = with_retry(lambda: list(
        db().payment_events.aggregate(pipe, maxTimeMS=MAX_TIME_MS)))

    # Incidente = z acima do limiar por Z_MIN_WINDOWS janelas seguidas. Um pico
    # isolado é ruído de amostragem; o que acusa degradação é desvio que não volta.
    streak = melhor = 0
    inicio_pico = fim_pico = None
    atual_inicio = None
    for linha in linhas:
        if linha["anomalo"]:
            streak += 1
            atual_inicio = atual_inicio or linha["ts"]
            if streak > melhor:
                melhor, inicio_pico, fim_pico = streak, atual_inicio, linha["ts"]
        else:
            streak = 0
            atual_inicio = None

    eventos = sum(x["eventos"] for x in linhas)
    recusados = sum(x["recusados"] for x in linhas)
    anomalas = [x for x in linhas if x["anomalo"]]
    return {
        "provedor": provedor,
        "from": start, "to": end,
        "granularity": {"unit": unit, "bin_size": size, "label": label(unit, size)},
        "points": linhas,
        "totals": {"eventos": eventos, "recusados": recusados,
                   "taxa_recusa": round(100 * recusados / eventos, 3) if eventos else 0.0,
                   "volume": round(sum(x["volume"] for x in linhas), 2)},
        "z_threshold": Z_SCORE_THRESHOLD,
        "min_windows": Z_MIN_WINDOWS,
        "longest_streak": melhor,
        "degradado": melhor >= Z_MIN_WINDOWS,
        "pico": {"inicio": inicio_pico, "fim": fim_pico,
                 "z_recusa_max": max((x["z_recusa"] for x in anomalas), default=0.0),
                 "z_p99_max": max((x["z_p99"] for x in anomalas), default=0.0)},
        "pipeline": pipe,
    }


def saude_ao_vivo(provedor: str) -> dict:
    """Mesma matemática sobre `payment_events_live`.

    Bins de 5 s e sem faixa: a TTL de uma hora já delimita o que existe lá, e
    agrupar por minuto devolveria um ponto só nos primeiros minutos.
    """
    janela = Z_MIN_WINDOWS * 4
    pipe = pipeline(provedor, None, None, "second", 5, janela)
    linhas = with_retry(lambda: list(
        db().payment_events_live.aggregate(pipe, maxTimeMS=MAX_TIME_MS)))
    streak = melhor = 0
    for linha in linhas:
        streak = streak + 1 if linha["anomalo"] else 0
        melhor = max(melhor, streak)
    eventos = sum(x["eventos"] for x in linhas)
    recusados = sum(x["recusados"] for x in linhas)
    anomalas = [x for x in linhas if x["anomalo"]]
    return {
        "provedor": provedor, "live": True, "collection": "payment_events_live",
        "from": linhas[0]["ts"] if linhas else None,
        "to": linhas[-1]["ts"] if linhas else None,
        "granularity": {"unit": "second", "bin_size": 5, "label": "5 s"},
        "points": linhas,
        "totals": {"eventos": eventos, "recusados": recusados,
                   "taxa_recusa": round(100 * recusados / eventos, 3) if eventos else 0.0,
                   "volume": round(sum(x["volume"] for x in linhas), 2)},
        "z_threshold": Z_SCORE_THRESHOLD, "min_windows": Z_MIN_WINDOWS,
        "longest_streak": melhor, "degradado": melhor >= Z_MIN_WINDOWS,
        "pico": {"inicio": None, "fim": None,
                 "z_recusa_max": max((x["z_recusa"] for x in anomalas), default=0.0),
                 "z_p99_max": max((x["z_p99"] for x in anomalas), default=0.0)},
        "pipeline": pipe,
    }


def ranking(hours: float, limite: int = 40) -> dict:
    """Placar dos provedores na janela: volume, recusa e p99 lado a lado."""
    start, end, _, _ = resolve(hours)
    pipe = [
        {"$match": {"ts": {"$gte": start, "$lt": end}}},
        {"$group": {"_id": {"provedor": "$meta.provedor", "canal": "$meta.canal"},
                    "eventos": {"$sum": 1},
                    "recusados": {"$sum": {"$cond": ["$aprovado", 0, 1]}},
                    "volume": {"$sum": "$valor"},
                    "lat": {"$percentile": {"input": "$latencia_ms", "p": [0.5, 0.99],
                                            "method": "approximate"}}}},
        {"$set": {"provedor": "$_id.provedor", "canal": "$_id.canal",
                  "p50": {"$arrayElemAt": ["$lat", 0]},
                  "p99": {"$arrayElemAt": ["$lat", 1]},
                  "taxa_recusa": {"$cond": [{"$gt": ["$eventos", 0]},
                                            {"$multiply": [100, {"$divide": [
                                                "$recusados", "$eventos"]}]}, 0]}}},
        {"$lookup": {"from": "provedores", "localField": "provedor",
                     "foreignField": "provedor_id", "as": "cadastro"}},
        {"$set": {"sla_p99_ms": {"$first": "$cadastro.sla_p99_ms"}}},
        {"$set": {"fora_do_sla": {"$gt": ["$p99", "$sla_p99_ms"]}}},
        {"$project": {"_id": 0, "cadastro": 0, "lat": 0}},
        {"$sort": {"eventos": -1}},
        {"$limit": limite},
    ]
    linhas = with_retry(lambda: list(
        db().payment_events.aggregate(pipe, maxTimeMS=MAX_TIME_MS)))
    for linha in linhas:
        for campo in ("p50", "p99", "taxa_recusa", "volume"):
            if linha.get(campo) is not None:
                linha[campo] = round(linha[campo], 2)
    return {"from": start, "to": end, "providers": linhas, "pipeline": pipe}
