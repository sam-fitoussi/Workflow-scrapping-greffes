"""E-mail du matin : les profils remontés dans Revue ce jour-là, NON VUS,
notés 13/20 ou plus — envoyé à la fin de robot/revue.py à Samuel, Bruno,
Pierre et Lio (destinataires fixés dans le Zap, pas ici).
Objet : « Sourcing du 3 nov : 9 bons profils. » (« 1 bon profil. »,
« aucun bon profil. »).

Construit ici, de façon déterministe (liste, tri, mise en forme) ; l'envoi
passe par un Zap (« Catch Hook » → Microsoft Outlook « Send Email » depuis
le compte de Samuel), dont l'adresse est dans la variable d'environnement
REVUE_EMAIL_WEBHOOK. Sans elle, ou si l'envoi échoue, la Revue n'est pas
affectée : un message ⚠️ le signale dans la sortie de la routine.

Une ligne par profil, de la meilleure note à la moins bonne :
  Nom (lien LinkedIn) — 15/20 · Sources (Evertrace : lien vers la fiche) ·
  Ville · X (lien, si connu) · Société
Jour sans profil à 13 ou plus : « Aucun bon profil remonté aujourd'hui par
nos agents, désolé ! ».
« Non vu » = case Vu de la ligne Revue décochée au moment de l'envoi (la
règle des 60 jours est appliquée en amont, à la création de la ligne).

Usage : python3 -m robot.email_revue [--essai] [AAAA-MM-JJ]
        (--essai : affiche l'e-mail sans l'envoyer)
"""

import datetime as dt
import html
import json
import os
import sys
import urllib.request
import zoneinfo

from . import airtable, config

PARIS = zoneinfo.ZoneInfo("Europe/Paris")
CR = config.CHAMPS_REVUE
SEUIL = 13
WEBHOOK = os.environ.get("REVUE_EMAIL_WEBHOOK", "")
URL_REVUE = f"https://airtable.com/{config.AIRTABLE_BASE_ID}/{config.TABLE_REVUE}"

# Champs Revue (formules et lookups)
F_NOTE = "fldb8B1qW9gpCkRrv"      # meilleure note, toutes sources
F_SOURCES = "fldmoQDVx1cGzrj1g"   # « Pappers Evertrace … »
F_X = "fldO4q3WmrUzoPClu"         # compte X (lookup Evertrace)
F_LIEN_EVERTRACE = config.CANAUX_REVUE["Evertrace"]["lien"]
# Table Evertrace : identifiant du signal et filtres où il remonte
EV_TABLE = config.CANAUX_REVUE["Evertrace"]["table"]
EV_SIGNAL, EV_FILTRES = "fldImAL1ZnJekMVly", "fldwUH3wFjmWLIw2y"
# Une fiche Evertrace s'ouvre dans le contexte d'une recherche sauvegardée :
# app.evertrace.ai/searches/<recherche>/signals/<signal>. Titre -> identifiant
# (relevé le 02/11/2026) ; filtre inconnu -> la recherche la plus large.
RECHERCHES_EVERTRACE = {
    "All founders France/Belg/Swi/Lux": "sch_qVNrxM7fJPCApxn8",
    "From France partout dans le monde": "sch_bUqG5kpXb1hfahXF",
    "New founders, X or HEC": "sch_Jg8hxJ3D2Rrc1GxP",
    "Ex-scale-ups & portefeuille Frst": "sch_hxcngsffHAMQtJeR",
    "Bonnes unis fr/suisse/lux/belg - rest of world": "sch_zLNuBMQuZgLJE1ZB",
}
RECHERCHE_PAR_DEFAUT = "sch_qVNrxM7fJPCApxn8"
MOIS = ["jan", "fév", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]
CANAUX = ["Pappers", "Evertrace", "The Veck FR", "The Veck INT", "Sales Navigator"]


def _sources(texte: str | None) -> list[str]:
    t = texte or ""
    return [c for c in CANAUX if c in t]


