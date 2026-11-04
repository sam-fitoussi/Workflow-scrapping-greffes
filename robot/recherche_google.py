"""Recherche Google via Apify — filet joué JUSTE APRÈS la recherche web du
modèle, avant la recherche LinkedIn par nom (robot/recherche_nom.py).

Pourquoi : l'outil WebSearch de la session est biaisé US et refuse
certaines requêtes sur des noms de personnes ; Google (google.fr, en
français) indexe bien mieux les profils LinkedIn français, et ses extraits
montrent souvent l'employeur ACTUEL. Test du 04/11/2026 : Rémi Dumas
(RentLabs), introuvable par WebSearch et mal attribué par la recherche par
nom, sort en tête sur « site:linkedin.com/in "Rémi Dumas" RentLabs ».

Pour chaque fiche « Non trouvé » sans URL : deux requêtes (0,0025 $ chacune)
  - site:linkedin.com/in "Prénom Nom" (et la variante nom d'usage /
    prénom usuel quand elle existe) ;
  - site:linkedin.com/in "Prénom Nom" <société> (fait remonter le profil
    qui cite déjà la nouvelle société parmi les homonymes).
Les résultats de Google varient d'un appel à l'autre et sont parfois
maigres (1 résultat sur un nom courant) : c'est un filet, pas une source
exhaustive — la recherche par nom passe derrière.
Choix du candidat — filet PRÉCIS, pas large (Google renvoie parfois un
seul résultat sur un nom courant : ce n'est pas « un seul profil à ce
nom », la recherche par nom voit l'index LinkedIn complet) :
  - la société du greffe dans le titre ou l'extrait → « Trouvé » ;
  - un seul candidat ET la ville du dirigeant ou du siège dans son
    « Lieu : » → « Ambigu » (le contrôle de l'étape 5 tranche) ;
  - sinon la fiche reste « Non trouvé » : la recherche par nom puis les
    filets société (robot/recherche_societe.py) prennent le relais.

Méthode écrite : « Recherche Google ». Panne Apify : les fiches restent
« Non trouvé » (la recherche par nom les reprend juste après).

Usage : python3 -m robot.recherche_google recherches.json <dossier du run>
"""

import json
import re
import sys
import urllib.parse
from pathlib import Path

from . import apify, config
from .recherche_nom import (FORMES, _meme_personne, _norm, _premier_prenom, _slug,
                            _societe_concorde, charger_exclues, url_propre)

CF = config.CHAMPS_FONDATEURS
METHODE = "Recherche Google"
LIEU = re.compile(r"Lieu\s*:\s*([^·|.]+)", re.I)


def societe_nette(denomination: str | None) -> str:
    """Dénomination sans forme juridique, pour une requête entre guillemets."""
    mots = [m for m in re.split(r"\s+", (denomination or "").strip())
            if _norm(m) not in FORMES and m]
    return " ".join(mots).strip(" ,.-")


def variantes_nom(c: dict) -> list[tuple[str, str]]:
    ind = c.get("indices") or {}
    prenoms = [p for p in dict.fromkeys([ind.get("prenom_usuel"), _premier_prenom(c.get("prenom"))]) if p]
    noms = [n for n in dict.fromkeys([ind.get("nom_usage"), c.get("nom")]) if n]
    return [(p.strip().title(), n.strip().title()) for p in prenoms[:1] for n in noms[:2]] + \
        [(p.strip().title(), noms[0].strip().title()) for p in prenoms[1:2] if noms]


def requetes(c: dict) -> list[str]:
    noms = variantes_nom(c)
    qs = [f'site:linkedin.com/in "{p} {n}"' for p, n in noms]
    soc = societe_nette(c.get("entreprise"))
    if len(_norm(soc)) >= 4 and noms:
        # société SANS guillemets : entre guillemets avec le seul nom de
        # famille, Google ne renvoie presque rien (test du 04/11)
        qs.append(f'site:linkedin.com/in "{noms[0][0]} {noms[0][1]}" {soc}')
    return list(dict.fromkeys(qs))


