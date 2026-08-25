"""Orchestrateur déterministe du run quotidien (étapes 2 à 4 du RUNBOOK).

Fait en un seul script tout ce qui n'a pas besoin du modèle : tirage
Pappers, filtres, anti-doublons SIREN, insertion Airtable (entreprises puis
fondateurs liés), écriture de la ligne du Journal — date par date, la ligne
du Journal étant écrite SITÔT la date insérée (si la session meurt ensuite,
la journée payée reste enregistrée).

Le modèle ne reprend la main qu'après : recherche LinkedIn (jugement),
scraping (robot/scraping_lot.py en tâche de fond), scoring + Note IA.

Usage :
    python3 -m robot.run --dates 21-08-2026 22-08-2026 --sortie /tmp/run
    python3 -m robot.run --sonde            # affiche total J-1..J-7 (0,1 jeton/date)

Sorties dans --sortie :
    <date>_bruts.json        tirage brut Pappers
    <date>_gardes.json       après filtres
    <date>_fondateurs.jsonl  file pour la recherche LinkedIn (1 ligne/fondateur,
                             avec rec_id Airtable, date_source, contexte)
"""

import argparse
import datetime as dt
import json
import pathlib

from . import airtable, config, pappers

CE = config.CHAMPS_ENTREPRISES
CF = config.CHAMPS_FONDATEURS
CJ = config.CHAMPS_JOURNAL


def _iso(date_fr: str) -> str:
    """JJ-MM-AAAA -> AAAA-MM-JJ."""
    j, m, a = date_fr.split("-")
    return f"{a}-{m}-{j}"


def sonder(nb_jours: int = 7) -> dict[str, int]:
    """Total de dirigeants cercle cœur publiés pour J-1..J-nb_jours (0,1 jeton/date)."""
    totaux = {}
    for i in range(1, nb_jours + 1):
        d = (dt.date.today() - dt.timedelta(days=i)).strftime("%d-%m-%Y")
        r = pappers._call("recherche-dirigeants", {
            "date_immatriculation_rcs_min": d,
            "date_immatriculation_rcs_max": d,
            "categorie_juridique": config.CATEGORIES_JURIDIQUES,
            "type_dirigeant": "physique",
            "code_naf": ",".join(config.NAF_COEUR),
            "par_page": 1,
        })
        totaux[d] = r.get("total", 0)
    return totaux


def _fiche_entreprise(e: dict, cercle: str, date_immat_fr: str) -> dict:
    siege = e.get("siege") or {}
    cp = siege.get("code_postal") or e.get("code_postal") or ""
    return {"fields": {
        CE["denomination"]: e.get("nom_entreprise"),
        CE["siren"]: e.get("siren"),
        CE["date_immat"]: _iso(date_immat_fr),
        CE["date_creation"]: e.get("date_creation"),
        CE["forme"]: {"5710": "SAS", "5720": "SASU"}.get(e.get("categorie_juridique"), e.get("forme_juridique")),
        CE["naf"]: (e.get("code_naf") or "").replace(".", ""),
        CE["libelle_naf"]: e.get("libelle_code_naf"),
        CE["ville"]: siege.get("ville") or e.get("ville"),
        CE["dept"]: cp[:2] if cp else None,
        CE["capital"]: e.get("capital"),
        CE["cercle"]: cercle,
        CE["lien_pappers"]: f"https://www.pappers.fr/entreprise/{e.get('siren')}",
    }}


def _fiche_fondateur(d: dict, e: dict, rec_entreprise: str) -> dict:
    prenom = d.get("prenom") or ""
    nom = d.get("nom") or ""
    siege = e.get("siege") or {}
    return {"fields": {
        CF["nom_complet"]: f"{prenom} {nom}".strip(),
        CF["prenom"]: prenom,
        CF["nom"]: nom,
        CF["age"]: d.get("age"),
        CF["qualite"]: d.get("qualite"),
        CF["ville"]: siege.get("ville") or e.get("ville"),
        CF["entreprise"]: [rec_entreprise],
        CF["siren_cible"]: e.get("siren"),
        CF["statut"]: "À chercher",
    }}


