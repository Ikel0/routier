# Routier

**Routier** est une plateforme de supervision pour données d'exploitation de transport urbain. Elle illustre une chaîne courte mais réaliste : publication de télémétrie véhicule, consommation Kafka, contrôle du contrat, calcul d'alertes et tableau opérationnel.

Le projet ne revendique pas de données de transport réelles : les événements inclus sont synthétiques et servent à démontrer les décisions de la plateforme.

## Ce que le projet démontre

- une frontière événementielle versionnée (`vehicle.telemetry.v1`) ;
- un consommateur Kafka idempotent et une zone de rejet exploitable ;
- des règles métier explicites pour qualifier le service ;
- une API de lecture légère pour les équipes opérations ;
- des tests de contrat et de décision ;
- un mode démo fiable, même sans broker, afin de faciliter la revue.

## Démarrer en local

Prérequis : Python 3.11+.

```bash
python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m routier.server
```

Ouvrir ensuite `http://localhost:8080`. Le bouton « Charger un service de démonstration » alimente le tableau par l'API locale.

## Parcours Kafka complet

Prérequis : Docker et Docker Compose.

```bash
docker compose up --build
docker compose exec api python scripts/publish_demo.py
```

Le producteur écrit dans `vehicle.telemetry.v1`, le worker consume le topic puis remet les événements validés à l'API. Les événements invalides sont publiés dans `vehicle.telemetry.invalid.v1` avec le motif du rejet.

## Architecture

```text
producer → Kafka / Redpanda → worker de contrôle → API + SQLite → tableau opérations
                 └────────→ topic de rejet
```

Le [working paper](docs/working-paper.md) décrit le contrat, les arbitrages et la suite de travail.

## API

- `GET /health` : statut de l'application
- `GET /api/overview` : indicateurs et derniers événements
- `GET /api/alerts` : alertes ouvertes
- `POST /api/events` : intégrer un événement conforme
- `POST /api/demo` : injecter le jeu synthétique de démonstration

## Évolutions crédibles

- remplacer SQLite par PostgreSQL/TimescaleDB pour l'exploitation multi-instance ;
- placer les règles de contrat dans un registry et ajouter une compatibilité ascendante ;
- instrumenter API et worker avec OpenTelemetry/Prometheus ;
- connecter une source GTFS-RT ou un partenaire de mobilité après accord d'accès.
