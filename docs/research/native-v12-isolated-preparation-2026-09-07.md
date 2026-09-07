# Préparation V12 indépendante — 7 septembre 2026

**État actualisé :** la préparation décrite ci-dessous a été suivie d'un build,
d'une installation et de l'unique essai V12 sur le Fold, réussi. Lire le
[résultat Android et ses preuves](native-v12-device-result-2026-09-07.md).
Ne pas rejouer les commandes de déploiement ni l'action unique.

Le texte suivant conserve l'état historique de la préparation PC. Les sources et le staging V12
sont prêts ; aucun APK V12 n'a été compilé par cette préparation, aucun paquet
n'a été installé et aucun essai Android n'a été lancé. Le [résultat V11](native-v11-device-result-2026-09-07.md)
reste un échec du worker avec sortie127, malgré son nettoyage confirmé.

## Entrées et identité

| Élément | Valeur V12 |
|---|---|
| Application | `app.foldgpt.kernelqualification.v12` |
| Version APK / diagnostic / UserService | `12` |
| Base native | `/data/local/tmp/foldgpt-bionic-supervisor-qualification-v4` |
| Rapports | `files/kernel-v12` |
| Tag UserService | `foldgpt-kernel-qualification-v12` |
| Suffixe processus | `kernelqualificationv12` |
| Action unique de travail | `.KERNEL_RUN_FIXED_V12` |
| Backend figé | `foldgpt-bionic-supervisor-PHREPY0u` |
| Façade fixe | `qualification_factory_v12:factory` |

Les identités V10/V11, leurs bases V2/V3, APK figés, preuves et markers ne sont
ni remplacés ni supprimés. La façade V12 délègue à la même implémentation
`_factory` avec sa base fixée dans l'APK ; aucune option RPC ne choisit la base.
La nouvelle identité Java accepte seulement ses propres actions et conserve
l'autorisation officielle, l'essai unique et les preuves de nettoyage.

Le superviseur ARM64 est celui déjà vérifié sur PC :
`7ed43a09ad5e22cb5e5e1ae347d83947f1f6167a797c8aa8b9d399bf09645a03`.
La CLI Python fournie par la tâche principale vise exactement V4 `/python` :
`0f25bf5dba0627b4fd31ee03e15a2b7673270df26249c7f4fb12f1d862ec2e1c`.
Elle se trouve dans `downloads/native-kernel-trial/python-cli-v12`.
`qualification-inputs-v12.json` épingle ces fichiers et les inventaires/preuves
du build figé. Les sources des helpers et du worker restent celles de ce build.

## Vérifications PC effectuées

Six tests d'empaquetage et sept tests d'identité passent. Ils vérifient les
hashes réels des entrées V12, le préfixe Python, les chemins de sortie disjoints,
les identités admises et le refus des croisements package/base/version avant
tout subprocess. Les tests ne lancent pas ADB. Le staging complet réussit ;
une deuxième lecture vérifie ses 2 557 hashes, 82 bibliothèques natives,
2 447 fichiers Python, 81 alias et 24 entrées du manifeste des sources.

Stage :
`tools/executor/shizuku-service/build/qualification-v12/qualification-stage-v12`.
SHA256 du `build-inventory.json` :
`2bda8c2eaf90d1e2b97a3c421e2e80eed2616631590ccf4dc94e455860da0471`.
Rapport : `downloads/native-kernel-trial/pc-v12-packaging/stage-verification.json`.

Ces vérifications ne qualifient pas le chargeur Bionic Samsung ni les opérations
noyau du worker. La revue du chargeur reste un préalable au prochain essai réel.
La limitation `O_PATH` décrite dans le résultat V11 n'est pas modifiée ici.

## Commandes PC et sorties isolées

Depuis `C:/Dev/ChatgptFold`, le staging a été effectué avec :

```powershell
python -B tools/executor/shizuku-service/stage-qualification.py --frozen C:/Dev/ChatgptFold/downloads/bionic-supervisor/foldgpt-bionic-supervisor-PHREPY0u --python-cli C:/Dev/ChatgptFold/downloads/native-kernel-trial/python-cli-v12/libfoldgpt_python_cli.so --package app.foldgpt.kernelqualification.v12
```

La sortie existe maintenant ; ne pas rejouer cette commande ni effacer le
stage pour masquer un échec. Le packageur refuse une sortie existante et une
base ou des entrées ne correspondant pas au profil revu.

Après revue du chargeur, depuis le projet `tools/executor/shizuku-service`,
la tâche principale pourra compiler l'APK et les tests JVM avec :

```powershell
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-21.0.12.8-hotspot'
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
& 'C:\Users\julie\.gradle\wrapper\dists\gradle-9.7.1-bin\1w1c7tv4s851m17nbqdsro2tv\gradle-9.7.1\bin\gradle.bat' --no-daemon :qualification:assembleDebug :transport:testDebugUnitTest -PfoldgptQualificationVersion=12 -PfoldgptFrozenTransportJni=C:/Dev/ChatgptFold/tools/executor/shizuku-lab/build/frozen-transport-jni --console=plain
```

Sortie attendue :
`build/qualification-v12/modules/qualification/outputs/apk/debug/qualification-debug.apk`.
Les sorties transport V12 restent sous `build/qualification-v12/modules/transport`.
L'absence de la propriété conserve le profil et les chemins historiques V11.

Depuis la racine du dépôt, vérifier et figer le futur APK dans un dossier neuf :

```powershell
python -B tools/executor/shizuku-service/verify-qualification.py --version 12 --output C:/Dev/ChatgptFold/tools/executor/shizuku-service/build/qualification-v12-independent
```

Le vérificateur contrôle signature, manifest binaire, bibliothèque native,
chaque asset, sources et véritables résultats des 24 tests JVM du transport.
Il ne conclut pas à une exécution Android. L'ancien
`verify-qualification-v11.py` délègue au même code avec la version11 fixe.

## Contrat de collecte futur

Les opérateurs runtime exigent `--package app.foldgpt.kernelqualification.v12`,
`--base /data/local/tmp/foldgpt-bionic-supervisor-qualification-v4` et
`--report-version 12`. Le snapshot avant essai doit aussi inclure le paquet
`app.foldgpt.kernelqualification.v11` en plus de FoldGPT, du laboratoire V10
et de V12. Le collecteur V12 exige leur conservation et la concordance réelle
des preuves app/native avant d'inspecter le workspace V4. Aucun essai V11
n'est relancé pour préparer V12 ; aucun marker antérieur n'est supprimé.
