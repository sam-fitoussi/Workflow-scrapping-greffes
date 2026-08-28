"""Robot Revue : peuple l'onglet « Revue » (vue unique du matin).

Une ligne Revue = un fondateur EXAMINABLE (profil LinkedIn identifié)
signalé un jour donné, tous canaux confondus, dédoublonné par slug
LinkedIn AU SEIN d'un même jour :
  - même profil remonté la même nuit par deux canaux -> UNE ligne,
    avec les liens vers les deux fiches sources ;
  - re-signalement un autre jour -> NOUVELLE ligne à ce jour-là
    (elle naît cochée « Vu » si une fiche source l'est déjà — le seuil
    des 60 jours est appliqué en amont par la déduplication inter-canaux).

Les informations affichées dans Revue sont des lookups qui suivent les
fiches sources en direct ; le script n'écrit que l'ossature (nom, jour,
slug, liens, et quelques champs de confort figés au signalement).

Idempotent : une fiche source déjà liée dans Revue n'est jamais retraitée ;
relancer le script ne crée aucun doublon. État durable = Airtable seul.

Usage : python3 -m robot.revue [--depuis AAAA-MM-JJ]
        (--depuis limite le rattrapage ; par défaut, tout l'historique)
"""

import argparse
import datetime as dt
import zoneinfo

from . import airtable, config

PARIS = zoneinfo.ZoneInfo("Europe/Paris")
CR = config.CHAMPS_REVUE
CE = config.CHAMPS_ENTREPRISES
# Priorité des canaux pour les champs de confort (nom, société…)
ORDRE = ["Pappers", "Evertrace", "The Veck FR", "The Veck INT"]


def _jour_paris(iso_dt: str) -> str:
    """'2026-08-27T22:15:00.000Z' -> '2026-08-28' (heure de Paris)."""
    d = dt.datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
    return d.astimezone(PARIS).strftime("%Y-%m-%d")


def _lignes_canal(nom_canal: str, denominations: dict[str, str]) -> list[dict]:
    """Les fiches examinables d'un canal : {rec_id, slug, jour, nom, ...}."""
    c = config.CANAUX_REVUE[nom_canal]
    champs = [v for k, v in c.items() if k != "table" and k != "lien" and v]
    champs.append(config.VU_SOURCES_REVUE[nom_canal])
    lignes = []
    for r in airtable.lire_table(c["table"], champs):
        f = r["fields"]
        slug = f.get(c["slug"])
        if not slug:
            continue  # pas de profil LinkedIn identifié : pas examinable
        if c["jour"] and f.get(c["jour"]):
            jour = str(f[c["jour"]]).strip()[:10]
        elif c["jour_dt"] and f.get(c["jour_dt"]):
            jour = _jour_paris(f[c["jour_dt"]])
        else:
            print(f"⚠️ {nom_canal} {r['id']} : aucune date d'ajout, ligne sautée")
            continue
        societe = (denominations.get(f.get(c["siren"])) if c["siren"]
                   else f.get(c["societe"]))
        lignes.append({
            "rec_id": r["id"], "canal": nom_canal, "slug": slug, "jour": jour,
            "nom": f.get(c["nom"]), "societe": societe,
            "role": f.get(c["role"]), "ville": f.get(c["ville"]),
            "url": f.get(c["url"]),
            "resume": f.get(c["resume"]) if c["resume"] else None,
            "vu": bool(f.get(config.VU_SOURCES_REVUE[nom_canal])),
        })
    return lignes


def main(depuis: str | None = None) -> None:
    liens = {canal: config.CANAUX_REVUE[canal]["lien"] for canal in ORDRE}

    # 1. État actuel de la Revue : fiches sources déjà liées + index (slug, jour)
    deja_liees: set[str] = set()
    index: dict[tuple[str, str], dict] = {}
    revue = airtable.lire_table(config.TABLE_REVUE,
                                [CR["slug"], CR["jour"]] + list(liens.values()))
    for r in revue:
        f = r["fields"]
        for fld in liens.values():
            deja_liees.update(f.get(fld) or [])
        if f.get(CR["slug"]) and f.get(CR["jour"]):
            index[(f[CR["slug"]], f[CR["jour"]])] = {
                "id": r["id"],
                "liens": {c: list(f.get(fld) or []) for c, fld in liens.items()},
            }

    # 2. Dénominations Pappers (société des fiches Pappers, via SIREN cible)
    ents = airtable.lire_table(config.TABLE_ENTREPRISES,
                               [CE["siren"], CE["denomination"]])
    denominations = {e["fields"].get(CE["siren"]): e["fields"].get(CE["denomination"])
                     for e in ents if e["fields"].get(CE["siren"])}

    # 3. Nouvelles fiches examinables, groupées par (slug, jour)
    groupes: dict[tuple[str, str], list[dict]] = {}
    for canal in ORDRE:
        for l in _lignes_canal(canal, denominations):
            if l["rec_id"] in deja_liees:
                continue
            if depuis and l["jour"] < depuis:
                continue
            groupes.setdefault((l["slug"], l["jour"]), []).append(l)

    # 4. Créations et compléments
    creations, majs = [], []
    for (slug, jour), lignes in sorted(groupes.items(), key=lambda x: x[0][1]):
        lignes.sort(key=lambda l: ORDRE.index(l["canal"]))
        existant = index.get((slug, jour))
        if existant:  # ligne du jour déjà là (autre canal passé avant) : lier
            nouveaux = dict(existant["liens"])
            for l in lignes:
                nouveaux[l["canal"]] = nouveaux[l["canal"]] + [l["rec_id"]]
            majs.append({"id": existant["id"], "fields": {
                liens[c]: ids for c, ids in nouveaux.items() if ids}})
            continue
        premier = lignes[0]
        champs = {
            CR["nom"]: premier["nom"], CR["jour"]: jour, CR["slug"]: slug,
            CR["societe"]: next((l["societe"] for l in lignes if l["societe"]), None),
            CR["role"]: next((l["role"] for l in lignes if l["role"]), None),
            CR["ville"]: next((l["ville"] for l in lignes if l["ville"]), None),
            CR["url"]: next((l["url"] for l in lignes if l["url"]), None),
            CR["resume"]: next((l["resume"] for l in lignes if l["resume"]), None),
        }
        for l in lignes:
            champs.setdefault(liens[l["canal"]], []).append(l["rec_id"])
        # Déjà vu ailleurs (dédup inter-canaux, seuil 60 j appliqué en amont) :
        # la ligne naît cochée, sans dépendre de l'automatisation de reflet
        if any(l["vu"] for l in lignes):
            champs[CR["vu"]] = True
        creations.append({"fields": {k: v for k, v in champs.items() if v is not None}})

    if majs:
        airtable.mettre_a_jour(config.TABLE_REVUE, majs)
    if creations:
        airtable.inserer(config.TABLE_REVUE, creations)
    par_jour: dict[str, int] = {}
    for cr in creations:
        par_jour[cr["fields"][CR["jour"]]] = par_jour.get(cr["fields"][CR["jour"]], 0) + 1
    print(f"Revue : {len(creations)} lignes créées, {len(majs)} complétées "
          f"(liens ajoutés). Par jour : "
          f"{', '.join(f'{j}: {n}' for j, n in sorted(par_jour.items())) or '—'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--depuis", default=None,
                   help="ne traiter que les signalements à partir de AAAA-MM-JJ")
    args = p.parse_args()
    main(args.depuis)
