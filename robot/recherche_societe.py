"""Filets « société » et « homonymes » — joués APRÈS la recherche LinkedIn
par nom (robot/recherche_nom.py), sur les fiches restées « Non trouvé ».

Constat du 04/11/2026 : 30 % des fondateurs (1 252 / 4 105) finissaient
« Non trouvé », dont 202 avec un cofondateur trouvé dans la même société,
et une bonne part noyés dans les homonymes (au-delà de 3 candidats
indiscernables, la recherche par nom renonce). Trois filets, du plus sûr
au plus coûteux, chacun ne jouant que sur ce que le précédent n'a pas
résolu :

  Filet A — Google par nom de SOCIÉTÉ (0,0025 $ la requête) :
    site:linkedin.com/in "<société>" → un profil au nom du fondateur qui
    cite la société (titre ou extrait) → « Trouvé ». La même passe cherche
    site:linkedin.com/company "<société>" : la page société sert au filet B.

  Filet B — page LinkedIn de la société → ses membres (~0,03 $) :
    la page vient du profil d'un COFONDATEUR déjà trouvé (son expérience
    chez la société porte l'adresse de la page — profil scrapé, versé
    dans resultats.jsonl, donc pas re-scrapé à la vague 2) ou, à défaut,
    du filet A. Les personnes rattachées à la page (acteur Apify
    « company employees ») sont comparées au nom du greffe — nom masqué
    (« Allan B. ») admis. Le membre retenu est scrapé (son adresse
    publique et son profil complet, versés dans resultats.jsonl) →
    « Trouvé ».

  Filet C — homonymes : quand la recherche par nom a renvoyé plus de 3
    homonymes indiscernables, les premiers (France d'abord,
    config.FILET_HOMONYMES_CANDIDATS au plus) sont scrapés et départagés
    sur pièces : société du greffe dans le parcours (→ « Trouvé »), ville
    du dirigeant ou du siège, employeur ou école commun avec un
    cofondateur, dates du parcours compatibles avec la naissance du greffe
    (une contradiction de 10 ans élimine, comme au contrôle d'identité).
    Le candidat retenu doit porter au moins un signal d'identité et
    devancer strictement les autres → « Ambigu » (le contrôle de l'étape 5
    tranche, comme toujours) ; sinon la fiche reste « Non trouvé ». Son
    profil est versé dans resultats.jsonl.

Garde-fous : config.FILET_SOCIETE_MAX_PAGES pages société et
config.FILET_HOMONYMES_MAX_FICHES fiches homonymes par run ; les profils
scrapés ici comptent dans le plafond quotidien (config.SCRAPE_DAILY_CAP).
Panne Apify : les fiches restent « Non trouvé », rien n'est cassé (filet
facultatif, la recherche est déjà faite).

Usage : python3 -m robot.recherche_societe recherches.json <dossier du run> [préfixe resultats]
  (préfixe par défaut : <dossier>/resultats — le MÊME que scraping_lot)
"""

import json
import re
import sys
from pathlib import Path

from . import apify, config
from .recherche_google import depuis_google, societe_nette
from .recherche_nom import (_meme_personne, _norm, _requete, _slug, FONDATEUR,
                            charger_exclues, url_propre)
from .scraping_lot import statut_de

CF = config.CHAMPS_FONDATEURS
GENERIQUES = {"freelance", "independant", "self employed", "stealth", "confidential",
              "linkedin", "france", "consultant", "auto entrepreneur", "micro entreprise"}


def _compact(s: str | None) -> str:
    return _norm(s).replace(" ", "")


def _cite_societe(soc: str, *textes: str | None) -> bool:
    cle = _compact(soc)
    return len(cle) >= 4 and any(cle in _compact(t) for t in textes if t)


def _page_depuis_google(soc: str, resultats: list[dict]) -> str | None:
    cle = _compact(soc)
    for o in resultats:
        url = o.get("url") or ""
        m = re.search(r"linkedin\.com/company/([^/?#]+)", url)
        if m and cle and _compact(re.split(r"\s+[|:–-]\s+", o.get("title") or "")[0]) == cle:
            return f"https://www.linkedin.com/company/{m.group(1)}/"
    return None


