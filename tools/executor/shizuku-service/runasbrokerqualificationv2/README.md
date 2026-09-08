# Qualification run-as broker V2

**Exécutée avec succès le 8 septembre 2026 : 12/12 preuves réelles.**
Le superviseur et le worker terminent avec code0 ; nettoyage, absence des PID,
boot et APK inchangés sont recoupés indépendamment. Preuves suivies :
`recovery/verification/runas-broker-20260908`. L'action RUN_BROKER_V2 est
consommée : ne pas la rejouer ni effacer son marker. Les instructions ci-dessous
conservent la provenance de cette qualification, pas une invitation à rejouer.

Nouvel APK `app.foldgpt.runasbrokerqualification.v2`, nouvelle action
`RUN_BROKER_V2`, nouveau marker de l'Activity. Aucun ancien essai n'est rejoué.
Le paquet FoldGPT et l'application officielle ne sont pas mis à jour par cette
qualification. Cible : `run-as app.foldgpt`, UID attesté par PackageManager.

Le même JNI `NativeSpawn` figé transmet fd0..3. Un lanceur Bionic spécifique
vérifie **avant le démarrage de Python** les données privées et les alias de
`/data/user/0/app.foldgpt/files/runas-native-v2/python`, ainsi que tous les ELF
attestés dans l'APK. Les empreintes sont compilées depuis l'inventaire Python
authentifié. Ce lanceur utilise le libcrypto officiel déjà inclus avec Python,
chargé depuis son propre APK. Il n'accorde aucun droit.

Après admission, il exec le nouveau CLI Python avec environnement vide et
`-I -S -B -u`. Le module signé reçoit l'UID, le parent et le nonce attestés ;
aucun chemin ni commande ne provient d'un RPC. Il crée exclusivement
`runas-native-v2/workspace` et `runas-native-v2/broker` neufs. Les protections,
12preuves noyau et limites de `kernel-qualification` sont identiques à celles
du superviseur qKM94iHA, avec le vrai UID FoldGPT cette fois.

Le propriétaire Python conserve le vrai backend et son marker en quarantaine
si le nettoyage natif ne peut pas être prouvé. FD3 est le canal d'annulation.
Le service Java attend le vrai propriétaire et vérifie aussi le reçu de
nettoyage natif ; la fin du PID seule ne prouve pas le nettoyage de descendants.
Un délai de collecte ne doit jamais déclencher un nouvel essai.

## Préparation PC

```powershell
python -B runasbrokerqualificationv2/stage.py --python-cli <nouveau-cli> --python-cli-sha256 <sha-revu>
gradle :runasbrokerqualificationv2:assembleDebug -PfoldgptFrozenTransportJni=C:/Dev/ChatgptFold/tools/executor/shizuku-lab/build/frozen-transport-jni --no-daemon --console=plain
```

CLI requis : RUNPATH exact
`/data/user/0/app.foldgpt/files/runas-native-v2/python/lib:$ORIGIN`.
Stage exclusif courant : `build/runasbrokerqualification-v2/stage-r2`.
Le premier stage, créé avant la correction du nom de bibliothèque CMake, reste
conservé ; il n'a produit aucun APK. R2 distingue aussi la demande de lancement
de la preuve `started` fournie par le vrai superviseur.
Sources Python : snapshotPCv3 figé (factory qKM94iHA identique, listing réparé),
helpers/superviseur/worker Android : qKM94iHA figé.

## Préparation Android à réaliser séparément par le responsable du test

Après revue et installation de l'APK séparé, obtenir `nativeLibraryDir` par
`COLLECT_INFO`. Copier uniquement `stage/staged-python-data` dans le préfixe
Python privé de FoldGPT avec propriétaires corrects ; créer les81alias exacts
de `stage/runtime-manifest.json` vers le `nativeLibraryDir` de ce nouvel APK.
La base et le dossier Python doivent être0700, les fichiers privés ordinaires
0600 et les sous-répertoires0700. Ne pas créer workspace/broker : le bootstrap
doit les réserver de manière exclusive.

Composant :
`app.foldgpt.runasbrokerqualification.v2/app.foldgpt.runasbrokerqualification.RunAsBrokerQualificationActivity`.
Actions : préfixe `app.foldgpt.runasbrokerqualification.v2.` suivi de
`COLLECT_INFO`, `AUTHORIZE`, `PREFLIGHT` ou `RUN_BROKER_V2`.
Rapport privé de l'APK : `files/runas-broker-v2/run_broker_v2.json`.

Le préflight Java recoupe les APK ; le contrôle du runtime privé est fait par
le lanceur natif après run-as, puisque shell ne peut pas ouvrir ces données.
Un succès de construction PC n'est pas une preuve d'exécution Android.
