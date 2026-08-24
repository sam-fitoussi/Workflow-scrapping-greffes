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

## Étape 4bis — Résultats du scraping

20 profils scrapés (les mieux matchés), **20/20 réussis**, ~35 s par
profil. Le résultat ne contient que les 2 derniers postes et les 2
dernières formations — le scoring ne voit donc pas tout le parcours.

Sécurité : 2 profils contenaient des tentatives d'injection de prompt
destinées aux agents IA dans leur description. Traitées comme des données ;
le pipeline ne doit jamais exécuter le texte des profils.

## Étape 5 — Scoring

Référentiel : table « Scoring » de la base Scrapping Pappers (820 lignes,
1 point par ligne). Matching : égalité de chaînes normalisées (minuscules,
espaces), accents conservés.

Résultat : **6 profils à score ≥ 1 sur 20 scrapés** — Eliot Andres (2 :
Photoroom, Télécom Paris), Louis Ramard (1 : HEC Paris), Alban Le Bail
(1 : Centrale Nantes), Louis de Valbray (1 : EDHEC), Jérémie Selana (1 :
Dauphine-PSL), Florian Mazabraud (1 : ManoMano).

Faux négatifs observés (à corriger en calibration) :
- Karim El Khadiri affiche « ESCP » dans son headline mais pas dans ses 2
  formations les plus récentes → envisager un matching complémentaire sur
  le headline (prudent, mots entiers uniquement).
- Hugo Esposito-Farese est « @42 Paris » : ajouter la variante « 42 Paris »
  au référentiel.

## Bilan chiffré de l'entonnoir (1 journée d'immatriculations)

74 dirigeants bruts → 56 après filtres → 40 avec URL LinkedIn (71 %) →
20 scrapés (sous-ensemble pilote) → **6 à examiner**. Coût Pappers du
pilote : ~8,5 jetons. Coût Anthropic : quelques centimes (recherche web +
jugements). Durée de bout en bout : ~1 h30, dont ~25 min de scraping.

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

## A/B test URL Finder (24/08, après partage du Sheet)

Phantom LinkedIn Profile URL Finder sur les 56 fondateurs (requête « nom +
société + ville ») : **4 URLs trouvées sur 56** (dont 1 faux positif
homonyme), 10 erreurs de requête. Contre **40/56** pour la recherche web
LLM avec jugement sur extraits. Cause : le Phantom exige la société dans
la requête, or elle ne figure pas encore sur les profils fraîchement créés.

**Décision : la recherche web LLM est la méthode de production ; le
Phantom URL Finder est retiré de ce workflow** (le Profile Scraper, lui,
reste central). Le Google Sheet public « Robot Sourcing - Pilote URL
Finder » n'a donc plus d'usage quotidien — conservé comme mécanisme de
secours pour alimenter un Phantom par lots si besoin.

## Note IA (ajoutée le 24/08)

Champ « Note IA » (/20) + « Justification note IA », remplis par Claude
Sonnet 5 (barème robot/note_ia_prompt.md) pour les profils à score ≥ 1.
Test sur les 6 profils du pilote : Eliot Andres 19/20, Alban Le Bail 11,
Jérémie Selana 8, Louis Ramard 7, Louis de Valbray 6, Florian Mazabraud 3.
Sévérité conforme à l'attendu.

## Automatisation (mise en place le 24/08)

Routine Claude quotidienne à 04:30 UTC (06:30 Paris) qui réveille la
session de construction du robot et déroule docs/RUNBOOK.md. Tourne dans
le cloud, ordinateur éteint. Premier run réel : 25/08, à vérifier.
