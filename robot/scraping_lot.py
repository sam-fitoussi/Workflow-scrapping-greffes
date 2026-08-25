"""Boucle de scraping autonome, à lancer en tâche de fond.

Lit une file JSONL ({"rec_id": ..., "url": ...} par ligne), scrape les
profils UN PAR UN (le compte LinkedIn ne supporte pas le parallélisme :
429 sinon), et écrit au fil de l'eau :
  - <sortie>.jsonl : une ligne par profil {"rec_id", "url", "statut",
    "profil" | "erreur"} — consultable une seule fois à la fin par le modèle ;
  - <sortie>.etat  : "i/n" pour suivre l'avancement sans lire le JSONL.

Le plafond quotidien (80) est appliqué ici, quoi qu'il arrive.
Une URL morte (404 côté Phantom / résultat vide) sort en statut "mort" :
le RUNBOOK demande alors de repasser la fiche en « Non trouvé » + Anomalie.

Usage :
    python3 -m robot.scraping_lot file.jsonl resultats [cap]
"""

import json
import sys
import time

from . import config, phantoms


def scraper_file(fichier_file: str, prefixe_sortie: str, cap: int = config.SCRAPE_DAILY_CAP) -> None:
    taches = [json.loads(l) for l in open(fichier_file) if l.strip()][:cap]
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
        open(f"{prefixe_sortie}.etat", "w").write(f"{i}/{len(taches)}")
        time.sleep(3)  # respiration entre deux profils
    sortie.close()


if __name__ == "__main__":
    scraper_file(sys.argv[1], sys.argv[2],
                 int(sys.argv[3]) if len(sys.argv) > 3 else config.SCRAPE_DAILY_CAP)
