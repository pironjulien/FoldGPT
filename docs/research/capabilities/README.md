# Inventaire des capacités pour l'exécution native FoldGPT

État du 7 septembre 2026. Les recherches antérieures étaient des analyses
ciblées ; elles ne constituaient pas quatre inventaires complets. Ce dossier
les organise et les complète avec un relevé réel du Fold en lecture seule.

| Document | Question traitée |
| --- | --- |
| [01 — Mécanismes effectifs](01-effective-mechanisms.md) | Qu'est-ce qui manque, existe, est interdit ou reste à valider pour notre exécuteur ? |
| [02 — Fold et One UI](02-fold.md) | Quel matériel, quel noyau, quelles fonctions déclarées et quels contextes de processus avons-nous réellement relevés ? |
| [03 — Android natif](03-android-native.md) | Quelles API et protections Android peuvent réaliser les opérations nécessaires ? |
| [04 — ARM64](04-arm64.md) | Qu'apportent l'architecture, les instructions et les extensions annoncées par ce processeur ? |
| [05 — Shizuku](05-shizuku.md) | Comment obtient-il des droits shell, quels blocages pourrait-il lever et quelles limites demeurent ? |

## Portée des inventaires

Le relevé brut contient **6 501 paramètres de configuration du noyau**,
**228 entrées de fonctions déclarées par Android**, **521 services Binder**,
les informations CPU/HWCAP et les droits de processus existants. Ce sont des
catalogues vérifiables. Un nom de service n'est pas une liste de ses méthodes
autorisées ; une API NDK n'est pas un appel système permis ; un bit CPU n'est
pas une permission du noyau. Nous ne prétendons pas avoir testé chaque fonction
d'Android, de One UI ou d'ARM.

Deux catalogues versionnés complètent les relevés privés :
[318 numéros de syscalls du NDK r29](catalogs/arm64-syscalls-ndk-r29.csv) et
[96 bits HWCAP définis, avec les 55 annonces mesurées](catalogs/arm64-hwcaps-ndk-r29.csv).
Le [manifeste](catalogs/arm64-ndk-r29-sources.json) conserve leurs sources et
empreintes. Ces nombres n'expriment pas une liste de permissions accordées.

Chaque conclusion distingue :

- **Observé** : lecture réelle ou test identifié sur ce Fold ; sa date et son
  contexte comptent. Un test ancien ne qualifie pas le runtime actuel.
- **Documenté** : contrat ou code primaire amont, avec version ; ce n'est pas
  nécessairement la politique Samsung.
- **Absent / refusé** : absence de code dans la configuration ou refus précis
  dans le contexte observé. Ce sont deux raisons différentes.
- **À qualifier** : assemblage, droit ou comportement qui n'a pas de preuve.

## Preuves et collecte

La référence est [l'inventaire v2](../../../downloads/runtime/capabilities-20260907-v2/inventory.json),
horodaté `2026-09-06T22:52:19.003675Z`, soit le 7 septembre à 00:52 à Paris.
Le [collecteur](../../../tools/runtime/inspect-native-capabilities.py) lit
configuration, propriétés et processus déjà présents. Il ne lance ni Shizuku,
ni sonde de namespace/seccomp/ptrace, ni diagnostic GNU. Les données privées
restent sous `downloads`, ignoré par Git ; aucun envoi externe n'a été fait.

Le premier répertoire `capabilities-20260907` reste conservé, mais son transport
texte `adb exec-out` ne conservait pas correctement le code de sortie distant.
La référence **v2** utilise `adb shell -T` pour le texte et garde stderr et les
refus. `exec-out` est réservé aux données binaires, dont le statut distant est
marqué inconnu. Un `Permission denied` n'est jamais une lecture réussie.

## Décision technique et prochain résultat utile

La direction reste un **exécuteur Bionic natif avec une politique réellement
appliquée**, indépendant des fichiers du client officiel. La
[qualification fixe Shizuku + Bionic](../shizuku-bionic-trial-2026-09-07.md)
a maintenant réussi sur le Fold : création/modification Python, trois tests,
paquet exécuté, refus de sécurité et nettoyage. Elle utilise une application
de test séparée ; Shizuku n'est ni un plugin ChatGPT ni le confinement des
commandes. L'exécution d'ELF produits dans le workspace reste distincte de
l'exécution de scripts/paquets Python démontrée ici.

La qualification doit produire des réponses concrètes, dans cet ordre :

1. Fixer le contrat du service : identité, workspace, accès par fichiers/FDs,
   parenté et cycle de vie. Comparer app, service Android isolé et UserService
   shell sans attribuer à l'un les droits mesurés chez l'autre.
2. Pour Shizuku, le vrai UserService est désormais mesuré : UID 2000,
   `u:r:shell:s0`, aucun filtre seccomp hérité, aucune capability effective.
   La chaîne Bionic fixe fonctionne dans ce contexte. Le diagnostic GNU
   suspect n'a pas été repris.
3. Vérifier la politique complète sur les opérations nécessaires, y compris
   refus fichiers/réseau/Binder/processus, sous-processus et nettoyage. La voie
   choisie doit refuser une politique qu'elle ne sait pas appliquer.
4. Raccorder toutes les routes requises du client, puis réaliser le critère
   convenu : création/modification, vrais tests et paquet d'un petit projet
   Python depuis l'interface ordinaire du Fold.

L'échec d'une variante ne démontre pas l'échec de toutes les autres. Aucune
solution complète conforme n'est cependant démontrée à cette date. Les deux
redémarrages du diagnostic GNU restent inexpliqués et sa reproduction reste
suspendue ; ce dossier n'annonce pas leur correction.
