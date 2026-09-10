# FoldGPT — point d'entrée de reprise

**État installé : r46/versionCode36, 10 septembre.** APK avec micro et paquet
natif r45 réintégré, SHA-256
`9ccf9da356c2bcef20fc0f3ac295948e3dea0b21b08079f2f41bc3fdf6faf7c5`.
La reconstruction précédente du micro avait omis le paquet natif : le client
ne raccordait plus `files/projects`, d'où `EACCES` à la création d'une tâche.
Le packaging APK/AAB refuse désormais les entrées natives manquantes ; utiliser
`tools/runtime/build-production-candidate.py` avec un paquet explicite.
Lecture/écriture aller-retour client/moteur natif et capture WebRTC réelle du
micro vérifiées sur le Fold ; les 355 fichiers de projet sont inchangés.
Voir [le diagnostic et les limites de validation](docs/research/audio-eacces-20260910.md).

**État précédent : r45/versionCode35, 9 septembre.** APK relu sur le téléphone :
`c60f842d07706f45c83357e69845eefe2e9f6d1dae75a4baaa1755a82b966da3`.
Plugin `0.1.0+codex.20260909132129`, fichiers installés identiques aux sources.
Accès écran autorisé et actif ; ne pas redemander cet accord. READ_SMS et
SEND_SMS restent non accordées. Aucun SMS lu ou envoyé pour les essais.

**Reprise après crash vérifiée.** Après SIGKILL du propriétaire natif puis du
service Java, le client redevient prêt en 18 286 ms, sans relance ni réparation
depuis le PC. L'ancien marqueur est archivé avec ses octets et son inode,
après verrou exclusif, identité du workspace et recensement des survivants.
Les threads Java sont reconnus par leur appartenance noyau ; `/proc` seul est
insuffisant sur ce téléphone. L'arrêt explicite persiste l'intention contraire.
Après 122 secondes il reste `closed`, sans notification ni processus moteur.
Le test séparé est désinstallé. Preuves et limites dans
[la reprise de session](docs/session-recovery.md), notamment `r45-hard-crash.json`.
Lancement v3 et nouveau paquet `work/android-extension-20260909/executor-r45` ;
la commande Gradle enregistrée pointe sur ce paquet. Régénérer les sources
via `stage-executor.py` avant toute nouvelle modification du runtime Python.

**Clavier Linux corrigé et vérifié.** R42 et r43 perdaient des caractères au
premier usage dans le navigateur. Chromium conservait son cache : il souscrit
à NewKeyboardNotify plutôt qu'aux modifications partielles envoyées par Lorie.
R44 publie le nouveau mapping virtuel après cohérence master/source et avant
frappe. La phrase « FoldGPT contrôle écran 123 — été Noël, Ω 中 🙂 » arrive
exactement au premier essai après redémarrage. Le composeur reçoit aussi
4 096 caractères exacts (21,53 s) et l'annulation laisse un préfixe stable de
40 caractères. Aucun brouillon envoyé, champ restauré vide. Preuves :
`work/android-extension-20260909/r44-linux-input.json` et `r44-linux-composer.json`.

Le lecteur serveur est incrémental et non bloquant, les producteurs client/GPU
sont sérialisés par trame et le dispatch conserve l'ordre. Le corps clipboard
retour est lu à sa longueur exacte et son contenu n'est plus journalisé. Les
suites ASan/UBSan lecteur/dispatcher/writer/XKB passent. Le chemin legacy
retour reste synchrone ; les gros transferts bidirectionnels ne sont pas qualifiés.
Natif `6955e9b377263a6f28b133a2f803c7b9b9086394ed581641960157871ee62e63`,
build `downloads/gpu/x11/build-AfibPN40/artifact`. APK et natif correspondants
vérifiés, ABI ARM64, JNI et alignement 16K contrôlés.

Échange 23 sur r42 : ChatGPT a cliqué/saisi/vérifié/effacé le texte accentué du
composeur avec ses propres MCP. **Échange 24 sur r44 terminé** dans « Analyser
le logiciel », ID `01a082ec-f39e-7b40-94f6-74b4b1992811` : vraie saisie
« Saisie vérifiée : æ ÿ Ж Œ € ✅ », capture exacte, sélection/effacement puis
capture du composeur vide. Aucune difficulté signalée pour cet essai.
Preuves `r44-phone-input.json`, `r44-phone-input-2.png` et `r44-phone-input-4.png`.
L'échange 22 avait réalisé 7 + 8 = 15 dans la calculatrice Android, contrôlé
l'arbre et la capture, refusé un ancien ID puis repris FoldGPT.

