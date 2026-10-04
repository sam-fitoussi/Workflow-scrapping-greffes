"""Étape 1 du robot : tirage des nouvelles immatriculations via l'API Pappers.

Modèle de coût vérifié : 0,1 jeton par résultat retourné (recherche-dirigeants).
Le champ `total` est renvoyé même avec par_page=1, ce qui permet de mesurer
un volume pour 0,1 jeton avant de payer la récupération complète.
"""

import json
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from . import config

BASE = "https://api.pappers.fr/v2"


def _call(endpoint: str, params: dict) -> dict:
    """Appel Pappers avec retry : tirage_du_jour fait 26 requêtes par date (plus
    les pages suivantes au-delà de 100 résultats), et
    un seul 500 transitoire au milieu ferait re-payer toute la date au run
    suivant (pas de ligne de Journal) — exactement ce que le Journal doit
    empêcher."""
    q = {"api_token": config.PAPPERS_API_KEY, **params}
    url = f"{BASE}/{endpoint}?" + urllib.parse.urlencode(q)
    for attente in (15, 30, None):
        try:
            with urllib.request.urlopen(url) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attente:
                time.sleep(attente)
                continue
            raise
        except urllib.error.URLError:
            if attente:
                time.sleep(attente)
                continue
            raise
    raise RuntimeError("inatteignable")


def _sans_accents(s: str) -> str:
    return unicodedata.normalize("NFD", (s or "").upper()).encode("ascii", "ignore").decode()


def jetons_restants() -> float:
    d = _call("suivi-jetons", {})
    return d.get("jetons_pay_as_you_go_restants", 0) + (
        d.get("jetons_abonnement", 0) - d.get("jetons_abonnement_utilises", 0)
    )


PAR_PAGE = 100  # plafond de l'API par page : au-delà, il FAUT paginer


def _recherche_complete(endpoint: str, params: dict) -> list[dict]:
    """Tous les résultats d'une recherche, page par page.

    Sans pagination, une journée à plus de PAR_PAGE dirigeants était
    silencieusement tronquée (28/09/2026 : 136 au sondage, 100 tirés), et le
    rattrapage du dimanche la re-tirait chaque semaine sans jamais rien
    regagner. Coût inchangé : 0,1 jeton par résultat retourné, quelle que
    soit la page. On s'arrête sur `total` atteint ou sur une page incomplète
    (garde-fou si `total` bouge pendant le tirage)."""
    resultats: list[dict] = []
    page = 1
    while True:
        d = _call(endpoint, {**params, "par_page": PAR_PAGE, "page": page})
        lot = d.get("resultats") or []
        resultats.extend(lot)
        if len(lot) < PAR_PAGE or len(resultats) >= (d.get("total") or 0):
            return resultats
        page += 1
        time.sleep(0.3)


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
    }

    resultats = []
    vus = set()
    coeur = _recherche_complete("recherche-dirigeants",
                                {**commun, "code_naf": ",".join(config.NAF_COEUR)})
    for r in coeur:
        cle = (r.get("nom"), r.get("prenom"), r.get("date_de_naissance"))
        if cle in vus:  # filet si l'ordre bouge d'une page à l'autre
            continue
        vus.add(cle)
        r["_cercle"] = "Cœur"
        resultats.append(r)

    # La périphérie se déduplique contre le cœur ET entre mots-clés
    for kw in config.MOTS_CLES_OBJET_SOCIAL:
        lot = _recherche_complete("recherche-dirigeants", {
            **commun,
            "code_naf": ",".join(config.NAF_PERIPHERIE),
            "objet_social": kw,
        })
        for r in lot:
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
