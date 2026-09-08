# r22b sur le Fold : Python et éditeur réussis, reprise bloquée par le cache

Le 8 septembre 2026, r22b/versionCode12 a été installé normalement après
récupération de la quarantaine r21. APK SHA256 :
`eedddbd13fa9b64a4be38e8ae2cf0a34ac91aadf48d5271cdea0f7014384b99b`.

## Résultats réels

- PREPARE puis STOP sans client : propriétaire8166, deux reçus de nettoyage
  et wait0, disparition du PID/socket/manifeste/marqueur, boot inchangé.
- Qualification de production ordinary-uid `f65b833a` : réussie. Propriétaire8454,
  cinq commandes Bash/Python, trois unittest, construction et exécution42,
  fichiers modèle et lectures humaines/config, puis arrêt propre indépendant.
- Conversation « Créer et tester une addition Python », projet
  `/data/user/0/app.foldgpt/files/projects/ui-python-caae3a83d156` : les vrais
  outils créent `addition.py`, `test_addition.py`, `app_main.py`, puis le zipapp.
  La sortie conservée rapporte Android/aarch64/UID10412, trois tests OK,
  `statuses: tests=0 zipapp_build=0 zipapp_run=0` et résultat42.
- L'inventaire Android indépendant retrouve les trois sources, l'archive et
  deux caches du projet. Ce ne sont pas des fichiers injectés par le pilote.
- Éditeur officiel : ajout du commentaire
  `# Sauvegarde depuis l'editeur FoldGPT r22 verifiee.` par saisie dans le
  contrôle éditable, sauvegarde puis fermeture/réouverture de l'onglet.
  Le contenu Android est confirmé, SHA256
  `f9d6616102991bd0b4debba05ced51b1d37ce447b467f76159cdb26af38da205`.
  La première collecte immédiate précédait la fin asynchrone de sauvegarde ;
  elle est conservée avec l'ancienne empreinte. La collecte suivante et la
  réouverture confirment les nouveaux octets.
- Arrêt complet après ce parcours : propriétaire8815, deux reçus de nettoyage
  et wait0, disparition des ressources et boot inchangé.

## Nouveau défaut réellement rencontré

La reprise suivante échoue avant création d'un propriétaire natif :
`qualified_native_deployment_unavailable`,
`java.lang.SecurityException: Python runtime directory is not admitted`.
Les commandes normales `python3` ont créé des `__pycache__` dans le runtime
signé. Quatorze répertoires apparaissent avec mode0777 ; le contrôle des modes
puis l'inventaire exact les refusent. Retirer uniquement ces caches sans changer
leur destination ne résoudrait pas la cause. Le correctif suivant doit conserver
le bytecode dans un emplacement writable séparé, puis réussir la reprise après
des commandes Python ordinaires, sans imposer `-B` au modèle.

`rg` est aussi absent du PATH natif. Le modèle a utilisé `find` et les opérations
Python ont réussi ; cet outil manquant reste à fournir pour l'usage général.

## Preuves conservées

Sous `work/r21-device-return-20260908/` : `r22-idle-device-v1/report.json`,
`ui-r22/model-tool-evidence.json`, `ui-r22/project-after-create/report.json`,
`ui-r22/project-after-editor-flushed/report.json`, `ui-r22/editor-reopened.json`,
`ui-r22/stop-first/{report,final-status}.json`. Qualification complète :
`downloads/native-ordinary-production-device-20260908/f65b833a/report.json`.
Reprise refusée :
`work/root-artifacts-20260907/native-ui-validation-20260908/r22b-resume-ui/`
et `work/r22-cache-20260908/`.

L'incident r21 reste un arrêt anormal : retrait ciblé29981 par pidfd, vrai
wait parental9, archivage sous les deux flocks, puis retrait du UserService29961.
Les reçus disent `normalClosure:false` ; aucun statut n'a été réécrit en succès.
Les scripts et toutes les captures sont dans le dossier de l'incident.

Architecture inchangée : commandes Bash/Python natives Android/Bionic ; interface
et contrôleur GNU sous PRoot. Ces résultats ne qualifient ni un produit entièrement
Bionic ni toutes les fonctions de Codex. Aucune VM sur le téléphone.
