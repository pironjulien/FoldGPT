# Exécution native ordinaire — préparation PC du 8 septembre 2026

## Résultat recherché et limite actuelle

La conversation réelle « Créer et tester une addition Python » du projet
« Validation Python FoldGPT » échoue encore sur le Fold installé en r20/R5.
Le nouveau code décrit ici est préparé sur PC. Il ne qualifie pas encore la
conversation, l'éditeur, la sauvegarde ni la reprise sur Android.

La cause vérifiée est le refus du contrat Full access : le moteur transmet
`sandbox: null` ou omet `sandbox`, tandis que notre backend exigeait toujours
un contexte managed. Le chemin modèle des fichiers présentait la même lacune.
La première erreur observée avait déjà franchi les contrôles de TTY, snapshot,
exécutable et environnement ; ces contrôles ne sont pas des blocages démontrés
de cette tentative précise. Ce constat provient du chemin source, sans capture
complète du message RPC de la conversation.

## Contrat implémenté

Le paquet sélectionne explicitement `backendOptions.ordinaryUid` avec un
exécuteur installé, inventorié et vérifié par empreinte. Aucun paramètre RPC
ne peut installer un profil ou fournir un autre exécuteur de supervision.

| Demande du moteur | Route |
| --- | --- |
| Commande avec sandbox absent ou null | Exécution sous l'UID Android ordinaire, résultat `sandboxType: none` |
| Commande avec un objet sandbox | Backend managed existant, y compris ses refus |
| Fichier avec contexte absent/null ou Disabled entièrement valide | Opération native sous l'UID ordinaire |
| Autre contexte de fichier | Backend managed, sans nouvelle tentative permissive |
| Lecture/fermeture/signal d'un handle | Backend propriétaire conservé depuis sa création |

L'exécuteur direct utilise les permissions ordinaires de son UID pour les
fichiers, les appels système et le réseau. Le profil managed reste distinct.
Le canal humain de l'éditeur n'est pas attribué aux outils du modèle.
Les handles, capacités de registre, verrou de travail et état de quarantaine
sont communs à la composition. Une fermeture inconnue ne permet pas de
réutiliser le dossier de travail.

Le propriétaire natif attend ses enfants réels. Les pidfds et la relation
enfant vérifiée permettent de signaler les descendants adoptés ; seul le
constat `ECHILD`, associé aux EOF et à l'attente du propriétaire lui-même,
autorise la libération. Ce mécanisme ne fournit pas d'isolation face à un
processus hostile du même UID ni de délai garanti pour une tâche noyau bloquée.
La conception détaillée figure dans
`tools/executor/bionic-supervisor/direct-design.md`.

## Options utiles à comparer au retour

1. **Paquet avec Full access natif** : reproduire la création de fichiers
   modèle et les commandes Python/Bash via les vrais canaux de production,
   puis reprendre la conversation habituelle sans changer son mode.
2. **Mode managed du même paquet** : vérifier explicitement ses autorisations
   et ses refus. Un succès de ce mode ne remplace pas le test Full access.
3. **Canal éditeur existant** : vérifier qu'il lit les fichiers effectivement
   créés, conserve les octets sauvegardés, puis survit à une fermeture/reprise.

Ce sont des voies réelles du produit, avec des critères différents. Aucun
émulateur PC n'est présenté comme une reproduction du noyau Samsung. Le nouveau
runner est actuellement sans PTY ; une demande TTY reste refusée explicitement.

## Ordre des essais Android

- Vérifier l'état réel de la session8507 après le départ du téléphone.
  L'action STOP avait été reçue, mais sa fermeture finale n'a pas pu être lue.
- Vérifier les octets/signature du candidat préparé et l'installation réelle.
- Exécuter le client de qualification de production dans un projet neuf,
  recueillir les résultats natifs et le reçu indépendant de fermeture.
- Reprendre le projet réel depuis l'interface : création, trois tests Python,
  construction et exécution de l'archive donnant42.
- Lire et sauvegarder depuis l'éditeur, arrêter normalement, relancer et
  vérifier les mêmes fichiers et la conversation conservée.

Les résultats PC, de paquet, de qualification Android et de conversation
restent identifiés séparément. Les rapports exacts et la version prête à
installer sont consignés dans `recovery/HANDOFF.md` après vérification.
