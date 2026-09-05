# Cible produit

## Expérience

- L'application ChatGPT Android officielle reste utilisable sur les deux écrans, avec Remote natif.
- L'application d'accueil ChatgptFold affiche le client Linux officiel seulement sur l'écran intérieur.
- Replier ou mettre l'interface en arrière-plan conserve le moteur et les tâches. Une action explicite Arrêter ferme proprement le client et l'invité.
- Aucun bureau Linux, terminal ou gestionnaire de paquets n'est exposé dans l'usage normal.
- Installation initiale guidée : téléchargement vérifié, préparation du stockage, démarrage, connexion OpenAI dans le client officiel.

## Contraintes Android à valider

Un service au premier plan avec notification persistante doit posséder le moteur. Une Activity seule ne garantit pas la durée de vie des tâches. Un arrêt forcé Android, un redémarrage ou une pression mémoire critique peuvent interrompre l'exécution ; ne pas promettre la continuité absolue. Le traitement de la fermeture depuis les applications récentes doit être explicite et testé.

L'état plié doit provenir des API de posture/appareil et des changements d'affichage, pas d'une diagonale ou résolution codée en dur. Le grand écran est réservé à l'interface Linux, pas à la durée de vie de son moteur.

## Mises à jour

Trois cycles distincts : application Android d'accueil, environnement Linux, paquet ChatGPT officiel. Conserver le dépôt signé OpenAI. Ne pas patcher le binaire, désactiver sa sandbox ou substituer un navigateur sans besoin démontré.

## État du prototype

Scripts de banc d'essai uniquement. Aucune APK d'accueil n'est livrée à ce stade. PRoot fournit un bureau mais ne lance pas ChatGPT ; la VM Debian complète fait l'objet du test actuel. L'intégration Remote et la connexion OpenAI n'ont pas encore été testées.