def _page_depuis_profil(soc: str, item: dict) -> str | None:
    for x in item.get("experience") or []:
        if x.get("companyLinkedinUrl") and _cite_societe(soc, x.get("companyName")):
            return x["companyLinkedinUrl"]
    return None


def _naissance(c: dict) -> int | None:
    n = (c.get("indices") or {}).get("naissance") or ""
    return int(n[:4]) if n[:4].isdigit() else None


def _premiere_annee(item: dict) -> int | None:
    annees = [(x.get("startDate") or {}).get("year")
              for cle in ("education", "experience") for x in item.get(cle) or []]
    annees = [a for a in annees if isinstance(a, int) and a > 1940]
    return min(annees) if annees else None


def _ensembles(item: dict) -> tuple[set[str], set[str]]:
    ent = {_norm(x.get("companyName")) for x in item.get("experience") or []} - {""} - GENERIQUES
    ecoles = {_norm(x.get("schoolName")) for x in item.get("education") or []} - {""}
    return ent, ecoles


def evaluer(c: dict, item: dict, equipe: list[dict]) -> tuple[int, bool, list[str]]:
    """(points, société citée, motifs) pour un homonyme scrapé ; points < 0
    = contradiction de dates rédhibitoire."""
    soc = societe_nette(c.get("entreprise"))
    motifs, points = [], 0
    exp = item.get("experience") or []
    cite = _cite_societe(soc, item.get("headline"),
                         *[f"{x.get('companyName') or ''} {x.get('position') or ''}" for x in exp])
    if cite:
        points += 5
        motifs.append("société du greffe dans le parcours")
    naissance, debut = _naissance(c), _premiere_annee(item)
    if naissance and debut:
        age = debut - naissance
        if age <= 8:  # parcours commencé à 8 ans : ~10 ans d'écart, autre personne
            return -1, cite, [f"parcours dès {debut}, né en {naissance}"]
        if age < 15:
            points -= 2
        elif age <= 23:
            points += 1
            motifs.append("dates cohérentes")
    villes = {_norm(c.get("ville")), _norm((c.get("indices") or {}).get("ville_dirigeant"))} - {""}
    lieu = _norm((item.get("location") or {}).get("linkedinText"))
    if any(v and v in lieu for v in villes):
        points += 2
        motifs.append("même ville")
    if ((item.get("location") or {}).get("countryCode") or "").upper() == "FR":
        points += 1
    ent, ecoles = _ensembles(item)
    for coll in equipe:
        e2, s2 = _ensembles(coll)
        if (ent & e2) or (ecoles & s2):
            points += 3
            motifs.append("point commun avec un cofondateur")
            break
    if FONDATEUR.search(f"{item.get('headline') or ''} {exp[0].get('position') if exp else ''}"):
        points += 1
    return points, cite, motifs


