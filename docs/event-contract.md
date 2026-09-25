# Contrat `vehicle.telemetry.v1.0`

## Intention

Le contrat décrit un signal de fonctionnement véhicule reçu par le control plane. Il est immuable une fois publié. Les métadonnées de livraison, comme l'identifiant de trace et l'origine, sont ajoutées par le transport ou l'API et ne font pas partie du payload métier.

## Exemple valide

```json
{
  "event_id": "metro-m2-20260811-081700-r118",
  "event_type": "vehicle.telemetry",
  "schema_version": "1.0",
  "vehicle_id": "R-118",
  "route_id": "M2",
  "recorded_at": "2026-08-11T08:17:00Z",
  "delay_seconds": 418,
  "occupancy_percent": 91,
  "status": "in_service",
  "latitude": 48.861,
  "longitude": 2.367
}
```

## Règles de validation

| Champ | Règle |
| --- | --- |
| `event_id` | Chaîne non vide, maximum 128 caractères, stable sur une relecture |
| `event_type` | Exactement `vehicle.telemetry` |
| `schema_version` | Exactement `1.0` |
| `recorded_at` | ISO-8601 avec fuseau horaire |
| `delay_seconds` | Nombre fini, supérieur ou égal à zéro |
| `occupancy_percent` | Nombre fini compris entre 0 et 100 |
| `status` | `in_service`, `disrupted` ou `out_of_service` |
| coordonnées | Nombres finis dans les bornes latitude/longitude |

## Résultat d'ingestion

Une insertion renvoie `201` avec `status: accepted`. La même charge avec le même `event_id` renvoie `200` avec `status: duplicate`. Dans les deux cas, `trace_id` permet de parcourir la piste d'audit.

```json
{
  "event_id": "metro-m2-20260811-081700-r118",
  "trace_id": "evt-…",
  "status": "accepted",
  "ingested_at": "2026-08-11T08:17:03+00:00",
  "decision": {
    "severity": "watch",
    "priority_score": 45,
    "rule_ids": ["delay.watch", "occupancy.watch"],
    "decision_version": "1.0"
  }
}
```