**Limites encore ouvertes :** la cause de la disparition constatée avant r41
reste inconnue. R45 corrige la reprise testée après disparition de l'ancien
moteur ; un propriétaire survivant ou en quarantaine reste refusé.
La pression des processus Android, la veille/pliage prolongés et la compatibilité
universelle des plugins ne sont pas qualifiés. Les 355 fichiers de projet et
le préfixe d'historique restent intacts. État final `ready`, 33 processus sous
l'UID, historique de 12 641 382 octets et conversation terminée
(`work/dependencies-fix-20260909/r44-final.json`).
Voir [les preuves et limites](docs/android-tools.md).

Téléphone USB `R3GL808JN4A`, déplié/déverrouillé lors des essais. Toujours lancer
sur affichage physique 0, sans simuler le pliage. Pas de root/bootloader/Knox.
Aucun nouveau complément de reprise distant publié pendant cette livraison.

## Historique des livraisons précédentes

**R38/versionCode28 installé, 9 septembre.** APK
`f5e93e4267a182d2218821ab5b6fedff74bd6303cc3cde710cd1c0000c53d72a`,
plugin `0.1.0+codex.20260909132129`. Julien a autorisé le contrôle écran ;
accessibilité active, READ_SMS et SEND_SMS toujours non accordées. Ne pas
redemander son accord écran. Client officiel et propriétaire natif `ready`
sur l'écran intérieur après installation. Nouvelle saisie X11 asynchrone,
annulable et sans journal de texte ; 25 tests natifs passent. Correction des
relances involontaires après fermeture ; 20 tests lancement/arrêt passent.
Échange 20 dans « Analyser le logiciel » en cours pour calculatrice/capture.
Essais saisie Linux et fermeture réelle restent à terminer. Voir
[les capacités et preuves actuelles](docs/android-tools.md).

Le téléphone a basculé de USB vers ADB Wi-Fi puis de nouveau USB. Pour les
essais physiques, lancer avec `am start --display 0 -n app.foldgpt/.FoldActivity`
afin de ne pas utiliser un écran virtuel scrcpy actif sur le PC. Aucun état
matériel de pliage n'a été simulé. Le marqueur orphelin avant r38 est archivé
avec preuve de quiescence complète dans
`work/android-extension-20260909/r37-stopped-owner-recovery-wifi`.

**R36/versionCode26 : contrôle global et accès simplifié.** Plugin
`0.1.0+codex.20260909130358`, APK SHA256
`cf485f30b6438b5c6492ece75546e0f88bf80c7fc01f2254351568079286f7ef`.
Suppression des interrupteurs locaux : les permissions Android font autorité.
`android_request_access(scope)` présente le consentement, sans auto-grant ou
rejeu. Entrées texte/clavier dans la surface Linux visible, contrôle des rotations
et protection des parcours d'autorisation. Les actions avec accès activé restent
à éprouver ; ne pas annoncer une parité universelle avec Windows/macOS.
Échange 17 : les nouveaux outils sont exposés ; READ_SMS est refusé explicitement
par absence de permission, plus de verrou sms_disabled. L'ouverture initiale de
la fiche accessibilité a été refusée par Samsung : le correctif emploie uniquement
`Settings.ACTION_ACCESSIBILITY_SETTINGS` public. Le retour MCP annonce un
dispatch/pending et ne confond pas une demande lancée avec un accord ou écran
observé. Aucun accès SMS ni accessibilité accordé automatiquement.
Échange 18 terminé : vrai MCP `android_request_access(screen_control)` retourne
`permission_request_dispatched`, puis `com.android.settings/.Settings$AccessibilitySettingsActivity`
est réellement au premier plan (capture `work/dependencies-fix-20260909/r36-public-consent-result.png`).
La décision d'activation reste à Julien. Ne pas lire ses SMS ou activer l'envoi
pour tester ; le prochain essai utile est contrôle d'une interface anodine après
accord. À l'accord, vérifier toutes les surfaces réelles et les erreurs de
snapshot périmé, sans qualifier la parité globale à partir d'une seule action.
L'écran a ensuite été préparé jusqu'à **Contrôle Android FoldGPT — Désactivé**
via les deux lignes observées Applications installées / Contrôle Android FoldGPT.
Le bouton n'a pas été activé ; `enabled_accessibility_services` reste `null`.
Capture finale : `work/dependencies-fix-20260909/r36-control-access-ready.png`.

