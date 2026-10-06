"""Recherche par nom dans Sales Navigator, pour les fiches que la recherche
web n'a pas trouvées.

La recherche web ne voit que les profils indexés par les moteurs ; la
recherche interne de LinkedIn voit aussi les profils récents, ceux dont le
nom est masqué hors réseau (« Allan B. ») et ceux dont l'adresse a changé.
Test sur 12 fondateurs en échec : ~7 retrouvés, dont 3 avec la bonne
société — la recherche web, la devinette d'adresse et Surfe : 0.

Entrée : le JSON de résultats de l'étape 3 (payload `robot.airtable maj`).
Les entrées « Non trouvé » sont cherchées par « Prénom Nom » en UN
lancement du Phantom ; le fichier est réécrit sur place, prêt à pousser.

Choix du candidat (règle de Samuel : tenter plutôt qu'enterrer — le
contrôle d'identité de l'étape 5 écarte un homonyme, et au run suivant la
fiche repart sur le candidat suivant, adresse exclue) :
  - candidats = résultats au même prénom et au même nom (initiale admise :
    « Allan B. »), hors adresses déjà exclues ;
  - un seul candidat → « Trouvé », même nom courant, même hors de France ;
  - la société du greffe dans son poste ou son entreprise → « Trouvé » ;
  - sinon le plus probable parmi ceux en France (titre de fondateur, puis
    ville du siège ou du dirigeant) → « Ambigu » ; si AUCUN n'est en
    France, « Non trouvé » (cent homonymes à l'étranger : un tirage au
    hasard).
  Ne PAS exiger la société : un fondateur du premier jour n'a souvent pas
  encore mis son profil à jour.

Usage : python3 -m robot.recherche_nom recherches.json <dossier du run>
"""

import json
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

from . import config, phantoms

CF = config.CHAMPS_FONDATEURS
METHODE = "Recherche Sales Nav"
FONDATEUR = re.compile(r"fondat|founder|pr[ée]sident|\bceo\b|\bcto\b|\bcoo\b|stealth|building|"
                       r"entrepreneur|g[ée]rant|dirigeant|cr[ée]ateur", re.I)
FORMES = {"sas", "sasu", "sarl", "eurl", "sa", "sci", "sc", "snc", "selarl", "group", "groupe"}


def _norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _slug(url: str | None) -> str:
    m = re.search(r"/in/([^/?#]+)", urllib.parse.unquote(url or ""))
    return m.group(1).lower() if m else ""


def _premier_prenom(prenom: str | None) -> str:
    return (prenom or "").split(",")[0].strip()


def _requete(c: dict) -> str:
    return f"{_premier_prenom(c.get('prenom'))} {c.get('nom') or ''}".strip()


def _meme_personne(c: dict, r: dict) -> bool:
    """Même prénom (un des prénoms du greffe) et même nom — ou son initiale,
    LinkedIn masquant le nom hors réseau (« Allan B. »)."""
    complet = _norm(r.get("fullName"))
    prenoms = {p for x in (c.get("prenom") or "").split(",") for p in _norm(x).split() if len(p) > 1}
    if not prenoms & set(_norm(r.get("firstName") or complet).split()):
        return False
    nom = _norm(c.get("nom"))
    nom_lk = _norm(r.get("lastName"))
    if nom and (nom in complet or nom.replace(" ", "") in complet.replace(" ", "")):
        return True
    morceaux = [m for m in nom.split() if len(m) >= 3]
    if morceaux and any(m in complet.split() for m in morceaux):
        return True  # nom composé partiel : « Faugeras » pour « Faugeras-Cultrera »
    return len(nom_lk) == 1 and nom.startswith(nom_lk)  # « B. » → initiale


def _societe_concorde(c: dict, r: dict) -> bool:
    soc = "".join(m for m in _norm(c.get("entreprise")).split() if m not in FORMES)
    poste = _norm(f"{r.get('companyName') or ''} {r.get('title') or ''}").replace(" ", "")
    return len(soc) >= 4 and soc in poste


