"""Étape 5 scriptée : des résultats de scraping aux payloads Airtable.

Entrées :
  - resultats.jsonl : sortie de robot/scraping_lot.py
  - ref.json        : table Scoring lue par `python3 -m robot.airtable lire`
  - contexte.jsonl  : lignes {"rec_id", "prenom", "nom", "age", "entreprise"}
                      (les *_fondateurs.jsonl de robot/run.py, concaténés ;
                      le reliquat des runs précédents suit le même format)

Sorties (préfixe donné en argument) :
  - <prefixe>_maj.json     : payload de mise à jour Fondateurs, à pousser
                             via `python3 -m robot.airtable maj` — Score,
                             Détail, Résumé, extrait JSON ; et pour les URLs
                             mortes : « Non trouvé » + Anomalie + motif.
  - <prefixe>_a_noter.jsonl : profils à score >= 1, prêts pour robot/note_ia.

Les statuts "erreur" ne sont PAS mis à jour : la fiche reste sans score et
repart en reliquat au run suivant (une seule relance, cf. RUNBOOK).

Usage :
    python3 -m robot.scorer_lot resultats.jsonl ref.json contexte.jsonl sortie
"""

import datetime as dt
import json
import sys

from . import config, phantoms, scoring
from .note_ia import CHAMPS_PROFIL

CF = config.CHAMPS_FONDATEURS
CS = config.CHAMPS_SCORING


def _resume(p: dict, ecoles: list[str]) -> str:
    poste = " @ ".join(x for x in [p.get("linkedinJobTitle"), p.get("companyName")] if x)
    avant = " @ ".join(x for x in [p.get("linkedinPreviousJobTitle"), p.get("previousCompanyName")] if x)
    morceaux = [
        p.get("linkedinHeadline"),
        poste and f"Actuel : {poste}",
        avant and f"Avant : {avant}",
        ecoles and "Écoles : " + ", ".join(ecoles),
        p.get("location"),
    ]
    return " • ".join(m for m in morceaux if m)[:1000]


def main(f_resultats: str, f_ref: str, f_contexte: str, prefixe: str) -> None:
    ref_records = json.load(open(f_ref))
    referentiel = scoring.construire_referentiel([
        {"nom": r["fields"].get(CS["nom"], ""), "points": r["fields"].get(CS["points"], 1)}
        for r in ref_records if r["fields"].get(CS["nom"])
    ])
    contexte = {}
    for l in open(f_contexte):
        if l.strip():
            c = json.loads(l)
            contexte[c["rec_id"]] = c

    maj, a_noter = [], []
    stats = {"ok": 0, "mort": 0, "erreur": 0, "score>=1": 0}
    aujourd_hui = dt.date.today().strftime("%d/%m")

    for l in open(f_resultats):
        if not l.strip():
            continue
        r = json.loads(l)
        if r["statut"] == "erreur":
            stats["erreur"] += 1  # reliquat : une seule relance au run suivant
            continue
        if r["statut"] == "mort":
            stats["mort"] += 1
            maj.append({"id": r["rec_id"], "fields": {
                CF["statut"]: "Non trouvé",
                CF["anomalie"]: True,
                CF["detail"]: f"URL LinkedIn morte ou profil vide le {aujourd_hui}",
            }})
            continue

        p = r["profil"]
        _, entreprises = phantoms.extraire_ecoles_entreprises(p)
        ecoles = scoring.ecoles_diplomantes([
            (p.get("linkedinSchoolName"), p.get("linkedinSchoolDegree")),
            (p.get("linkedinPreviousSchoolName"), p.get("linkedinPreviousSchoolDegree")),
        ])
        score, detail = scoring.scorer_profil(referentiel, ecoles, entreprises)
        extrait = {k: p.get(k) for k in CHAMPS_PROFIL if p.get(k) is not None}
        maj.append({"id": r["rec_id"], "fields": {
            CF["score"]: score,
            CF["detail"]: ", ".join(detail) if detail else "—",
            CF["resume"]: _resume(p, ecoles),
            CF["json"]: json.dumps(extrait, ensure_ascii=False)[:2500],
        }})
        stats["ok"] += 1

        if score >= 1:
            stats["score>=1"] += 1
            c = contexte.get(r["rec_id"], {})
            nom = f"{c.get('prenom') or ''} {c.get('nom') or ''}".strip() or "(nom inconnu)"
            a_noter.append({"rec_id": r["rec_id"], "nom": nom, "age": c.get("age"),
                            "societe": c.get("entreprise"), "score": score, "profil": extrait})

    json.dump(maj, open(f"{prefixe}_maj.json", "w"), ensure_ascii=False)
    with open(f"{prefixe}_a_noter.jsonl", "w") as f:
        for ligne in a_noter:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main(*sys.argv[1:5])
