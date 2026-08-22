# Routier

**Routier** est une plateforme de supervision pour données d'exploitation de transport urbain. Elle illustre une chaîne courte mais réaliste : publication de télémétrie véhicule, consommation Kafka, contrôle du contrat, calcul d'alertes et tableau opérationnel.

Les événements véhicule inclus restent volontairement synthétiques : ils servent à démontrer le contrat et les décisions sans faire passer un jeu de démonstration pour des opérations réelles. En parallèle, l'application sait synchroniser une photographie du flux public **SNCF GTFS-RT Service Alerts**. Elle stocke uniquement les métadonnées nécessaires à la traçabilité : horodatage, volume, nombre d'entités et empreinte SHA-256 tronquée. Le contenu brut n'est ni conservé ni présenté comme de la télémétrie véhicule.

## Ce que le projet démontre

- une frontière événementielle versionnée (`vehicle.telemetry.v1`) ;
- un consommateur Kafka idempotent et une zone de rejet exploitable ;
- des règles métier explicites pour qualifier le service ;
- une API de lecture légère pour les équipes opérations ;
- un adaptateur de source externe avec preuve de provenance et empreinte de contenu ;
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

### Provenance externe

```text
flux GTFS-RT SNCF → adaptateur Routier → métadonnées + empreinte → SQLite → tableau de provenance
```

La source est demandée à la demande, via `POST /api/sources/sncf/sync`. Les données GTFS-RT exposent des perturbations et messages de service, ce qui est un signal distinct des positions, retards et charges utilisés dans la démo métier. Cette séparation évite de fabriquer un lien analytique qui n'existe pas.

## API

- `GET /health` : statut de l'application
- `GET /api/overview` : indicateurs et derniers événements
- `GET /api/alerts` : alertes ouvertes
- `GET /api/sources` : dernières photographies de sources externes
- `POST /api/events` : intégrer un événement conforme
- `POST /api/demo` : injecter le jeu synthétique de démonstration
- `POST /api/sources/sncf/sync` : capturer les métadonnées du flux SNCF GTFS-RT Service Alerts

## Évolutions crédibles

- remplacer SQLite par PostgreSQL/TimescaleDB pour l'exploitation multi-instance ;
- placer les règles de contrat dans un registry et ajouter une compatibilité ascendante ;
- instrumenter API et worker avec OpenTelemetry/Prometheus ;
- enrichir l'adaptateur GTFS-RT avec un schéma de normalisation explicite lorsque le cas d'usage est validé ;
- stocker les snapshots chiffrés dans un espace gouverné si la politique de conservation le permet ;
- corréler les alertes de service et les événements véhicule seulement après avoir défini une clé de rapprochement et des règles métier vérifiables.
