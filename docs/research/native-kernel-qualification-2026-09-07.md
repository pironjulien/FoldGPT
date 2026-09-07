# Qualification du superviseur natif sur le Fold — 7 septembre 2026

Cette étape mesure les mécanismes nécessaires au superviseur `8Kd8xQRE` dans
le véritable contexte Shizuku/Bionic. Le succès du précédent projet Python
fixe ne mesurait pas `/proc/TID/mem` et `pidfd_getfd`. Les résultats PC ne
permettent donc pas de sélectionner cet exécuteur pour les commandes du modèle.

## Préparation réellement effectuée

L'APK diagnostic séparé `app.foldgpt.kernelqualification` a été compilé, signé,
relu puis installé. Version finale :
`1d41258772e0a27191e60430d4dce82065ec6a3b34964f0387918b037dc2fdf4`.
La signature conserve le certificat FoldGPT existant. La revue a contrôlé
82 bibliothèques natives, 22 sources et les quatre ELF du build corrigé.
Les 17 tests Java, les régressions réelles Linux de transport/résolution et
les six tests de la façade diagnostique passent sur PC.

La fixture v2 du téléphone contient les trois fichiers exacts, le répertoire
privé et le dossier `.git` vide. Les fichiers sont shell2000/mode0600 ; les
répertoires shell2000/mode0700. La collecte revue vérifie les octets via base64,
les noms exacts et les métadonnées. Le nouveau CLI Python est recompilé pour
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2/python` ; ses
extensions pointent vers le `nativeLibraryDir` réellement lu de PackageManager.

Le runtime installé a été récupéré et comparé indépendamment : 2 447 fichiers
de données, 81 liens ELF, 209 répertoires ; les 82 empreintes ELF installées
correspondent au manifeste. Ce runtime shell privé reste une entrée de
diagnostic vérifiée. Un hash avant lancement ne le rend pas immuable face à
un autre processus du même UID.

## Problèmes de transfert corrigés avant toute exécution du worker

- Sur cette version Windows d'ADB, `exec-out` ne fournissait pas le statut
  d'échec distant et n'acheminait pas correctement l'entrée de `tar`. Les
  commandes de contrôle utilisent maintenant `shell -T` et leurs vrais codes
  de sortie ; les fichiers sont lus via base64 pour conserver leurs octets
  malgré la conversion LF/CRLF de stdout observée.
- L'archive Python compressée envoyée sur stdin a été tronquée. Elle passe
  maintenant par le protocole de transfert ADB ; son hash est vérifié sur le
  téléphone avant que `tar` ne l'extraie.
- Le `tar` Android ignorait `PAX linkpath`, tronquant les longues cibles
  `/data/app/...` à 100 octets. Les archives GNU LongLink conservent les vraies
  cibles. Les 81 liens ont été vérifiés après récupération.

Les préparations échouées sont conservées, sans suppression : base v1 vide,
`python-partial-stdin` et `python-partial-pax` dans la base v2. Aucun de ces
répertoires n'est admis comme runtime. Les preuves se trouvent sous
`downloads/native-kernel-trial`; `staging-notes.json` indique les snapshots
remplacés et le dernier contrôle valable.

## Premier paquet : autorisation en attente, pas un échec noyau

L'action fixe du paquet séparé a atteint l'attente d'autorisation officielle
Shizuku. Le téléphone verrouillé réclame empreinte ou PIN ; aucun code n'a été
essayé, aucun verrou ni réglage de sécurité n'a été modifié. Il n'y avait aucun
UserService de qualification, aucun fichier de preuve natif et le broker était
vide. La collecte indépendante conserve donc `success:false`, avec preuve
native absente. Cette tentative ne mesure aucun appel noyau du worker.

Après ces constatations, seule l'application diagnostique en attente a été
arrêtée ; aucun propriétaire natif n'existait. Le téléphone a été remis en
veille. Les APK FoldGPT et du laboratoire précédent sont encore identiques
à leurs empreintes initiales dans cette collecte, avec le même boot ID
`348d453e-f4e5-40e0-8ef0-030f4d5e38af`, warranty0, verifiedboot green,
flash locked1 et SELinux Enforcing.

## Laboratoire v6 : Shizuku fonctionne, arrêt du bootstrap avant le worker

La mise à jour normale du laboratoire déjà autorisé a été installée, avec le
même certificat et le même UID10350. APK SHA-256 :
`fb6889c2e284eba1508e37e2fac0825539033369668cf374dd6abcaa45440c49`.
Les cinq anciennes sources Java/AIDL, le guard natif et l'ancien rapport Python
sont conservés ; le SHA-256 du rapport est toujours
`6d59d999174322d3ce84538899019f280a3ccc98442d5bb4df706df8f226c18a`.
Le diagnostic supplémentaire écrit exclusivement dans `files/kernel-v2`.
La correction du chemin canonique des fichiers privés a permis la collecte
effective de PackageManager ; les alias Python ont été recréés pour son nouveau
`nativeLibraryDir`, puis vérifiés après récupération.

L'unique action fixe a réellement lancé le bootstrap via Shizuku UID2000.
Celui-ci est sorti avec le code 70 avant `ready` et avant toute réponse RPC.
JNI a effectivement attendu sa terminaison (`waitStatus=17920`) et constaté
`cleanupComplete=true`, sans propriétaire retenu ni quarantaine. La collecte
indépendante conserve donc `success:false` : aucune preuve native n'existe.
Le broker ne contient que son verrou vide, sans socket ni marqueur de session ;
aucun UserService du laboratoire, superviseur ou worker ne reste actif.
Les preuves se trouvent dans
`downloads/native-kernel-trial/lab-v6-bootstrap-refusal`.

Cette sortie survient pendant l'initialisation du relais Python. La version v6
ne conservait pas le stade et l'exception de préparation : elle ne permet donc
pas d'attribuer cet échec à un mécanisme noyau. Le superviseur et son worker
ne se sont pas exécutés. Le boot et les indicateurs d'intégrité sont inchangés.
Une nouvelle itération doit conserver cette preuve et corriger l'observabilité
avant tout nouvel essai ; elle ne doit pas effacer la réservation v6.

ChatGPT et FoldGPT restent intacts. Aucun réglage Shizuku, verrou du téléphone
ou mécanisme de sécurité Android n'a été modifié. La mesure effective des
mécanismes noyau reste à effectuer.

## Laboratoires v7/v8 : rapports automatiques avant restaging

L'APK v7 `0f7a673f8b5ec14f09368ebd31d974bbc5d0540617ff91e7d433fe65a072c82d`
ajoute un diagnostic bootstrap privé borné. Les 84 ELF et le déploiement sont
identiques à v6 ; vingt tests JVM et les vrais tests bootstrap PC passent. La
revue indépendante a contrôlé APK, signature, sources et manifeste.

Les rapports v7/v8 conservés ont été produits automatiquement pendant les
mises à jour, par restauration de l'ancien Intent de l'Activity, **avant le
restaging des alias Python vers le nouvel APK**. Ils ne prouvent donc pas de
nouveaux essais explicites après restaging. La chronologie est conservée dans
`downloads/native-kernel-trial/lab-v8-inspection/report-times.txt` ; notamment
la réservation et le rapport v8 précèdent son préflight ultérieur.

Le rapport v7 porte `Executor admission failed` avant retour de session, sans
frame RPC ni preuve native et avec `transportCleanupComplete:false`. Il reste
dans `lab-v7-admission-refusal`, avec la réservation `files/kernel-v3` intacte.
Son erreur Binder générique ne révèle pas la cause imbriquée. PID6162 et ses
maps v7 étaient des observations de cette collecte historique, pas un état
actuel. Le statut de l'ancien service, lu ensuite sans le créer, le trouve
absent mais conserve `ownershipEstablished:false` : cela ne prouve pas son
nettoyage précédent.

V8 (`76f58714ac9900c7162b291822cd8b620916766c87945bdcf9e607beee26fee4`)
ajoute le diagnostic Java d'admission. Son premier préflight refuse
`python_aliases` : `lib/engines-3/afalg.so` cible l'ancien chemin d'APK.
Après reconstruction des alias, `lab-v8-inspection/preflight-restaged.json`
passe dans le véritable UserService UID2000, version installée8, état idle,
avec `nativeSpawnAttempted:false`. L'admission des entrées est ainsi vérifiée ;
elle ne constitue pas une exécution du worker. Conserver aussi `files/kernel-v4`.

## Laboratoire v9 : rejeu refusé puis blocage bind réellement identifié

L'APK v9
`7fa98c225e88dc912620cc37fe178713c753a5168ee393b2f5feaa1edfb19819`
conserve les 84 ELF et les 27 assets du v8. Sa signature, son manifeste, les
82 empreintes natives, 22 sources empaquetées et 13 sources figées ont été
vérifiés indépendamment sur PC. Les 24 résultats JVM sont réutilisés du v8 ;
ils ne qualifient pas le nouveau comportement Android de lancement.

Seule l'action `KERNEL_RUN_FIXED_V9` peut réserver un essai v9, dans
`files/kernel-v5`, avec le service tag `foldgpt-kernel-qualification-v5`,
version5. Le téléphone a réellement restauré l'ancien `KERNEL_RUN_FIXED` :
`lab-v9-inspection/inherited-intent-refusal.json` enregistre son refus et la
version9 ; `inherited-intent-directory.txt` constate l'absence de réservation
à ce stade. Tous ces chemins de preuves sont sous `downloads/native-kernel-trial`.

L'action v9 explicite exécutée ensuite est distincte de ce rejeu. Son rapport
enregistre l'action versionnée et les heures civile/monotone. Le préflight
réel passe en version9, UID2000, PID9798, état idle. Le libellé `preflight_v4`
est seulement historique ; il ne change ni la version installée ni le service
cible. Le bootstrap échoue ensuite à `broker_open`, avec `PermissionError`,
errno13, dans `private_exec_broker.py:93` : c'est l'appel `bind()` AF_UNIX.
Cette opération en échec est désormais identifiée ; la règle Android à
l'origine du refus reste à déterminer.

Le transport n'atteint pas `ready`, ne produit aucune frame et ne lance aucun
worker. `bootstrapReaped=true`, `cleanupComplete=true`, `waitStatus=17920`
(sortie70), `ownerRetained=false` et `quarantined=false` sont réellement
rapportés. Le contrôle indépendant constate PID9798 absent, la fixture, le
boot, les indicateurs d'intégrité et les APK inchangés. Le broker ne contient
que `broker.lock`, vide ; la réservation v9 reste conservée. Les preuves sont
`lab-v9-bootstrap-refusal/app-report.json`,
`lab-v9-bootstrap-refusal/independent-verification.json`,
`lab-v9-cleanup-inspection/snapshot.json` et
`lab-v9-cleanup-inspection/broker-and-marker-listing.txt`.

Le collecteur conserve correctement `success:false` : aucun `evidence.json`
natif n'existe. `/proc/TID/mem`, `pidfd_getfd` et leurs variantes depuis un
thread secondaire restent **non mesurés dans ce worker Android**. La prochaine
étape porte sur le refus de `bind()` dans le contexte réel, sans modifier
SELinux, le noyau ou les protections du téléphone.

`onNewIntent` évite de laisser silencieusement un ancien rapport lors d'une
nouvelle action. Sa revue de cycle de vie reste limitée : `finished` peut être
fixé par le délai de rapport avant la fin du worker Java. Ne pas réutiliser
l'Activity après timeout, ni assimiler ce drapeau à une fin d'opération ou à
un nettoyage. L'essai v9 étant réservé, aucun rejeu ni effacement de marqueur
n'est autorisé par cette procédure.
