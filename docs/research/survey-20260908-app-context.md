# Essai Bionic depuis une application Android ordinaire

**Mise à jour du 8 septembre 2026 : les deux cas ont réussi sur le Fold sans
Shizuku actif.** Voir les [preuves Android](app-context-device-validation-20260908.md).
Le protocole ci-dessous avait été préparé pendant l'absence du téléphone ;
le raccordement à la production demeure une étape distincte.

## Question réellement testée

Les propriétaires r25 pipe et PTY fonctionnent-ils lorsqu'ils héritent du
contexte normal d'une application Android, sans démarrage par Shizuku ?

L'application de diagnostic distincte `app.foldgpt.contextprobe` contient les
mêmes ELF et adaptateurs r25. Sa seule entrée est
`app.foldgpt.contextprobe/.ContextProbeService`, protégée par la permission DUMP.
Le système Android crée ce Service via Zygote. Le Service démarre ensuite Python
avec `ProcessBuilder`, puis les adaptateurs r25 démarrent leurs propriétaires
natifs. Une éventuelle commande ADB ne fait que demander l'ouverture du Service
à Android ; elle ne lance aucun interpréteur ou propriétaire natif directement.

Le diagnostic n'accepte ni commande, ni chemin, ni URI, ni extra d'Intent. Il
possède son propre UID et son propre stockage. Il ne remplace pas FoldGPT,
n'arrête pas son propriétaire actif et ne modifie aucun garde du bootstrap de
production. Il ne dépend d'aucun service Shizuku et n'utilise aucune de ses API.
L'inventaire r25 copié à l'identique comprend son ELF de transport Shizuku,
qui reste inactif ; sa présence n'est pas une dépendance d'exécution du test.

## Sources et procédure de construction

Sources à versionner : [tools/runtime/app-context-probe](../../tools/runtime/app-context-probe/README.md).
Les APK, clés de signature de diagnostic, données Python copiées et journaux sont
exclus des sources et restent sous `work/`.

```powershell
python tools/runtime/app-context-probe/build.py --output work/feasibility-survey-20260908/app-context/versioned-build-v1
```

Le constructeur accepte un APK source et son SHA-256 explicite, ainsi qu'un
nouveau répertoire de sortie obligatoirement sous `work`. Les valeurs par
défaut ciblent le r25 vérifié. Les sorties existantes sont refusées. Une tentative
de sortie sous `tools/runtime/app-context-probe/forbidden-output` a été refusée
avant création de fichiers. Les sources exactes du build sont recopiées dans
son sous-dossier `source`.

Il utilise directement javac, D8, aapt2, zipalign et apksigner déjà installés,
sans Gradle et sans ADB. Le candidat actuel est :

```text
work/feasibility-survey-20260908/app-context/versioned-build-v1/foldgpt-app-context-probe.apk
SHA-256 325b0bcfc6ef951d5a4ad71f067b1369c0ae44eaa15d89b1b8149e2806cae41b
23 911 825 octets
```

Son rapport `build-report.json` confirme 89 ELF et 2 543 fichiers de données :
2 447 fichiers Python, 95 sources r25 et le nouveau harness. Chaque hash est
comparé à l'APK r25 source puis relu dans l'APK finale. Le Service refait cette
vérification après son extraction locale. Compilation Java/D8, empaquetage,
alignement et vérification de signature réussissent. La nouvelle clé de
diagnostic n'a aucun lien avec la signature de production.

## Mesures attendues et critère de réussite

Deux cas courts exécutent le vrai Python Bionic, créent puis relisent un fichier,
et démarrent/attendent un sous-processus Python réel. Le cas pipe transmet aussi
une entrée puis exige la sortie 23. Le cas PTY vérifie les trois descripteurs
terminal et la dimension initiale, envoie `process/signal` avec `interrupt`, puis
exige un `KeyboardInterrupt` observé et la sortie 130.

La réussite exige les deux cas, la réponse native de nettoyage complet,
l'attente réelle du propriétaire avec code 0, les EOF, la libération du verrou,
l'absence de quarantaine et l'absence de propriétaire retenu. La fin Java exige
également la sortie 0 du Python de contrôle et la réussite agrégée du rapport.

Les observations comprennent l'identité Java, Python et worker, leurs liens
PID/PPID, le UID réel uniforme, le mode seccomp hérité 2, tracer 0, capacités
effectives/autorisées nulles, les cgroups, les CPU autorisés et les valeurs mémoire
totale/disponible. Le statut du propriétaire est lu lorsque le noyau l'autorise ;
un refus reste visible et ne change pas son comportement nondumpable.

Chaque worker arme une alarme de huit secondes. Chaque propriétaire natif a
douze secondes de durée maximale et cinq secondes de grâce de nettoyage. Un
nettoyage incertain conserve l'adaptateur, sa boucle asyncio et son propriétaire.
Java consigne un échec après 90 secondes et conserve également le Service : aucun
kill externe, arrêt forcé ou faux succès de nettoyage n'est produit. Les dossiers
d'évidence sont conservés après le test.

## Limites

Ce diagnostic reproduit la filiation Zygote et le filtre hérité, avec un autre
UID, un autre processus et un autre cgroup. Il ne prouve pas le raccordement au
Service de production, les canaux privés du contrôleur, le broker dynamique avec
politique, l'interface complète, le redémarrage sans PC ou les performances X11.
Les exigences de même processus du compositeur X11 sont une question distincte.

Les données Python sont relogées dans l'espace privé du diagnostic. Le CLI r25
inchangé permet cette sélection par son mécanisme ordinaire `PYTHONHOME` ; les
environnements Java/worker sont explicites et les options sont `-B -s`. Le test
n'utilise pas `-I`, qui ignorerait ce relogement et chercherait les données dans
l'application FoldGPT. Aucun code de garde de production n'est retiré.

## Documentation et preuves antérieures

Les sources suivantes ont été effectivement lues via le connecteur GitHub. Les
extraits avec numéros de ligne sont conservés dans
`work/feasibility-survey-20260908/app-context/upstream-source-excerpts.json` :

- [AOSP Zygote](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/core/jni/com_android_internal_os_Zygote.cpp),
  `SetUpSeccompFilter` et son appel pendant la spécialisation d'une application,
  établissent que le filtre hérité dépend de la filiation de lancement.
- [Termux terminal JNI](https://github.com/termux/termux-app/blob/master/terminal-emulator/src/main/jni/termux.c)
  implémente l'ouverture de `/dev/ptmx`, `fork`, `setsid`, la redirection des
  descripteurs et `execvp` depuis la filiation de l'application. Cela justifie
  l'essai de ces mécanismes ordinaires, sans prouver les opérations supplémentaires
  des propriétaires r25 sur le noyau exact du Fold.

Les anciens Services de diagnostic existent déjà dans l'APK FoldGPT, notamment
`NativeProcessRpcProbeService`, mais leurs sources et cas sont fixes. Ils ne
peuvent pas sélectionner les adaptateurs r25 actuels. Les résultats des
6 septembre restent attribués à leurs anciens APK :
[34 réponses / 12 groupes de fichiers](../../tools/executor/native-files-android-rpc.md)
et [17 tests / 46 observations de processus gérés](../../tools/executor/native-managed-android.md).
La nouvelle preuve Android conserve ces limites : les deux cas réussissent,
le boot et les APK sont inchangés. Le propriétaire de production était déjà
indisponible avant l'essai ; sa coexistence active n'est pas validée.
