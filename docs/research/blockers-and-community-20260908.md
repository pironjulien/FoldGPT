# Blocages, couverture des logs et retours externes — 8 septembre 2026

Recherche et analyse locales uniquement. Aucun programme tiers n'a été installé,
aucun essai Android n'a été lancé et le candidat r21 n'est pas modifié.

## Ce que permettent les logs

Le journal général R5 contient les 29 637 lignes jusqu'au résumé final et au
code100. Ses 238 échecs et deux timeouts ont été reliés à 240 identifiants de
tests distincts. Des sous-processus plafonnent leurs propres sorties ; cela
ne constitue pas une capture exhaustive de tous leurs octets. Le
[triage détaillé](r5-failure-audit-20260908.md) classe les symptômes suivants :
102 erreurs bwrap/permissions Linux, 35 débordements de pile, 28 différences
de snapshots, six assertions TLS, une incohérence de feature de test V8,
deux timeouts et 66 autres assertions/attentes. Toutes les causes ne sont
pas identifiées ; il ne faut pas assimiler ces cas à des défauts cosmétiques
ou à 240 blocages indépendants du téléphone.

Sur Android, l'erreur de contexte Full access dans la conversation et l'absence
réelle de fichiers sont établies. Les paramètres/réponses RPC bruts complets,
l'erreur interne imbriquée d'apply_patch et le reçu final de la session8507
ne sont pas conservés. Aucun essai Android r21 n'existe encore. L'
[audit des traces](device-evidence-audit-20260908.md) donne les fichiers exacts.
Les anciens redémarrages du diagnostic GNU sont documentés dans
[leur rapport](gnu-managed-reboot-2026-09-06.md) ; les LAST_KMSG disponibles
ne contiennent pas de pile noyau exploitable et leur cause reste inconnue.

## Blocage d'une voie et impossibilité du projet

La configuration relevée sur le Fold ne fournit pas les namespaces USER/PID
nécessaires à la voie Bubblewrap étudiée. Reconstruire le binaire ne fournit
pas ces fonctions noyau. La [documentation officielle du sandbox](https://learn.chatgpt.com/docs/sandboxing),
ouverte aujourd'hui dans le navigateur intégré depuis
`developers.openai.com/codex/sandboxing`, confirme notamment le besoin de
création de user namespaces pour le helper Linux. Elle définit également
le mode Full access distinct du mode restreint.

La dernière conversation r20 est bloquée par notre contrat logiciel, qui
refuse le contexte absent/null du mode Full access. r21 corrige ce contrat
pour processus et fichiers ; 190 tests Python/natifs Linux passent. Le
projet Python natif avait déjà réussi sur le Fold dans les qualifications
dédiées. Ces preuves justifient le test r21, sans démontrer conversation,
édition/sauvegarde, fermeture et reprise. PTY, snapshots et proxy restent
des limites connues, sans preuve qu'ils aient causé cette dernière tentative.

## Retours GitHub réellement lus

Le [comparatif de code](github-comparables-20260908.md) détaille les versions,
commits et limites des projets suivants. Les lectures structurées GitHub
complètent la documentation officielle ; aucun commentaire n'a été publié.

1. **[DioNanos/codex-termux](https://github.com/DioNanos/codex-termux/releases/tag/v0.153.3)**,
   release du 5 septembre 2026 : compilation Android/Bionic, vrai V8 et
   exécutable `codex-code-mode-host`. Les recettes de liaison C++/V8 et de
   PTY sont pertinentes pour notre moteur séparé. Certains patches ignorent
   des erreurs de verrouillage ou neutralisent une mise à jour : une adoption
   globale du fork ne satisfait pas automatiquement nos exigences.
2. **[openai/codex #11809](https://github.com/openai/codex/issues/11809)**,
   ouvert au contrôle du 8 septembre : problèmes DNS/authentification et
   verrous en Termux natif. L'auteur
   [rapporte](https://github.com/openai/codex/issues/11809#issuecomment-3900527361)
   qu'une cible `aarch64-linux-android` corrige le DNS, avec une adaptation
   distincte des verrous. Il
   [publie ensuite](https://github.com/openai/codex/issues/11809#issuecomment-4900074251)
   un fork suivant les releases. Ce sont des retours tiers, pas nos mesures.
3. **[Retour Termux dans le même ticket](https://github.com/openai/codex/issues/11809#issuecomment-4581648164)** :
   un utilisateur décrit un binaire Linux/musl, un proxy DNS local et Full
   access ; il rapporte une latence supérieure avec PRoot. Cela confirme des
   problèmes comparables, sans fournir une mesure de FoldGPT ni une raison
   d'introduire ce proxy tant que notre DNS n'est pas le blocage observé.
4. **[openai/codex #30153](https://github.com/openai/codex/issues/30153)**,
   toujours ouvert sans commentaire : refus `bwrap: fchdir to oldroot` sous
   Termux/PRoot. L'auteur rapporte des namespaces disponibles dans son
   environnement : son résultat ne peut pas être transposé au noyau Samsung
   relevé. Installer Bubblewrap ne constitue donc pas une solution validée
   pour notre appareil.

Les recettes Termux Bash et CPython Android sont déjà exploitées dans FoldGPT ;
Shizuku est déjà utilisé dans les exécutions natives vérifiées. Le nouveau
port récent fournit surtout une source de correctifs de moteur Bionic/V8.
Une interface web de remplacement ne valide pas l'expérience officielle demandée.
Cette passe ne dispose pas d'un témoignage Reddit directement vérifié à citer ;
elle ne prétend pas avoir épuisé Reddit ni tous les projets publics.

## Prochain travail utile

Conserver r21 comme prochain essai du projet Python depuis l'interface réelle.
Capturer les échanges RPC ciblés et leurs erreurs imbriquées si cet essai échoue,
puis comparer la cause aux patches Android identifiés. Étudier séparément les
échecs R5, notamment les erreurs HTTP partagées et attentes core, sans remplacer
les assertions par un résultat attendu. Aucun élément lu ne démontre à lui seul
une impossibilité définitive de la voie native choisie ; aucun ne démontre non
plus que tous les obstacles restants sont résolus.
