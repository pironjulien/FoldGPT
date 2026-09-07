# Résultat V12 sur le Fold — 7 septembre 2026

La qualification native fixe V12 **réussit sur le Fold réel**. Le collecteur
indépendant valide ses 24 contrôles. Cela établit les mécanismes de l'exécuteur
Shizuku/Bionic employés par ce worker ; les commandes ordinaires depuis
l'interface FoldGPT restent à raccorder et à vérifier.

## Résultat et preuves

Le worker démarre sous Android, exécute ses opérations depuis le thread principal
et un pthread, puis quitte avec 0. Il vérifie lecture/écriture mémoire,
`pidfd_getfd`, partage réel des offsets de dossiers et refus des opérations
non admises. Les 301 octets stdout concordent dans les rapports natif et RPC ;
stderr est vide. Le superviseur rapporte 16 autorisations et 22 refus.

Le nettoyage natif et du transport est confirmé par les propriétaires réels :
superviseur attendu, sortie 0, `cleanupComplete=true`, absence des processus
après collecte et aucune quarantaine V12. Le boot avant/après est identique
(`348d453e-f4e5-40e0-8ef0-030f4d5e38af`). Les APK FoldGPT, V10 et V11, la fixture
et les indicateurs d'intégrité contrôlés sont inchangés. Ce constat porte sur
cet essai et ne constitue pas une garantie générale de stabilité.

Les [copies exactes et leurs empreintes](../../recovery/verification/native-v12-20260907/manifest.json)
comprennent les admissions, snapshots avant/après, rapports et validation
indépendante. Les sorties complètes locales sont dans
`downloads/native-kernel-trial/v12-fixed-collection-20260907`.

| Entrée figée | Identité |
|---|---|
| Package | `app.foldgpt.kernelqualification.v12` |
| Base | `/data/local/tmp/foldgpt-bionic-supervisor-qualification-v4` |
| Build superviseur | `foldgpt-bionic-supervisor-PHREPY0u` |
| Superviseur ARM64 SHA256 | `7ed43a09ad5e22cb5e5e1ae347d83947f1f6167a797c8aa8b9d399bf09645a03` |
| CLI Python SHA256 | `0f25bf5dba0627b4fd31ee03e15a2b7673270df26249c7f4fb12f1d862ec2e1c` |
| APK SHA256 | `0bb75d5bb2af7638b8bc6337d18e3a0b6853e2fca3a6d84554f248f86d3ba2d1` |
| Rapport application SHA256 | `2245732dcaecd7e180dddf4ce43fa5c448e26df133385e58460c38d48d0b1099` |
| Rapport natif SHA256 | `d22f3ea5925005cc2a23dc0f6d522e10375b3e3c07c6a9d4aaa16ee600ab7685` |

L'APK vérifié est conservé sous
`tools/executor/shizuku-service/build/qualification-v12-independent`.
Sa compilation et les 24 tests JVM du transport passent. Les tests PC
d'empaquetage et d'identité totalisent 13 succès ; l'inventaire du stage
contrôle 2 557 entrées, 82 bibliothèques et 2 447 fichiers Python.

## Cause du précédent blocage

V11 échouait à identifier l'exécutable au chargement. V12 fournit les vraies
métadonnées de l'alias exact `/proc/self/exe`. La lecture des binaires Samsung
réels a établi que le chargeur conserve le chemin initial si `realpath` échoue
après un `stat` réussi. Le chargement et le worker ont ensuite réussi sur le
téléphone. Aucun faux descripteur `O_PATH`, remplacement par `O_RDONLY`, accès
global à `/proc` ou changement de chemins de bibliothèques n'a été introduit.

## Suite et limites

L'action unique `.KERNEL_RUN_FIXED_V12` est consommée. Ne pas relancer V12 ni
effacer son marker. V11 et la quarantaine historique V10 restent conservés.
Ne pas réactiver l'ancien diagnostic GNU/PRoot associé aux redémarrages.

Le prochain package isolé `app.foldgpt.runtimequalification.v1` doit exécuter
Bash puis le petit projet Python : création, modification, trois tests,
archive exécutable, flux binaires et refus. Ce workload passe déjà sur PC,
mais un test d'annulation a révélé une course dans la transmission du rapport
final. Sa correction et ses régressions sont en cours avant de figer ce
nouveau package. Aucun succès Android de ce nouveau workload n'est revendiqué.

Le raccordement du moteur auxiliaire, les accès projet du contrôleur et les
autorités filesystem restent également à terminer. Lire
l'[audit du contrôleur](native-executor-controller-path-audit-2026-09-07.md).
L'interface actuelle conserve encore sa compatibilité GNU/PRoot ; la réussite
de l'exécuteur Bionic ne signifie pas que toute l'application est portée.
