"""Reconstruit le reliquat depuis Airtable — l'état durable fait foi.

Produit d'un coup tout ce que les étapes 3 à 6 du RUNBOOK consomment,
sans aucune jointure ni parsing à la main :

  reliquat_a_chercher.jsonl  fiches « À chercher » des runs précédents,
                             avec `urls_exclues` (homonymes déjà écartés)
                             et `indices` (indices greffe posés par run.py),
                             tous deux extraits de « Détail score »
  reliquat_scrape.jsonl      {rec_id, url} : fiches Trouvé/Ambigu avec URL
                             mais SANS Score (le scraping n'a pas abouti)
  contexte.jsonl             contexte de toutes ces fiches (nom, âge,
                             ville, dénomination et activité via la table
                             Entreprises) + les fichiers du jour — prêt
                             pour les étapes 5-6
  equipes.jsonl              une ligne par société à >= 2 cofondateurs
                             dans contexte.jsonl : membres côte à côte
                             (indices greffe, URLs déjà écartées) — le
                             recoupement d'équipe, signal n°1 de la
                             recherche, servi tout cuit

Les fichiers du jour (motif daté `JJ-MM-AAAA_fondateurs.jsonl`, trouvés
AUTOMATIQUEMENT dans <sortie_dir>) servent aussi d'exclusion : une fiche
insérée par run.py aujourd'hui est encore « À chercher » mais n'est pas
un reliquat. Le motif daté évite que les autres .jsonl du répertoire
soient pris pour des fichiers du jour lors d'une seconde invocation, et un
jour sans date cible (zéro fichier) fonctionne normalement.

Usage : python3 -m robot.reliquat <sortie_dir> [fondateurs_jour.jsonl ...]
        (les fichiers explicites remplacent la détection automatique)
"""

import json
import pathlib
import re
import sys

from . import airtable, config

CF = config.CHAMPS_FONDATEURS
CE = config.CHAMPS_ENTREPRISES


def main(sortie_dir: str, fichiers_jour: list[str]) -> None:
    sortie = pathlib.Path(sortie_dir)
    sortie.mkdir(parents=True, exist_ok=True)
    if not fichiers_jour:  # détection automatique, motif daté uniquement
        fichiers_jour = sorted(str(p) for p in sortie.glob("[0-9]*-[0-9]*-[0-9]*_fondateurs.jsonl"))
        print(f"Fichiers du jour détectés : {len(fichiers_jour)}")

    ids_jour = set()
    lignes_jour = []
    for f in fichiers_jour:
        for l in open(f):
            if l.strip():
                d = json.loads(l)
                ids_jour.add(d["rec_id"])
                lignes_jour.append(d)

    ents = airtable.lire_table(config.TABLE_ENTREPRISES,
                               [CE["siren"], CE["denomination"], CE["libelle_naf"],
                                CE["ville"]])
    par_siren = {r["fields"].get(CE["siren"]): r["fields"] for r in ents
                 if r["fields"].get(CE["siren"])}

    fond = airtable.lire_table(config.TABLE_FONDATEURS, [
        CF["statut"], CF["linkedin_url"], CF["score"], CF["detail"],
        CF["prenom"], CF["nom"], CF["age"], CF["ville"], CF["siren_cible"],
    ])

    a_chercher, a_scraper, ctx_reliquat = [], [], []
    for r in fond:
        if r["id"] in ids_jour:
            continue  # fiche du jour, pas un reliquat
        f = r["fields"]
        statut = f.get(CF["statut"])
        e = par_siren.get(f.get(CF["siren_cible"]), {})
        detail = f.get(CF["detail"]) or ""
        # Indices greffe consignés dans Détail par run.py à l'insertion
        # (naissance, ville du dirigeant, noms d'usage, autres mandats) :
        # les signaux d'identité des paliers et du contrôle (RUNBOOK)
        m = re.search(r"Indices greffe : (\{.*?\})(?:\s*\||$)", detail)
        try:
            indices = json.loads(m.group(1)) if m else {}
        except json.JSONDecodeError:
            indices = {}
        # ville = SIÈGE (table Entreprises), comme dans les fichiers du jour ;
        # la ville personnelle du dirigeant est dans indices.ville_dirigeant
        base = {"rec_id": r["id"], "prenom": f.get(CF["prenom"]), "nom": f.get(CF["nom"]),
                "age": f.get(CF["age"]), "ville": e.get(CE["ville"]) or f.get(CF["ville"]),
                "entreprise": e.get(CE["denomination"]), "naf": e.get(CE["libelle_naf"]),
                "siren": f.get(CF["siren_cible"]), "indices": indices}
        if statut == "À chercher":
            urls = re.findall(r"https?://[^\s)|]+", detail)
            a_chercher.append(base | {"urls_exclues": urls})
        elif statut in ("Trouvé", "Ambigu") and f.get(CF["linkedin_url"]) \
                and f.get(CF["score"]) is None:  # Score rempli (même 0) = déjà traité
            a_scraper.append({"rec_id": r["id"], "url": f[CF["linkedin_url"]]})
            ctx_reliquat.append(base)

    def ecrire(nom_fichier, lignes):
        with open(sortie / nom_fichier, "w") as f:
            for l in lignes:
                f.write(json.dumps(l, ensure_ascii=False) + "\n")

    ecrire("reliquat_a_chercher.jsonl", a_chercher)
    ecrire("reliquat_scrape.jsonl", a_scraper)
    # contexte.jsonl inclut AUSSI les « À chercher » : re-cherchés puis
    # scrapés dans le même run, ils arrivent au contrôle d'identité et à
    # la Note IA — sans leur contexte, le juge recevrait un greffe vide
    ctx_a_chercher = [{k: v for k, v in x.items() if k != "urls_exclues"}
                      for x in a_chercher]
    contexte = ctx_reliquat + ctx_a_chercher + lignes_jour
    ecrire("contexte.jsonl", contexte)

    # equipes.jsonl : la vue par société. La recherche recoupe entre
    # cofondateurs (villes personnelles, écoles, employeurs communs) — au
    # lieu de reconstituer les équipes depuis des fichiers à plat, elles
    # sont émises groupées, avec les URLs déjà écartées de chaque membre.
    exclusions = {x["rec_id"]: x["urls_exclues"] for x in a_chercher if x["urls_exclues"]}
    par_equipe: dict[str, list[dict]] = {}
    for c in contexte:
        if c.get("siren"):
            par_equipe.setdefault(c["siren"], []).append(c)
    equipes = []
    for siren, membres in sorted(par_equipe.items()):
        if len(membres) < 2:
            continue
        equipes.append({
            "siren": siren,
            "entreprise": membres[0].get("entreprise"),
            "naf": membres[0].get("naf"),
            "membres": [{"rec_id": m["rec_id"], "prenom": m.get("prenom"),
                         "nom": m.get("nom"), "age": m.get("age"),
                         "indices": m.get("indices") or {}}
                        | ({"urls_exclues": exclusions[m["rec_id"]]}
                           if m["rec_id"] in exclusions else {})
                        for m in membres],
        })
    ecrire("equipes.jsonl", equipes)
    print(f"Reliquat : {len(a_chercher)} à re-chercher "
          f"(dont {sum(1 for x in a_chercher if x['urls_exclues'])} avec URLs à exclure), "
          f"{len(a_scraper)} à re-scraper. contexte.jsonl : {len(contexte)} lignes ; "
          f"equipes.jsonl : {len(equipes)} sociétés à cofondateurs.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
