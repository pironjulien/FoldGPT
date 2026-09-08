# Audit borné des échecs R5 — 8 septembre 2026

**La suite Rust globale échoue réellement. Les tests natifs ciblés passent. Les deux constats sont compatibles et ne doivent pas être fusionnés.** Audit des fichiers locaux seulement : aucun build, test, changement de production ou contact téléphone.

Run `34192652057`, commit `8963acc8e961c0d34b068910b973cc6f9b9df3bc`. Source exacte : `work/ci-results/34192652057/engine/evidence/engine-full-tests.log`, résumé **ligne29392** :17173 exécutés,16933 réussis,238 échoués,2timeouts,35skips. Les238 échecs comprennent **203 FAIL et35 ABRT** ; les35skips sont un ensemble différent. La commande sort avec code100 ;4,66Go restent libres, donc une saturation disque n’est pas démontrée.

## Comptage sans doublons

Les240 identifiants distincts du résumé final sont raccordés à leur dernier bloc `TRY 2` dans le journal. Chaque test n’est compté qu’une fois, malgré deux tentatives et la répétition dans le résumé. Les catégories suivantes sont exclusives et totalisent240 ; elles classent les **symptômes observés**, pas240 causes racines identifiées.

| Observation principale | Cas | Ce que cela établit et limite |
| --- | ---: | --- |
| Erreur explicite bwrap + permission refusée |102| Échec réel du démarrage sandbox Linux. Les48 échecs exec-server sont inclus. La règle hôte exacte responsable n’est pas établie ici. |
| Débordement de pile avec SIGABRT |35| Crash réel de tests TUI sous pile8Mio. Une correction par augmentation de pile n’a pas été démontrée. |
| Différence de snapshots TUI |28| Sorties de rendu différentes ; version et largeur sont impliquées dans les diffs déjà examinés. Aucun snapshot n’a été remplacé. |
| Assertions TLS/classification/repli |6| Erreurs observées de classification de certificat/protocole et de décision de nouvelle tentative. Ni bwrap ni une cause purement environnementale ne sont prouvés. |
| Incohérence du feature de test V8 |1| Le POC attend false alors que V8 lié rapporte true ; le contrôle du sandbox V8 produit passe. |
| Tests arrêtés à60s par le runner |2| Budget des images et envoi de feedback ne terminent pas dans le délai. Cause de lenteur/blocage non établie. |
| Autres assertions et attentes |66| Échecs réels dans commandes, interruption, permissions, hooks, historique/MCP. Une alerte générique bwrap ne suffit pas à leur attribuer cette cause. |

Répartition indépendante par paquet, incluant les deux timeouts : core77, TUI63, exec-server48, app-server25, linux-sandbox12, HTTP6, MCP4, CLI3, feedback1, V8-POC1. Les66 cas résiduels comprennent notamment15 cas d’approbation réseau,4 apply_patch,4 extensions sandbox,4 racines de travail,4 analytics et4 outils MCP. Le JSON donne les240 noms, catégories, lignes, extraits, empreintes et sous-familles.

## Exemples exacts dans le journal R5

