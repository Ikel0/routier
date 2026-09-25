# Working paper 01 : construire une alerte qui tient à la relecture

## Problème

Les signaux opérationnels n'ont de valeur que si une équipe peut répondre à quatre questions : quel message a déclenché la situation, quelle règle a été appliquée, le même message peut-il être rejoué sans dégâts, et qui a pris la situation en charge ?

Routier est une expérimentation autour de cette chaîne minimale. Le périmètre est volontairement étroit pour que les garanties soient observables, testables et discutables.

## Hypothèse

Un contrat de données strict, un worker at least once, un sink idempotent et un journal de décision apportent davantage de confiance qu'une projection de "temps réel" dont on ne peut ni vérifier la provenance ni rejouer les effets.

## Décisions

| Décision | Pourquoi | Limite assumée |
| --- | --- | --- |
| Contrat `vehicle.telemetry.v1.0` | Rendre les attendus explicites à la frontière du système | Pas de schema registry dans cette itération |
| Commit Kafka manuel | Ne pas perdre un offset avant l'effet durable aval | Un message peut être reconsommé |
| `event_id` unique au sink | Transformer la relecture en résultat `duplicate` | Un producteur doit fournir un identifiant stable |
| Règles et score de priorité déterministes | Pouvoir expliquer chaque alerte au métier | Les seuils ne sont pas encore calibrés sur un historique réel |
| Audit séparé des événements | Distinguer accepté, doublon, rejet et accusé | Pas encore de politique de rétention ni export analytique |
| Feed SNCF GTFS-RT limité aux métadonnées | Démontrer la provenance sans inventer une corrélation métier | Aucun rapprochement avec la télémétrie de démonstration |

## Modèle de livraison

```text
Kafka record
  -> validation
  -> API idempotente ou DLQ confirmée
  -> commit du consumer
```

Si l'API devient indisponible, le worker ne commite pas. Au redémarrage, Kafka redélivre le message. Si la première écriture avait réussi juste avant la coupure, l'API renvoie `duplicate` sur la deuxième tentative et la nouvelle consommation peut être commitée. Cette combinaison est plus honnête que de prétendre atteindre exactly once sans infrastructure de transaction distribuée.

## Protocole de revue

1. Lancer les 11 tests de la suite.
2. Charger le scénario de démonstration.
3. Le charger à nouveau et constater quatre doublons, sans nouveau véhicule ni nouvelle alerte.
4. Envoyer un corps JSON incomplet à `POST /api/events` et contrôler le rejet 422 dans le journal.
5. Accuser l'alerte critique puis vérifier qu'elle sort de la file active mais reste visible dans l'historique.
6. Synchroniser la provenance SNCF et vérifier que seule la photographie de source est stockée.

## Suite de recherche

Une prochaine itération introduirait un registry de schémas, des métriques OpenTelemetry, des SLO de fraîcheur et de taux de rejet, une identité opérateur, puis un stockage relationnel capable de gérer plusieurs instances. Avant tout modèle prédictif, elle demanderait un historique métier gouverné et une définition partagée des faux positifs acceptables.
