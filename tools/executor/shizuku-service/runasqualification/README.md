# Qualification run-as V1 : identité et quatre FD

APK séparé `app.foldgpt.runasqualification.v1`. Il ne met pas à jour FoldGPT
ou ChatGPT. Son UserService Shizuku shell2000 lance exclusivement
`/system/bin/run-as app.foldgpt <son ELF Bionic signé> --identity-fds-v1 …`
par le `NativeSpawn` de production inchangé. Le paquet cible doit porter la
signature FoldGPT préservée et être debuggable. Les identités PackageManager,
chemins d'installation, empreintes APK et bibliothèques sont explicitement
recoupés côté Activity et UserService avant lancement, puis après le vrai waitpid.

L'ELF vérifie UID/GID réels/effectifs/sauvegardés, capabilities, contexte,
NoNewPrivs/Seccomp, parent réel, propriétaire/résolution du répertoire privé,
quatre pipes et fermeture de tous les autres FD. Deux challenges nonce exacts
suivis d'EOF arrivent sur FD0/FD3 ; des reçus indépendants sortent sur FD1/FD2.
Le programme n'a aucun enfant. Une alarme borne sa vie à20secondes. Il ne lance
aucun ancien probe et ne modifie aucune politique, identité ou protection.

Cette phase ne qualifie **ni le broker, ni Python, ni le partage PRoot**.
Le succès Android reste à démontrer avec le vrai APK, pas avec une fixture PC.

## Actions explicites

Composant :
`app.foldgpt.runasqualification.v1/app.foldgpt.runasqualification.RunAsQualificationActivity`

Actions exactes, réservées par la permission Android DUMP au lanceur shell :

- `app.foldgpt.runasqualification.v1.COLLECT_INFO` : identité installée locale, sans UserService.
- `app.foldgpt.runasqualification.v1.AUTHORIZE` : demande officielle Shizuku, sans lancement natif.
- `app.foldgpt.runasqualification.v1.PREFLIGHT` : comparaison identité Activity/service, sans lancement natif.
- `app.foldgpt.runasqualification.v1.RUN_IDENTITY_FDS_V1` : unique essai ; réserve `files/runas-identity-v1/attempt-started-v1` avant bind.

Ne jamais effacer le marker, nettoyer les données ou rejouer l'essai consommé.
Un refus garde les vraies sorties et le statut waitpid ; aucun succès n'est déduit
d'une échéance. Un propriétaire non reaped reste en quarantaine.

Le rapport final se collecte par `run-as app.foldgpt.runasqualification.v1 cat
files/runas-identity-v1/run_identity_fds_v1.json`. Les autres actions ont des
fichiers `collect_info.json`, `authorize.json`, `preflight.json` voisins.
Le vérificateur indépendant est `python -B runasqualification/verify-identity.py <rapport>`.
Recouper aussi boot ID, PID absent après wait et APK cible inchangé depuis le PC.

## Construction Windows

Java21, Android SDK37/NDK29.0.14206865, Gradle9.7.1, clé préservée fournie
par `tools/recovery/android-signing.gradle`.

```powershell
# Depuis tools/executor/shizuku-service
gradle :runasqualification:assembleDebug -PfoldgptFrozenTransportJni=C:/Dev/ChatgptFold/tools/executor/shizuku-lab/build/frozen-transport-jni --no-daemon --console=plain
```

L'APK est sous `build/runasqualification-v1/modules/runasqualification/outputs/apk/debug/`.
Les builds/artefacts restent dans le projet. L'essai téléphone est séparé de la
compilation et doit attendre la revue de cet APK et de ses empreintes.
