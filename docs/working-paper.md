# Working paper 01 : rendre une alerte exploitable

## Question de départ

Une équipe opérations reçoit des positions et statuts véhicule toutes les quelques secondes. Comment éviter de traiter chaque message comme une alerte, tout en gardant une trace contrôlable des situations qui comptent ?

## Hypothèse de travail

Un petit contrat versionné, des règles de décision transparentes et un circuit de rejet lisible donnent plus de valeur au premier incrément qu'un tableau sophistiqué sans frontière de données.

## Proposition

Routier consomme `vehicle.telemetry.v1`. Avant d'intégrer un événement dans le tableau, le worker vérifie : identifiants, horodatage, bornes de charge, coordonnées et statut. Les événements non conformes sont envoyés vers un topic de rejet avec une raison. Les événements conformes passent dans un moteur de règles volontairement explicite :

- surveillance à partir de 5 minutes de retard ou 85 % de charge ;
- niveau critique à partir de 15 minutes de retard, 95 % de charge, ou d'un service hors exploitation ;
- aucune alerte quand le service est nominal.

## Décisions d'architecture

| Décision | Raisonnement | Limite assumée |
| --- | --- | --- |
| Kafka-compatible via Redpanda | Rejouabilité et découplage producteur/consommateur | Pas de schema registry dans cette itération |
| API Python légère | Démonstration lisible, exécution facile | Remplacer SQLite en multi-instance |
| Règles déterministes | Chaque alerte est justifiable par une équipe métier | La calibration vient après observation réelle |
| Jeu synthétique | Pas de données ou de promesses de transport réel | Ne mesure pas encore la performance métier |
| Feed GTFS-RT SNCF | Une source ouverte permet de démontrer la provenance et la fraîcheur | Les messages de service ne sont pas assimilés à de la télémétrie véhicule |

## Frontière entre démonstration et source externe

L'interface peut synchroniser le flux public SNCF GTFS-RT Service Alerts. Routier enregistre alors une photographie minimale : URL, instant de capture, taille, nombre d'entités et empreinte du contenu. Le flux binaire n'est pas conservé dans cette version. Il sert à prouver qu'un adaptateur externe fonctionne et que sa provenance est visible, sans inventer de précision sur les véhicules ou les retards.

Une future corrélation serait un sujet de recherche à part entière : elle demanderait une clé de rapprochement explicite, un historique conservé avec une politique de rétention, ainsi qu'une évaluation des faux rapprochements. Elle ne doit pas être ajoutée comme un simple effet visuel au tableau.

## Protocole de revue

1. Lancer les tests de contrat.
2. Démarrer la pile Docker.
3. Publier le jeu synthétique sur le topic.
4. Vérifier que les trois véhicules à risque apparaissent avec le bon motif.
5. Injecter un événement malformé et vérifier sa présence dans le topic de rejet.

## Suite de recherche

La prochaine version comparerait la précision des règles avec un modèle de prévision de retard, et ajouterait des traces OpenTelemetry pour mesurer le délai événement-vers-tableau et le taux de rejet par source.
