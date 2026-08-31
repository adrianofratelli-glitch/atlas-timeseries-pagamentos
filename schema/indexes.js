// Índices do PoV. Idempotente: createIndex é no-op se o índice já existe.
// Rodar com: mongosh "$MONGODB_URI" schema/indexes.js
const dbName = process.env.MONGODB_DB || "energia_medicao";
const d = db.getSiblingDB(dbName);

// --- série -------------------------------------------------------------------
// Índice em coleção time series indexa buckets, não medições. Só a forma
// {meta.x: 1, ts: 1} paga; não existe índice único aqui.
d.readings.createIndex({ "meta.meter_id": 1, ts: 1 });
d.readings.createIndex({ "meta.transformer_id": 1, ts: 1 });

// --- cadastro ----------------------------------------------------------------
d.meters.createIndex({ meter_id: 1 }, { unique: true });
d.meters.createIndex({ transformer_id: 1 });
d.meters.createIndex({ location: "2dsphere" });
d.meters.createIndex({ under_investigation: 1 }, { sparse: true });
d.transformers.createIndex({ transformer_id: 1 }, { unique: true });
d.transformers.createIndex({ feeder_id: 1 });
d.feeders.createIndex({ feeder_id: 1 }, { unique: true });
d.loss_scenarios.createIndex({ transformer_id: 1 }, { unique: true });

// --- casos -------------------------------------------------------------------
d.investigations.createIndex({ meter_id: 1, status: 1 });
d.investigations.createIndex({ transformer_id: 1, opened_at: -1 });
d.investigations.createIndex({ opened_at: -1 });
d.loss_alerts.createIndex({ created_at: -1 });

// Deliberadamente ausentes:
//  - índice em `kwh`: "toda leitura acima de X" não é pergunta deste workload e o
//    índice teria o tamanho do dado que indexa.
//  - {meta.feeder_id, meta.transformer_id, ts}: o rollup do alimentador parte do
//    agregado por transformador (centenas), não das medições (milhões).

print("índices em " + dbName + ":");
["readings", "meters", "transformers", "investigations"].forEach(function (c) {
  print("  " + c + ": " + d[c].getIndexes().map(function (i) { return i.name; }).join(", "));
});
