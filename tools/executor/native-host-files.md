# Autorité fichiers de l'hôte

`native_host_files.py` ajoute une capacité Python pour les opérations de fichiers
initiées par l'interface de confiance. Elle emploie le workspace déjà détenu par
`NativeExecutorBackend`, son descripteur racine, son verrou `flock`, son verrou
asynchrone partagé avec les processus, sa session et sa quarantaine. Elle n'ouvre
aucune nouvelle racine.

## Contrat

Seul le propriétaire de confiance appelle
`create_host_file_authority(owner, session_id=actual_session_id)`. Le résultat
immuable et non sérialisable fournit :

| Méthode | Résultat réel |
| --- | --- |
| `read_file(uri)` | Octets exacts d'un fichier ordinaire |
| `write_file(uri, data)` | Écriture complète puis synchronisation du fichier et du parent |
| `get_metadata(uri, follow_symlinks=True)` | Métadonnées natives, dont taille et date de modification |
| `read_directory(uri)` | Enfants exacts après validation native de l'instantané |
| `canonicalize(uri)` | URI canonique après résolution native effective de l'objet |
| `create_directory(uri, recursive=True)` | Création native du suffixe manquant, après contrôle du parent existant |

`workspace_root_uri` indique la racine inclusive existante. Les URI doivent être
canoniques et situées sous cette racine. Les alias, liens symboliques, liens
physiques, fichiers spéciaux et fichiers `.git` de redirection restent refusés.
Les URI comportant des caractères de contrôle restent hors du profil admis,
même avec un encodage en pourcentage. Les octets du contenu sont arbitraires.

Les limites existantes s'appliquent : 16 Mio par lecture/écriture, profondeur de
64 répertoires, 100 000 entrées par workspace et 50 000 enfants par listing.
L'écriture reçoit un objet `bytes` complet et crée les nouveaux fichiers en
0600 ; les répertoires sont créés en 0700. Une erreur après le début d'une
mutation ne garantit pas de retour à l'état précédent.

## Séparation des autorités

Aucune méthode RPC modèle, option JSON ou route réseau publique n'expose cette capacité.
Les RPC modèle conservent leur politique obligatoire ; `sandbox: null`, son
omission et les sélecteurs d'autorité forgés restent refusés. La capacité
`BootstrapReadAuthority` conserve exclusivement ses méthodes de lecture.
L'objet Python est un contrat entre composants de confiance, pas une isolation
contre du code hostile exécuté dans le même interpréteur.

`native_host_files_channel.py` fournit séparément le canal privé de l'interface,
schéma `foldgpt.host-files.v1`. Selon le [contrat du canal](native-host-files-channel.md),
le propriétaire injecte une socketpair anonyme connectée et l'identité réelle
du pair. Chaque paquet est vérifié par
`SCM_CREDENTIALS` ; les descripteurs reçus sont fermés et refusés. Il n'existe
aucun listener. Une écriture annonce ses octets et fragments de 32 Kio, puis
transmet ses fragments et un commit explicite. Aucun helper d'écriture n'est
lancé avant réception et validation de l'ensemble. Les séquences rejouées,
champs inconnus, trames invalides et recouvrements de requêtes ferment le canal.

L'interface peut modifier un fichier sous `.git`, `.agents` ou un sous-dossier
refusé au modèle sans accorder ces droits au modèle. Les permissions du système
restent appliquées. Un processus en cours détient le même verrou : l'écriture
attend son nettoyage réel. Une quarantaine annule l'opération en attente ; une
annulation ou fermeture attend la terminaison du helper avant de libérer le
verrou et la racine.

## Qualification sur PC

Lancer sous WSL Linux avec le vrai superviseur compilé pour l'hôte :

```sh
bash tools/executor/native-host-files-test.sh /chemin/vers/runner
bash tools/executor/native-host-files-test.sh /chemin/vers/runner tools.executor.test_native_host_files_channel
```

Le script photographie les sources et binaires dans `/var/tmp`, compile les
helpers C statiquement avec `-Werror`, puis lance les tests sous un UID non nul
(`nobody` lorsque le script est lancé en root WSL). Les empreintes et observations
restent avec l'instantané, y compris en cas d'échec.

Qualification du 8 septembre 2026 : **30 tests réussis** (15 de capacité et
15 de canal), UID 65534, instantané `/var/tmp/foldgpt-host-files-CVCFU6kF`.
Les tests couvrent les octets binaires,
les métadonnées, mkdir/listing, les refus et l'absence de mutation, la séparation
des autorités, la substitution de racine, les permissions réelles, `flock`, la
quarantaine, l'annulation répétée et la fermeture pendant un vrai helper.
Un vrai processus supervisé attend sur stdin ; son arrêt rend
`cleanupComplete: true`, le superviseur est terminé, puis l'écriture reprend.
Ce scénario passe également par le canal privé complet. Les essais du canal
couvrent notamment 16 Mio exacts en 512 fragments, l'écriture vide avec commit,
41 refus de protocole sans mutation, un vrai processus émetteur de PID étranger,
les transferts de descripteurs, les coupures/annulations avant commit et la
récupération d'un vrai helper après commit. La quarantaine révoque également
une écriture déjà validée mais encore en attente du verrou.

Ce résultat qualifie la capacité Python, le canal privé et les helpers sur PC.
Le client Rust, son branchement au moteur et les essais Android restent à
réaliser. L'audit du client officiel a également constaté que son éditeur Linux
lit via `process/spawn` (`cat`) et utilise un processus avec stdin pour certaines
écritures : cette capacité fichiers seule ne valide donc pas l'éditeur complet.