**Extension en cours : r35/versionCode25 installé, 9 septembre.** Voir
[les outils Android et leurs limites](docs/android-tools.md). Plugin personnel
`foldgpt-android` installé avec accès contrôle/SMS désactivés en attente d'accord
d'activation. Révision installée `0.1.0+codex.20260909125234` : le format
legacy de manifeste n'interpole ni `${CODEX_PLUGIN_ROOT}` ni `${PLUGIN_ROOT}`.
Le correctif utilise `cwd: "."` (résolu par le moteur au dossier du plugin)
et `scripts/server.py` comme argument. Échange 16 sur le téléphone : vrais MCP
`android_status`, puis refus `global_control_disabled` et `sms_disabled`.
Aucune lecture SMS, capture par le plugin ou activation réalisée. APK SHA256
`dfbb826f5e733c216ed9f17e5182da197582ce5752dbca8ef1afc60b153072d7`.
Le retour Android `codex://connector/oauth_callback`
atteint désormais le client officiel ; aucune authentification tierce complète
n'est qualifiée par la fixture sans code. Android a tué le propriétaire natif
par `Trimming phantom processes` pendant cette séance : historique et 355
fichiers préservés, récupération avec preuve de quiescence complète de l'UID.
Ce problème de pression des processus reste ouvert.

**Dernier état : r34/versionCode24 installé, 9 septembre.** Le paquet
FoldGPT-ARM64-2026.09.09.2 et le moteur corrigé réparent l'installation des
dépendances et la synchronisation des cinq plugins. Un fichier manquant est
détecté par **Diagnostiquer**, puis restauré par **Réinstaller** avec son hash
original. Le diagnostic repasse après un arrêt et une réouverture normaux.
Voir [les composants livrés et le changement de source](docs/workspace-dependencies.md).

Le lancement direct et les notifications des conversations restent livrés ;
leur preuve initiale est dans le [rapport r31](docs/research/r31-startup-notifications-20260909.md).
Le [constat initial des dépendances](docs/research/workspace-dependencies-20260909.md)
conserve le catalogue reçu et son HTTP 404. Le paquet de remplacement est
identifié FoldGPT ; il ne se présente pas comme une publication OpenAI ARM64.

**Référence précédente : r28/versionCode18.** Démarrage direct depuis FoldGPT
sans Shizuku, ancienne conversation reprise sans correction temporaire du cwd,
projet Python créé, six tests réussis, zipapp construit et exécuté. Arrêt propre
et réouverture démontrés. Après reboot complet Android, la même conversation
repasse six tests et exécute son zipapp, sans préparation du moteur par le PC.
Voir le [rapport r28](docs/research/r28-device-validation-20260908.md).

L'[inventaire demandé du client desktop](docs/research/desktop-client-inventory-20260908/README.md)
couvre 9 737 JavaScript et 57 ELF. Il a permis d'identifier les délais de
conservation des conversations : jusqu'à une heure côté interface avant
désabonnement, puis 30 minutes côté moteur. r26b a atteint 45 processus UID
et subi un arrêt Android par dépassement de la limite des sous-processus.
Ce défaut de fiabilité reste ouvert ; aucun réglage Android n'a été désactivé.

**Priorité confirmée par Julien : ouvrir FoldGPT et travailler avec le PC
éteint.** Le panneau de terminal manuel est reporté ; il n'est pas nécessaire
pour qualifier le travail depuis la conversation. La [revue des alternatives](docs/research/phone-only-options-20260908.md)
retrouve un résultat Python Bionic sous application ordinaire : Shizuku est
une dépendance de r25, supprimée du lancement courant dans r26b/r28. La reprise
après arrêt propre et après reboot complet est démontrée. La stabilité durable
avec plusieurs conversations reste à corriger.

Le statut technique actuel et les prochaines étapes sont dans
[recovery/HANDOFF.md](recovery/HANDOFF.md). Les commandes ordinaires depuis
l'interface sont maintenant validées pour le parcours Python natif Android :
création, tests, construction, puis reprise d'un projet avec Packaging 26.3
sous r24. R28 ajoute la reprise après reboot sans préparation du moteur par le PC.
Le panneau de terminal utilisateur reste à qualifier ; interface et contrôleur
utilisent encore PRoot.

La récupération des sources, dépendances et preuves est décrite dans
[recovery/README.md](recovery/README.md). Le dépôt de travail est **privé** :
`pironjulien/FoldGPT-workspace`, branche `codex/foldgpt-beta`.
Le [complément v16](recovery/supplement-v16.md) est publié, retéléchargé et
restauré : 39 584 fichiers et 1 252 sources Git vérifiés, APK r24/r25 revérifiés.
Le [complément v17](recovery/supplement-v17.md) est publié, retéléchargé et
restauré : 20 008 fichiers, 1 433 sources Git, trois APK revérifiés et
24 346 copies d'audit reconstruites. Il complète l'archive principale et les
compléments 1 à 16. Une copie chiffrée redondante de 1,76 Go a été retirée.
Tous les téléchargements, snapshots et rapports de reprise vont sous
`C:\Dev\ChatgptFold\work\FoldGPT-recovery`. Les outils de fusion acceptent
ce confinement précis et protègent les sources Git ainsi que leurs snapshots.

Les preuves et limites de chaque essai sont consignées dans les documents liés.
Les consulter avant toute action sur le téléphone ; aucune publication publique
ne fait partie de cette reprise.
