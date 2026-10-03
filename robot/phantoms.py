"""Pilotage des Phantoms PhantomBuster (validé pendant le pilote).

Découverte utile : le LinkedIn Profile Scraper accepte une URL de profil
unique dans `spreadsheetUrl` via bonusArgument — pas besoin de Google Sheet
pour des lots pilotés profil par profil. Un exitCode 87 avec endType
"finished" est un succès (avertissement de configuration « Delete previous
files »).

Ce réglage « Delete previous files » (fileMgmt = "delete") est
INDISPENSABLE : en mode "mix", le Phantom garde la mémoire des profils déjà
traités et saute toute URL déjà scrapée une fois (« All leads have been
processed ») sans rien renvoyer — un profil valide était alors pris pour
une URL morte et enterré en « Non trouvé » (incident du 03/10/2026, après
la bascule sur le workspace de Samuel). Garde-fous : `verifier_reglages()`
au lancement de robot.scraping_lot, et l'exception `ProfilDejaTraite` qui
distingue ce cas d'une URL morte.
"""

import json
import time
import urllib.parse
import urllib.request

from . import config

BASE = "https://api.phantombuster.com/api/v2"

MARQUEUR_DEJA_TRAITE = "all leads have been processed"


class ProfilDejaTraite(Exception):
    """Le Phantom a sauté l'URL parce qu'il l'a déjà traitée (déduplication
    du mode fileMgmt "mix") : ce n'est PAS une URL morte."""


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
    """Lance le Profile Scraper sur une URL et attend le résultat.

    Un incident réseau transitoire (connection reset) coûte sinon un jour
    de délai au profil (aller-retour de reliquat) : on retente UNE fois
    après 10 s avant de laisser l'erreur remonter. Si la coupure survient
    pendant le polling, le retry relance un second container (deux visites
    LinkedIn pour un profil) — accepté, la marge du plafond le couvre."""
    try:
        return _scraper_profil(url_profil, timeout_s)
    except (TimeoutError, ProfilDejaTraite):
        raise  # un vrai timeout ou un saut de déduplication ne se rejoue pas ici
    except Exception:
        time.sleep(10)
        return _scraper_profil(url_profil, timeout_s)


def _scraper_profil(url_profil: str, timeout_s: int) -> list[dict] | None:
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
            if brut:
                return json.loads(brut)
            sortie = _call("containers/fetch-output", params={"id": container_id})
            if MARQUEUR_DEJA_TRAITE in (sortie.get("output") or "").lower():
                raise ProfilDejaTraite(
                    f"PhantomBuster a sauté ce profil, déjà traité par le Phantom "
                    f"(container {container_id}) : régler « Delete previous files »")
            return None
    raise TimeoutError(f"Scraping non terminé après {timeout_s}s (container {container_id})")


def verifier_reglages() -> str | None:
    """Renvoie une alerte si le Profile Scraper n'est pas en mode « Delete
    previous files » (sinon il saute les profils déjà scrapés), None sinon."""
    agent = _call("agents/fetch", params={"id": config.PHANTOM_SCRAPER_ID})
    mode = agent.get("fileMgmt")
    if mode != "delete":
        return (f"⚠️ ALERTE PhantomBuster : le Profile Scraper est en fileMgmt "
                f"« {mode} » au lieu de « delete » — il SAUTE tout profil déjà "
                f"scrapé une fois. Régler « Delete previous files » dans les "
                f"paramètres du Phantom.")
    return None


def extraire_ecoles_entreprises(profil: dict) -> tuple[list[str], list[str]]:
    """Champs école/entreprise du résultat du Profile Scraper (2 + 2 max)."""
    ecoles = [profil.get("linkedinSchoolName"), profil.get("linkedinPreviousSchoolName")]
    entreprises = [profil.get("companyName"), profil.get("previousCompanyName")]
    return [e for e in ecoles if e], [e for e in entreprises if e]
