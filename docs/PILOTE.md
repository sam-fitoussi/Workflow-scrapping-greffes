# Journal du pilote — journée d'immatriculations du 20/08/2026

Pilote exécuté le 24/08/2026, de bout en bout, pour calibrer le robot avant
l'automatisation quotidienne.

## Étape 1 — Pappers

- Modèle de coût vérifié empiriquement : **0,1 jeton par résultat retourné**
  (`recherche-dirigeants`). Le champ `total` est renvoyé même avec
  `par_page=1` → on peut mesurer un volume pour 0,1 jeton.
- Le paramètre `objet_social` filtre côté serveur (un mot-clé par requête,
  la virgule est un ET). Testé : périphérie 123 dirigeants → 1 avec
  « logiciel ».
- Volumes du jeudi 20/08 (SAS+SASU, France entière) :
  - Cercle cœur (20 codes NAF) : **65 dirigeants**
  - Cercle périphérie (13 codes NAF) : 123 dirigeants, dont **9 uniques**
    après filtre mots-clés d'objet social
- Coût total du tirage : **~8 jetons**.

## Étape 2 — Filtres déterministes

74 dirigeants → **56 gardés**, 18 écartés (17 par l'âge ≥ 45, 1
serial-gérant). La liste noire n'a rien éliminé ce jour-là (les codes NAF
cœur sont déjà propres). 45 sociétés distinctes.

## Étape 3 — Recherche des profils LinkedIn (méthode « recherche web LLM »)

4 sous-agents Claude en parallèle, 1-3 recherches web par fondateur,
jugement sur les extraits (localisation, plausibilité, âge) SANS exiger que
la société figure sur le profil (elle vient d'être créée).

- **Trouvés : 36/56 (64 %) — Ambigus : 4 (7 %) — Non trouvés : 16 (29 %)**
- 7 profils confirmés par la société déjà affichée (PublikConnect ×2,
  Morphal, Datafalk, brAIny, OnVaConstruire, TakeMe via un post)
- Enseignement clé : les « non trouvés » sont très concentrés sur les
  profils à faible valeur (SASU de conseil solo) ; les équipes de
  cofondateurs tech se trouvent bien.
- Piste Phantom URL Finder : non comparée ce jour-là — le Phantom lit un
  Google Sheet public et l'écriture automatisée du Sheet nécessite soit un
  partage « toute personne avec le lien » (un clic dans Drive), soit la
  connexion Google Drive dans Zapier. À brancher pour l'A/B test.

## Étape 4 — Scraping (PhantomBuster LinkedIn Profile Scraper)

Découverte utile : le Phantom accepte une **URL de profil unique** dans
`spreadsheetUrl` via `bonusArgument` → pas besoin de Google Sheet pour des
lots pilotés un par un. En production on gardera un lot par jour via le
Sheet public dédié.

## Étape 5 — Scoring

Référentiel : table « Scoring » de la base Scrapping Pappers (820 lignes,
1 point par ligne). Matching : égalité de chaînes normalisées (minuscules,
espaces), accents conservés.

## Reste à faire identifié pendant le pilote

- [ ] Partager le Google Sheet « Robot Sourcing - Pilote URL Finder » en
      « toute personne avec le lien : lecteur » pour pouvoir A/B tester le
      Phantom URL Finder contre la recherche web LLM.
- [ ] Connecter Google Drive dans Zapier (ou créer un identifiant Google
      API dédié) pour que le robot écrive lui-même les Sheets d'entrée des
      Phantoms en production.
- [ ] Clé API Anthropic dédiée au robot (juge Haiku) pour l'exécution
      autonome hors session Claude.
- [ ] GitHub Actions : workflow quotidien (tirage J-2) + hebdomadaire
      (rattrapage 7 jours + relances techniques).
- [ ] Vue Airtable « À examiner » : filtre Score ≥ 1 et Vu décoché, tri
      Score décroissant.
