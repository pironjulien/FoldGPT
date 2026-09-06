# Brouillon X — 6 septembre 2026

Brouillon uniquement ; aucune publication effectuée.

## Aperçu publiable du prototype

> FoldGPT : le client officiel ChatGPT/Codex tourne sur mon Fold sans root, en ARM64 avec GPU Adreno. Menus corrigés et navigation de base testée. 17 tests de commandes natives passent. Prototype : tâches protégées et installation autonome restent à terminer.

Les preuves qualifient le téléphone testé : [foldgpt5](verification-gpu-renderpasses-2026-09-06.md)
passe 24 cas pixels et le parcours des 20 paramètres ; le [navigateur intégré](../tools/browser/README.md)
a réellement ouvert/lu Example Domain, cliqué vers IANA puis effectué le retour ;
la [fixture RPC Android](../tools/executor/native-files-android-rpc.md) passe
34 réponses et 12 groupes avec collecte indépendante. Un [pont privé ultérieur](../tools/executor/private-exec-android.md)
relie le client de test GNU au broker Android : 53 réponses sur deux sessions,
dont parcours des dossiers, copie/suppression, refus d’accès et lecture par blocs
d’un fichier de 37 Mio, vérifiés par une collecte indépendante.

La [suite d’acquisition native](../tools/executor/native-managed-android.md) passe
ensuite 17 tests et 46 observations de processus réels, avec l’interface graphique
active : exécution statique ARM64, règles d’accès aux fichiers, exceptions de
métadonnées, mutations des pointeurs après copie, flags des descripteurs,
expiration, annulation et nettoyage des descendants. La collecte indépendante
lie les événements au véritable APK, à 30 bibliothèques et huit sources exécutées.
Le comptage des tâches UID corrige l’échec initial de fork sans arrêter l’interface
ni relever les plafonds hérités. Ces diagnostics ne raccordent pas encore une
tâche modèle normale ou le cycle complet des RPC de processus ; le shell,
stdin/TTY, le réseau et le routage Desktop restent à intégrer et vérifier.

Le diagnostic du runtime officiel Linux ARM64 retourne encore HTTP 404. La
préparation complète v2 Debian/compte/client/coffre a passé deux appels sur
Android en restant inactive ; la v3 ajoutant l’intégration GPU a également
réussi ses deux appels sur le Fold après correction d’un conflit de permissions.
La collecte indépendante retrouve les 345 entrées et les mêmes identités/hashes.
L’APK `f6f5...` a produit ce rapport ; la collecte ultérieure sous `b47b...` a
inspecté le même état conservé sans réexécuter la préparation. Les [preuves v3](install/inactive-native-integration.md)
précisent les deux APK et leurs hashes complets.
Aucun APK autonome ou exécuteur complet n’est annoncé.

## Conditions avant une annonce « APK prêt »

- Installer depuis des données d’application vierges : composants authentifiés,
  enchaînement de la préparation v3 déjà vérifiée vers la validation complète,
  l’activation atomique, le démarrage et la connexion officielle, sans image
  Termux préconfigurée.
- Exécuter une tâche Codex normale avec le véritable routage Desktop, des
  commandes et modifications de fichiers protégées ; vérifier les accès permis
  et refusés, les politiques par requête et le nettoyage des processus.
- Résoudre la fourniture du runtime ARM64 signalée par le diagnostic et tester
  les fonctions navigateur restantes, dont transferts de fichiers,
  authentification et sites de développement locaux.
- Vérifier redémarrage, pliage, verrouillage/déverrouillage et reprise d’une
  tâche active, ainsi que la durée en arrière-plan et les contrôles GPU restants.
- Établir le stockage durable des données et tester les mises à jour APK,
  runtime et client avec conservation du compte, du coffre et des espaces de
  travail ; vérifier récupération et retour à une révision compatible.
- Fournir une identité de signature APK durable, un canal de mise à jour
  authentifié, l’inventaire exact des composants, leurs sources correspondantes
  et les notices requises, sans client propriétaire ni données de compte inclus.

Ces critères reprennent le [contrat d’acceptation](install/end-to-end-architecture.md#acceptance-and-publication-evidence).
Les tests actuels n’établissent ni 120 FPS, ni fiabilité universelle, ni sécurité
de production, ni garantie de compatibilité Knox/paiement/garantie constructeur.