def main(f_recherches: str, dossier: str, prefixe: str | None = None) -> None:
    d = Path(dossier)
    prefixe = prefixe or str(d / "resultats")
    f_res = Path(f"{prefixe}.jsonl")
    payload = json.load(open(f_recherches))
    contexte = {c["rec_id"]: c for c in (json.loads(l) for l in open(d / "contexte.jsonl") if l.strip())}
    exclues = charger_exclues(d)
    par_id = {e["id"]: e for e in payload}
    cibles = [e for e in payload if e["fields"].get(CF["statut"]) == "Non trouvé"
              and not e["fields"].get(CF["linkedin_url"]) and e["id"] in contexte]
    if not cibles:
        print("Filets société : aucune fiche « Non trouvé ».")
        return
    deja = {json.loads(l)["rec_id"] for l in open(f_res) if l.strip()} if f_res.exists() else set()
    # La vague 1 (reliquat) peut tourner en tâche de fond dans le même
    # resultats.jsonl : ses fiches ne sont jamais versées une 2e fois ici.
    f_v1 = d / "reliquat_scrape.jsonl"
    if f_v1.exists():
        deja |= {json.loads(l)["rec_id"] for l in open(f_v1) if l.strip()}
    a_scraper = sum(1 for e in payload if e["fields"].get(CF["linkedin_url"]) and e["id"] not in deja)
    budget = max(0, config.SCRAPE_DAILY_CAP - len(deja) - a_scraper)
    stats = {"A": 0, "B": 0, "C": 0}
    nouveaux: list[dict] = []  # lignes à verser dans resultats.jsonl
    cout = 0.0

    def verser(rec_id: str, url: str, item: dict) -> None:
        statut, extra = statut_de(item)
        nouveaux.append({"rec_id": rec_id, "url": url, "statut": statut, **extra})
        deja.add(rec_id)

    def attribuer(e: dict, statut: str, url: str, methode: str, filet: str) -> None:
        c = contexte[e["id"]]
        e["fields"][CF["statut"]] = statut
        e["fields"][CF["linkedin_url"]] = url
        e["fields"][CF["methode"]] = methode
        stats[filet] += 1
        print(f"  [{filet}] {c.get('prenom')} {c.get('nom')} ({c.get('entreprise')}) → {statut} : {url}")

    def ouverts() -> list[dict]:
        return [e for e in cibles if e["fields"].get(CF["statut"]) == "Non trouvé"]

    # ---------- Filet A : Google par nom de société ----------
    societes = {}
    for e in cibles:
        c = contexte[e["id"]]
        soc = societe_nette(c.get("entreprise"))
        if len(_compact(soc)) >= 4:
            societes.setdefault(c.get("siren") or soc, soc)
    qs = [q for soc in societes.values()
          for q in (f'site:linkedin.com/in "{soc}"', f'site:linkedin.com/company "{soc}"')]
    google: dict[str, list[dict]] = {}
    try:
        for i in range(0, len(qs), 40):
            google.update(apify.google(qs[i:i + 40]))
        cout += len(qs) * apify.PRIX_GOOGLE
    except Exception as ex:
        print(f"⚠️ Filet A (Google société) indisponible : {str(ex)[:150]}")
    for e in ouverts():
        c = contexte[e["id"]]
        soc = societe_nette(c.get("entreprise"))
        for o in google.get(f'site:linkedin.com/in "{soc}"', []):
            r = depuis_google(o)
            if (r and _meme_personne(c, r) and _slug(r["defaultProfileUrl"]) not in exclues.get(e["id"], set())
                    and _cite_societe(soc, r["title"], r["companyName"])):
                attribuer(e, "Trouvé", url_propre(r["defaultProfileUrl"]), "Filet société (Google)", "A")
                break

    # ---------- Profils des cofondateurs trouvés (pages société + recoupement) ----------
    equipes: dict[str, list[str]] = {}
    for c in contexte.values():
        if c.get("siren"):
            equipes.setdefault(c["siren"], []).append(c["rec_id"])
    sirens_ouverts = {contexte[e["id"]].get("siren") for e in ouverts()} - {None}
    cofond = {rid: par_id[rid]["fields"][CF["linkedin_url"]] for s in sirens_ouverts
              for rid in equipes.get(s, []) if rid in par_id and par_id[rid]["fields"].get(CF["linkedin_url"])}
    profils_cofond: dict[str, dict] = {}
    if cofond and budget:
        urls = list(cofond.values())[:budget]
        try:
            items = apify.scraper(urls)
            cout += len(urls) * apify.PRIX_PROFIL
            for rid, url in cofond.items():
                it = items.get(url)
                if it and not apify.introuvable(it):
                    profils_cofond[rid] = it
                    if rid not in deja:
                        verser(rid, url, it)
            budget -= len(urls)
        except Exception as ex:
            print(f"⚠️ Scraping des cofondateurs impossible : {str(ex)[:150]}")

    # ---------- Filet B : membres de la page société ----------
    pages_vues = 0
    for siren in sorted(sirens_ouverts):
        restant = [e for e in ouverts() if contexte[e["id"]].get("siren") == siren]
        if not restant or pages_vues >= config.FILET_SOCIETE_MAX_PAGES or budget <= 0:
            continue
        soc = societe_nette(contexte[restant[0]["id"]].get("entreprise"))
        page = next((p for rid in equipes.get(siren, []) if rid in profils_cofond
                     for p in [_page_depuis_profil(soc, profils_cofond[rid])] if p), None) \
            or _page_depuis_google(soc, google.get(f'site:linkedin.com/company "{soc}"', []))
        if not page:
            continue
        pages_vues += 1
        try:
            membres = apify.employes(page)
            cout += 0.02 + 0.004 * len(membres)
        except Exception as ex:
            print(f"⚠️ Filet B indisponible ({page}) : {str(ex)[:150]}")
            continue
        for e in restant:
            c = contexte[e["id"]]
            for m in membres:
                nom = f"{m.get('firstName') or ''} {m.get('lastName') or ''}".strip()
                r = {"fullName": nom, "firstName": m.get("firstName"), "lastName": m.get("lastName")}
                if not _meme_personne(c, r) or budget <= 0:
                    continue
                try:  # adresse interne (/in/ACwAA…) → profil public complet
                    it = next(iter(apify.scraper([m["linkedinUrl"]]).values()), None)
                    cout += apify.PRIX_PROFIL
                    budget -= 1
                except Exception:
                    it = None
                url = (it or {}).get("linkedinUrl")
                if not url or apify.introuvable(it) or _slug(url) in exclues.get(e["id"], set()):
                    continue
                url = url_propre(url)
                verser(e["id"], url, it)
                attribuer(e, "Trouvé", url, "Filet société (page LinkedIn)", "B")
                break

    # ---------- Filet C : départage des homonymes sur pièces ----------
    try:
        brut = json.load(open(d / "recherche_nom_brut.json"))
    except FileNotFoundError:
        brut = {}
    lots = []
    for e in ouverts():
        c = contexte[e["id"]]
        cands = [r for r in brut.get(_requete(c), []) if _meme_personne(c, r)
                 and _slug(r.get("defaultProfileUrl")) not in exclues.get(e["id"], set())]
        if len(cands) > 3:  # ≤ 3 : la recherche par nom a déjà tenté le plus probable
            cands.sort(key=lambda r: not r.get("en_france"))
            lots.append((e, cands[:config.FILET_HOMONYMES_CANDIDATS]))
    lots = lots[:config.FILET_HOMONYMES_MAX_FICHES]
    urls = list(dict.fromkeys(r["defaultProfileUrl"] for _, cs in lots for r in cs))[:max(0, budget)]
    items = {}
    if urls:
        try:
            for i in range(0, len(urls), config.SCRAPE_LOT * 2):
                items.update(apify.scraper(urls[i:i + config.SCRAPE_LOT * 2]))
            cout += len(urls) * apify.PRIX_PROFIL
        except Exception as ex:
            print(f"⚠️ Filet C (homonymes) indisponible : {str(ex)[:150]}")
    for e, cands in lots:
        c = contexte[e["id"]]
        equipe = [profils_cofond[rid] for rid in equipes.get(c.get("siren"), [])
                  if rid in profils_cofond and rid != e["id"]]
        notes = []
        for r in cands:
            it = items.get(r["defaultProfileUrl"])
            if it and not apify.introuvable(it) and apify.en_profil(it):
                pts, cite, motifs = evaluer(c, it, equipe)
                if pts >= 0:
                    notes.append((pts, cite, motifs, r["defaultProfileUrl"], it))
        notes.sort(key=lambda n: -n[0])
        if not notes:
            continue
        meilleur = notes[0]
        signal = meilleur[1] or any(m in ("même ville", "point commun avec un cofondateur")
                                    for m in meilleur[2])
        if signal and (len(notes) == 1 or meilleur[0] > notes[1][0]):
            url = url_propre(meilleur[3])
            verser(e["id"], url, meilleur[4])
            attribuer(e, "Trouvé" if meilleur[1] else "Ambigu", url, "Filet homonymes", "C")
            print(f"      ({', '.join(meilleur[2])} ; {len(notes)} homonymes départagés)")

    if nouveaux:
        with open(f_res, "a") as out:
            for l in nouveaux:
                out.write(json.dumps(l, ensure_ascii=False) + "\n")
    json.dump(payload, open(f_recherches, "w"), ensure_ascii=False)
    print(f"Filets société : A (Google société) {stats['A']}, B (page LinkedIn) {stats['B']}, "
          f"C (homonymes) {stats['C']} — {len(ouverts())} restent « Non trouvé » ; "
          f"{len(nouveaux)} profils versés dans {f_res.name} ; coût ~{cout:.2f} $.")


if __name__ == "__main__":
    main(*sys.argv[1:4])
