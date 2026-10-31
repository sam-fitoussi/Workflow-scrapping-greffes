"""Recherche LinkedIn par nom (Apify, sans compte LinkedIn), pour les
fiches que la recherche web n'a pas trouvées.

La recherche web ne voit que les profils indexés par les moteurs ; la
recherche interne de LinkedIn voit aussi les profils récents, ceux dont le
nom est masqué hors réseau (« Allan B. ») et ceux dont l'adresse a changé.
Test sur 12 fondateurs en échec : ~7 retrouvés, dont 3 avec la bonne
société — la recherche web, la devinette d'adresse et Surfe : 0.
Elle passait par Sales Navigator (PhantomBuster, compte LinkedIn de
Samuel) ; depuis le 31/10/2026 par Apify (robot/apify.rechercher_nom) :
mêmes résultats sur les 13 noms du test, sans exposer le compte.

Entrée : le JSON de résultats de l'étape 3 (payload `robot.airtable maj`).
Les entrées « Non trouvé » sont cherchées par prénom + nom (une recherche
par nom, 0,004 $) ; le fichier est réécrit sur place, prêt à pousser.
Quand plusieurs homonymes sortent, une 2e recherche limitée à la France
dit lesquels y vivent (Apify ne donne souvent que la ville : « Nice »,
« Fasano »). Si la recherche échoue (clé absente, panne), ces entrées
passent en « À chercher » : jamais enterrées sans avoir été cherchées.

Choix du candidat (règle de Samuel : tenter plutôt qu'enterrer — le
contrôle d'identité de l'étape 5 écarte un homonyme, et au run suivant la
fiche repart sur le candidat suivant, adresse exclue) :
  - candidats = résultats au même prénom et au même nom (initiale admise :
    « Allan B. »), hors adresses déjà exclues ;
  - un seul candidat → « Trouvé », même nom courant, même hors de France ;
  - la société du greffe dans son poste ou son entreprise → « Trouvé » ;
  - sinon le plus probable (en France, puis titre de fondateur, puis ville
    du siège ou du dirigeant) → « Ambigu », dès qu'il est un peu plus
    probable que les autres, ou s'il reste au plus 3 candidats
    indiscernables (une chance sur 3 au moins : on tente, le 1er de
    LinkedIn). Au-delà (beaucoup d'homonymes indiscernables) : « Non
    trouvé ».
  Ne PAS exiger la société : un fondateur du premier jour n'a souvent pas
  encore mis son profil à jour.

Usage : python3 -m robot.recherche_nom recherches.json <dossier du run>
"""

import json
import re
import sys
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import apify, config

CF = config.CHAMPS_FONDATEURS
METHODE = "Recherche par nom"
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
    return bool(r.get("en_france")) or "France" in lieu or "et périphérie" in lieu


def _score(c: dict, r: dict) -> int:
    villes = {_norm(c.get("ville")), _norm((c.get("indices") or {}).get("ville_dirigeant"))} - {""}
    lieu = _norm(r.get("location"))
    return (3 * _en_france(r)
            + 2 * bool(FONDATEUR.search(r.get("title") or ""))
            + 1 * any(v in lieu for v in villes))


def _format(it: dict) -> dict:
    """Profil court Apify → champs lus par choisir() (format historique)."""
    nom = (it.get("name") or "").strip()
    return {"fullName": nom, "firstName": None,
            "lastName": nom.split()[-1] if nom else None,
            "title": it.get("position") if it.get("position") != "--" else None,
            "companyName": None,
            "location": (it.get("location") or {}).get("linkedinText"),
            "defaultProfileUrl": it.get("linkedinUrl"), "en_france": False}


def _chercher(c: dict) -> list[dict] | Exception:
    """Résultats de la recherche par nom d'une fiche ; plusieurs homonymes :
    2e recherche limitée à la France pour savoir lesquels y vivent."""
    prenom, nom = _premier_prenom(c.get("prenom")), (c.get("nom") or "").strip()
    try:
        res = [_format(it) for it in apify.rechercher_nom(prenom, nom)]
        if sum(_meme_personne(c, r) for r in res) > 1:
            fr = {_slug(it.get("linkedinUrl")) for it in apify.rechercher_nom(prenom, nom, france=True)}
            for r in res:
                r["en_france"] = _slug(r["defaultProfileUrl"]) in fr
        return res
    except Exception as e:  # clé absente, panne : la fiche reste « À chercher »
        return e


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
    notes = sorted((_score(c, r) for r in cands), reverse=True)
    if notes[0] > notes[1] or notes.count(notes[0]) <= 3:
        return "Ambigu", max(cands, key=lambda r: _score(c, r))  # à égalité : l'ordre de LinkedIn
    return None


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
    par_requete: dict[str, dict] = {}
    for e in cibles:
        par_requete.setdefault(_requete(contexte[e["id"]]), contexte[e["id"]])
    print(f"Recherche par nom : {len(cibles)} fiches, {len(par_requete)} recherches LinkedIn (Apify)…",
          flush=True)
    resultats: dict[str, list[dict]] = {}
    echecs: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for q, res in zip(par_requete, pool.map(_chercher, par_requete.values())):
            if isinstance(res, Exception):
                echecs[q] = str(res)[:150]
            else:
                resultats[q] = res
    json.dump(resultats, open(d / "recherche_nom_brut.json", "w"), ensure_ascii=False)
    if echecs:
        # Recherche impossible (clé absente, panne) : ne JAMAIS enterrer ces
        # fiches en « Non trouvé » sans avoir cherché — elles restent « À
        # chercher » et repartent au run suivant.
        for e in cibles:
            if _requete(contexte[e["id"]]) in echecs:
                e["fields"][CF["statut"]] = "À chercher"
        print(f"⛔ Recherche par nom impossible pour {len(echecs)} nom(s) "
              f"({next(iter(echecs.values()))}) : fiches laissées « À chercher » (reprises au "
              "prochain run). À signaler EN TÊTE du rapport.")

    trouves = ambigus = 0
    for e in cibles:
        c = contexte[e["id"]]
        if _requete(c) in echecs:
            continue
        choix = choisir(c, resultats.get(_requete(c), []), exclues.get(e["id"], set()))
        if not choix:
            continue
        statut, r = choix
        e["fields"][CF["statut"]] = statut
        e["fields"][CF["linkedin_url"]] = ("https://www.linkedin.com/in/"
                                           + urllib.parse.quote(_slug(r["defaultProfileUrl"])))
        e["fields"][CF["methode"]] = METHODE
        trouves += statut == "Trouvé"
        ambigus += statut == "Ambigu"
        print(f"  {_requete(c)} → {statut} : {r.get('fullName')} — "
              f"{r.get('title') or '?'} / {r.get('companyName') or '?'} / {r.get('location') or '?'}")
    json.dump(payload, open(f_recherches, "w"), ensure_ascii=False)
    restent = sum(1 for e in cibles if e["fields"].get(CF["statut"]) == "Non trouvé")
    print(f"Recherche par nom : {trouves} trouvés, {ambigus} ambigus, {restent} restent "
          f"« Non trouvé » — {f_recherches} mis à jour.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
