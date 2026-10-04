"""Boucle de scraping autonome, à lancer en tâche de fond.

Lit une file JSONL ({"rec_id": ..., "url": ...} par ligne), scrape les
profils UN PAR UN (le compte LinkedIn ne supporte pas le parallélisme :
429 sinon), et écrit au fil de l'eau :
  - <sortie>.jsonl : une ligne par profil {"rec_id", "url", "statut",
    "profil" | "erreur"} — consultable une seule fois à la fin par le modèle ;
  - <sortie>.etat  : "i/n" pour suivre l'avancement sans lire le JSONL.

Reprise : relancer avec le MÊME préfixe de sortie (un préfixe par jour).
Les rec_id déjà présents dans <sortie>.jsonl sont sautés et comptent dans
le plafond — le cap (config.SCRAPE_DAILY_CAP) est donc bien quotidien,
pas par invocation.
Un Phantom terminé SANS aucun résultat est un plantage (cookie LinkedIn
expiré, limitation), pas une URL morte : statut "erreur", fiche intacte,
reprise en reliquat. Après config.SCRAPE_ERREURS_MAX erreurs (ou scrapes
vides) d'affilée, le lot s'arrête : le reste n'est pas tenté (alerte).
Échéance : passé config.SCRAPE_ECHEANCE_MIN minutes, le lot s'arrête
proprement entre deux profils (une commande de fond est coupée à 2 h) ;
relancer la même commande reprend là où il s'est arrêté.
Un profil que PhantomBuster déclare introuvable (« No Linkedin profile
found ») sort en statut "perimee" : l'adresse LinkedIn a changé (LinkedIn
ne redirige pas les anciennes adresses personnalisées, mais l'index de
recherche les garde en cache) — re-scraper ne sert à rien, il faut
retrouver l'adresse actuelle de la MÊME personne (robot/verif_identite.py
renvoie la fiche en « À chercher », adresse exclue).
Un objet renvoyé mais SANS contenu exploitable (moins de 2 des champs
utiles remplis — un compteur à zéro compte comme vide, cf.
config.champs_remplis) sort en statut "vide" : re-scrapé une fois au run
suivant, puis traité comme une adresse périmée.
Un profil que le Phantom SAUTE parce qu'il l'a déjà traité (« All leads
have been processed », déduplication du mode fileMgmt "mix") sort en
statut "deja_traite" : ce n'est PAS une URL morte — la fiche n'est pas
touchée et repart en reliquat. Le réglage du Phantom est vérifié au
lancement (alerte à reprendre EN TÊTE du rapport).

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
    try:
        alerte = phantoms.verifier_reglages()
    except Exception as e:
        alerte = f"⚠️ Réglages du Profile Scraper non vérifiables : {str(e)[:150]}"
    if alerte:
        print(alerte)
    deja = _rec_ids_deja_traites(prefixe_sortie)
    reste = max(0, cap - len(deja))
    taches = [t for t in (json.loads(l) for l in open(fichier_file) if l.strip())
              if t["rec_id"] not in deja][:reste]
    print(f"{len(deja)} déjà scrapés, {len(taches)} à faire (plafond {cap}).")

    sortie = open(f"{prefixe_sortie}.jsonl", "a")
    echeance = time.time() + config.SCRAPE_ECHEANCE_MIN * 60
    erreurs_suite = 0
    for i, t in enumerate(taches, 1):
        if time.time() > echeance:
            print(f"⏱️ Échéance de {config.SCRAPE_ECHEANCE_MIN} min atteinte : {len(taches) - i + 1} "
                  "profil(s) restant(s) — relancer la MÊME commande (reprise automatique).")
            break
        if erreurs_suite >= config.SCRAPE_ERREURS_MAX:
            print(f"⛔ Scraping arrêté après {erreurs_suite} erreurs consécutives : vérifier le cookie "
                  f"LinkedIn dans PhantomBuster. {len(taches) - i + 1} profil(s) non tentés, intacts "
                  "(repris au prochain run).")
            break
        ligne = {"rec_id": t["rec_id"], "url": t["url"]}
        try:
            profil = phantoms.scraper_profil(t["url"])
            p = profil[0] if isinstance(profil, list) and profil else profil
            if not p:
                ligne["statut"] = "mort"  # aucun résultat
            elif "no linkedin profile found" in str(p.get("error") or "").lower():
                ligne["statut"] = "perimee"  # adresse LinkedIn changée : à re-chercher
                ligne["profil"] = p
            elif config.champs_remplis(p) < 2:
                ligne["statut"] = "vide"  # objet renvoyé mais sans contenu : échec technique
                ligne["profil"] = p
            else:
                ligne["statut"] = "ok"
                ligne["profil"] = p
        except phantoms.ProfilDejaTraite as e:
            ligne["statut"] = "deja_traite"  # jamais une URL morte : fiche intacte
            ligne["erreur"] = str(e)[:300]
        except Exception as e:  # on continue la file, l'erreur est tracée
            ligne["statut"] = "erreur"
            ligne["erreur"] = str(e)[:300]
        erreurs_suite = erreurs_suite + 1 if ligne["statut"] in ("erreur", "vide") else 0
        sortie.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        sortie.flush()
        open(f"{prefixe_sortie}.etat", "w").write(f"{len(deja) + i}/{len(deja) + len(taches)}")
        time.sleep(3)  # respiration entre deux profils
    sortie.close()


if __name__ == "__main__":
    scraper_file(sys.argv[1], sys.argv[2],
                 int(sys.argv[3]) if len(sys.argv) > 3 else config.SCRAPE_DAILY_CAP)
