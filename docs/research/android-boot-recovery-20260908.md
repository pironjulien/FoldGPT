# Reprise du propriétaire natif après un nouveau boot Android

Implémentation et contrôles PC du 8 septembre 2026. **39 tests Linux réels et
28 tests d'admission passent.** La qualification physique ultérieure est
décrite dans le [rapport r28](r28-device-validation-20260908.md) : BOOT_COUNT8→9,
archivage automatique du marqueur et exécution du projet depuis la conversation.
Les limites de qualification indiquées plus bas décrivent l'étape PC initiale.
Les comptes de boot employés dans les tests Linux sont
des entrées de protocole explicites ; les fichiers, verrous, sockets, attentes
d'enfants et archives sont réels.

## Autorité et protocole

Android expose `Settings.Global.BOOT_COUNT`, entier annoté `@Readable` dans
[AOSP Settings.java](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/core/java/android/provider/Settings.java).
Sa documentation indique « Boot count since the device starts running API
level 24 ». L'extrait effectivement lu par le connecteur GitHub est conservé
dans `work/boot-recovery-20260908/upstream-boot-count.json`.

`AndroidBootEpoch` lit ce réglage sans valeur par défaut, sous l'UID réel de
l'application. `NativeLaunch` inscrit l'objet dans le manifeste privé
`foldgpt.native-launch.v2`. `Deployment` relit le réglage avant le fork et
compare le manifeste ouvert et vérifié. L'objet exact est :

```json
{"schema":"foldgpt.android-boot-epoch.v1","source":"android.provider.Settings.Global.BOOT_COUNT","bootCount":8}
```

Le `8` est un exemple ; le code utilise la valeur fournie par Android. Python
refuse une autre source, un autre schéma, des champs supplémentaires, un booléen,
un entier négatif ou une valeur au-delà de l'entier signé Android. La voie app
exige le manifeste v2. Le manifeste run-as v1 conserve son contrat exact. Le
bootstrap C et ses arguments restent identiques : les vérifications préalables
du fichier privé et de l'inventaire précèdent toujours Python ; Java et Python
contrôlent les nouveaux champs du manifeste.

## Récupération sous verrou

Le propriétaire app enregistre désormais un marqueur `version:2` avec cet
objet `bootEpoch`, avant toute admission de processus. Il conserve les mêmes
contrôles de fermeture ordinaire. Un prochain propriétaire doit obtenir le
véritable `flock` exclusif avant toute récupération.

Si le marqueur est un fichier privé régulier, non lié, borné, stable pendant
la lecture, appartenant au même UID et conforme au contrat v2, la récupération
exige strictement `nouveau bootCount > ancien bootCount`. Elle archive alors
le fichier original dans un nouveau répertoire privé `recovered-boot-…`, en
préservant son inode et ses octets. Un reçu contient les deux epochs, l'empreinte
du marqueur et `previousCleanupClaimed:false`. Fichiers et répertoires sont
synchronisés avant de permettre une nouvelle session.

Un crash pendant le même boot, un compteur régressif, un verrou encore détenu,
un ancien socket fixe, des données modifiées ou un marqueur v1 sans preuve de
boot restent refusés. Aucun test de PID absent ne libère de session. Aucun
workspace, dossier de session ou socket antérieur n'est supprimé. La récupération
n'invente pas de réussite du nettoyage effectué avant le reboot.

## Preuves PC conservées

- `work/boot-recovery-20260908/linux-tests.json` et `linux-tests.stderr` :
  39 tests, UID Linux réel 1000, filesystem ext4 stocké dans une image sous le
  projet puis démonté ; exclusion concurrente, crash réel d'un enfant, refus
  du même boot, archivage des octets/inode, permissions et schémas.
- `work/boot-recovery-20260908/origin-tests.json` : 28 tests d'admission.
- `work/boot-recovery-20260908/admission/build.json` et `runas-regression/build.json` :
  compilations ARM64 NDK r29 ; le binaire run-as demeure identique au r25.

La lecture du compteur par l'application et la reprise complète après un
redémarrage physique restent à qualifier sur le Fold. Les anciens marqueurs
sans epoch nécessitent leur preuve de récupération distincte ; ils ne sont
pas automatiquement attribués à un boot antérieur.