def _lien_evertrace(ids: list[str], fiches: dict) -> str | None:
    for rid in ids or []:
        f = fiches.get(rid) or {}
        sig = f.get(EV_SIGNAL)
        if sig:
            noms = [x if isinstance(x, str) else x.get("name") for x in f.get(EV_FILTRES) or []]
            sch = next((RECHERCHES_EVERTRACE[n] for n in noms if n in RECHERCHES_EVERTRACE),
                       RECHERCHE_PAR_DEFAUT)
            return f"https://app.evertrace.ai/searches/{sch}/signals/{sig}"
    return None


def _a(url: str | None, texte: str, gras: bool = False) -> str:
    t = html.escape(texte)
    t = f"<b>{t}</b>" if gras else t
    return f'<a href="{html.escape(url, quote=True)}">{t}</a>' if url else t


def construire(jour: str) -> dict:
    lignes = [r for r in airtable.lire_table(config.TABLE_REVUE, [
        CR["nom"], CR["jour"], CR["vu"], CR["url"], CR["ville"], CR["societe"],
        F_NOTE, F_SOURCES, F_X, F_LIEN_EVERTRACE]) if r["fields"].get(CR["jour"]) == jour
        and not r["fields"].get(CR["vu"])]
    hautes = sorted((r for r in lignes if (r["fields"].get(F_NOTE) or 0) >= SEUIL),
                    key=lambda r: -r["fields"][F_NOTE])
    fiches_ev = {}
    if any(r["fields"].get(F_LIEN_EVERTRACE) for r in hautes):
        fiches_ev = {r["id"]: r["fields"] for r in airtable.lire_table(EV_TABLE, [EV_SIGNAL, EV_FILTRES])}
    d = dt.date.fromisoformat(jour)
    date = f"{d.day} {MOIS[d.month - 1]}"  # « 3 nov », « 17 jan »

    items = []
    for r in hautes:
        f = r["fields"]
        sources = _sources(f.get(F_SOURCES))
        lien_ev = _lien_evertrace(f.get(F_LIEN_EVERTRACE), fiches_ev)
        morceaux = [f"{f[F_NOTE]}/20",
                    " + ".join(_a(lien_ev, s) if s == "Evertrace" else html.escape(s) for s in sources)]
        if f.get(CR["ville"]):
            morceaux.append(html.escape(f[CR["ville"]]))
        x = next((u for u in (f.get(F_X) or []) if u), None)
        if x:
            morceaux.append(_a(x, "X"))
        if f.get(CR["societe"]):
            morceaux.append(html.escape(f[CR["societe"]]))
        items.append(f'<li>{_a(f.get(CR["url"]), f.get(CR["nom"]) or "?", gras=True)} — '
                     + " · ".join(m for m in morceaux if m) + "</li>")

    pied = f'<p><a href="{URL_REVUE}">Ouvrir la Revue</a></p>'
    if hautes:
        n = len(hautes)
        sujet = f"Sourcing du {date} : {n} bon{'s' if n > 1 else ''} profil{'s' if n > 1 else ''}."
        corps = "<ul>" + "".join(items) + "</ul>" + pied
    else:
        sujet = f"Sourcing du {date} : aucun bon profil."
        corps = "<p>Aucun bon profil remonté aujourd'hui par nos agents, désolé !</p>"
    return {"sujet": sujet, "html": corps, "nb": len(hautes)}


def envoyer(jour: str | None = None, essai: bool = False) -> None:
    jour = jour or dt.datetime.now(PARIS).date().isoformat()
    try:
        mail = construire(jour)
    except Exception as e:
        print(f"⚠️ E-mail du matin non construit : {str(e)[:200]}")
        return
    if essai:
        print(f"ESSAI — non envoyé.\nObjet : {mail['sujet']}\n{mail['html']}")
        return
    if not WEBHOOK:
        print("⚠️ E-mail du matin non envoyé : variable REVUE_EMAIL_WEBHOOK absente.")
        return
    try:
        req = urllib.request.Request(WEBHOOK, data=json.dumps(mail).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        print(f"E-mail du matin envoyé : {mail['sujet']}")
    except Exception as e:
        print(f"⚠️ E-mail du matin non envoyé (Zapier) : {str(e)[:200]}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    envoyer(args[0] if args else None, essai="--essai" in sys.argv)
