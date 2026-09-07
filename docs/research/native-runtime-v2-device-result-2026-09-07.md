# Projet Python natif V2 réussi sur le Fold — 7 septembre 2026

Le petit projet Python **réussit sur le Fold réel avec l'exécuteur natif
Shizuku/Bionic**. Le collecteur indépendant valide ses 20 contrôles. Ce test
fixe utilise le vrai transport de production ; les commandes ordinaires depuis
l'interface FoldGPT restent à raccorder et à démontrer.

## Résultat réel

Bash change de dossier et lance Python Bionic 3.14.7. Python crée une
calculatrice, modifie sa source de 41 à 42, lance trois tests unitaires avec
un véritable enfant, construit une archive zipapp de 606 octets et l'exécute :
stdout vaut exactement `42\n`. Un autre enfant reçoit/restitue les octets
binaires, écrit séparément stderr et quitte avec 23. Les enfants ont un
environnement explicitement vide. Les huit opérations interdites provoquent
leurs vraies erreurs. Le résultat matériel, les trois sources et le contenu/CRC
de l'archive sont relus indépendamment.

Le worker sort avec 0, 2 056 octets stdout et aucun stderr. Le superviseur
rapporte 935 autorisations et 420 refus, sort avec 0 et est réellement attendu.
Le nettoyage natif/JNI est complet, sans quarantaine ; les propriétaires 2636
et 2676 sont absents après collecte. Le boot reste
`348d453e-f4e5-40e0-8ef0-030f4d5e38af`. Les APK retenus, les indicateurs
contrôlés et la fixture protégée restent inchangés. Aucun redémarrage n'est
observé pendant cet essai ; ce constat reste borné à cette exécution.

Les [preuves exactes](../../recovery/verification/native-runtime-v2-20260907/manifest.json)
conservent admissions, rapports, snapshots, sources matérielles, archive et
revue du chargement. Données complètes locales :
`downloads/runtime-qualification/fixed-collection-v2`.

| Identité figée | Valeur |
|---|---|
| Package | `app.foldgpt.runtimequalification.v2` |
| Base | `/data/local/tmp/foldgpt-bionic-runtime-qualification-v2` |
| Build | `foldgpt-bionic-supervisor-qKM94iHA` |
| Superviseur SHA256 | `6bccc77b4f2dff0f78fd22e4f6427263ee159d87b35c740e8be0622319fd4dd4` |
| CLI Python SHA256 | `b0709f801f95739b1a6988d51f22d8df1373316595ce19df8ce329d5c84628f2` |
| APK SHA256 | `8572ecc3ed975e6eb8dc98e1df5247931e5354aa6dd737f400c4e7c699674b2c` |
| Stage inventory SHA256 | `827a86280bfb5e98135de48f7d3069c712c79620cf96cafbe9e949e1308d501b` |

## Correction vérifiée

V1 échouait à trouver `libpython3.14.so`, pourtant présente dans l'APK. V2 ajoute
au RUNPATH du CLI le vrai préfixe `python/lib` de son runtime avant `$ORIGIN`.
Les alias y ciblent les bibliothèques attestées de l'APK. Les quatre dépendances
Python sont chargées directement. Aucun changement de politique du téléphone
ni faux descripteur `O_PATH` n'a été introduit.

La revue du véritable chargeur Samsung et des ELF ne trouvait pas de bloqueur.
Sur PC nonroot, chargement, dépendances transitives, `dlopen` et réexécution avec
environnement vide passaient sous le superviseur de production. Les contrôles
négatifs `$ORIGIN` seul et dépendance transitive non chargée directement
échouaient. Ces tests glibc n'étaient pas une preuve Bionic ; le présent essai
sur le téléphone fournit maintenant cette preuve pour le workload testé.

Le gel qKM94iHA passe cinq tests PC du projet, six courses de terminaison et les
contrôles canoniques. Sept tests JVM runtime et 24 transport passent. Le stage
vérifie 2 559 fichiers ; 84 bibliothèques natives, 2 447 fichiers Python et 81
alias ont ensuite été vérifiés sur l'appareil.

## Suite et limites

L'action unique `.RUNTIME_RUN_FIXED_V2` est consommée. Ne pas la rejouer ni
effacer son marker. Conserver V1, V11, V12 et la quarantaine historique V10.
Ne pas réactiver l'ancien diagnostic GNU/PRoot associé aux redémarrages.

Le moteur auxiliaire doit encore obtenir les bons chemins projet et des
autorités filesystem distinctes pour ses lectures, l'interface humaine et le
modèle. Son bootstrap app-server passe sur PC, mais `ExecutorOnly` demeure
refusé tant que ces routes ne sont pas qualifiées. La suite est un projet créé
et testé à la demande depuis l'interface habituelle. Le réseau géré, TTY,
certaines opérations Git et d'autres capacités restent également incomplets.

Les fichiers de l'application officielle n'ont pas été modifiés. L'interface
actuelle utilise encore sa compatibilité GNU/PRoot ; ce résultat porte sur
l'exécuteur Bionic natif séparé.