def traiter_date(date_fr: str, sirens_connus: set[str], sortie: pathlib.Path,
                 note_journal: str = "") -> dict:
    """Déroule tirage → filtres → insertion → Journal pour UNE date. Retourne les stats."""
    jetons_avant = pappers.jetons_restants()

    bruts = pappers.tirage_du_jour(date_fr)
    (sortie / f"{date_fr}_bruts.json").write_text(json.dumps(bruts, ensure_ascii=False))
    gardes, _ = pappers.filtrer(bruts)

    # Anti-doublons SIREN (rattrapages, dates retraitées)
    nouveaux = [g for g in gardes if g["entreprise"]["siren"] not in sirens_connus]
    (sortie / f"{date_fr}_gardes.json").write_text(json.dumps(nouveaux, ensure_ascii=False))

    # Une fiche entreprise par SIREN (plusieurs cofondateurs -> même société)
    par_siren: dict[str, dict] = {}
    for g in nouveaux:
        par_siren.setdefault(g["entreprise"]["siren"], g)
    payload_ent = [_fiche_entreprise(g["entreprise"], g["dirigeant"].get("_cercle", "Cœur"), date_fr)
                   for g in par_siren.values()]
    crees = airtable.inserer(config.TABLE_ENTREPRISES, payload_ent)
    rec_par_siren = {r["fields"][CE["siren"]]: r["id"] for r in crees}
    sirens_connus.update(rec_par_siren)

    payload_fond = [_fiche_fondateur(g["dirigeant"], g["entreprise"],
                                     rec_par_siren[g["entreprise"]["siren"]])
                    for g in nouveaux]
    fondateurs = airtable.inserer(config.TABLE_FONDATEURS, payload_fond)

    # File pour la recherche LinkedIn, taguée avec la date source
    with open(sortie / f"{date_fr}_fondateurs.jsonl", "w") as f:
        for g, rec in zip(nouveaux, fondateurs):
            d, e = g["dirigeant"], g["entreprise"]
            f.write(json.dumps({
                "rec_id": rec["id"],
                "date_source": date_fr,
                "prenom": d.get("prenom"), "nom": d.get("nom"), "age": d.get("age"),
                "ville": (e.get("siege") or {}).get("ville") or e.get("ville"),
                "entreprise": e.get("nom_entreprise"),
                "naf": e.get("libelle_code_naf"),
            }, ensure_ascii=False) + "\n")

    jetons_apres = pappers.jetons_restants()
    stats = {"date": date_fr, "bruts": len(bruts), "gardes": len(gardes),
             "inseres": len(fondateurs), "jetons": round(jetons_avant - jetons_apres, 1)}

    # Ligne du Journal écrite IMMÉDIATEMENT (jamais deux fois la même journée payée)
    airtable.inserer(config.TABLE_JOURNAL, [{"fields": {
        CJ["date_traitee"]: _iso(date_fr),
        CJ["bruts"]: stats["bruts"],
        CJ["gardes"]: stats["gardes"],
        CJ["inseres"]: stats["inseres"],
        CJ["jetons"]: stats["jetons"],
        CJ["notes"]: note_journal or f"Run scripté du {dt.date.today():%d/%m/%Y}.",
    }}])
    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dates", nargs="*", default=[], help="dates JJ-MM-AAAA à traiter")
    p.add_argument("--sortie", default="sorties", help="répertoire de travail")
    p.add_argument("--sonde", action="store_true", help="sonder J-1..J-7 et sortir")
    p.add_argument("--note", default="", help="note à inscrire au Journal")
    args = p.parse_args()

    if args.sonde:
        print(json.dumps(sonder(), ensure_ascii=False, indent=1))
        return

    solde = pappers.jetons_restants()
    if solde < 15:
        raise SystemExit(f"STOP : {solde} jetons Pappers restants (< 15). Recharger puis relancer.")
    if solde < 50:
        print(f"⚠️ ALERTE : jetons Pappers bas ({solde} restants), recharger le pay-as-you-go.")

    sortie = pathlib.Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)

    existants = airtable.lire_table(config.TABLE_ENTREPRISES, [CE["siren"]])
    sirens = {r["fields"].get(CE["siren"]) for r in existants if r["fields"].get(CE["siren"])}
    print(f"{len(sirens)} SIREN déjà connus.")

    for date_fr in args.dates:
        stats = traiter_date(date_fr, sirens, sortie, args.note)
        print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
