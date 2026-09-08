# Téléphone seul : alternatives, signature, Store et Pixel

Revue du 8 septembre 2026. Sources officielles ouvertes dans le navigateur
intégré, lecture des sources locales et vérification des cinq empreintes du
reçu historique Python. Aucun build ni essai téléphone pendant cette revue.

## Conclusion opérationnelle

Shizuku est une dépendance de notre lancement r25. Son caractère indispensable
à tout FoldGPT n'est pas démontré. Avant d'investir dans un serveur Shizuku
embarqué et son démarrage ADB sans fil, qualifier séparément le lancement
direct de l'exécuteur Bionic depuis l'application Android normale. Conserver
r25 et ses critères d'admission existants pendant cet examen.

Le résultat recherché demeure l'expérience desktop officielle, avec les outils
et fichiers sur le Fold, sans PC personnel, VM, root, changement de protections
ou modification de l'application officielle. Une interface réécrite ne peut
pas être présentée comme ce même résultat sans décision explicite de Julien.

## Pourquoi la nécessité de Shizuku doit être réexaminée

- Le JNI de production impose l'identité shell ; le bootstrap après run-as
  impose notamment `PR_GET_SECCOMP()==0` dans
  `tools/executor/runas-runtime/native-bootstrap.c`. Un lancement depuis une
  application Android normale est donc refusé par le contrat de cette route.
- Le résultat SIGSYS sur `set_robust_list` concernait Python GNU/glibc.
  Le [rapport Bionic suivant](../../tools/executor/native-files-android-rpc.md)
  prouve 34 réponses RPC et 12 groupes de contrôles sous l'UID10412 normal,
  avec filtre hérité actif, aucune capability et aucun traceur. Il couvre
  fichiers, sous-processus auxiliaires, asyncio, FD et EOF. Il ne qualifie pas
  le propriétaire pipe/PTY r25 complet ni le produit depuis l'interface.
- Les cinq empreintes de ce reçu ont été revérifiées pendant cette revue :
  `downloads/native-files-rpc/android-052f7bd5-1635-47d8-9286-2e9fe8e4f55d/independent-verification.json`.
- Le direct-runner courant gère les descendants par pidfd/subreaper/attentes ;
  il ne fait pas de ptrace et n'installe pas de nouvelle sandbox syscall.
  Ne pas lui attribuer les exigences du broker restreint distinct.

Le candidat pertinent serait un propriétaire lancé directement par un service
Android, avec un profil d'admission explicite adapté à ce contexte, les mêmes
contrôles des sources/FD/identité et les mêmes preuves de fermeture. Ne pas
supprimer simplement une vérification du bootstrap actuel pour annoncer une
solution. Le lancement pipe, PTY, les autres profils requis, le parcours réel
et la reprise restent à qualifier. Un succès du seul Python n'établit pas tout cela.

## Ce que font les autres

| Architecture | Existence vérifiée | Portée pour FoldGPT |
| --- | --- | --- |
| Termux | Le site officiel annonce un environnement Android sans root et propose Bash, Python et autres outils | Montre que l'exécution locale ne requiert pas Shizuku par principe. Ses paquets, chemins et variantes de distribution ne sont pas automatiquement transposables à notre APK ni au Play Store |
| Python embarqué, exemple Chaquopy | SDK Android avec intégration Gradle, appels Java/Kotlin/Python et dépendances Python | Exemple d'application ordinaire exécutant un interpréteur intégré ; ne fournit pas tout Codex, Electron ou nos garanties de gestion des processus |
| Ports CLI DioNanos/wallentx | Recettes Bionic déjà étudiées dans notre comparatif | Sources utiles pour le contrôleur ; aucun hôte Android de notre interface desktop livré par ces recettes. Leurs pages n'ont pas été rafraîchies à nouveau pendant cette revue |
| Shizuku | Route r25 réellement qualifiée avec serveur lancé par ADB ; démarrage depuis le téléphone documenté par Shizuku | Fonctionne pour le parcours validé, mais impose la préparation Android et ne rend pas le serveur autonome par simple intégration du SDK |

## Compte développeur et signature

Un compte Play fournit la distribution, les tests et les mises à jour de notre
application. Android lui attribue toujours son propre UID et ses permissions.
La signature Play est celle de notre application ; ce n'est pas une signature
de plateforme Samsung ni un accès shell.

Le certificat public d'un APK OpenAI permet d'en vérifier l'origine. Il ne
contient pas la clé privée de signature. Copier un composant ou décompiler un
APK ne permet pas de signer notre code comme OpenAI. Modifier l'APK puis le
signer avec notre clé ne conserve pas son identité ni son circuit de mise à jour
officiel. Même une identité OpenAI n'est pas une identité système Samsung.

Analyser une copie locale du manifeste, des bibliothèques, activités et services
peut aider à trouver un point d'interfaçage existant. Aucun point permettant
l'exécution locale complète n'est établi par cette revue ; aucune décompilation
nouvelle n'y est revendiquée. Une API exposée ou un composant réutilisable exige
un contrat vérifiable ; la signature n'en crée pas un.

## Pixel et AVF

Si « vpc » désigne AVF/pKVM/pVM, il s'agit de virtualisation : des machines
invitées gérées par VirtualizationService/crosvm. La disponibilité des API dépend
du support effectif de l'appareil ; une présence matérielle ARM64 ne suffit pas.
Sur un Pixel compatible, cette voie pourrait donner un environnement invité
différent. Elle ne garantit ni un noyau invité convenable pour notre client,
ni les droits d'accès de FoldGPT, ni son intégration graphique ou ses mises à jour.
Elle reste une VM, même si elle utilise directement les instructions ARM.
La phrase « sur Pixel le projet serait déjà terminé » n'est pas établie.
Cette revue n'a testé aucun Pixel et n'active aucune virtualisation sur le Fold.

## Client local et modèle OpenAI

La documentation OpenAI distingue les tâches locales du desktop des tâches
cloud. Elle indique explicitement que l'exécution locale ne signifie pas une
inférence hors ligne ou uniquement sur l'appareil. Le portage vise des outils
et fichiers locaux avec le service de modèle OpenAI, et non un téléchargement
des modèles ChatGPT contenus dans un APK. Cette distinction doit être expliquée
sans appeler l'application mobile un faux ChatGPT ni confondre absence de PC
personnel et absence de connexion Internet.

## Sources ouvertes pendant cette revue

- [AOSP : application sandbox](https://source.android.com/docs/security/app-sandbox).
- [Android : signature d'application et clés](https://developer.android.com/studio/publish/app-signing).
- [AOSP : AVF](https://source.android.com/docs/core/virtualization).
- [AOSP : VirtualizationService](https://source.android.com/docs/core/virtualization/virtualization-service).
- [Termux : fonctionnement et outils](https://termux.dev/en/).
- [Chaquopy : SDK Python Android](https://chaquo.com/chaquopy/).
- [OpenAI : frontière Work local/cloud](https://learn.chatgpt.com/docs/enterprise/chatgpt-work-overview).
- [OpenAI : exécution locale et inférence](https://learn.chatgpt.com/docs/enterprise/chatgpt-work-local-security#where-local-tasks-run).
- [Comparatif des ports CLI déjà étudiés](community-selection-20260908.md).
