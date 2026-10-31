"""Pilotage du Phantom PhantomBuster « Robot sourcing - Recherche par nom ».

Le scraping des profils ne passe PLUS par PhantomBuster (robot/apify.py,
sans compte LinkedIn) : LinkedIn a signalé une activité inhabituelle sur le
compte de Samuel et déconnecté PhantomBuster. Seule la recherche par nom
(Sales Navigator, via son compte) reste ici — quelques dizaines de
recherches par jour.

Règle : ne jamais modifier les réglages du Phantom ; tout passe par
bonusArgument (les requêtes sauvegardées dans le Phantom sont vides — sinon
elles s'ajoutent aux nôtres).
"""

import json
import time
import urllib.parse
import urllib.request

from . import config

BASE = "https://api.phantombuster.com/api/v2"

def _call(path: str, payload: dict | None = None, params: dict | None = None) -> dict:
    url = f"{BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "X-Phantombuster-Key-1": config.PHANTOMBUSTER_API_KEY,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def rechercher_noms(requetes: list[str], timeout_s: int = 6600) -> list[dict]:
    """Recherche Sales Navigator « Prénom Nom », toutes les requêtes en UN
    lancement (~30 s par requête). Renvoie les résultats bruts du Phantom
    (champ `query` = la requête d'origine, `defaultProfileUrl` = adresse
    publique /in/…). La recherche interne de LinkedIn voit les profils que
    les moteurs de recherche n'indexent pas (récents, nom masqué « Allan B. »
    hors réseau, adresse changée)."""
    launch = _call("agents/launch", {
        "id": config.PHANTOM_RECHERCHE_NOM_ID,
        "manualLaunch": True,
        # le compte LinkedIn (identité) est celui réglé dans le Phantom
        "bonusArgument": {
            "queries": requetes,
            "numberOfResultsPerSearch": 10,
            "numberOfProfiles": 10 * len(requetes),
            "removeDuplicateProfiles": False,
            "watcherMode": False,
            "csvName": "recherche_nom",
        },
    })
    container_id = launch["containerId"]
    debut = time.time()
    while time.time() - debut < timeout_s:
        time.sleep(30)
        if _call("containers/fetch", params={"id": container_id}).get("status") == "finished":
            brut = _call("containers/fetch-result-object",
                         params={"id": container_id}).get("resultObject")
            if not brut:
                raise RuntimeError(f"Recherche par nom terminée sans résultat (container "
                                   f"{container_id}) : plantage probable, vérifier le cookie LinkedIn")
            res = json.loads(brut)
            if isinstance(res, dict) and res.get("jsonUrl"):
                # gros lot : PhantomBuster ne renvoie que le lien du fichier
                with urllib.request.urlopen(res["jsonUrl"]) as r:
                    res = json.load(r)
            return res
    raise TimeoutError(f"Recherche par nom non terminée après {timeout_s}s (container {container_id})")
