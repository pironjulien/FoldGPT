# Changelog

## 2026-09-05

- Création du projet pour ChatGPT graphique Linux ARM64 sur Fold.
- Vérification de la documentation officielle OpenAI et Termux:X11.
- Téléchargement du DEB officiel et vérification des empreintes des APK officiels.
- Installation de Termux Google Play compatible Android 17 et de Termux:X11 sans désactiver Play Protect.
- Installation et démarrage vérifiés de Debian 13.6 ARM64 et XFCE.
- Installation du paquet ChatGPT 26.901.41600 ; échec au démarrage SIGTRAP dans un contrôle de namespace utilisateur.
- Ajout des scripts reproductibles et accès SSH par clé limité au loopback via ADB USB.
- Tests AVF/Gunyah : Microdroid protégé démarre sans root hôte, mais son noyau minimal ne fournit pas les namespaces recherchés.
- Prototype QEMU Debian ARM64 complet : démarrage, cloud-init et namespaces utilisateur vérifiés. Installation graphique en cours, résultat non encore utilisable.
- Client officiel installé dans la VM, lancement au-delà du blocage PRoot, fenêtre de création du trousseau sécurisé affichée. Authentification et usage restent à vérifier.
- Connexion OAuth du client Linux au compte demandé vérifiée ; tunnel de callback temporaire, aucun binaire modifié.
- Essai après connexion : écriture du fichier d'accueil vérifiée ; tâche personnalisée non confirmée après plusieurs minutes. Prototype non validé, Remote non testé.
