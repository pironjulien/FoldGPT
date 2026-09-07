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
