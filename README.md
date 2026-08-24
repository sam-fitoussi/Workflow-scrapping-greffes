# Robot-sourcing

Robot de sourcing pre-seed : détecte chaque jour les sociétés tout juste
immatriculées aux greffes (via l'API Pappers), retrouve les profils LinkedIn
de leurs fondateurs, les score contre un référentiel d'écoles et
d'entreprises, et présente les profils retenus dans Airtable.

## Architecture

```
Pappers (recherche-dirigeants, J-2)
  └─ filtres déterministes (NAF cœur/périphérie, âge < 45, liste noire,
     serial-gérants, qualités)
      └─ Airtable « Scrapping Pappers » : tables Entreprises + Fondateurs
          └─ recherche des URLs LinkedIn (Phantom URL Finder / recherche web LLM)
              └─ validation d'identité (règles déterministes puis juge Haiku)
                  └─ scraping (PhantomBuster LinkedIn Profile Scraper, ≤ 80/jour)
                      └─ scoring déterministe (table « Scoring », 1 pt / item)
                          └─ vue « À examiner » (score ≥ 1, non vus), case « Vu »
```

## Bases Airtable

Base **Scrapping Pappers** (`appdJUoNvhEi5jsJr`) :

| Table | Rôle |
|---|---|
| `Scoring` | Référentiel écoles/entreprises (orthographe LinkedIn exacte, 1 point par item, extensible à la main) |
| `Entreprises` | Sociétés retenues (clé d'unicité : SIREN) |
| `Fondateurs` | Dirigeants retenus, URL LinkedIn, score, case « Vu » |

## Anti-doublons / exhaustivité

- Tirage quotidien : **une seule journée d'immatriculation (J-2), jamais
  retirée deux fois** — chaque résultat Pappers n'est payé qu'une fois
  (0,1 jeton/résultat).
- Rattrapage hebdomadaire : re-balayage des 7 derniers jours, doublons
  écartés par SIREN avant insertion.
- Pagination par curseur avec vérification `récupérés == total`.

## Secrets

Aucune clé dans le code. Variables d'environnement attendues :
`PAPPERS_API_KEY`, `AIRTABLE_API_KEY`, `ANTHROPIC_API_KEY`,
`PHANTOMBUSTER_API_KEY` (secrets GitHub Actions en production).

## Journal

Voir `docs/PILOTE.md` pour le déroulé et les enseignements du pilote
(journée d'immatriculations du 20/08/2026).
