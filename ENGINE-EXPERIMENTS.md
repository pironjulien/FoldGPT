# Essais moteur — 5 septembre 2026

## Contraintes

Client ChatGPT officiel non modifié, mises à jour officielles, aucun root du téléphone ni déverrouillage. Interface Linux seulement sur écran intérieur ; tâches actives après repliage jusqu'à arrêt explicite. L'application Android officielle et Remote sont conservés.

## AVF / Gunyah

`vm info` : seules les VM protégées sont prises en charge, hyperviseur Gunyah, aucun /dev/kvm, OS fourni : microdroid. L'application Terminal système est présente mais ses activités ne sont pas disponibles au lancement normal.

Deux essais avec `vm run-microdroid --protected --ephemeral` ont atteint `payload is ready`, avec et sans débogage invité. Aucun root hôte utilisé. Le mode de débogage invité est une option officielle du moteur ; SELinux reste Enforcing.

Le noyau invité Microdroid 6.6.118 ne présente pas les namespaces user/pid dans `/proc/self/ns`. Ce résultat ne suffit pas à choisir Microdroid pour Chromium. Le lancement brut du JSON Microdroid sans ramdisk échoue pour métadonnées invalides ; ce test incomplet ne démontre pas une interdiction générale des OS personnalisés. Les deux VM de test ont été arrêtées.

## QEMU

Test d'un noyau Debian complet en émulation ARM64 TCG multithread : image officielle Debian 13 generic ARM64 du 31 août 2026, SHA512 comparé au manifeste officiel. Disque extensible 16 Gio, mémoire invitée 4 Gio, 4 vCPU. Ce sont des paramètres de banc d'essai, pas une allocation finale optimisée.

Cloud-init crée un utilisateur julien avec accès SSH par clé seulement. Les ports de maintenance écoutent sur loopback et passent par ADB USB. Aucun compte ChatGPT ni mot de passe utilisateur n'est injecté dans l'image.

La preuve recherchée est le lancement réel de ChatGPT avec sandbox, puis une mesure des performances. Une VM démarrée ne constitue pas une version fonctionnelle du produit.

Résultat intermédiaire : Debian démarre, cloud-init termine, accès SSH par clé vérifié. Noyau `6.12.107+deb13-arm64`. `unshare --user --map-root-user id` fonctionne depuis l'utilisateur invité julien : l'isolation utilisateur manquante sous PRoot existe ici. Le uid 0 affiché concerne ce namespace invité, pas un root du téléphone. Installation du client officiel en cours. Premier démarrage de plusieurs minutes, performances interactives non encore validées.

Installation terminée (`VM_CLIENT_INSTALLED`, version 26.901.41600). Le lancement via SSH X11 depuis Termux dépasse le SIGTRAP de PRoot : processus principal et zygotes Chromium présents. Fenêtre ChatGPT créée (1280×820), puis demande graphique de création du trousseau gnome-keyring affichée sur le Fold. En attente de saisie personnelle du mot de passe du trousseau ; aucun secret OpenAI ni mot de passe saisi par l'agent. Ne pas considérer cela comme un test de connexion réussi.

Observation de performances : remettre Termux au premier plan a coïncidé avec une accélération importante de la préparation des paquets. Cela devra être mesuré formellement avant de choisir l'architecture finale. L'installation et le premier lancement TCG prennent plusieurs minutes.

19:58 : création du trousseau autorisée par Julien avec mot de passe aléatoire conservé exclusivement dans NexusSecure/projects/ChatgptFold/linux-keyring-password.txt. Contrôle NexusSecure vert. Fenêtre officielle « Sign in to ChatGPT » affichée et vérifiée visuellement sur le Fold. Connexion au compte pas encore validée.

Sources :
- https://source.android.com/docs/core/virtualization
- https://android.googlesource.com/platform/packages/modules/Virtualization/+/refs/heads/android17-release/docs/custom_vm.md
- https://cloud.debian.org/images/cloud/trixie/latest/

20:18 : authentification OAuth officielle réussie pour le compte de test autorisé. Utilisation du bouton Copy sign-in link et du navigateur intégré, avec tunnel SSH loopback Windows1455 vers VM1455 pour le callback. Le navigateur affiche Connexion réussie et le journal du client confirme authenticatedAccountPresent=true, authMethod=chatgpt, result=succeeded. Chargement de l'interface en cours ; aucune tâche encore validée.


20:30 : test fonctionnel après connexion. Le parcours d'accueil a créé /home/julien/Desktop/Note from ChatGPT.txt, contenu relu par SSH. Le répertoire Desktop manquait dans l'image minimale : création du dossier puis permission accordée via UI. Ce test d'accueil ne prouve pas l'exécution agentique. Consigne personnalisée envoyée vers 20:26 : créer fold-smoke-test/result.txt avec marqueur et uname. À 20:30, fichier absent et interface Task creation is not yet confirmed. Journaux : délais de démarrage outils, timeout plugin/list, manifeste primary runtime HTTP404. Causalité exacte non établie. Remote non testé faute de tâche confirmée. Verdict : prototype TCG non validé pour usage réel, aucune désactivation de sandbox ou root hôte. Capture logs/smoke-task-unconfirmed.png (ignorée par Git).

