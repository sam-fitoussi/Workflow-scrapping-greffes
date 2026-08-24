"""Étape 1 du robot : tirage des nouvelles immatriculations via l'API Pappers.

Modèle de coût vérifié : 0,1 jeton par résultat retourné (recherche-dirigeants).
Le champ `total` est renvoyé même avec par_page=1, ce qui permet de mesurer
un volume pour 0,1 jeton avant de payer la récupération complète.
"""

import json
import time
import unicodedata
import urllib.parse
import urllib.request

from . import config

BASE = "https://api.pappers.fr/v2"


def _call(endpoint: str, params: dict) -> dict:
    q = {"api_token": config.PAPPERS_API_KEY, **params}
    url = f"{BASE}/{endpoint}?" + urllib.parse.urlencode(q)
    with urllib.request.urlopen(url) as r:
        return json.load(r)


def _sans_accents(s: str) -> str:
    return unicodedata.normalize("NFD", (s or "").upper()).encode("ascii", "ignore").decode()


def jetons_restants() -> float:
    d = _call("suivi-jetons", {})
    return d.get("jetons_pay_as_you_go_restants", 0) + (
        d.get("jetons_abonnement", 0) - d.get("jetons_abonnement_utilises", 0)
    )


def tirage_du_jour(date_immat: str) -> list[dict]:
    """Récupère les dirigeants des sociétés immatriculées au RCS le jour donné.

    date_immat au format JJ-MM-AAAA. Retourne une liste de résultats bruts
    Pappers (un par dirigeant), cercle cœur + cercle périphérie filtré par
    mots-clés d'objet social.
    """
    commun = {
        "date_immatriculation_rcs_min": date_immat,
        "date_immatriculation_rcs_max": date_immat,
        "categorie_juridique": config.CATEGORIES_JURIDIQUES,
        "type_dirigeant": "physique",
        "par_page": 100,
    }

    resultats = []
    coeur = _call("recherche-dirigeants", {**commun, "code_naf": ",".join(config.NAF_COEUR)})
    for r in coeur["resultats"]:
        r["_cercle"] = "Cœur"
        resultats.append(r)

    vus = set()
    for kw in config.MOTS_CLES_OBJET_SOCIAL:
        d = _call("recherche-dirigeants", {
            **commun,
            "code_naf": ",".join(config.NAF_PERIPHERIE),
            "objet_social": kw,
        })
        for r in d["resultats"]:
            cle = (r.get("nom"), r.get("prenom"), r.get("date_de_naissance"))
            if cle in vus:
                continue
            vus.add(cle)
            r["_cercle"] = "Périphérie"
            resultats.append(r)
        time.sleep(0.3)

    return resultats


def societe_cible(dirigeant: dict) -> dict | None:
    """Parmi les sociétés du dirigeant, celle qui correspond à nos critères."""
    nafs = set(config.NAF_COEUR) | set(config.NAF_PERIPHERIE)
    candidates = [
        e for e in dirigeant.get("entreprises", [])
        if e.get("categorie_juridique") in ("5710", "5720")
        and (e.get("code_naf") or "").replace(".", "") in nafs
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda e: e.get("date_creation") or "", reverse=True)[0]


def filtrer(dirigeants: list[dict]) -> tuple[list[dict], list[dict]]:
    """Applique les filtres déterministes. Retourne (gardés, écartés).

    Chaque élément gardé est un dict {"dirigeant": ..., "entreprise": ...}.
    """
    gardes, ecartes = [], []
    vus = set()
    for r in dirigeants:
        e = societe_cible(r)
        raisons = []
        if e is None:
            raisons.append("pas de société cible identifiable")
        else:
            cle = (r.get("nom"), r.get("prenom"), e["siren"])
            if cle in vus:
                continue
            vus.add(cle)

            age = r.get("age")
            if age is not None and age >= config.AGE_MAX:
                raisons.append(f"âge {age}")
            if (r.get("nb_entreprises_total") or 0) >= config.SERIAL_GERANT_MIN:
                raisons.append(f"serial-gérant ({r['nb_entreprises_total']} sociétés)")
            nom_ent = _sans_accents(e.get("nom_entreprise", ""))
            touches = [b for b in config.BLACKLIST_DENOMINATION if b in nom_ent]
            if touches:
                raisons.append(f"liste noire : {touches}")
            if r.get("qualite") in config.QUALITES_EXCLUES:
                raisons.append("qualité exclue")

        cible = {"dirigeant": r, "entreprise": e, "raisons": raisons}
        (ecartes if raisons else gardes).append(cible)
    return gardes, ecartes
