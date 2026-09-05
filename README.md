# ChatgptFold

Objectif : exécuter la véritable application graphique ChatGPT Linux ARM64 localement sur le Galaxy Fold, sans root ni déverrouillage du bootloader.

Architecture envisagée : Termux officiel, Termux:X11, Debian 13 ARM64 via PRoot-Distro. Android/PRoot ne constitue pas une plateforme prise en charge par OpenAI : le lancement, la sandbox, le navigateur et l'authentification doivent être testés réellement.

## Sources

- https://learn.chatgpt.com/docs/linux/linux-app
- https://github.com/termux/termux-app/releases/tag/v0.118.3
- https://github.com/termux/termux-x11

## État

Les trois paquets sont téléchargés dans `downloads/` (non versionnés). Les SHA256 des APK Termux et X11 correspondent aux sommes publiées. Aucun environnement Linux n'est encore installé.

L'APK stable GitHub a été refusé par Play Protect pour cible Android ancienne. La branche officielle Google Play `googleplay.2026.06.21`, targetSdk 37, est installée à la place, sans désactivation des protections. Termux:X11 officiel et son paquet compagnon sont installés.

Debian 13.6 ARM64 (`fold-debian`) et XFCE démarrent réellement sur le téléphone. Le paquet ChatGPT `26.901.41600` est installé avec ses dépendances. L'utilisateur Linux `julien` a été créé.

**Blocage constaté :** ChatGPT quitte avant affichage avec SIGTRAP (code 133). GDB localise une assertion dans la préparation des espaces de noms : le contrôle du drapeau `CLONE_NEWUSER` (0x10000000) échoue. `/proc/self/ns/user` et `/proc/self/ns/pid` sont absents dans cet environnement. Aucun `--no-sandbox`, correctif binaire ou faux namespace n'a été appliqué. Le bureau visible n'est pas une preuve de fonctionnement de ChatGPT.

L'accès de maintenance SSH écoute exclusivement sur `127.0.0.1:8022` côté téléphone, exposé par ADB USB sur le port Windows 18022. La clé locale se trouve sous `%LOCALAPPDATA%/ChatgptFold/usb_ed25519`, hors dépôt. La configuration refuse les mots de passe. L'écran reste éveillé sous alimentation USB à la demande de Julien pendant le projet ; état initial `stay_on_while_plugged_in=0`, restauration par `adb shell svc power stayon false` en fin de projet.

Les scripts `install-debian.sh`, `start-desktop.sh` et `test-chatgpt.sh` documentent les opérations effectuées. Les journaux restent dans `~/fold-logs` sous Termux ; les copies de diagnostic Windows sont exclues de Git. La suite envisageable est une vraie VM avec noyau Linux, à évaluer pour les performances et la disponibilité de l'accélération matérielle Android.

## Critères de réussite

1. Debian ARM64 et affichage X11 fonctionnent réellement.
2. Le paquet ChatGPT officiel démarre avec sa sandbox intacte.
3. La connexion au compte, un projet local et le navigateur intégré sont vérifiés.
4. Un lanceur reproductible et un arrêt propre sont disponibles.

Les garanties contractuelles Care+ ne sont pas déduites du fonctionnement technique. Aucun flash, root, modification de SELinux ou contournement de sécurité n'est prévu.
