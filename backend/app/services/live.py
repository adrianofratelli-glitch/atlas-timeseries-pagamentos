"""Ingestão ao vivo: a série crescendo na tela enquanto a demo acontece.

Escreve em `readings_live`, uma coleção time series **separada** com
`expireAfterSeconds`. Três razões para não escrever em `readings`:

1. A base histórica é a evidência conferida contra a verdade de terra. Injetar
   medição nova nela faria o gap medido divergir do gap esperado no meio da demo.
2. Apagar depois seria caro: em coleção time series o delete é restrito e o TTL
   expira o bucket inteiro, não o documento.
3. A TTL curta é justamente o que permite rodar o roteiro várias vezes no mesmo dia
   sem limpeza manual — o dado ao vivo desaparece sozinho.

O relógio é acelerado, mas **o timestamp gravado é o real**. Cada tick escreve as
medições de `LIVE_MINUTES_PER_TICK` minutos simulados, carimbadas no tempo de relógio
do tick. A primeira versão carimbava o tempo simulado, continuando de onde a base
histórica termina — e como esse instante já estava horas no passado, a TTL de uma hora
apagava a série ao vivo em menos de um minuto.

Consequência para a tela: o eixo X é tempo real (~1 s por tick, 30 min simulados), e o
dado envelhece e expira de verdade. O relógio simulado continua visível no status, para
o apresentador dizer que hora do dia está sendo gerada.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

from ..config import LIVE_MINUTES_PER_TICK, LIVE_TICK_SECONDS, LIVE_TTL_SECONDS
from ..db.client import db

# O gerador é a fonte de verdade da curva; a ingestão ao vivo usa exatamente o mesmo
# modelo, senão a série ao vivo não se parece com a histórica.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "data-generator"))

COLLECTION = "readings_live"


def ensure_collection():
    d = db()
    if COLLECTION not in d.list_collection_names():
        d.create_collection(
            COLLECTION,
            timeseries={"timeField": "ts", "metaField": "meta",
                        # Bucket curto: aqui o objetivo é ver o dado chegar e expirar,
                        # não densidade de armazenamento.
                        "bucketMaxSpanSeconds": 300, "bucketRoundingSeconds": 300},
            expireAfterSeconds=LIVE_TTL_SECONDS)
        d[COLLECTION].create_index([("meta.transformer_id", 1), ("ts", 1)])
        d[COLLECTION].create_index([("meta.meter_id", 1), ("ts", 1)])
    return d[COLLECTION]


class LiveFeed:
    """Um alimentador por vez. Trocar de transformador reinicia o relógio simulado."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.transformer_id: str | None = None
        self.started_at: datetime | None = None
        self.simulated_now: datetime | None = None
        self.written = 0
        self.ticks = 0
        self.state = "parado"
        self.last_error: str | None = None

    # ------------------------------------------------------------------ controle
    def start(self, transformer_id: str) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                if self.transformer_id == transformer_id:
                    return self.status()
                self._stop.set()
                self._thread.join(timeout=5)
            self._stop.clear()
            self.transformer_id = transformer_id
            self.started_at = datetime.now(timezone.utc)
            self.simulated_now = None
            self.written = 0
            self.ticks = 0
            self.last_error = None
            self._thread = threading.Thread(target=self._run, args=(transformer_id,),
                                            name="live-feed", daemon=True)
            self._thread.start()
        # Espera o primeiro tick para que a tela não abra vazia.
        for _ in range(40):
            if self.written:
                break
            time.sleep(0.1)
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        t = self._thread
        if t:
            t.join(timeout=5)
        self.state = "parado"
        return self.status()

    def clear(self) -> dict:
        """Apaga o dado ao vivo agora, sem esperar a TTL."""
        self.stop()
        d = db()
        if COLLECTION in d.list_collection_names():
            d[COLLECTION].drop()
        self.written = 0
        self.ticks = 0
        self.simulated_now = None
        return self.status()

    def status(self) -> dict:
        return {
            "state": self.state,
            "transformer_id": self.transformer_id,
            "started_at": self.started_at,
            "simulated_now": self.simulated_now,
            "written": self.written,
            "ticks": self.ticks,
            "minutes_per_tick": LIVE_MINUTES_PER_TICK,
            "tick_seconds": LIVE_TICK_SECONDS,
            "ttl_seconds": LIVE_TTL_SECONDS,
            "collection": COLLECTION,
            "last_error": self.last_error,
        }

    # ------------------------------------------------------------------ execução
    def _run(self, transformer_id: str) -> None:
        try:
            # Import dentro do try: fora dele, um ImportError morria como traceback de
            # thread e o status continuava dizendo "sem erro".
            import numpy as np

            import common  # noqa: PLC0415 — o gerador vive fora do pacote do backend

            col = ensure_collection()
            d = db()
            transformer = d.transformers.find_one({"transformer_id": transformer_id})
            meters = list(d.meters.find({"transformer_id": transformer_id}))
            if not transformer or not meters:
                self.state = "parado"
                self.last_error = f"transformador {transformer_id} sem medidores"
                return

            rng = np.random.default_rng()
            slots_por_tick = max(LIVE_MINUTES_PER_TICK // common.INTERVAL_MIN, 1)
            # Espaçamento real entre as medições de um tick, para que a série avance
            # continuamente no eixo do relógio em vez de empilhar no mesmo instante.
            passo_real = timedelta(seconds=LIVE_TICK_SECONDS / slots_por_tick)
            # Começa onde a base histórica termina: a série ao vivo continua a
            # anterior em vez de abrir um buraco de dias no gráfico.
            info = d.dataset_info.find_one({"_id": "readings"}) or {}
            inicio = info.get("last_ts")
            inicio = inicio.replace(tzinfo=timezone.utc) if inicio else \
                datetime.now(timezone.utc)
            self.simulated_now = inicio
            self.state = "rodando"

            while not self._stop.is_set():
                docs = []
                dia = self.simulated_now
                agora = datetime.now(timezone.utc)
                instantes = [agora - passo_real * (slots_por_tick - 1 - i)
                             for i in range(slots_por_tick)]
                temp = common.temperature_factor(dia, rng)
                entregue = np.zeros(slots_por_tick)

                for m in meters:
                    curva = common.day_curve(rng, m["customer_class"], m["kwh_dia_base"],
                                             dia.weekday(), temp)
                    primeiro = (dia.hour * 60 + dia.minute) // common.INTERVAL_MIN
                    janela = np.take(curva, range(primeiro, primeiro + slots_por_tick),
                                     mode="wrap")
                    entregue += janela
                    registrado = janela * m["register_factor"]
                    meta = {"meter_id": m["meter_id"], "transformer_id": transformer_id,
                            "feeder_id": m["feeder_id"], "phase": m["phase"],
                            "kind": "medidor"}
                    for i in range(slots_por_tick):
                        docs.append({
                            "ts": instantes[i],
                            "meta": meta,
                            "kwh": round(float(registrado[i]), 4),
                            "voltage": round(float(rng.normal(220.0, 2.2)), 1),
                            "current": round(float(registrado[i]) * 4000 / 220 / 0.92, 3),
                            "power_factor": round(float(rng.normal(0.93, 0.02)), 3),
                            "quality": "ok",
                        })

                perda = 1.0 + transformer["technical_loss"]
                meta_fronteira = {"meter_id": transformer["boundary_meter_id"],
                                  "transformer_id": transformer_id,
                                  "feeder_id": transformer["feeder_id"],
                                  "phase": "ABC", "kind": "fronteira"}
                for i in range(slots_por_tick):
                    docs.append({
                        "ts": instantes[i],
                        "meta": meta_fronteira,
                        "kwh": round(float(entregue[i] * perda), 4),
                        "voltage": round(float(rng.normal(13800.0, 60.0)), 1),
                        "current": round(float(entregue[i] * perda) * 4000 / 13800, 3),
                        "power_factor": round(float(rng.normal(0.96, 0.01)), 3),
                        "quality": "ok",
                    })

                col.insert_many(docs, ordered=False)
                self.written += len(docs)
                self.ticks += 1
                self.simulated_now = dia + timedelta(minutes=LIVE_MINUTES_PER_TICK)
                self._stop.wait(LIVE_TICK_SECONDS)
        except Exception as exc:  # noqa: BLE001 — o alimentador não derruba a API
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self.state = "parado"


feed = LiveFeed()
