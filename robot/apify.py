"""Scraping des profils LinkedIn via Apify, SANS le compte LinkedIn de Samuel.

Décision du 31/10/2026 : LinkedIn a signalé une activité inhabituelle sur
le compte de Samuel (520 à 680 profils/jour visités par nos robots via
PhantomBuster) et l'a déconnecté. Le scraping passe désormais par l'acteur
Apify « harvestapi/linkedin-profile-scraper » (sans cookie ni compte) :
profil en temps réel, parcours COMPLET (toutes les expériences et
formations, descriptions, prix), 0,004 $ par profil. Il remplace le Profile
Scraper PhantomBuster (2 postes / 2 écoles seulement) ET l'enrichissement
Crustdata (0,30 $ par profil, cache parfois en retard).

Comportements constatés au test : une adresse inexistante revient avec
status 404 « Profile not found » (→ statut "perimee") ; une ANCIENNE
adresse personnalisée est résolue vers le profil actuel ; les profils au
nom masqué hors réseau (« Allan B. ») sont lus en entier.

Le profil renvoyé est converti au format historique du pipeline (champs
« linkedin… » du Profile Scraper), plus :
  - linkedinParcours : parcours complet en texte (Note IA, contrôle
    d'identité) ;
  - toutesEcoles / toutesEntreprises : pour le scoring (toutes, plus
    seulement les deux plus récentes).

Clé : variable d'environnement APIFY_TOKEN.

Aussi : la recherche par nom (rechercher_nom, robot/recherche_nom.py).

Usage (palier « au cas par cas » du RUNBOOK, lire des candidats) :
    python3 -m robot.apify <url LinkedIn> [<url> ...]
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import config

ACTEUR = "harvestapi~linkedin-profile-scraper"
MODE = "Profile details no email ($4 per 1k)"
PRIX_PROFIL = 0.004  # $


class ApifyIndisponible(Exception):
    """Clé absente ou refusée, crédit épuisé : rien ne sert d'insister."""


