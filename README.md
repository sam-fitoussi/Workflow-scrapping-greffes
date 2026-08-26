# Workflow-scrapping-greffes

Robot de sourcing pre-seed (Frst) : détecte chaque jour les sociétés tout
juste immatriculées aux greffes (API Pappers), retrouve les profils
LinkedIn de leurs fondateurs, contrôle leur identité, les score contre un
référentiel d'écoles et d'entreprises, les note sur 20, et présente les
profils à examiner dans Airtable.

## Source de vérité

**`docs/RUNBOOK.md` fait foi pour tout** : procédure du run quotidien,
identifiants, plafonds, noms des variables d'environnement, cas
particuliers. Ce README ne duplique volontairement aucun chiffre ni aucun
nom de variable — quand un détail diverge entre les deux, c'est le
runbook qui a raison, et ce README qui est en retard.

## Contenu du repo

| Chemin | Rôle |
|---|---|
| `docs/RUNBOOK.md` | LA procédure du run quotidien (autoportante) |
| `docs/PILOTE.md` | Journal du pilote et enseignements |
| `robot/config.py` | Constantes : périmètre Pappers, filtres, IDs Airtable, plafonds |
| `robot/pappers.py` | Tirage des immatriculations + filtres déterministes |
| `robot/run.py` | Orchestrateur : sondage, tirage, insertion, Journal |
| `robot/reliquat.py` | Reconstruit le travail en attente depuis Airtable |
| `robot/airtable.py` | Client REST Airtable (payloads sur disque) |
| `robot/scraping_lot.py` | Boucle de scraping PhantomBuster en tâche de fond |
| `robot/verif_identite.py` | Contrôle anti-homonymes des profils scrapés |
| `robot/scorer_lot.py` | Scoring déterministe + payloads de mise à jour |
| `robot/note_ia.py` | Note IA sur 20 (barème `robot/note_ia_prompt.md`) |

Le modèle (session Claude planifiée) n'intervient qu'aux deux endroits où
le jugement compte : la recherche des profils LinkedIn et le rapport
final. Tout le reste est scripté.

## Secrets

Aucune clé dans le code ni dans ce repo, jamais. Les clés vivent dans les
variables d'environnement de l'environnement d'exécution — noms exacts et
pièges dans le runbook.
