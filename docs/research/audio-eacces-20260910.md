# Microphone et retour de l'erreur EACCES — 10 septembre 2026

## Cause vérifiée

L'APK installé avant réparation, versionCode35, avait le SHA-256
`b8f31a258206ccf70d397a8d2a47a8eea41642ca849bdf0a7d49a62d0997d852`.
Il contenait `FoldAudioBridge`, mais pas
`assets/foldgpt-executor-deployment.json`. Le droit Android `RECORD_AUDIO`
était accordé et les deux connexions au pont PulseAudio étaient établies.

Sans le manifeste natif, `FoldExecutorRuntime.isNativeSelected()` sélectionnait
le chemin historique. La commande PRoot réellement en cours travaillait dans
`/home/julien`, sans raccordement du dossier Android `files/projects`, et le
client lançait `resources/codex` au lieu de `foldgpt-codex-native`.
Le profil conservait le chemin absolu des projets de l'installation native.
La préparation puis l'envoi d'une nouvelle tâche échouaient donc avec :

```text
EACCES: permission denied, mkdir '/data/data/app.foldgpt/files/projects/2026-09-10'
```

L'ancien fichier `native-executor-status.json` indiquait encore `ready` avec un
propriétaire disparu. Cette trace persistante ne prouvait pas qu'un moteur
natif fonctionnait dans l'APK courant. Le contrôle a porté sur l'inventaire de
l'APK extrait, les processus vivants et leur commande réelle.

## Correction livrée

- `android/app/build.gradle` exige les assets et JNI du paquet natif lors du
  packaging du principal APK/AAB, y compris debug. Le contrôle est une
  dépendance des tâches de fusion des assets et de packaging. L'ancien
  `foldgptRequireExecutor=false` ne permet pas de produire un APK incomplet.
- La compilation Java et les tests unitaires restent possibles sans emballer
  le paquet natif. Les APK de qualification distincts ne sont pas modifiés.
- Le README indique la construction via le script canonique et un paquet
  explicitement sélectionné. Aucun paquet local n'est choisi implicitement.
- r46/versionCode36 rassemble le code micro existant et le paquet natif r45.
  Aucun droit des projets n'a été élargi et aucun fichier du profil Linux n'a
  été modifié pour résoudre l'erreur.

Commande de cette livraison depuis la racine du dépôt :

```powershell
python tools/runtime/build-production-candidate.py --candidate r46audio --package work/android-extension-20260909/executor-r45
```

APK conservé dans
`downloads/native-production-20260908/foldgpt-native-candidate-r46audio.apk`,
SHA-256 `9ccf9da356c2bcef20fc0f3ac295948e3dea0b21b08079f2f41bc3fdf6faf7c5`.
L'APK installé sur le Fold a cette même empreinte et le versionCode36.

## Vérifications réalisées

1. Une vraie invocation Gradle `assembleDebug` et `bundleDebug` sans paquet
   échoue sur le nouveau contrôle et laisse l'APK précédent inchangé.
   Les assets seuls et l'ancien indicateur désactivé sont aussi refusés.
   La compilation Java sans paquet réussit.
2. Le script canonique construit et vérifie l'APK complet : inventaires,
   empreintes des 91 bibliothèques natives déclarées, 2 447 fichiers de données
   Python et fermeture des 99 fichiers sources. Les 42 tests du transport
   restent verts, réutilisés par Gradle car leurs entrées sont inchangées.
3. Arrêt normal du service : les boucles audio de lecture et de capture
   terminent, et seul le processus Activity de l'application reste sous son
   UID. L'installation utilise une mise à jour conservant les données.
4. Après installation, le client et le propriétaire natif vivant redeviennent
   `ready` en 16,354 secondes. La commande du bureau contient les raccordements
   natifs et `CODEX_CLI_PATH=/usr/local/bin/foldgpt-codex-native`.
5. Depuis le moteur WebRTC du client installé, le périphérique « Samsung Galaxy
   Fold Microphone » fournit un flux `live`, non muet, à 44 100 Hz. Sur 32 768
   échantillons mesurés, RMS ≈ 0,00221 et crête ≈ 0,0394 : le signal n'est pas
   nul. Le haut-parleur est aussi énuméré. Aucun son brut n'est conservé ; les
   pistes du test sont fermées à sa fin.
6. Après ce test micro, un lancement diagnostic reprend les arguments réels
   du bureau. En omettant uniquement le raccordement des projets, il reproduit
   errno 13 sur le même `mkdir`. Avec les raccordements installés, il crée un
   dossier temporaire et écrit un fichier. Le Python natif Android 3.14.7,
   lancé séparément hors PRoot sous l'UID de l'application, lit puis réécrit ce
   même fichier. Le bureau relit la modification ; les inodes concordent.
   Les deux fichiers/dossiers temporaires du test sont ensuite supprimés.
7. Les empreintes des 355 fichiers préexistants sont inchangées, sans fichier
   manquant. Le journal du nouveau client ne contient aucune occurrence
   `EACCES` au relevé de 19:02:48 UTC. Le moteur natif et PulseAudio sont vivants.

Les reçus privés sont sous `work/audio-eacces-20260910/` : `before-apk.json`,
`packaging-guard.json`, `installation.json`, `microphone.json`,
`project-access.json` et `final-check.json`. Les captures de journaux sont sous
`logs/audit-20260910T185150848564Z/` et `logs/audit-20260910T190248592460Z/`.

## Portée

Ces essais établissent la cause et la réparation de l'accès au dossier des
projets après la reconstruction du micro. Aucun nouveau tour modèle n'a été
envoyé pour la validation et le brouillon utilisateur n'a pas été soumis.
La reconnaissance vocale distante, la restitution audible du haut-parleur,
les captures prolongées en arrière-plan et la stabilité multi-conversations
ne sont pas requalifiées par ces essais.
