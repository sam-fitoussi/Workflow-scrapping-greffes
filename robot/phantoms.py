"""Pilotage des Phantoms PhantomBuster (validé pendant le pilote).

Découverte utile : le LinkedIn Profile Scraper accepte une URL de profil
unique dans `spreadsheetUrl` via bonusArgument — pas besoin de Google Sheet
pour des lots pilotés profil par profil. Un exitCode 87 avec endType
"finished" est un succès (avertissement de configuration « Delete previous
files »).
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


def scraper_profil(url_profil: str, timeout_s: int = 180) -> list[dict] | None:
    """Lance le Profile Scraper sur une URL et attend le résultat."""
    launch = _call("agents/launch", {
        "id": config.PHANTOM_SCRAPER_ID,
        "manualLaunch": True,
        "bonusArgument": {
            "spreadsheetUrl": url_profil,
            "pushResultToCRM": False,
            "numberOfAddsPerLaunch": 1,
        },
    })
    container_id = launch["containerId"]

    debut = time.time()
    while time.time() - debut < timeout_s:
        time.sleep(15)
        etat = _call("containers/fetch", params={"id": container_id})
        if etat.get("status") == "finished":
            res = _call("containers/fetch-result-object", params={"id": container_id})
            brut = res.get("resultObject")
            return json.loads(brut) if brut else None
    raise TimeoutError(f"Scraping non terminé après {timeout_s}s (container {container_id})")


def extraire_ecoles_entreprises(profil: dict) -> tuple[list[str], list[str]]:
    """Champs école/entreprise du résultat du Profile Scraper (2 + 2 max)."""
    ecoles = [profil.get("linkedinSchoolName"), profil.get("linkedinPreviousSchoolName")]
    entreprises = [profil.get("companyName"), profil.get("previousCompanyName")]
    return [e for e in ecoles if e], [e for e in entreprises if e]