- **Ligne1587**, `command_exec_accepts_permission_profile` : `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, sortie1 au lieu du succès attendu. C’est bien bwrap exécuté sur le runner Linux, pas un message « bwrap absent » du téléphone.
- **Lignes21753–21756**, `overview_cold_resume_honors_working_directory_selection` : `has overflowed its stack`, `fatal runtime error: stack overflow, aborting`, SIGABRT. Le journal impose `RUST_MIN_STACK=8388608` dès la ligne1. Ces35 crashs ne sont pas des finitions cosmétiques ; leur effet sur l’application graphique Android reste non démontré.
- **Lignes23845 et23874–23875**, `initial_session_header_starts_at_the_top_of_the_viewport` : véritable échec de comparaison de rendu. Les28 cas sont les mêmes que dans le triage précédent, qui analyse versions0.0.0/0.153.4 et largeurs calculées ; aucune correction n’est déclarée passée.
- **Lignes17569–17570**, `request_failures_classify_real_untrusted_certificate_handshakes` : assertion de classification devant `InvalidCertificate(UnknownIssuer)`. **Lignes17623–17624**, `does_not_retry_a_non_replayable_streaming_request` : `native TLS protocol failure should be retryable`, `AlertReceived(ProtocolVersion)`. L’impact potentiel concerne le client HTTP partagé ; il mérite un diagnostic distinct.
- **Lignes29278–29283**, `sandbox_feature_matches_linked_v8` : gauche true, droite false. Le contrôle produit `linked_v8_has_sandbox_enabled` est **PASS ligne6067**. La revue précédente `work/ci-results/34190100825/v8-feature-review.md` explique l’unification Cargo et le feature local du POC ; cette incohérence ne signifie pas absence du sandbox V8 produit.
- **Ligne8434** : `image_preparation::tests::detail_policies_apply_the_expected_budgets`,60,007s. **Ligne18597** : `feedback_upload_delivers_whole_files_or_marked_prefixes`,60,018s. Les journaux ne donnent pas de cause suffisante.
- **Lignes12773–12774**, nouveau cas `rollout_budget::restates_the_current_remainder_after_rollback` : `timeout waiting for event: Elapsed(())`. C’est une attente interne échouée, comptée FAIL, distincte des deux timeouts du runner.
- **Lignes1130–1131**, analytics : absence de `Process running with session ID` attendue. Le voisinage contient également des erreurs de fixture MCP HTTP404 ; il ne permet pas de conclure que le transport MCP produit est globalement cassé.

## Comparaison et portée pour FoldGPT

Les **239 cas échoués/expirés de34190100825 échouent encore**, et un cas supplémentaire apparaît : l’attente après rollback citée ci-dessus. L’ancien bilan était237échecs +2timeouts. Le nouveau comporte également deux tests exécutés de plus ; le décompte seul ne prouve pas une régression causée par le patch R5.

L’ancien triage annonçait103 observations bwrap selon un critère plus large. Le présent recomptage conservateur trouve102 dans chaque run, en exigeant dans le dernier bloc une erreur `bwrap:` et une permission refusée. Les autres cas restent visibles ; aucune « amélioration de bwrap » n’est déduite de cette différence de méthode.

Les étapes ciblées du **même run R5** sont à code0 :355 tests exec-server,33 tests d’intégration injectée,3 de démarrage natif et1 projet Python réel via app-server. Des filtres excluent d’autres tests de ces étapes ; le scénario modèle utilise des réponses SSE déterministes. Cela soutient les chemins Linux précis du moteur, pas une conversation réelle Android ni l’ensemble des fonctions historiques. Les vérifications finales dépendantes de la suite globale ne sont pas toutes exécutées.

Le code ordinaire r21 est **postérieur** à cette source Rust et possède sa CI Python distincte34203936964. Ce journal ne teste donc pas le nouveau runner Android r21. Les102 erreurs du backend sandbox Linux ne prouvent pas qu’il lui faudrait bwrap. Les crashs TUI, assertions HTTP et attentes core restent de vrais défauts de qualification à examiner ; leur présence interdit de dire « il ne reste que du cosmétique » ou « toute la suite passe ». Elle ne démontre pas non plus238 blocages indépendants du petit projet sur le Fold.

## Avons-nous tous les logs ?

Nous avons le journal agrégé complet de cette commande jusqu’au résumé final et à son code100, les240 blocs finaux identifiés, les reçus de commande, sources et étapes ciblées. **Cela ne veut pas dire chaque octet de chaque sous-processus** : certains tests plafonnent volontairement leurs propres sorties ; `command_exec_streaming_does_not_buffer_output`, bloc ligne2270, ne conserve que `stderr="bwrap"`. Les octets perdus à ce niveau ne peuvent pas être reconstruits.

Nous n’avons pas les traces d’un succès r21 sur le téléphone, puisque cet essai n’a pas encore eu lieu, ni le reçu final historique de la session8507 avant débranchement. Ces absences doivent être dites explicitement. Les prochaines investigations peuvent être choisies à partir de ce triage ; aucun test ou correctif supplémentaire n’a été lancé par cet audit.
