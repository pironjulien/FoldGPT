# Résultat runtime V1 sur le Fold — 7 septembre 2026

Le premier projet Python natif **échoue au chargement de Python**. Bash démarre,
change de dossier et lance le véritable exécutable Python, mais le chargeur ne
trouve pas `libpython3.14.so`. La bibliothèque est présente et attestée dans
l'APK ; aucun test Python ni artefact du projet n'est produit par cet essai.

## Observations réelles

L'admission, l'autorisation officielle Shizuku UID2000 et le transport passent.
Le canal `process/write` accepte les 13 octets `native input\n`. Le worker sort
avec le code1 et 454 octets stderr. Le superviseur sort avec0 après son attente
réelle ; le nettoyage natif/JNI est complet, sans quarantaine. Les propriétaires
30064 et30076 sont absents après collecte. Les snapshots complets conservent le
même boot, les APK retenus, les indicateurs contrôlés et la fixture initiale.
Ces observations ne constituent pas un succès du workload.

Le collecteur renforcé conserve explicitement le refus et la vraie erreur :

```text
library "libpython3.14.so" not found: needed by main executable
```

Les [copies exactes avec empreintes](../../recovery/verification/native-runtime-v1-20260907/manifest.json)
conservent les rapports, snapshots et admissions. Les données complètes locales
sont dans `downloads/runtime-qualification/fixed-collection-v1-reviewed`.

| Identité | Valeur |
|---|---|
| Package | `app.foldgpt.runtimequalification.v1` |
| Base | `/data/local/tmp/foldgpt-bionic-runtime-qualification-v1` |
| APK SHA256 | `e39c89f536f2d31a676a2c5d9fdcce51c9e22c0e69cef9ea215c044a3142b73b` |
| Superviseur | `foldgpt-bionic-supervisor-N0kMFS8z` |
| Action consommée | `.RUNTIME_RUN_FIXED_V1` |

## Correction en cours et limites

Le CLI V1 utilise uniquement `$ORIGIN` pour ses bibliothèques. Dans ce contexte,
le chargeur Bionic peut conserver `/proc/self/exe` après l'échec de sa résolution
canonique, puis calculer un mauvais répertoire d'origine. La source du chargeur
et les observations rendent cette piste précise ; l'expansion exacte n'est pas
encore tracée sur le téléphone.

Le CLI candidat V2 ajoute le vrai préfixe des bibliothèques du runtime dans son
RUNPATH, avant `$ORIGIN`. Ses dépendances directes et son ELF sont contrôlés.
Il doit être testé avec les alias attestés, y compris lors d'un lancement avec
environnement vide, dans un package/base V2 séparé. V1, son marker et ses preuves
restent intacts. Aucun changement de politique du téléphone n'est nécessaire
pour ce correctif de packaging ; aucun succès Android V2 n'est encore établi.

Le raccordement app-server du moteur auxiliaire passe séparément six nouveaux
tests JSON-RPC réels et29 tests API sur PC, avec revue indépendante et Clippy.
Les couches projet et les autorités filesystem restent à raccorder. Le refus
`ExecutorOnly` demeure ; le petit projet depuis l'interface habituelle n'est
donc pas encore démontré. L'interface actuelle conserve sa compatibilité
GNU/PRoot ; seul l'exécuteur étudié est Bionic natif.
