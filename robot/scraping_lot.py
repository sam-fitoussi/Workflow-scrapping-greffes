"""Boucle de scraping autonome, à lancer en tâche de fond.

Lit une file JSONL ({"rec_id": ..., "url": ...} par ligne), scrape les
profils UN PAR UN (le compte LinkedIn ne supporte pas le parallélisme :
429 sinon), et écrit au fil de l'eau :
  - <sortie>.jsonl : une ligne par profil {"rec_id", "url", "statut",
    "profil" | "erreur"} — consultable une seule fois à la fin par le modèle ;
  - <sortie>.etat  : "i/n" pour suivre l'avancement sans lire le JSONL.

Reprise : relancer avec le MÊME préfixe de sortie (un préfixe par jour).
Les rec_id déjà présents dans <sortie>.jsonl sont sautés et comptent dans
le plafond — le cap de 80 est donc bien quotidien, pas par invocation.
Une URL morte (404 / résultat vide) sort en statut "mort" : le RUNBOOK
demande alors « Non trouvé » + Anomalie (fait par robot/scorer_lot.py).

Usage :
    python3 -m robot.scraping_lot file.jsonl resultats [cap]
"""

import json
import sys
import time

from . import config, phantoms


def _rec_ids_deja_traites(prefixe_sortie: str) -> set[str]:
    try:
        return {json.loads(l)["rec_id"] for l in open(f"{prefixe_sortie}.jsonl") if l.strip()}
    except FileNotFoundError:
        return set()


def scraper_file(fichier_file: str, prefixe_sortie: str, cap: int = config.SCRAPE_DAILY_CAP) -> None:
    if not config.PHANTOMBUSTER_API_KEY:
        raise SystemExit("PHANTOMBUSTER_API_KEY absent : sans elle chaque profil "
                         "sortirait en 401/erreur. Piloter le Phantom via le MCP à la place.")
    deja = _rec_ids_deja_traites(prefixe_sortie)
    reste = max(0, cap - len(deja))
    taches = [t for t in (json.loads(l) for l in open(fichier_file) if l.strip())
              if t["rec_id"] not in deja][:reste]
    print(f"{len(deja)} déjà scrapés, {len(taches)} à faire (plafond {cap}).")

    sortie = open(f"{prefixe_sortie}.jsonl", "a")
    for i, t in enumerate(taches, 1):
        ligne = {"rec_id": t["rec_id"], "url": t["url"]}
        try:
            profil = phantoms.scraper_profil(t["url"])
            p = profil[0] if isinstance(profil, list) and profil else profil
            if not p:
                ligne["statut"] = "mort"  # URL 404 ou profil vide
            else:
                ligne["statut"] = "ok"
                ligne["profil"] = p
        except Exception as e:  # on continue la file, l'erreur est tracée
            ligne["statut"] = "erreur"
            ligne["erreur"] = str(e)[:300]
        sortie.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        sortie.flush()
        open(f"{prefixe_sortie}.etat", "w").write(f"{len(deja) + i}/{len(deja) + len(taches)}")
        time.sleep(3)  # respiration entre deux profils
    sortie.close()


if __name__ == "__main__":
    scraper_file(sys.argv[1], sys.argv[2],
                 int(sys.argv[3]) if len(sys.argv) > 3 else config.SCRAPE_DAILY_CAP)
