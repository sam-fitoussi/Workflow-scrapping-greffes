"""Robot Revue : peuple l'onglet « Revue » (vue unique du matin).

Une ligne Revue = un fondateur EXAMINABLE (profil LinkedIn identifié)
découvert par CE run, tous canaux confondus. « Jour » = la date du run
(heure de Paris) : tout ce qui apparaît dans la Revue apparaît dans le
groupe du matin où Samuel va le lire — y compris les fiches arrivées la
veille en journée ou les reliquats résolus tardivement, qui sinon
atterriraient dans un groupe déjà dépilé.

Dédoublonnage : un même profil découvert par plusieurs canaux dans le
même run -> UNE ligne, avec les liens vers toutes les fiches sources.
Un re-signalement un autre jour -> nouvelle ligne à ce jour-là ; elle
naît cochée « Vu » si une fiche source l'est déjà (le seuil des 60 jours
est appliqué en amont par la déduplication inter-canaux).

Les informations affichées dans Revue sont des lookups qui suivent les
fiches sources en direct ; le script n'écrit que l'ossature (nom, jour,
slug, liens, et quelques champs de confort figés à la découverte).

Idempotent : une fiche source déjà liée dans Revue n'est jamais retraitée ;
relancer le script ne crée aucun doublon. État durable = Airtable seul.

Usage : python3 -m robot.revue
"""

import datetime as dt
import zoneinfo

from . import airtable, config

PARIS = zoneinfo.ZoneInfo("Europe/Paris")
CR = config.CHAMPS_REVUE
CE = config.CHAMPS_ENTREPRISES
# Priorité des canaux pour les champs de confort (nom, société…)
ORDRE = ["Pappers", "Evertrace", "The Veck FR", "The Veck INT"]


def _lignes_canal(nom_canal: str, denominations: dict[str, str]) -> list[dict]:
    """Les fiches examinables d'un canal : {rec_id, slug, nom, ...}."""
    c = config.CANAUX_REVUE[nom_canal]
    champs = [v for k, v in c.items() if k != "table" and k != "lien" and v]
    champs.append(config.VU_SOURCES_REVUE[nom_canal])
    lignes = []
    for r in airtable.lire_table(c["table"], champs):
        f = r["fields"]
        slug = f.get(c["slug"])
        if not slug:
            continue  # pas de profil LinkedIn identifié : pas examinable
        societe = (denominations.get(f.get(c["siren"])) if c["siren"]
                   else f.get(c["societe"]))
        lignes.append({
            "rec_id": r["id"], "canal": nom_canal, "slug": slug,
            "nom": f.get(c["nom"]), "societe": societe,
            "role": f.get(c["role"]), "ville": f.get(c["ville"]),
            "url": f.get(c["url"]),
            "resume": f.get(c["resume"]) if c["resume"] else None,
            "vu": bool(f.get(config.VU_SOURCES_REVUE[nom_canal])),
        })
    return lignes


def main() -> None:
    jour_du_run = dt.datetime.now(PARIS).strftime("%Y-%m-%d")
    liens = {canal: config.CANAUX_REVUE[canal]["lien"] for canal in ORDRE}

    # 1. État actuel de la Revue : fiches sources déjà liées + index des
    #    lignes du jour (pour une seconde exécution le même jour)
    deja_liees: set[str] = set()
    index_du_jour: dict[str, dict] = {}
    revue = airtable.lire_table(config.TABLE_REVUE,
                                [CR["slug"], CR["jour"]] + list(liens.values()))
    for r in revue:
        f = r["fields"]
        for fld in liens.values():
            deja_liees.update(f.get(fld) or [])
        if f.get(CR["slug"]) and f.get(CR["jour"]) == jour_du_run:
            index_du_jour[f[CR["slug"]]] = {
                "id": r["id"],
                "liens": {c: list(f.get(fld) or []) for c, fld in liens.items()},
            }

    # 2. Dénominations Pappers (société des fiches Pappers, via SIREN cible)
    ents = airtable.lire_table(config.TABLE_ENTREPRISES,
                               [CE["siren"], CE["denomination"]])
    denominations = {e["fields"].get(CE["siren"]): e["fields"].get(CE["denomination"])
                     for e in ents if e["fields"].get(CE["siren"])}

    # 3. Nouvelles fiches examinables, groupées par slug (dédup du run)
    groupes: dict[str, list[dict]] = {}
    for canal in ORDRE:
        for l in _lignes_canal(canal, denominations):
            if l["rec_id"] in deja_liees:
                continue
            groupes.setdefault(l["slug"], []).append(l)

    # 4. Créations (et compléments si seconde exécution le même jour).
    # Ventilation par canal PRINCIPAL de chaque ligne créée : la somme des
    # quatre chiffres égale exactement le nombre de lignes (un profil
    # multi-canaux compte une fois, il est signalé à part).
    creations, majs = [], []
    par_canal = {c: 0 for c in ORDRE}
    multi_canaux = 0
    for slug, lignes in groupes.items():
        lignes.sort(key=lambda l: ORDRE.index(l["canal"]))
        existant = index_du_jour.get(slug)
        if existant:
            nouveaux = dict(existant["liens"])
            for l in lignes:
                nouveaux[l["canal"]] = nouveaux[l["canal"]] + [l["rec_id"]]
            majs.append({"id": existant["id"], "fields": {
                liens[c]: ids for c, ids in nouveaux.items() if ids}})
            continue
        premier = lignes[0]
        par_canal[premier["canal"]] += 1
        if len({l["canal"] for l in lignes}) > 1:
            multi_canaux += 1
        champs = {
            CR["nom"]: premier["nom"], CR["jour"]: jour_du_run, CR["slug"]: slug,
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
    ventilation = " · ".join(f"{c} {n}" for c, n in par_canal.items())
    print(f"Revue du {jour_du_run} : {len(creations)} lignes créées — {ventilation}"
          + (f" (dont {multi_canaux} multi-canaux)" if multi_canaux else "")
          + (f" ; {len(majs)} lignes du jour complétées" if majs else "")
          + ".")


if __name__ == "__main__":
    main()
