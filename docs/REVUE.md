# Robot Revue — la vue unique du matin

Ce document fait foi pour la routine « Robot Revue » (~8h30 Paris,
après les trois robots nocturnes). Une session de cette routine ne fait
QUE ce qui est décrit ici : exécuter le script, vérifier sa sortie,
notifier. Pas de scraping, pas de notation, pas d'écriture ailleurs.
Repo en LECTURE SEULE : jamais de commit ni de push.

## Ce que c'est

L'onglet **Revue** (`tblcAnzoiOw7qt8WA`) de la base « Sourcing -
principal » (`appdJUoNvhEi5jsJr`) agrège les fondateurs EXAMINABLES
(profil LinkedIn identifié) des 4 tables sources — Fondateurs (Pappers),
Fondateurs (Evertrace), France (The Veck), International (The Veck) —
en une ligne par (profil, jour de signalement), dédoublonnée par slug
LinkedIn au sein d'un même jour. Samuel la regarde chaque matin,
groupée par « Jour », filtrée sur « Vu » décoché.

- Les colonnes d'information (Note IA, Justification, Score…) sont des
  **lookups** qui suivent les fiches sources en direct — le script
  n'écrit que l'ossature (nom, jour, slug, liens, champs de confort).
- Un re-signalement à un autre jour crée une **nouvelle ligne** ; elle
  naît cochée « Vu » si une fiche source l'est déjà (le seuil des
  60 jours est appliqué en amont par la déduplication inter-canaux).
- La case « Vu » de la Revue est cochable : deux automatisations
  Airtable (« Revue : Vu cliqué → fiches sources » et « Revue : reflet
  des sources ») la relient au système de déduplication existant.
  Convention : pour DÉ-voir quelqu'un, décocher ses fiches dans les
  onglets sources — décocher dans Revue seule serait recoché.

## Le run quotidien

1. `git fetch origin claude/vc-founder-prospecting-workflow-5qfbdr`
   puis checkout de cette branche (le repo est déjà cloné).
2. `python3 -m robot.revue` — idempotent : les fiches sources déjà
   liées dans Revue sont ignorées, relancer ne crée aucun doublon.
   La clé est dans `AIRTABLE_API_KEY` (variables d'environnement).
3. Lire la sortie du script (« N lignes créées, M complétées, par
   jour : … »). Zéro création est NORMAL si les canaux n'ont rien
   remonté — ce n'est pas une erreur.
4. Terminer par une PushNotification d'UNE ligne :
   « Revue : N nouveaux profils ce matin (Pappers X · Evertrace Y ·
   The Veck Z) » — ou la description du blocage si le script a échoué.
   Le silence n'est jamais acceptable.

## En cas de problème

- Erreur du script → relancer UNE fois (idempotent). Si ça persiste,
  PushNotification avec le message d'erreur exact ; ne rien bricoler
  à la main dans Airtable.
- Un champ introuvable (KeyError/422) signifie que le schéma Airtable
  a changé : le signaler, ne pas tenter de le réparer.
- Les IDs des tables et champs vivent dans `robot/config.py`
  (`TABLE_REVUE`, `CHAMPS_REVUE`, `CANAUX_REVUE`, `VU_SOURCES_REVUE`).
- Ne jamais toucher aux automatisations Airtable ni aux onglets
  miroirs ; ne jamais écrire dans les tables sources.
