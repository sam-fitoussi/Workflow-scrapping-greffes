"""Parcours COMPLET d'un profil via Crustdata, en complément du scraper.

Le Profile Scraper PhantomBuster ne remonte que le poste actuel, le poste
précédent et les deux écoles les plus récentes : un passage chez Google il
y a trois postes, ou une prépa avant Polytechnique, échappait à la Note IA.
Crustdata (POST /person/enrich, base indexée, profils rafraîchis au moins
tous les 30 jours) renvoie le parcours daté complet, descriptions des
boîtes comprises. Le profil scrapé reste la source fraîche du jour 0.

Choix de Samuel : Crustdata plutôt que Context.dev (test du 27/10 : Context
vide ou en retard de mois sur 2 profils sur 2, Crustdata complet et à jour)
— 1 crédit (0,30 $) par profil, seuls les profils envoyés à la Note IA
(~200/mois). Garde-fous : config.CRUSTDATA_MAX_PAR_RUN par run, arrêt sous
config.CRUSTDATA_RESERVE crédits ou à la première erreur de crédits.
Facultatif : sans clé CRUSTDATA_API_KEY, la Note IA tourne comme avant.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import config

BASE = "https://api.crustdata.com"
LOT = 25  # profils max par appel


class CreditsEpuises(Exception):
    pass


def slug(url: str | None) -> str:
    m = re.search(r"/in/([^/?#]+)", urllib.parse.unquote(url or ""))
    return m.group(1).lower().rstrip("/") if m else ""


def _appel(chemin: str, payload: dict | None = None) -> object:
    req = urllib.request.Request(
        f"{BASE}/{chemin}", data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {config.CRUSTDATA_API_KEY}",
                 "x-api-version": "2025-11-01", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        corps = e.read().decode(errors="replace")[:200]
        if e.code == 402 or "credit" in corps.lower():
            raise CreditsEpuises(corps)
        raise RuntimeError(f"Crustdata HTTP {e.code} : {corps}")


def credits_restants() -> float:
    """Solde du compte (appel gratuit)."""
    return float(_appel("account/credits")["account"]["credits"])


def enrichir(urls: list[str]) -> dict[str, dict]:
    """{slug LinkedIn: person_data} pour les profils trouvés (25 par appel)."""
    trouves = {}
    for i in range(0, len(urls), LOT):
        rep = _appel("person/enrich", {
            "professional_network_profile_urls": urls[i:i + LOT],
            "fields": ["basic_profile", "experience", "education", "skills"]})
        for item in rep if isinstance(rep, list) else []:
            m = (item.get("matches") or [{}])[0]
            if (item.get("match_status") == "matched" and m.get("person_data")
                    and (m.get("confidence_score") or 0) >= 0.9):
                trouves[slug(item.get("matched_on"))] = m["person_data"]
    return trouves


def _mois(d: str | None) -> str:
    return f"{d[5:7]}/{d[:4]}" if d and len(d) >= 7 else "?"


def texte(p: dict) -> str | None:
    """Parcours compact pour le prompt de la Note IA (None si vide)."""
    b = p.get("basic_profile") or {}
    e = (p.get("experience") or {}).get("employment_details") or {}
    postes = sorted((e.get("current") or []) + (e.get("past") or []),
                    key=lambda x: x.get("start_date") or "", reverse=True)
    ecoles = (p.get("education") or {}).get("schools") or []
    if not postes and not ecoles:
        return None
    lignes = []
    if b.get("headline"):
        lignes.append(f"Titre : {b['headline'][:300]}")
    if b.get("summary"):
        lignes.append(f"À propos : {b['summary'][:600]}")
    lignes.append("Expériences :")
    for x in postes[:25]:
        fin = _mois(x.get("end_date")) if x.get("end_date") else "aujourd'hui"
        ligne = f"- {x.get('title') or '?'} @ {x.get('name') or '?'} ({_mois(x.get('start_date'))} → {fin})"
        if x.get("description"):
            ligne += f" : {x['description'][:200]}"
        elif x.get("company_description"):
            ligne += f" [boîte : {x['company_description'][:150]}]"
        lignes.append(ligne)
    if ecoles:
        lignes.append("Formation :")
    for x in ecoles[:10]:
        diplome = ", ".join(v for v in (x.get("degree"), x.get("field_of_study")) if v)
        ligne = f"- {x.get('school') or '?'}" + (f" — {diplome}" if diplome else "")
        ligne += f" ({x.get('start_year') or '?'} → {x.get('end_year') or '?'})"
        extra = " ".join(v for v in (x.get("description"), x.get("activities_and_societies")) if v)
        if extra:
            ligne += f" : {extra[:200]}"
        lignes.append(ligne)
    competences = (p.get("skills") or {}).get("professional_network_skills") or []
    if competences:
        lignes.append("Compétences : " + ", ".join(competences[:25]))
    return "\n".join(lignes)[:6000]