def depuis_google(o: dict) -> dict | None:
    """Résultat organique Google → candidat au format de choisir()."""
    url = o.get("url") or ""
    if "linkedin.com/in/" not in url:
        return None
    titre = o.get("title") or ""
    nom = ""
    site = o.get("websiteTitle") or ""
    if "·" in site:
        nom = site.split("·", 1)[1].strip()
    if not nom:
        nom = re.split(r"\s+[-–|]\s+", titre)[0].strip()
    desc = o.get("description") or ""
    m = LIEU.search(desc)
    lieu = m.group(1).strip() if m else ""
    hote = urllib.parse.urlparse(url).hostname or ""
    return {"fullName": nom, "firstName": None,
            "lastName": nom.split()[-1] if nom else None,
            "title": titre, "companyName": desc,
            "location": lieu, "defaultProfileUrl": url,
            "en_france": hote.startswith("fr.") or "France" in lieu or "France" in desc}


def candidats(c: dict, resultats: dict[str, list[dict]]) -> list[dict]:
    """Candidats au nom du greffe ; un profil sorti sur plusieurs requêtes
    cumule ses extraits (la société n'apparaît souvent que dans l'extrait
    de la requête qui la cite)."""
    par_slug: dict[str, dict] = {}
    for q in requetes(c):
        for o in resultats.get(q, []):
            r = depuis_google(o)
            if not (r and _meme_personne(c, r)):
                continue
            s = _slug(r["defaultProfileUrl"])
            if s in par_slug:
                vu = par_slug[s]
                vu["companyName"] = f"{vu['companyName']} {r['companyName']}"
                vu["location"] = vu["location"] or r["location"]
                vu["en_france"] = vu["en_france"] or r["en_france"]
            else:
                par_slug[s] = r
    return list(par_slug.values())


def choisir_google(c: dict, cands: list[dict], exclues: set[str]) -> tuple[str, dict] | None:
    cands = [r for r in cands if _slug(r["defaultProfileUrl"]) not in exclues]
    concordants = [r for r in cands if _societe_concorde(c, r)]
    if concordants:
        return "Trouvé", concordants[0]
    villes = {_norm(c.get("ville")), _norm((c.get("indices") or {}).get("ville_dirigeant"))} - {""}
    lieu = _norm(f"{cands[0]['location']} {cands[0]['companyName']}") if cands else ""
    if len(cands) == 1 and any(v in lieu for v in villes):
        return "Ambigu", cands[0]
    return None


def main(f_recherches: str, dossier: str) -> None:
    d = Path(dossier)
    payload = json.load(open(f_recherches))
    contexte = {c["rec_id"]: c for c in (json.loads(l) for l in open(d / "contexte.jsonl") if l.strip())}
    exclues = charger_exclues(d)
    cibles = [e for e in payload if e["fields"].get(CF["statut"]) == "Non trouvé"
              and not e["fields"].get(CF["linkedin_url"]) and e["id"] in contexte]
    if not cibles:
        print("Recherche Google : aucune fiche « Non trouvé » à chercher.")
        return
    toutes = list(dict.fromkeys(q for e in cibles for q in requetes(contexte[e["id"]])))
    print(f"Recherche Google : {len(cibles)} fiches, {len(toutes)} requêtes (Apify, "
          f"~{len(toutes) * apify.PRIX_GOOGLE:.2f} $)…", flush=True)
    resultats: dict[str, list[dict]] = {}
    try:
        for i in range(0, len(toutes), 40):
            resultats.update(apify.google(toutes[i:i + 40]))
    except Exception as e:
        print(f"⚠️ Recherche Google impossible ({str(e)[:150]}) : fiches laissées « Non trouvé », "
              "la recherche par nom les reprend. À mentionner dans le rapport.")
    json.dump(resultats, open(d / "recherche_google_brut.json", "w"), ensure_ascii=False)

    trouves = ambigus = 0
    for e in cibles:
        c = contexte[e["id"]]
        choix = choisir_google(c, candidats(c, resultats), exclues.get(e["id"], set()))
        if not choix:
            continue
        statut, r = choix
        e["fields"][CF["statut"]] = statut
        e["fields"][CF["linkedin_url"]] = url_propre(r["defaultProfileUrl"])
        e["fields"][CF["methode"]] = METHODE
        trouves += statut == "Trouvé"
        ambigus += statut == "Ambigu"
        print(f"  {c.get('prenom')} {c.get('nom')} ({c.get('entreprise')}) → {statut} : "
              f"{r['fullName']} — {r['title'][:80]}")
    json.dump(payload, open(f_recherches, "w"), ensure_ascii=False)
    restent = sum(1 for e in cibles if e["fields"].get(CF["statut"]) == "Non trouvé")
    print(f"Recherche Google : {trouves} trouvés, {ambigus} ambigus, {restent} restent "
          f"« Non trouvé » — {f_recherches} mis à jour.")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
