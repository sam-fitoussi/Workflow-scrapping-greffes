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

Nouveau signal sur un profil NON VU : quand Evertrace fusionne un nouveau
signal dans une fiche déjà liée (moins de 15 jours après le précédent, note
« nouveau signal le JJ/MM »), la ligne Revue est redatée du jour du run —
le profil remonte dans le groupe du matin (règle de Samuel : un second
signal = un projet qui avance). Jamais si la ligne ou une de ses fiches
sources est déjà vue. (Au-delà de 15 jours, Evertrace crée une nouvelle
fiche : nouvelle ligne Revue, cas déjà couvert ci-dessus.)

Idempotent : une fiche source déjà liée dans Revue n'est jamais retraitée ;
relancer le script ne crée aucun doublon. État durable = Airtable seul.

Un canal peut porter un « filtre » (champ, valeur) : seules ses fiches qui
le satisfont entrent dans Revue (Sales Navigator : Signal startup = 1 —
les autres fiches ne portent aucun signal de création d'entreprise).

Usage : python3 -m robot.revue                 (run quotidien)
        python3 -m robot.revue --essai         (à blanc : rien n'est écrit)
        python3 -m robot.revue --historique    (rattrapage ponctuel quand un
            canal est branché : chaque ligne est datée du jour d'ajout de sa
            fiche source au lieu du jour du run, pour ne pas noyer le groupe
            du matin sous l'historique)
"""

import datetime as dt
import re
import sys
import zoneinfo

from . import airtable, config

PARIS = zoneinfo.ZoneInfo("Europe/Paris")
CR = config.CHAMPS_REVUE
CE = config.CHAMPS_ENTREPRISES
# Priorité des canaux pour les champs de confort (nom, société…)
ORDRE = list(config.CANAUX_REVUE)
# Clés d'un canal qui désignent des champs à lire (les autres sont de la
# configuration : table, lien, filtre)
CHAMPS_LUS = ("slug", "nom", "societe", "siren", "role", "ville", "url", "resume", "date",
              "signal")


def _lignes_canal(nom_canal: str, denominations: dict[str, str]) -> list[dict]:
    """Les fiches examinables d'un canal : {rec_id, slug, nom, ...}."""
    c = config.CANAUX_REVUE[nom_canal]
    filtre = c.get("filtre")
    champs = [c[k] for k in CHAMPS_LUS if c.get(k)]
    champs.append(config.VU_SOURCES_REVUE[nom_canal])
    if filtre:
        champs.append(filtre[0])
    lignes = []
    for r in airtable.lire_table(c["table"], champs):
        f = r["fields"]
        slug = f.get(c["slug"])
        if not slug:
            continue  # pas de profil LinkedIn identifié : pas examinable
        if filtre and f.get(filtre[0]) != filtre[1]:
            continue  # hors du périmètre Revue de ce canal
        societe = (denominations.get(f.get(c["siren"])) if c["siren"]
                   else f.get(c["societe"]))
        lignes.append({
            "rec_id": r["id"], "canal": nom_canal, "slug": slug,
            "nom": f.get(c["nom"]), "societe": societe,
            "role": f.get(c["role"]), "ville": f.get(c["ville"]),
            "url": f.get(c["url"]),
            "resume": f.get(c["resume"]) if c["resume"] else None,
            "vu": bool(f.get(config.VU_SOURCES_REVUE[nom_canal])),
            "date": _jour_paris(f.get(c["date"])) if c.get("date") else None,
            "signal": _dernier_signal(f.get(c["signal"])) if c.get("signal") else None,
        })
    return lignes


def _dernier_signal(notes: str | None) -> str | None:
    """AAAA-MM-JJ du dernier « nouveau signal le JJ/MM » des notes (année
    déduite : la plus récente qui ne soit pas dans le futur)."""
    aujourd_hui = dt.datetime.now(PARIS).date()
    dates = []
    for j, m in re.findall(r"nouveau signal le (\d{2})/(\d{2})", notes or ""):
        try:
            d = dt.date(aujourd_hui.year, int(m), int(j))
        except ValueError:
            continue
        dates.append(d if d <= aujourd_hui else d.replace(year=d.year - 1))
    return max(dates).isoformat() if dates else None


def _jour_paris(horodatage: str | None) -> str | None:
    """AAAA-MM-JJ (heure de Paris) d'un horodatage ISO Airtable ou d'une date."""
    if not horodatage:
        return None
    if len(horodatage) == 10:
        return horodatage
    t = dt.datetime.fromisoformat(horodatage.replace("Z", "+00:00"))
    return t.astimezone(PARIS).strftime("%Y-%m-%d")


def main(essai: bool = False, historique: bool = False) -> None:
    jour_du_run = dt.datetime.now(PARIS).strftime("%Y-%m-%d")
    liens = {canal: config.CANAUX_REVUE[canal]["lien"] for canal in ORDRE}

    # 1. État actuel de la Revue : fiches sources déjà liées + index des
    #    lignes par (slug, jour) (seconde exécution le même jour, rattrapage)
    deja_liees: set[str] = set()
    index_lignes: dict[tuple[str, str], dict] = {}
    revue = airtable.lire_table(config.TABLE_REVUE,
                                [CR["slug"], CR["jour"], CR["vu"]] + list(liens.values()))
    for r in revue:
        f = r["fields"]
        for fld in liens.values():
            deja_liees.update(f.get(fld) or [])
        if f.get(CR["slug"]) and f.get(CR["jour"]):
            index_lignes[(f[CR["slug"]], f[CR["jour"]])] = {
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
    sources: dict[str, dict] = {}
    for canal in ORDRE:
        for l in _lignes_canal(canal, denominations):
            sources[l["rec_id"]] = l
            if l["rec_id"] in deja_liees:
                continue
            groupes.setdefault(l["slug"], []).append(l)

    # 3b. Nouveau signal sur un profil NON VU : la ligne remonte au jour du run
    remontees = []
    if not historique:
        for r in revue:
            f = r["fields"]
            recs = [sources[x] for fld in liens.values() for x in f.get(fld) or [] if x in sources]
            signal = max((l["signal"] for l in recs if l["signal"]), default=None)
            vue = f.get(CR["vu"]) or any(l["vu"] for l in recs)
            jour = f.get(CR["jour"])
            if signal and jour and signal > jour and jour < jour_du_run and not vue:
                remontees.append({"id": r["id"], "fields": {CR["jour"]: jour_du_run}})
                if f.get(CR["slug"]):  # une fiche du même profil arrivée ce jour la complète
                    index_lignes[(f[CR["slug"]], jour_du_run)] = {
                        "id": r["id"],
                        "liens": {c: list(f.get(fld) or []) for c, fld in liens.items()}}

    # 4. Créations (et compléments si seconde exécution le même jour).
    # Ventilation par canal PRINCIPAL de chaque ligne créée : la somme des
    # quatre chiffres égale exactement le nombre de lignes (un profil
    # multi-canaux compte une fois, il est signalé à part).
    creations, majs = [], []
    par_canal = {c: 0 for c in ORDRE}
    multi_canaux = 0
    for slug, lignes in groupes.items():
        lignes.sort(key=lambda l: ORDRE.index(l["canal"]))
        # Jour de la ligne : date du run ; en rattrapage historique, le plus
        # ancien jour d'ajout des fiches du groupe (à défaut, date du run)
        jour = (min((l["date"] for l in lignes if l["date"]), default=jour_du_run)
                if historique else jour_du_run)
        existant = index_lignes.get((slug, jour))
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

    if essai:
        print("ESSAI À BLANC — rien n'est écrit dans Airtable.")
    else:
        if remontees:
            airtable.mettre_a_jour(config.TABLE_REVUE, remontees)
        if majs:
            airtable.mettre_a_jour(config.TABLE_REVUE, majs)
        if creations:
            airtable.inserer(config.TABLE_REVUE, creations)
    ventilation = " · ".join(f"{c} {n}" for c, n in par_canal.items())
    if historique:
        jours = sorted(c["fields"][CR["jour"]] for c in creations)
        print(f"Rattrapage historique : lignes datées du {jours[0]} au {jours[-1]}"
              if jours else "Rattrapage historique : rien à créer.")
    print(f"Revue du {jour_du_run} : {len(creations)} lignes créées — {ventilation}"
          + (f" (dont {multi_canaux} multi-canaux)" if multi_canaux else "")
          + (f" ; {len(majs)} lignes du jour complétées" if majs else "")
          + (f" ; {len(remontees)} profils non vus remontés (nouveau signal)" if remontees else "")
          + ".")


if __name__ == "__main__":
    main(essai="--essai" in sys.argv, historique="--historique" in sys.argv)
