"""Suíte hostil: entrada inválida, cenário negativo, duplicata, concorrência.

Roda contra a API viva. Não usa mock — o objetivo é descobrir o que quebra com o
cluster real do outro lado, antes que um cliente descubra.

    .venv/bin/python tests/test_resilience.py
    .venv/bin/python tests/test_resilience.py --quick   # sem SSE e sem carga
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8400"
falhas: list[str] = []
passou = 0


def call(path: str, params: dict | None = None, method: str = "GET",
         payload: dict | None = None, timeout: float = 30.0):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": body.decode(errors="replace")}


def check(nome: str, condicao: bool, detalhe: str = "") -> None:
    global passou
    if condicao:
        passou += 1
        print(f"  ok   {nome}")
    else:
        falhas.append(f"{nome} — {detalhe}")
        print(f"  FALHA {nome} — {detalhe}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    print("saúde")
    status, health = call("/health")
    check("health responde 200", status == 200, str(status))
    check("banco reporta medições", health.get("readings", 0) > 0, str(health.get("readings")))
    check("change stream ativo", health.get("change_stream") == "ativo",
          str(health.get("change_stream")))

    status, cen = call("/api/scenarios")
    scenarios = cen.get("scenarios", [])
    check("cenários plantados presentes", len(scenarios) >= 4, str(len(scenarios)))
    severo = next((s for s in scenarios if s["kind"] == "severo"), None)
    controle = next((s for s in scenarios if s["kind"] == "controle"), None)
    outage = (cen.get("demo_meters") or {}).get("outage")
    check("medidor com falha de comunicação plantado", bool(outage), "ausente")

    print("\nfaixa e granularidade")
    for days, unidade in ((1, "minute"), (7, "hour"), (30, "day")):
        status, body = call("/api/balance", {"transformer_id": severo["transformer_id"],
                                             "days": days})
        check(f"servidor escolhe {unidade} em {days}d",
              status == 200 and body["granularity"]["unit"] == unidade,
              f"{status} {body.get('granularity')}")
    for days in (0, -1, 5000):
        status, _ = call("/api/balance", {"transformer_id": severo["transformer_id"],
                                          "days": days})
        check(f"faixa {days} recusada", status == 422, str(status))

    print("\nbalanço contra a verdade de terra")
    status, sev = call("/api/balance", {"transformer_id": severo["transformer_id"], "days": 7})
    erro = abs(sev["totals"]["gap_pct"] - severo["expected_gap_pct"])
    check("gap medido bate com o cenário (< 1pp)", erro < 1.0, f"{erro:.2f}pp")
    check("cenário severo é suspeito", sev["suspeito"] is True, str(sev["suspeito"]))

    status, ctl = call("/api/balance", {"transformer_id": controle["transformer_id"], "days": 7})
    check("controle negativo NÃO abre suspeita", ctl["suspeito"] is False, str(ctl["suspeito"]))
    check("controle abaixo do limiar",
          ctl["totals"]["gap_pct"] < ctl["threshold_pct"],
          f'{ctl["totals"]["gap_pct"]} vs {ctl["threshold_pct"]}')

    status, vazio = call("/api/balance", {"transformer_id": "TR-INEXISTENTE", "days": 7})
    check("transformador inexistente devolve série vazia, não erro",
          status == 200 and vazio["points"] == [], str(status))

    print("\nreconstrução de lacuna")
    mid = outage["meter_id"]
    status, sem = call("/api/curve", {"meter_id": mid, "days": 1, "fill": "false"})
    status, com = call("/api/curve", {"meter_id": mid, "days": 1, "fill": "true"})
    check("sem preenchimento não inventa ponto", sem["filled_count"] == 0, str(sem["filled_count"]))
    check("preenchimento cobre exatamente a falha de 6 h",
          com["filled_count"] == 24, str(com["filled_count"]))
    check("preenchido volta rotulado",
          all(p["fill_method"] for p in com["points"] if p["filled"]), "método ausente")
    check("preenchimento aumenta a série",
          com["point_count"] > sem["point_count"],
          f'{com["point_count"]} vs {sem["point_count"]}')

    status, inexistente = call("/api/curve", {"meter_id": "MED-NAO-EXISTE", "days": 1})
    check("medidor inexistente devolve série vazia",
          status == 200 and inexistente["points"] == [], str(status))

    print("\narmazenamento")
    status, st = call("/api/storage")
    check("comparação disponível", st.get("available") is True, str(st.get("reason")))
    check("time series comprime mais que coleção normal",
          st["storage_ratio"] > 1, str(st.get("storage_ratio")))
    check("razão contando índice é maior ainda",
          st["total_ratio"] >= st["storage_ratio"],
          f'{st["total_ratio"]} vs {st["storage_ratio"]}')

    print("\ncasos e transação")
    call("/api/demo/reset", method="POST")
    alvo = severo["fraud_meters"][0]
    corpo = {"meter_id": alvo, "transformer_id": severo["transformer_id"],
             "gap_kwh": sev["totals"]["gap_kwh"], "gap_pct": sev["totals"]["gap_pct"],
             "windows": sev["longest_streak"]}
    status, caso = call("/api/cases", method="POST", payload=corpo)
    check("caso aberto", status == 200 and caso.get("case_id"), str(status))
    status, _ = call("/api/cases", method="POST", payload=corpo)
    check("duplicata recusada com 409", status == 409, str(status))

    status, _ = call("/api/cases", method="POST",
                     payload={**corpo, "meter_id": "MED-NAO-EXISTE"})
    check("medidor inexistente recusado com 404", status == 404, str(status))

    print("\nvalidação de entrada")
    invalidos = [
        ("gap negativo", {**corpo, "gap_kwh": -5}),
        ("gap acima de 100%", {**corpo, "gap_pct": 180}),
        ("meter_id como lista", {**corpo, "meter_id": ["a", "b"]}),
        ("windows absurdo", {**corpo, "windows": 10**9}),
        ("campo obrigatório ausente", {"meter_id": alvo}),
    ]
    for nome, payload in invalidos:
        status, _ = call("/api/cases", method="POST", payload=payload)
        check(f"{nome} recusado com 422", status == 422, str(status))

    print("\ningestão ao vivo")
    call("/api/live/clear", method="POST")
    status, st = call("/api/live/start", method="POST",
                      payload={"transformer_id": severo["transformer_id"]})
    check("ingestão inicia", status == 200 and st["state"] == "rodando", str(st))
    time.sleep(6)
    status, st = call("/api/live/status")
    check("ingestão grava medições", st["written"] > 0, str(st["written"]))
    check("ingestão sem erro", st["last_error"] is None, str(st["last_error"]))

    status, vivo = call("/api/balance", {"transformer_id": severo["transformer_id"],
                                         "live": "true"})
    check("balanço ao vivo lê readings_live",
          vivo.get("collection") == "readings_live" and len(vivo["points"]) > 0,
          f'{vivo.get("collection")} {len(vivo.get("points", []))}')
    check("ao vivo agrega em segundos",
          vivo["granularity"]["unit"] == "second", str(vivo["granularity"]))

    status, _ = call("/api/live/start", method="POST",
                     payload={"transformer_id": "TR-INEXISTENTE"})
    check("transformador inexistente recusado com 404", status == 404, str(status))

    status, st = call("/api/live/stop", method="POST")
    check("ingestão para", st["state"] == "parado", str(st["state"]))

    # A TTL é a razão de existir da coleção separada: sem ela o roteiro não roda
    # duas vezes no mesmo dia sem limpeza manual.
    from pymongo import MongoClient  # noqa: PLC0415 — só o teste precisa do driver
    import os as _os
    uri = None
    for linha in open(_os.path.join(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__))), ".env")):
        if linha.startswith("MONGODB_URI="):
            uri = linha.split("=", 1)[1].strip()
    cli = MongoClient(uri)
    banco = cli[_os.getenv("MONGODB_DB", "energia_medicao")]
    opcoes = next((c.get("options", {}) for c in banco.list_collections()
                   if c["name"] == "readings_live"), {})
    check("readings_live tem TTL", opcoes.get("expireAfterSeconds", 0) > 0,
          str(opcoes.get("expireAfterSeconds")))
    check("readings_live é time series", "timeseries" in opcoes, str(list(opcoes)))
    cli.close()

    status, st = call("/api/live/clear", method="POST")
    check("limpeza remove o dado ao vivo", st["written"] == 0, str(st["written"]))

    if not args.quick:
        print("\nchange stream")
        recebidos: list[dict] = []

        def escuta():
            req = urllib.request.Request(BASE + "/api/alerts/stream")
            try:
                with urllib.request.urlopen(req, timeout=20) as res:
                    for linha in res:
                        texto = linha.decode(errors="replace").strip()
                        if texto.startswith("data:") and "case_id" in texto:
                            recebidos.append(json.loads(texto[5:].strip()))
                            return
            except Exception:  # noqa: BLE001 — o teste falha pela ausência do evento
                pass

        t = threading.Thread(target=escuta, daemon=True)
        t.start()
        time.sleep(2)
        outro = severo["fraud_meters"][1] if len(severo["fraud_meters"]) > 1 else alvo
        call("/api/demo/reset", method="POST")
        call("/api/cases", method="POST", payload={**corpo, "meter_id": outro})
        t.join(timeout=15)
        check("alerta chega pelo change stream", len(recebidos) == 1, str(len(recebidos)))

        print("\nconcorrência")
        respostas: list[int] = []
        lock = threading.Lock()

        def carga():
            s, _ = call("/api/balance", {"transformer_id": severo["transformer_id"],
                                         "days": 30})
            with lock:
                respostas.append(s)

        threads = [threading.Thread(target=carga) for _ in range(24)]
        t0 = time.time()
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        elapsed = time.time() - t0
        ok = sum(1 for s in respostas if s == 200)
        recusadas = sum(1 for s in respostas if s == 429)
        erros = [s for s in respostas if s not in (200, 429)]
        check("nenhum 500 sob concorrência", not erros, str(erros))
        check("saturação recusa em vez de enfileirar sem fim",
              ok + recusadas == len(respostas), f"{ok} ok / {recusadas} 429")
        print(f"       24 chamadas em {elapsed:.1f}s — {ok} ok, {recusadas} recusadas")

    status, reset = call("/api/demo/reset", method="POST")
    check("reset também limpa a ingestão ao vivo",
          reset.get("ao_vivo", {}).get("state") == "parado", str(reset.get("ao_vivo")))

    print(f"\n{passou} passaram, {len(falhas)} falharam")
    for f in falhas:
        print(f"  - {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