def scraper(urls: list[str], timeout_s: int = 300) -> dict[str, dict]:
    """{url demandée: item Apify brut} — un seul appel pour tout le lot."""
    if not config.APIFY_TOKEN:
        raise ApifyIndisponible("APIFY_TOKEN absent")
    plafond = round(PRIX_PROFIL * len(urls) * 1.5 + 0.01, 3)  # garde-fou de facturation
    req = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{ACTEUR}/run-sync-get-dataset-items?"
        + urllib.parse.urlencode({"maxTotalChargeUsd": plafond, "timeout": timeout_s}),
        data=json.dumps({"profileScraperMode": MODE, "queries": urls}).encode(),
        headers={"Authorization": f"Bearer {config.APIFY_TOKEN}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s + 60) as r:
            items = json.load(r)
    except urllib.error.HTTPError as e:
        corps = e.read().decode(errors="replace")[:200]
        if e.code in (401, 402, 403):
            raise ApifyIndisponible(f"HTTP {e.code} : {corps}")
        raise RuntimeError(f"Apify HTTP {e.code} : {corps}")
    par_cle = {_cle((it.get("originalQuery") or {}).get("query")): it for it in items or []}
    return {u: par_cle[_cle(u)] for u in urls if _cle(u) in par_cle}


def _cle(url: str | None) -> str:
    """Adresse normalisée (accents encodés ou non, sous-domaine, / final)
    pour retrouver le résultat de chaque adresse demandée."""
    m = re.search(r"/in/([^/?#]+)", urllib.parse.unquote(url or ""))
    return m.group(1).lower() if m else (url or "")


ACTEUR_RECHERCHE = "harvestapi~linkedin-profile-search-by-name"
PRIX_RECHERCHE = 0.004  # $ par page de 10 résultats


def rechercher_nom(prenom: str, nom: str, france: bool = False, timeout_s: int = 120) -> list[dict]:
    """Recherche LinkedIn par prénom + nom (sans compte LinkedIn) : profils
    courts {name, position, linkedinUrl, location.linkedinText}, 10 au plus.
    Remplace la recherche Sales Navigator via PhantomBuster (test du 31/10 :
    mêmes résultats sur 13 noms, noms masqués « Allan B. » compris).
    france=True : seulement les profils situés en France — la localisation
    renvoyée n'est souvent que la ville (« Nice », « Fasano »), le pays n'y
    figure pas."""
    if not config.APIFY_TOKEN:
        raise ApifyIndisponible("APIFY_TOKEN absent")
    entree = {"profileScraperMode": "Short", "firstName": prenom, "lastName": nom,
              "strictSearch": True, "maxPages": 1}
    if france:
        entree["locations"] = ["France"]
    req = urllib.request.Request(
        f"https://api.apify.com/v2/acts/{ACTEUR_RECHERCHE}/run-sync-get-dataset-items?"
        + urllib.parse.urlencode({"maxTotalChargeUsd": round(PRIX_RECHERCHE * 2 + 0.01, 3),
                                  "timeout": timeout_s}),
        data=json.dumps(entree).encode(),
        headers={"Authorization": f"Bearer {config.APIFY_TOKEN}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s + 60) as r:
            return [it for it in json.load(r) or [] if it.get("linkedinUrl")]
    except urllib.error.HTTPError as e:
        corps = e.read().decode(errors="replace")[:200]
        if e.code in (401, 402, 403):
            raise ApifyIndisponible(f"HTTP {e.code} : {corps}")
        raise RuntimeError(f"Apify HTTP {e.code} : {corps}")


def introuvable(item: dict) -> bool:
    return item.get("status") == 404 or "not found" in str(item.get("error") or "").lower()


def _periode(x: dict) -> str | None:
    debut = (x.get("startDate") or {}).get("text")
    fin = (x.get("endDate") or {}).get("text")
    return " - ".join(v for v in (debut, fin) if v) or x.get("period")


def _experiences(item: dict) -> list[dict]:
    vus, out = set(), []
    for x in item.get("experience") or []:
        cle = (x.get("position"), x.get("companyName"), (x.get("startDate") or {}).get("text"))
        if cle not in vus:
            vus.add(cle)
            out.append(x)
    return out


def _texte_parcours(item: dict) -> str:
    lignes = ["Expériences :"]
    for x in _experiences(item):
        ligne = f"- {x.get('position') or '?'} @ {x.get('companyName') or '?'} ({_periode(x) or '?'})"
        if x.get("description"):
            ligne += f" : {x['description'][:250]}"
        lignes.append(ligne)
    if item.get("education"):
        lignes.append("Formation :")
    for x in item.get("education") or []:
        diplome = ", ".join(v for v in (x.get("degree"), x.get("fieldOfStudy")) if v)
        ligne = f"- {x.get('schoolName') or '?'}" + (f" — {diplome}" if diplome else "")
        ligne += f" ({_periode(x) or '?'})"
        extra = " ".join(v for v in (x.get("description"), x.get("insights")) if v)
        if extra:
            ligne += f" : {extra[:250]}"
        lignes.append(ligne)
    for cle, titre in (("honorsAndAwards", "Prix"), ("publications", "Publications"),
                       ("patents", "Brevets"), ("projects", "Projets")):
        elems = [e.get("title") or e.get("name") for e in item.get(cle) or []]
        elems = [e for e in elems if e]
        if elems:
            lignes.append(f"{titre} : " + " ; ".join(elems[:10]))
    return "\n".join(lignes)[:6000]


def en_profil(item: dict) -> dict:
    """Item Apify → profil au format historique du pipeline."""
    exp = _experiences(item)
    edu = item.get("education") or []
    p = {
        "linkedinHeadline": item.get("headline"),
        "location": (item.get("location") or {}).get("linkedinText"),
        "linkedinDescription": item.get("about"),
        "linkedinFollowersCount": item.get("followerCount"),
        "linkedinConnectionsCount": item.get("connectionsCount"),
        "linkedinSkillsLabel": ", ".join(item.get("topSkills") or []) or None,
        "linkedinProfileUrl": item.get("linkedinUrl"),
        "firstName": item.get("firstName"), "lastName": item.get("lastName"),
        "toutesEcoles": [[x.get("schoolName"), x.get("degree")] for x in edu if x.get("schoolName")],
        "toutesEntreprises": list(dict.fromkeys(x.get("companyName") for x in exp if x.get("companyName"))),
    }
    for i, prefixe in ((0, ""), (1, "Previous")):
        if len(exp) > i:
            x = exp[i]
            p["companyName" if not i else "previousCompanyName"] = x.get("companyName")
            p[f"linkedin{prefixe}JobTitle"] = x.get("position")
            p[f"linkedin{prefixe}JobDateRange"] = _periode(x)
        if len(edu) > i:
            x = edu[i]
            p[f"linkedin{prefixe}SchoolName"] = x.get("schoolName")
            p[f"linkedin{prefixe}SchoolDegree"] = x.get("degree")
            p[f"linkedin{prefixe}SchoolFieldOfStudy"] = x.get("fieldOfStudy")
            p[f"linkedin{prefixe}SchoolDateRange"] = _periode(x)
    if exp or edu:
        p["linkedinParcours"] = _texte_parcours(item)
    return {k: v for k, v in p.items() if v not in (None, "", [])}


if __name__ == "__main__":
    for url, it in scraper(sys.argv[1:]).items():
        print(f"=== {url}")
        if introuvable(it):
            print("introuvable (404)")
            continue
        p = en_profil(it)
        print(p.get("linkedinHeadline") or "")
        print(p.get("linkedinParcours") or "(profil vide)")
