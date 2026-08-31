"""API do PoV. Só expõe HTTP e traduz exceção em status.

Nenhuma rota importa pymongo: toda consulta vive em app/db/. É o que permite trocar
driver ou versão sem tocar em rota.
"""
from __future__ import annotations

import json
import queue
import time
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError, ExecutionTimeout

from app import config
from app.db import assets, balance, cases, curve, storage
from app.db.client import db
from app.db.ranges import RangeError
from app.services import limits
from app.services.alerts import hub
from app.services.live import feed

app = FastAPI(title="Medição inteligente · MongoDB Atlas time series", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    hub.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    hub.stop()


def _json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _timed(fn, kind: str):
    """Executa medindo o tempo de servidor e devolve (payload, ms)."""
    t0 = time.perf_counter()
    with limits.slot(kind):
        try:
            out = fn()
        except RangeError as exc:
            raise HTTPException(status_code=422, detail={
                "reason": exc.detail, "max_range_days": exc.max_range_days}) from exc
        except ExecutionTimeout as exc:
            raise HTTPException(status_code=503, detail={
                "reason": "consulta excedeu maxTimeMS",
                "max_time_ms": config.MAX_TIME_MS, "detail": str(exc)}) from exc
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


# ----------------------------------------------------------------------- saúde
@app.get("/health")
def health():
    d = db()
    try:
        d.command("ping")
        collections = set(d.list_collection_names())
        # A contagem vem de dataset_info, gravado pelo gerador. Em uma coleção time
        # series com 58 M medições, estimated_document_count() leva ~3 s — e o health
        # é a primeira chamada da tela, então esses 3 s eram 3 s de "sem conexão"
        # aparecendo para a plateia.
        info = d.dataset_info.find_one({"_id": "readings"}) or {}
        readings = info.get("measurements")
        if readings is None:
            readings = d.readings.estimated_document_count() if "readings" in collections else 0
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail={"reason": str(exc)}) from exc
    return {
        "status": "ok",
        "database": config.MONGODB_DB,
        "readings": readings,
        "flat_sample": "readings_flat" in collections,
        "change_stream": hub.state,
        "live": feed.status(),
        "change_stream_error": hub.last_error,
        "archive_enabled": config.ARCHIVE_ENABLED,
        "thresholds": {"loss_pct": config.LOSS_THRESHOLD_PCT,
                       "min_windows": config.LOSS_MIN_WINDOWS},
    }


@app.get("/health/live")
def live():
    return {"status": "ok"}


# ---------------------------------------------------------------------- cadastro
@app.get("/api/transformers")
def list_transformers(limit: int = Query(200, ge=1, le=1000)):
    return {"transformers": assets.transformers(limit)}


@app.get("/api/transformers/{transformer_id}/meters")
def list_meters(transformer_id: str, limit: int = Query(500, ge=1, le=2000)):
    return {"meters": assets.meters_of(transformer_id, limit)}


@app.get("/api/meters/{meter_id}")
def get_meter(meter_id: str):
    m = assets.meter(meter_id)
    if not m:
        raise HTTPException(status_code=404, detail={"reason": "medidor não encontrado"})
    return m


@app.get("/api/scenarios")
def list_scenarios():
    """Verdade de terra dos cenários plantados. Rotulada como tal na tela."""
    return {"scenarios": assets.scenarios(), "demo_meters": assets.demo_meters(),
            "aviso": "verdade de terra do gerador; a demo confere o balanço contra ela"}


# ------------------------------------------------------------------------ série
@app.get("/api/curve")
def load_curve(meter_id: str, days: float = Query(1.0, gt=0), fill: bool = False,
               live: bool = False):
    return _timed(lambda: curve.load_curve(meter_id, days, fill, live), "interativo")


@app.get("/api/balance")
def transformer_balance(transformer_id: str, days: float = Query(7.0, gt=0),
                        live: bool = False):
    return _timed(lambda: balance.transformer_balance(transformer_id, days, live),
                  "analitico")


# ------------------------------------------------------------------- ao vivo
class LiveStart(BaseModel):
    transformer_id: str = Field(min_length=3, max_length=64)


@app.post("/api/live/start")
def live_start(body: LiveStart):
    if not db().transformers.find_one({"transformer_id": body.transformer_id},
                                      {"_id": 1}):
        raise HTTPException(status_code=404,
                            detail={"reason": "transformador não encontrado"})
    return feed.start(body.transformer_id)


@app.post("/api/live/stop")
def live_stop():
    return feed.stop()


@app.post("/api/live/clear")
def live_clear():
    return feed.clear()


@app.get("/api/live/status")
def live_status():
    return feed.status()


@app.get("/api/storage")
def storage_comparison():
    return _timed(lambda: storage.comparison(), "storage")


# ------------------------------------------------------------------------ casos
class OpenCase(BaseModel):
    meter_id: str = Field(min_length=3, max_length=64)
    transformer_id: str = Field(min_length=3, max_length=64)
    gap_kwh: float = Field(ge=0)
    gap_pct: float = Field(ge=0, le=100)
    windows: int = Field(ge=0, le=10000)
    opened_by: str = Field(default="demo", max_length=64)
    note: str | None = Field(default=None, max_length=500)


@app.post("/api/cases")
def create_case(body: OpenCase):
    try:
        return cases.open_case(body.meter_id, body.transformer_id, body.gap_kwh,
                               body.gap_pct, body.windows, body.opened_by, body.note)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=409, detail={"reason": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"reason": str(exc)}) from exc


@app.get("/api/cases")
def list_cases(limit: int = Query(50, ge=1, le=200)):
    return {"cases": cases.recent(limit)}


@app.post("/api/cases/{case_id}/close")
def finish_case(case_id: str, outcome: str = Query("confirmado", max_length=64),
                by: str = Query("demo", max_length=64)):
    case = cases.close_case(case_id, outcome, by)
    if not case:
        raise HTTPException(status_code=404, detail={"reason": "caso aberto não encontrado"})
    return case


@app.post("/api/demo/reset")
def reset():
    # Reiniciar a demo também para e apaga a ingestão ao vivo: senão o próximo
    # roteiro começa com a série da apresentação anterior ainda na tela.
    resultado = cases.reset_demo()
    resultado["ao_vivo"] = feed.clear()
    return resultado


# ---------------------------------------------------------------------- alertas
@app.get("/api/alerts/stream")
def alert_stream():
    def events():
        q = hub.subscribe()
        yield "retry: 3000\n\n"
        yield f"event: hello\ndata: {json.dumps({'state': hub.state})}\n\n"
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    yield f"event: alert\ndata: {data}\n\n"
                except queue.Empty:
                    # Keepalive: proxy que fecha conexão ociosa mata a tira de alertas.
                    yield f": keepalive {int(time.time())}\n\n"
        finally:
            hub.unsubscribe(q)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/alerts")
def list_alerts(limit: int = Query(50, ge=1, le=200)):
    rows = list(db().loss_alerts.find({}, {"_id": 0}).sort("at", -1).limit(limit))
    return {"alerts": json.loads(json.dumps(rows, default=_json))}
