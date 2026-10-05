# Runbook de démonstration

## Objectif

Ce runbook explique le comportement de Routier dans son périmètre actuel. Il ne remplace pas une procédure d'exploitation transport réelle.

## Quand une alerte apparaît

1. Lire les `rule_ids` et les motifs associés. Une alerte peut venir du statut de service, du retard, de la charge, ou d'une combinaison de ces signaux.
2. Ouvrir le journal d'ingestion et retrouver le `trace_id`. Vérifier l'origine et le statut `accepted`, `duplicate` ou `rejected`.
3. Si le signal est traité dans cette sandbox, utiliser « Prendre en charge ». L'alerte quitte la file active et l'accusé reste dans l'audit.
4. Ne pas conclure sur l'état d'un réseau réel. Les événements véhicule visibles sont synthétiques.

## Quand le taux de rejet augmente

1. Consulter les motifs dans `/api/audit`.
2. Contrôler que le producteur envoie bien `event_type: vehicle.telemetry` et `schema_version: 1.0`.
3. Vérifier les timestamps et les bornes de charge avant de modifier les règles métier.
4. Dans la pile Kafka, inspecter le topic `vehicle.telemetry.invalid.v1` afin de préserver les messages rejetés pour analyse. Un même `rejection_id` peut apparaître deux fois après un redémarrage du worker : compter les rejets distincts, pas les messages.

## Quand le worker redémarre

Le worker n'accuse un offset Kafka qu'après un effet durable. Une relecture est donc attendue et visible comme `duplicate` si l'API avait déjà écrit l'événement. Cette propriété dépend d'un `event_id` stable fourni par le producteur.

## Limites de sécurité

L'API de démonstration n'authentifie pas l'opérateur. En environnement partagé, les routes d'accusé et de consultation d'audit devraient être protégées par une identité, des rôles, un journal d'accès et une politique de rétention.