def _en_france(r: dict) -> bool:
    lieu = r.get("location") or ""
    return "France" in lieu or "et périphérie" in lieu


def _score(c: dict, r: dict) -> int:
    villes = {_norm(c.get("ville")), _norm((c.get("indices") or {}).get("ville_dirigeant"))} - {""}
    lieu = _norm(r.get("location"))
    return (2 * bool(FONDATEUR.search(r.get("title") or ""))
            + 1 * any(v in lieu for v in villes))


def choisir(c: dict, resultats: list[dict], exclues: set[str]) -> tuple[str, dict] | None:
    cands = [r for r in resultats if _meme_personne(c, r)
             and _slug(r.get("defaultProfileUrl")) and _slug(r.get("defaultProfileUrl")) not in exclues]
    if not cands:
        return None
    if len(cands) == 1:
        return "Trouvé", cands[0]
    concordants = [r for r in cands if _societe_concorde(c, r)]
    if concordants:
        return "Trouvé", concordants[0]
    en_france = [r for r in cands if _en_france(r)]
    if not en_france:
        return None
    return "Ambigu", max(en_france, key=lambda r: _score(c, r))  # à égalité : l'ordre de LinkedIn


def main(f_recherches: str, dossier: str) -> None:
    d = Path(dossier)
    payload = json.load(open(f_recherches))
    contexte = {c["rec_id"]: c for c in (json.loads(l) for l in open(d / "contexte.jsonl") if l.strip())}
    exclues: dict[str, set[str]] = {}
    f_ac = d / "reliquat_a_chercher.jsonl"
    if f_ac.exists():
        for l in open(f_ac):
            if l.strip():
                x = json.loads(l)
                exclues[x["rec_id"]] = {_slug(u) for u in
                                        x.get("urls_exclues", []) + x.get("urls_perimees", [])}

    cibles = [e for e in payload if e["fields"].get(CF["statut"]) == "Non trouvé"
              and not e["fields"].get(CF["linkedin_url"]) and e["id"] in contexte]
    if not cibles:
        print("Recherche par nom : aucune fiche « Non trouvé » à chercher.")
        return
    requetes = sorted({_requete(contexte[e["id"]]) for e in cibles})
    print(f"Recherche par nom : {len(cibles)} fiches, {len(requetes)} requêtes Sales Navigator "
          f"(~{len(requetes) // 2 + 1} min)…", flush=True)
    resultats = phantoms.rechercher_noms(requetes)
    json.dump(resultats, open(d / "recherche_nom_brut.json", "w"), ensure_ascii=False)
    par_requete: dict[str, list[dict]] = {}
    for r in resultats:
        par_requete.setdefault(r.get("query"), []).append(r)

    trouves = ambigus = 0
    for e in cibles:
        c = contexte[e["id"]]
        choix = choisir(c, par_requete.get(_requete(c), []), exclues.get(e["id"], set()))
        if not choix:
            continue
        statut, r = choix
        e["fields"][CF["statut"]] = statut
        e["fields"][CF["linkedin_url"]] = "https://www.linkedin.com/in/" + _slug(r["defaultProfileUrl"])
        e["fields"][CF["methode"]] = METHODE
        trouves += statut == "Trouvé"
        ambigus += statut == "Ambigu"
        print(f"  {_requete(c)} → {statut} : {r.get('fullName')} — "
              f"{r.get('title') or '?'} / {r.get('companyName') or '?'} / {r.get('location') or '?'}")
    json.dump(payload, open(f_recherches, "w"), ensure_ascii=False)
    print(f"Recherche par nom : {trouves} trouvés, {ambigus} ambigus, "
          f"{len(cibles) - trouves - ambigus} restent « Non trouvé » — {f_recherches} mis à jour.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
