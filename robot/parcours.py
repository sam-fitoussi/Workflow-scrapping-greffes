"""Parcours COMPLET d'un profil via Context.dev, en complément du scraper.

Le Profile Scraper PhantomBuster ne remonte que le poste actuel, le poste
précédent et les deux écoles les plus récentes : un passage chez Google il
y a trois postes, ou une prépa avant Polytechnique, échappait à la Note IA.
Context.dev (people/enrich par URL LinkedIn) renvoie le parcours daté
complet — mais avec des semaines de retard (le nouveau projet n'y figure
souvent pas : le profil scrapé reste la source fraîche) et parfois vide.

Seuls les profils envoyés à la Note IA sont enrichis (20 crédits chacun,
~200/mois sur le plan Developer de 10 000 crédits partagé avec les skills).
Garde-fous : config.CONTEXT_MAX_PAR_RUN par run, arrêt sous
config.CONTEXT_RESERVE crédits restants ou à la première erreur de crédits.
Facultatif : sans clé CONTEXT_DEV_API_KEY, la Note IA tourne comme avant.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import config

URL = "https://api.context.dev/v1/people/enrich"


class CreditsEpuises(Exception):
    pass


def _slug(url: str | None) -> str:
    m = re.search(r"/in/([^/?#]+)", urllib.parse.unquote(url or ""))
    return m.group(1).lower().rstrip("/") if m else ""


def enrichir(url_linkedin: str) -> tuple[dict | None, int | None]:
    """(personne Context.dev ou None, crédits restants ou None)."""
    req = urllib.request.Request(URL, data=json.dumps({
        "social_urls": [url_linkedin], "tags": ["robot-pappers"],
        "timeoutOpts": {"milliseconds": 60000, "behavior": "fail"},
    }).encode(), headers={"Authorization": f"Bearer {config.CONTEXT_DEV_API_KEY}",
                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        corps = e.read().decode(errors="replace")[:200]
        if e.code in (401, 402) and ("USAGE" in corps or "credit" in corps.lower()):
            raise CreditsEpuises(corps)
        raise RuntimeError(f"Context.dev HTTP {e.code} : {corps}")
    restants = (d.get("key_metadata") or {}).get("credits_remaining")
    m = d.get("match") or {}
    p = m.get("person")
    # Même personne : URL fournie => score ~99 ; on vérifie quand même le slug
    if (m.get("status") != "candidate" or (m.get("score") or 0) < 90 or not p
            or _slug(url_linkedin) not in {_slug(u) for u in p.get("social_urls") or []}):
        return None, restants
    if not (p.get("experience") or p.get("education")):
        return None, restants  # profil connu mais vide : rien à ajouter
    return p, restants


def _date(d: dict | None) -> str:
    if not d or not d.get("year"):
        return "?"
    return f"{d['month']:02d}/{d['year']}" if d.get("month") else str(d["year"])


def texte(p: dict) -> str:
    """Parcours compact pour le prompt de la Note IA."""
    lignes = []
    if p.get("bio"):
        lignes.append(f"Bio : {p['bio'][:400]}")
    for x in (p.get("experience") or [])[:25]:
        org = (x.get("organization") or {}).get("name") or "?"
        fin = "aujourd'hui" if x.get("is_current") else _date(x.get("end_date"))
        ligne = f"- {x.get('title') or '?'} @ {org} ({_date(x.get('start_date'))} → {fin})"
        if x.get("description"):
            ligne += f" : {x['description'][:200]}"
        lignes.append(ligne)
    if p.get("education"):
        lignes.append("Formation :")
    for x in (p.get("education") or [])[:10]:
        inst = (x.get("institution") or {}).get("name") or "?"
        diplome = ", ".join(v for v in (x.get("degree"), x.get("field_of_study")) if v)
        ligne = f"- {inst}" + (f" — {diplome}" if diplome else "")
        ligne += f" ({_date(x.get('start_date'))} → {_date(x.get('end_date'))})"
        if x.get("description"):
            ligne += f" : {x['description'][:200]}"
        lignes.append(ligne)
    return "\n".join(lignes)[:6000]
