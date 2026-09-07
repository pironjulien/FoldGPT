# Reprise du projet FoldGPT

Le dépôt privé de travail est `pironjulien/FoldGPT-workspace`, branche
`codex/foldgpt-beta`. Il contient les sources et les recherches en cours ; ce
checkpoint ne signifie pas que les commandes ordinaires fonctionnent déjà sur
le téléphone.

```powershell
gh repo clone pironjulien/FoldGPT-workspace C:\Dev\ChatgptFold
Set-Location C:\Dev\ChatgptFold
python tools/recovery/restore-submodules.py
```

Le script récupère les deux sous-modules et applique les modifications exactes
de Termux:X11, après contrôle du commit et du SHA-256. Il conserve un état déjà
restauré et refuse un conflit. Les originaux officiels sont récupérés à leurs
commits figés.

Les dépendances, résultats d'essais et données locales ignorées par Git sont
conservés séparément dans une archive chiffrée de la release privée de reprise.
La clé de déchiffrement reste dans le coffre OneDrive
`Documents/NexusSecure/projects/FoldGPT/recovery.agekey`, jamais dans GitHub.
Les instructions et le manifeste précis de cette archive sont ajoutés après
validation du téléchargement et du déchiffrement.

Le code du moteur séparé est développé sous `C:\Dev\FoldgptEngine`, à partir du
commit Codex `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` (`rust-v0.153.4`).
Son état de travail sera inclus dans la même reprise.

La clé de signature Android de FoldGPT est également conservée dans le coffre,
fichier `android-debug.keystore` à côté de `recovery.agekey`. Le build principal
la sélectionne depuis OneDrive, ou depuis `FOLDGPT_SIGNING_KEYSTORE`, puis
contrôle son certificat. Cela permet de mettre à jour l'application déjà
installée sans changer d'identité de signature sur l'autre PC. Un coffre absent
ou une autre clé produit une erreur explicite ; aucune nouvelle identité n'est
créée silencieusement. Cette clé concerne FoldGPT, pas l'application officielle
ChatGPT.

État technique vérifié au début de cette sauvegarde : le test fixe
Shizuku/Bionic crée, teste et construit réellement un projet Python sur le
Fold. L'intégration aux commandes, fichiers et sessions ordinaires est en cours.
Voir `docs/research/shizuku-bionic-trial-2026-09-07.md`. Ne pas relancer l'ancien
diagnostic GNU/PRoot/seccomp associé aux redémarrages du téléphone.
