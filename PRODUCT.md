# Cible produit

## Expérience visée

- Une seule application FoldGPT héberge le client Linux officiel sur l'écran intérieur, sans terminal ni bureau Linux visible.
- L'application ChatGPT Android officielle reste utilisable sur les deux écrans ; Remote doit atteindre la même instance Linux.
- Replier le Fold ou passer en arrière-plan conserve le moteur et les tâches, jusqu'à une action explicite Arrêter.
- L'installation guidée télécharge les composants vérifiés, prépare le stockage et laisse la connexion OpenAI au client officiel.

Ces comportements de routage entre écrans, de Remote et de continuité restent des objectifs à tester.

## État vérifié

L'APK `app.foldgpt` possède désormais son affichage Termux:X11, son service et son stockage Linux. Le client officiel et l'interface Codex fonctionnent dans ce nouvel hôte, sous son propre UID Android. Le PRoot compilé depuis les sources corrige les chemins des chargeurs ; le partage mémoire et `xfwm4` permettent l'affichage plein écran 2448 × 1848.

Le clavier Samsung s'ouvre au toucher d'un champ et se ferme au toucher extérieur. La réouverture indésirable provoquée par le focus automatique après envoi reste en cours de correction et de vérification. Le mode d'écran annoncé à 119,98 Hz ne mesure pas les images par seconde produites par l'application.

Les commandes locales Codex restent bloquées. Un diagnostic reproduit l'échec de `bwrap --help` par refus d'accès à `/proc/sys/kernel/overflowuid`. Le shim actuel simule des appels d'isolation ; le confinement nécessaire au produit final reste à résoudre.

## Travail restant

Le service au premier plan possède le moteur, mais sa présence ne garantit pas la continuité après repliage, retrait des applications récentes, pression mémoire ou arrêt forcé. Le routage doit utiliser les API de posture et les changements d'affichage, sans déduire le repliage d'une résolution fixe.

Trois cycles de mise à jour doivent être validés : hôte Android, environnement Linux et client ChatGPT officiel. Préserver les fichiers et le dépôt officiels ne suffit pas à démontrer la compatibilité du shim avec leurs mises à jour.

La compilation et la migration actuelles utilisent encore Termux et des outils de développement. La publication fournit les sources du prototype ; l'installation neuve et la bêta restent à réaliser. Voir [PUBLICATION.md](PUBLICATION.md).
