"""Digest structuré du run, pour le rapport final (étape 8 du RUNBOOK).

Le rapport était assemblé à la main par le modèle : rejoindre scores,
notes, contexte et anomalies à chaque run est une source d'oublis (et de
tokens). Ce script fait la partie DÉTERMINISTE — entonnoir chiffré,
profils à examiner groupés par société, anomalies nominatives, profils
quasi vides — à partir des fichiers déjà produits par les étapes
précédentes, sans aucun appel réseau. La RÉDACTION du rapport en
français reste au modèle, qui n'a plus qu'à mettre en forme et à
ajouter ce que le script ne voit pas (coût/solde Pappers, palier 3,
incidents de session).

Tolérant aux runs partiels : un fichier absent est signalé en tête et
sa section est sautée.

Usage : python3 -m robot.rapport /tmp/run_du_jour
(le répertoire du run doit contenir, parmi : *_fondateurs.jsonl datés,
reliquat_*.jsonl, contexte.jsonl, resultats.jsonl, verif.jsonl,
verif_maj.json, score_maj.json, score_a_noter.jsonl, notes.jsonl)
"""

import json
import pathlib
import sys

from . import config

CF = config.CHAMPS_FONDATEURS


def main(dossier: str) -> None:
    d = pathlib.Path(dossier)
    manquants: list[str] = []

    def jsonl(nom: str) -> list[dict]:
        p = d / nom
        if not p.exists():
            manquants.append(nom)
            return []
        return [json.loads(l) for l in open(p) if l.strip()]

    def jsonf(nom: str) -> list[dict]:
        p = d / nom
        if not p.exists():
            manquants.append(nom)
            return []
        return json.load(open(p))

    fichiers_jour = sorted(d.glob("[0-9]*-[0-9]*-[0-9]*_fondateurs.jsonl"))
    jour = [json.loads(l) for f in fichiers_jour for l in open(f) if l.strip()]
    contexte = {c["rec_id"]: c for c in jsonl("contexte.jsonl")}
    reliquat_ac = jsonl("reliquat_a_chercher.jsonl")
    reliquat_sc = jsonl("reliquat_scrape.jsonl")
    resultats = jsonl("resultats.jsonl")
    verif = jsonl("verif.jsonl")
    verif_maj = jsonf("verif_maj.json")
    score_maj = jsonf("score_maj.json")
    a_noter = jsonl("score_a_noter.jsonl")
    notes = jsonl("notes.jsonl")

    def nom_de(rec_id: str) -> str:
        c = contexte.get(rec_id, {})
        return f"{c.get('prenom') or ''} {c.get('nom') or ''}".strip() or f"({rec_id})"

    if manquants:
        print("⚠️ Fichiers absents (sections incomplètes) : " + ", ".join(manquants))
        print()

    # --- Entonnoir ---
    print("== Entonnoir du run ==")
    detail_jour = ", ".join(
        f"{f.name.removesuffix('_fondateurs.jsonl')} : "
        f"{sum(1 for l in open(f) if l.strip())}" for f in fichiers_jour)
    print(f"Fiches insérées du jour : {len(jour)}"
          + (f" ({detail_jour})" if detail_jour else " (aucune date tirée)"))
    print(f"Reliquat repris : {len(reliquat_ac)} à re-chercher, "
          f"{len(reliquat_sc)} à re-scraper")
    st = {"ok": 0, "vide": 0, "mort": 0, "erreur": 0}
    for r in resultats:
        st[r["statut"]] = st.get(r["statut"], 0) + 1
    print(f"Scrapés : {len(resultats)} — ok {st['ok']}, vides {st['vide']}, "
          f"morts {st['mort']}, erreurs {st['erreur']}")
    n_confirmes = sum(1 for v in verif if v["verdict"] == "ok" and not v.get("non_verifie"))
    n_nv = sum(1 for v in verif if v.get("non_verifie"))
    n_mauvais = sum(1 for v in verif if v["verdict"] == "mauvais")
    print(f"Contrôle d'identité : {n_confirmes} confirmés, {n_mauvais} homonymes "
          f"écartés, {n_nv} non vérifiés (Anomalie)")
    n_scores = sum(1 for m in score_maj if m["fields"].get(CF["statut"]) != "Non trouvé")
    print(f"Scorés : {n_scores}, dont score >= 1 : {len(a_noter)}")
    notes_ix = {n["rec_id"]: n for n in notes}
    sans_note = [l for l in a_noter if l["rec_id"] not in notes_ix]
    print(f"Notes IA : {len(notes_ix)}/{len(a_noter)}"
          + (f" — ⚠️ {len(sans_note)} manquante(s), relancer robot.note_ia"
             if sans_note else ""))
    print()

    # --- Profils à examiner, groupés par société (un deal = une équipe) ---
    resume_ix = {m["id"]: m["fields"].get(CF["resume"]) for m in score_maj}
    urls = {r["rec_id"]: r.get("url") for r in resultats}
    remplis = {r["rec_id"]: config.champs_remplis(r.get("profil") or {})
               for r in resultats if r.get("statut") == "ok"}
    par_siren: dict[str, list[str]] = {}
    for rid, c in contexte.items():
        if c.get("siren"):
            par_siren.setdefault(c["siren"], []).append(rid)

    groupes: dict[str, list[dict]] = {}
    for l in a_noter:
        cle = contexte.get(l["rec_id"], {}).get("siren") or l.get("societe") or l["rec_id"]
        groupes.setdefault(cle, []).append(l)

    def meilleure_note(lignes: list[dict]) -> int:
        return max((notes_ix[l["rec_id"]]["note"] for l in lignes
                    if l["rec_id"] in notes_ix), default=-1)

    print(f"== À examiner (score >= 1) : {len(a_noter)} profils, "
          f"{len(groupes)} sociétés ==")
    for cle, lignes in sorted(groupes.items(),
                              key=lambda kv: -meilleure_note(kv[1])):
        premier = lignes[0]
        c0 = contexte.get(premier["rec_id"], {})
        entete = c0.get("entreprise") or premier.get("societe") or "(société inconnue)"
        naf = c0.get("naf") or premier.get("naf")
        equipe = par_siren.get(c0.get("siren"), [])
        autres = [nom_de(r) for r in equipe
                  if r not in {l["rec_id"] for l in lignes}]
        print(f"\n● {entete}" + (f" ({naf})" if naf else ""))
        if autres:
            print(f"  Cofondateurs au greffe non listés ci-dessous : {', '.join(autres)}")
        for l in sorted(lignes, key=lambda x: -(notes_ix.get(x["rec_id"], {}).get("note", -1))):
            n = notes_ix.get(l["rec_id"])
            note_txt = (f"Note {n['note']}/20 — {n['justification']}" if n
                        else "⚠️ note manquante (relancer robot.note_ia)")
            age = f", {l['age']} ans" if l.get("age") else ""
            print(f"  - {l['nom']}{age} — score {l['score']} — {note_txt}")
            if urls.get(l["rec_id"]):
                print(f"    {urls[l['rec_id']]}")
            if resume_ix.get(l["rec_id"]):
                print(f"    {resume_ix[l['rec_id']]}")
            r = remplis.get(l["rec_id"])
            if r is not None and r < 5:
                print(f"    ⚠️ PROFIL QUASI VIDE ({r}/16 champs) : score et note "
                      f"fondés sur presque rien — possible fondateur en stealth")
    if not a_noter:
        print("(aucun)")
    print()

    # --- Anomalies, nominatives ---
    print("== Anomalies (à reprendre nominativement dans le rapport) ==")
    lignes_anomalies = []
    maj_ix = {m["id"]: m["fields"] for m in verif_maj}
    for v in verif:
        if v["verdict"] == "mauvais":
            f = maj_ix.get(v["rec_id"], {})
            terminal = (f.get(CF["statut"]) == "Non trouvé")
            lignes_anomalies.append(
                f"- Homonyme écarté : {nom_de(v['rec_id'])} ({v.get('url')}) — "
                f"{v.get('raison')}"
                + (" — 2e homonyme : recherche ABANDONNÉE" if terminal
                   else " — repart en « À chercher »"))
        elif v.get("non_verifie"):
            lignes_anomalies.append(
                f"- Non vérifié (API indisponible) : {nom_de(v['rec_id'])} — "
                f"passé au scoring avec Anomalie cochée")
    for r in resultats:
        if r["statut"] == "vide":
            f = maj_ix.get(r["rec_id"], {})
            terminal = "2e scrape vide" in (f.get(CF["detail"]) or "")
            lignes_anomalies.append(
                f"- Scrape vide : {nom_de(r['rec_id'])} ({r.get('url')}) — "
                + ("2e fois, URL traitée comme morte" if terminal
                   else "échec technique, re-scrape au prochain run"))
        elif r["statut"] == "erreur":
            lignes_anomalies.append(
                f"- Erreur de scraping : {nom_de(r['rec_id'])} ({r.get('url')}) — "
                f"{(r.get('erreur') or '')[:120]} — une seule relance au run suivant")
    for m in score_maj:
        if m["fields"].get(CF["statut"]) == "Non trouvé":
            lignes_anomalies.append(
                f"- URL morte : {nom_de(m['id'])} ({urls.get(m['id'])}) — "
                f"« Non trouvé » définitif")
    print("\n".join(lignes_anomalies) if lignes_anomalies else "(aucune)")
    print()

    # --- Ce que le script ne voit pas ---
    print("== À compléter par le modèle (hors de portée du script) ==")
    print("- Coût Pappers du tirage et solde restant : sortie de robot.run "
          "(alerte solde < 50 EN TÊTE du rapport).")
    print("- Jetons du palier 3 (objet social) consommés pendant la recherche.")
    print("- Repli éventuel du modèle IA (⚠️ affiché au lancement de "
          "note_ia / verif_identite) ; incidents de session.")


if __name__ == "__main__":
    main(sys.argv[1])
