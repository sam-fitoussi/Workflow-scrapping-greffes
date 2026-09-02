# Enseignements du pilote (historique)

Pilote exécuté le 24/08/2026 sur la journée d'immatriculations du
20/08/2026, pour calibrer le robot avant l'automatisation. **Ce document
n'est pas une procédure** : il conserve le *pourquoi* de quelques choix
structurants. Pour l'exécution, seul `docs/RUNBOOK.md` fait foi.

## Pappers — modèle de coût et volumes de référence

- Coût vérifié empiriquement : **0,1 jeton par résultat retourné**
  (`recherche-dirigeants`). Le champ `total` est renvoyé même avec
  `par_page=1` : on mesure un volume pour 0,1 jeton avant de payer la
  récupération complète — c'est ce qui rend le sondage quotidien des
  dates quasi gratuit.
- Le paramètre `objet_social` filtre côté serveur, un mot-clé par
  requête (la virgule est un ET) : d'où une requête par mot-clé pour le
  cercle périphérie, dédupliquée par SIREN.
- Ordre de grandeur d'un jour ouvré (SAS + SASU, France entière) :
  ~65 dirigeants dans le cercle cœur ; ~120 en périphérie dont ~10
  retenus après filtre d'objet social ; ~8 jetons le tirage.

## Filtres déterministes

74 dirigeants → 56 gardés : l'âge (≥ 45 ans) est de loin le premier
filtre ; la liste noire de dénominations sert surtout en périphérie, les
codes NAF cœur étant déjà propres.

## Pourquoi la recherche LinkedIn est faite par le modèle et non par un Phantom

A/B test sur les mêmes 56 fondateurs : le Phantom « LinkedIn Profile URL
Finder » a trouvé **4 URLs sur 56** (dont un homonyme), contre **40/56**
pour la recherche web menée par le modèle avec jugement sur les extraits.
Cause : le Phantom exige la société dans la requête, or elle ne figure
pas encore sur un profil fraîchement immatriculé. Décision : la recherche
web par le modèle est la méthode de production ; l'URL Finder est retiré
du workflow. Le Profile Scraper, lui, reste central. Enseignement
connexe : les « non trouvés » se concentrent sur les profils à faible
valeur (SASU de conseil solo) ; les équipes de cofondateurs tech se
trouvent bien.

## Scraping — ce que le Profile Scraper renvoie

- Il accepte une URL de profil unique via `bonusArgument.spreadsheetUrl` :
  pas besoin de Google Sheet, on scrape profil par profil (~35-38 s
  chacun).
- Le résultat ne contient que les **2 derniers postes et les 2 dernières
  formations** : le scoring ne voit pas tout le parcours. C'est la limite
  connue du matching déterministe (une école citée seulement dans le
  headline n'est pas vue).

## Scoring et Note IA — calibration initiale

- Référentiel « Scoring » d'Airtable (~820 lignes, 1 point par ligne),
  matching par égalité de chaînes normalisées, accents conservés : les
  variantes d'orthographe s'ajoutent comme lignes du référentiel (ex.
  « 42 Paris »), pas dans le code.
- Note IA testée sur les 6 profils à score ≥ 1 du pilote : de 19/20 à
  3/20, sévérité conforme à l'attendu — le barème vit depuis dans la
  table Prompts d'Airtable, éditable sans toucher au code.
