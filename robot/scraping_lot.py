"""Boucle de scraping autonome, à lancer en tâche de fond.

Lit une file JSONL ({"rec_id": ..., "url": ...} par ligne), scrape les
profils PAR LOTS via Apify (robot/apify.py — sans le compte LinkedIn de
Samuel, parcours complet) et écrit au fil de l'eau :
  - <sortie>.jsonl : une ligne par profil {"rec_id", "url", "statut",
    "profil" | "erreur"} — consultable une seule fois à la fin par le modèle ;
  - <sortie>.etat  : "i/n" pour suivre l'avancement sans lire le JSONL.

Statuts :
  - "ok"      : profil lu ;
  - "perimee" : adresse introuvable (404) — l'étape 5 renvoie la fiche en
                « À chercher », adresse exclue (une ancienne adresse encore
                valable est résolue d'office par Apify) ;
  - "vide"    : objet sans contenu exploitable (moins de 2 champs utiles,
                cf. config.champs_remplis) : re-scrapé une fois au run
                suivant, puis traité comme une adresse périmée ;
  - "erreur"  : panne technique, fiche intacte, reprise en reliquat.
Après config.SCRAPE_ERREURS_MAX lots en échec d'affilée, ou si Apify est
indisponible (clé absente, crédit épuisé), le lot s'arrête : le reste n'est
pas tenté (alerte EN TÊTE du rapport).

Reprise : relancer avec le MÊME préfixe de sortie (un préfixe par jour).
Les rec_id déjà présents dans <sortie>.jsonl sont sautés et comptent dans
le plafond — le cap (config.SCRAPE_DAILY_CAP) est donc bien quotidien.
Échéance : passé config.SCRAPE_ECHEANCE_MIN minutes, arrêt propre entre
deux lots ; relancer la même commande reprend là où il s'est arrêté.

Usage :
    python3 -m robot.scraping_lot file.jsonl resultats [cap]
"""

import json
import sys
import time

from . import apify, config


def _rec_ids_deja_traites(prefixe_sortie: str) -> set[str]:
    try:
        return {json.loads(l)["rec_id"] for l in open(f"{prefixe_sortie}.jsonl") if l.strip()}
    except FileNotFoundError:
        return set()


def statut_de(item: dict | None) -> tuple[str, dict]:
    """(statut, ligne partielle) pour un profil demandé."""
    if item is None:
        return "erreur", {"erreur": "aucun résultat Apify pour cette adresse"}
    if apify.introuvable(item):
        return "perimee", {"erreur": str(item.get("error") or "404")[:300]}
    if item.get("error"):
        return "erreur", {"erreur": str(item["error"])[:300]}
    p = apify.en_profil(item)
    if config.champs_remplis(p) < 2:
        return "vide", {"profil": p}
    return "ok", {"profil": p}


def scraper_file(fichier_file: str, prefixe_sortie: str, cap: int = config.SCRAPE_DAILY_CAP) -> None:
    if not config.APIFY_TOKEN:
        raise SystemExit("⛔ APIFY_TOKEN absent : scraping impossible, fiches intactes "
                         "(reprises au prochain run). À signaler EN TÊTE du rapport.")
    deja = _rec_ids_deja_traites(prefixe_sortie)
    reste = max(0, cap - len(deja))
    taches = [t for t in (json.loads(l) for l in open(fichier_file) if l.strip())
              if t["rec_id"] not in deja][:reste]
    print(f"{len(deja)} déjà scrapés, {len(taches)} à faire (plafond {cap}).")

    echeance = time.time() + config.SCRAPE_ECHEANCE_MIN * 60
    echecs_suite, faits = 0, 0
    with open(f"{prefixe_sortie}.jsonl", "a") as sortie:
        for i in range(0, len(taches), config.SCRAPE_LOT):
            lot = taches[i:i + config.SCRAPE_LOT]
            if time.time() > echeance:
                print(f"⏱️ Échéance de {config.SCRAPE_ECHEANCE_MIN} min atteinte : {len(taches) - i} "
                      "profil(s) restant(s) — relancer la MÊME commande (reprise automatique).")
                break
            try:
                items = apify.scraper([t["url"] for t in lot])
                echecs_suite = 0
            except apify.ApifyIndisponible as e:
                print(f"⛔ Apify indisponible ({e}) : {len(taches) - i} profil(s) non tentés, "
                      "intacts (repris au prochain run).")
                break
            except Exception as e:  # panne passagère : le lot est noté en erreur
                echecs_suite += 1
                items = {}
                print(f"Lot en échec ({str(e)[:150]})")
            for t in lot:
                statut, extra = statut_de(items.get(t["url"]))
                sortie.write(json.dumps({"rec_id": t["rec_id"], "url": t["url"], "statut": statut,
                                         **extra}, ensure_ascii=False) + "\n")
            sortie.flush()
            faits += len(lot)
            open(f"{prefixe_sortie}.etat", "w").write(f"{len(deja) + faits}/{len(deja) + len(taches)}")
            if echecs_suite >= config.SCRAPE_ERREURS_MAX:
                print(f"⛔ Scraping arrêté après {echecs_suite} lots en échec d'affilée : "
                      f"{len(taches) - faits} profil(s) non tentés, intacts (repris au prochain run).")
                break


if __name__ == "__main__":
    scraper_file(sys.argv[1], sys.argv[2],
                 int(sys.argv[3]) if len(sys.argv) > 3 else config.SCRAPE_DAILY_CAP)
