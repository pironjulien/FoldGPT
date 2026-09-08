# Compteur Android pour la reprise après redémarrage

## Admission Java réalisée

Le lancement `android-app` reçoit un document privé `foldgpt.native-launch.v2`.
Ses cinq champs historiques sont conservés ; le sixième est :

```json
{
  "bootEpoch": {
    "schema": "foldgpt.android-boot-epoch.v1",
    "source": "android.provider.Settings.Global.BOOT_COUNT",
    "bootCount": 8
  }
}
```

`8` illustre la valeur relevée séparément par le parent de cette tâche. Le code
ne contient aucune valeur de compteur imposée. `AndroidBootEpoch.capture`
vérifie l'UID réel puis appelle `Settings.Global.getInt(ContentResolver,
Settings.Global.BOOT_COUNT)` **sans valeur par défaut**. Une valeur négative,
absente, mal formée ou une lecture refusée bloque explicitement le démarrage.
La source n'est ni une option du moteur, ni un champ fourni par son contrôleur.

`NativeLaunch` écrit ce document dans la séance privée. `Deployment` relit
le compteur Android et le document avant le fork. Le document doit être
canonique, régulier, possédé par l'UID/GID de l'application, sans autre lien
physique, privé et borné à 64 Kio. Ses inode, taille et horodatages sont vérifiés
pendant la lecture. Les champs du compteur sont stricts ; seule l'égalité avec
la nouvelle lecture Android autorise ce lancement. Le lancement run-as garde
son document v1 sans ce champ. Aucun changement JNI/argv n'est nécessaire.

## Portée de la récupération

La partie Python propriétaire doit préserver ses locks et contrôles d'inode.
Un compteur courant **strictement supérieur** au compteur enregistré permet
de conclure que les anciens processus ne peuvent plus survivre. Un compteur
égal, inférieur ou absent ne fournit pas cette preuve. La fraîcheur du
document de lancement ne constitue jamais, à elle seule, un reçu de nettoyage.

Un marqueur historique sans compteur ne doit pas être effacé automatiquement.
Une migration sûre peut d'abord enregistrer, sous le lock propriétaire, un
reçu d'observation privé contenant le compteur actuel et l'identité/contenu
du marqueur. Après un redémarrage ultérieur, un compteur strictement supérieur
et le même marqueur intégralement vérifié prouvent qu'il existait avant ce
redémarrage. Cette procédure dépend de l'implémentation Python et de ses tests.

Un force-stop au cours du même démarrage peut supprimer l'observateur avant
ses reçus. L'absence du PID principal ou une raison d'arrêt dans
`ApplicationExitInfo` ne prouve pas indépendamment la fin de tous ses descendants.
La voie Java n'efface donc aucun marqueur dans ce cas. Une récupération au même
démarrage demanderait une preuve complète supplémentaire de propriété et de
fin des descendants ; elle n'est pas fournie par ce changement.

## Vérification et limites

- Le SDK Android 37 officiel installé confirme la constante `BOOT_COUNT`
  (`"boot_count"`), sa disponibilité depuis API 24 dans `data/api-versions.xml`,
  et la surcharge `getInt` qui lève `SettingNotFoundException` sans défaut.
- Référence officielle : [Settings.Global.BOOT_COUNT](https://developer.android.com/reference/android/provider/Settings.Global#BOOT_COUNT).
  La navigation intégrée étant indisponible pendant cette tâche, la page n'a
  pas été relue en ligne ; la vérification ci-dessus porte sur le SDK local.
- Compilation Java, y compris `NativeLaunch`, et **38 tests du transport**
  réussis : `work/app-transport-20260908/java-r5/test.log`.
- Les tests couvrent la sérialisation réelle du compteur, ses bornes/types,
  la source/version exactes et le refus d'un lancement d'un autre compteur.
  Ils ne remplacent pas une lecture ContentResolver réelle sur le Fold ni
  une qualification téléphone avant/après redémarrage.
- Aucune opération téléphone, aucun APK, aucune modification du JNI dans
  cette sous-tâche. Le JNI reste celui de `work/app-transport-20260908/build-r2`.
