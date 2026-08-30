"""Orchestrateur déterministe du run quotidien (étapes 2 à 4 du RUNBOOK).

Fait en un seul script tout ce qui n'a pas besoin du modèle : tirage
Pappers, filtres, anti-doublons SIREN, insertion Airtable (entreprises puis
fondateurs liés), écriture de la ligne du Journal — date par date, la ligne
du Journal étant écrite SITÔT la date insérée (si la session meurt ensuite,
la journée payée reste enregistrée).

Le modèle ne reprend la main qu'après : recherche LinkedIn (jugement),
scraping (robot/scraping_lot.py en tâche de fond), scoring + Note IA.

Usage :
    python3 -m robot.run --dates 21-08-2026 22-08-2026 --sortie /tmp/run
    python3 -m robot.run --sonde            # affiche total J-1..J-7 (0,1 jeton/date)

Sorties dans --sortie :
    <date>_bruts.json        tirage brut Pappers
    <date>_gardes.json       après filtres
    <date>_fondateurs.jsonl  file pour la recherche LinkedIn (1 ligne/fondateur,
                             avec rec_id Airtable, date_source, contexte)
"""

import argparse
import datetime as dt
import json
import pathlib

from . import airtable, config, pappers

CE = config.CHAMPS_ENTREPRISES
CF = config.CHAMPS_FONDATEURS
CJ = config.CHAMPS_JOURNAL


def _iso(date_fr: str) -> str:
    """JJ-MM-AAAA -> AAAA-MM-JJ."""
    j, m, a = date_fr.split("-")
    return f"{a}-{m}-{j}"


def sonder(nb_jours: int = 7, sauf: set[str] | None = None) -> dict[str, int]:
    """Total de dirigeants cercle cœur publiés pour J-1..J-nb_jours (0,1 jeton/date).

    `sauf` : dates JJ-MM-AAAA à ne pas sonder (déjà au Journal — les sonder
    quand même ne sert qu'au rattrapage du dimanche)."""
    totaux = {}
    for i in range(1, nb_jours + 1):
        d = (dt.date.today() - dt.timedelta(days=i)).strftime("%d-%m-%Y")
        if sauf and d in sauf:
            continue
        r = pappers._call("recherche-dirigeants", {
            "date_immatriculation_rcs_min": d,
            "date_immatriculation_rcs_max": d,
            "categorie_juridique": config.CATEGORIES_JURIDIQUES,
            "type_dirigeant": "physique",
            "code_naf": ",".join(config.NAF_COEUR),
            "par_page": 1,
        })
        totaux[d] = r.get("total", 0)
    return totaux


def _fiche_entreprise(e: dict, cercle: str, date_immat_fr: str) -> dict:
    siege = e.get("siege") or {}
    cp = siege.get("code_postal") or e.get("code_postal") or ""
    return {"fields": {
        CE["denomination"]: e.get("nom_entreprise"),
        CE["siren"]: e.get("siren"),
        CE["date_immat"]: _iso(date_immat_fr),
        CE["date_creation"]: e.get("date_creation"),
        CE["forme"]: {"5710": "SAS", "5720": "SASU"}.get(e.get("categorie_juridique"), e.get("forme_juridique")),
        CE["naf"]: (e.get("code_naf") or "").replace(".", ""),
        CE["libelle_naf"]: e.get("libelle_code_naf"),
        CE["ville"]: siege.get("ville") or e.get("ville"),
        CE["dept"]: cp[:2] if cp else None,
        CE["capital"]: e.get("capital"),
        CE["cercle"]: cercle,
        CE["lien_pappers"]: f"https://www.pappers.fr/entreprise/{e.get('siren')}",
    }}


def _indices_greffe(d: dict, e: dict) -> dict:
    """Signaux d'identité gratuits, déjà dans la réponse Pappers payée
    (RUNBOOK, recherche par paliers et contrôle d'identité) :
    - naissance AAAA-MM et ville PERSONNELLE du dirigeant (≠ siège) :
      les vrais discriminants d'homonymes ;
    - nom d'usage / prénom usuel : souvent le nom du profil LinkedIn ;
    - autres sociétés (rare sur cette population de primo-fondateurs,
      ~1 fiche sur 70, mais quasi unique comme terme de recherche)."""
    autres = []
    for x in d.get("entreprises") or []:
        nom = x.get("nom_entreprise")
        if nom and x.get("siren") != e.get("siren") and nom not in autres:
            autres.append(nom)
    ind = {
        "naissance": d.get("date_de_naissance_rgpd"),
        "ville_dirigeant": d.get("ville"),
        "nom_usage": d.get("nom_usage") if d.get("nom_usage") != d.get("nom") else None,
        "prenom_usuel": (d.get("prenom_usuel")
                         if d.get("prenom_usuel") != d.get("prenom") else None),
        "sexe": d.get("sexe"),
        "autres_societes": autres or None,
    }
    return {k: v for k, v in ind.items() if v}


def _fiche_fondateur(d: dict, e: dict, rec_entreprise: str) -> dict:
    prenom = d.get("prenom") or ""
    nom = d.get("nom") or ""
    siege = e.get("siege") or {}
    fields = {
        CF["nom_complet"]: f"{prenom} {nom}".strip(),
        CF["prenom"]: prenom,
        CF["nom"]: nom,
        CF["age"]: d.get("age"),
        CF["qualite"]: d.get("qualite"),
        # Ville PERSONNELLE du dirigeant (le siège est sur la fiche entreprise)
        CF["ville"]: d.get("ville") or siege.get("ville") or e.get("ville"),
        CF["entreprise"]: [rec_entreprise],
        CF["siren_cible"]: e.get("siren"),
        CF["statut"]: "À chercher",
    }
    # Consignés dans Détail pour survivre au reliquat (le disque est éphémère,
    # et les noms courants qui rebouclent sont précisément des reliquats).
    # scorer_lot écrase Détail au scoring : à ce stade l'identité est réglée.
    indices = _indices_greffe(d, e)
    if indices:
        fields[CF["detail"]] = "Indices greffe : " + json.dumps(indices, ensure_ascii=False)
    return {"fields": fields}


def traiter_date(date_fr: str, entreprises_connues: dict[str, str], sirens_traites: set[str],
                 sortie: pathlib.Path, note_journal: str = "",
                 journal_existant: dict[str, dict] | None = None) -> dict:
    """Déroule tirage → filtres → insertion → Journal pour UNE date. Retourne les stats.

    Idempotent : un SIREN ne compte comme « traité » que si un FONDATEUR y est
    rattaché (sirens_traites, bâti sur la table Fondateurs). Une insertion à
    moitié faite (entreprise créée, fondateurs non) se rejoue donc toute seule,
    en réutilisant la fiche entreprise existante (entreprises_connues)."""
    jetons_avant = pappers.jetons_restants()

    bruts = pappers.tirage_du_jour(date_fr)
    (sortie / f"{date_fr}_bruts.json").write_text(json.dumps(bruts, ensure_ascii=False))
    gardes, _ = pappers.filtrer(bruts)

    # Anti-doublons : sur les fondateurs déjà rattachés, pas sur les entreprises
    nouveaux = [g for g in gardes if g["entreprise"]["siren"] not in sirens_traites]
    # Tri par SIREN : les cofondateurs d'une même société restent groupés
    # dans le fichier (la recherche et le rapport travaillent par équipe)
    nouveaux.sort(key=lambda g: g["entreprise"].get("siren") or "")
    (sortie / f"{date_fr}_gardes.json").write_text(json.dumps(nouveaux, ensure_ascii=False))

    # Une fiche entreprise par SIREN (plusieurs cofondateurs -> même société),
    # créée seulement si elle n'existe pas déjà
    par_siren: dict[str, dict] = {}
    for g in nouveaux:
        par_siren.setdefault(g["entreprise"]["siren"], g)
    a_creer = [g for siren, g in par_siren.items() if siren not in entreprises_connues]
    payload_ent = [_fiche_entreprise(g["entreprise"], g["dirigeant"].get("_cercle", "Cœur"), date_fr)
                   for g in a_creer]
    if payload_ent:  # les champs imbriqués Pappers (siege, capital…) peuvent manquer : mesurer
        remplis = sum(1 for p in payload_ent for v in p["fields"].values() if v not in (None, "", []))
        total = sum(len(p["fields"]) for p in payload_ent)
        print(f"{date_fr} : remplissage fiches entreprises {remplis}/{total} champs")
    crees = airtable.inserer(config.TABLE_ENTREPRISES, payload_ent)
    entreprises_connues.update({r["fields"].get(CE["siren"]): r["id"]
                                for r in crees if r["fields"].get(CE["siren"])})

    sans_fiche = [g for g in nouveaux
                  if g["entreprise"]["siren"] not in entreprises_connues]
    if sans_fiche:  # théorique (Pappers renvoie toujours le SIREN) mais jamais silencieux
        print(f"⚠️ {len(sans_fiche)} fondateur(s) sans fiche entreprise (SIREN absent), ignorés")
        nouveaux = [g for g in nouveaux if g["entreprise"]["siren"] in entreprises_connues]
    payload_fond = [_fiche_fondateur(g["dirigeant"], g["entreprise"],
                                     entreprises_connues[g["entreprise"]["siren"]])
                    for g in nouveaux]
    fondateurs = airtable.inserer(config.TABLE_FONDATEURS, payload_fond)
    sirens_traites.update(g["entreprise"]["siren"] for g in nouveaux)

    # File pour la recherche LinkedIn, taguée avec la date source
    with open(sortie / f"{date_fr}_fondateurs.jsonl", "w") as f:
        for g, rec in zip(nouveaux, fondateurs):
            d, e = g["dirigeant"], g["entreprise"]
            f.write(json.dumps({
                "rec_id": rec["id"],
                "date_source": date_fr,
                "prenom": d.get("prenom"), "nom": d.get("nom"), "age": d.get("age"),
                # ville = SIÈGE (la Note IA écrit « siège à … ») ; la ville
                # personnelle du dirigeant est dans indices.ville_dirigeant
                "ville": (e.get("siege") or {}).get("ville") or e.get("ville"),
                "entreprise": e.get("nom_entreprise"),
                "naf": e.get("libelle_code_naf"),
                "siren": e.get("siren"),  # clé de regroupement des cofondateurs
                "indices": _indices_greffe(d, e),
            }, ensure_ascii=False) + "\n")

    jetons_apres = pappers.jetons_restants()
    stats = {"date": date_fr, "bruts": len(bruts),
             "bruts_coeur": sum(1 for r in bruts if r.get("_cercle") == "Cœur"),
             "gardes": len(gardes),
             "inseres": len(fondateurs), "jetons": round(jetons_avant - jetons_apres, 1)}

    # Ligne du Journal écrite IMMÉDIATEMENT (jamais deux fois la même journée
    # payée). UNE ligne par date : si la date figure déjà au Journal
    # (rattrapage du dimanche), on met à jour la ligne existante au lieu d'en
    # créer une seconde. Les totaux (bruts, cœur, gardés) sont des
    # photographies du re-tirage complet -> écrasés ; « Insérés » et
    # « Jetons » sont des compteurs propres à chaque run -> additionnés.
    champs_journal = {
        CJ["date_traitee"]: _iso(date_fr),
        CJ["bruts"]: stats["bruts"],
        CJ["bruts_coeur"]: stats["bruts_coeur"],
        CJ["gardes"]: stats["gardes"],
        CJ["inseres"]: stats["inseres"],
        CJ["jetons"]: stats["jetons"],
        CJ["notes"]: note_journal or f"Run scripté du {dt.date.today():%d/%m/%Y}.",
    }
    existante = (journal_existant or {}).get(_iso(date_fr))
    if existante:
        f = existante["fields"]
        champs_journal[CJ["inseres"]] = (f.get(CJ["inseres"]) or 0) + stats["inseres"]
        champs_journal[CJ["jetons"]] = round((f.get(CJ["jetons"]) or 0) + stats["jetons"], 1)
        ajout = note_journal or f"Rattrapage effectué le {dt.date.today():%d/%m/%Y}."
        champs_journal[CJ["notes"]] = ((f.get(CJ["notes"]) or "").rstrip() + " " + ajout).strip()
        airtable.mettre_a_jour(config.TABLE_JOURNAL,
                               [{"id": existante["id"], "fields": champs_journal}])
    else:
        airtable.inserer(config.TABLE_JOURNAL, [{"fields": champs_journal}])
    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dates", nargs="*", default=[], help="dates JJ-MM-AAAA à traiter")
    p.add_argument("--sortie", default="sorties", help="répertoire de travail")
    p.add_argument("--sonde", action="store_true", help="sonder J-1..J-7 et sortir")
    p.add_argument("--auto", action="store_true",
                   help="avec --sonde : lire le Journal soi-même (calcule --sauf et --jours)")
    p.add_argument("--sauf", nargs="*", default=[],
                   help="avec --sonde : dates JJ-MM-AAAA à ne pas sonder (déjà au Journal)")
    p.add_argument("--jours", type=int, default=7, help="avec --sonde : profondeur en jours")
    p.add_argument("--note", default="", help="note à inscrire au Journal")
    args = p.parse_args()

    if args.sonde:
        sauf, jours = set(args.sauf), args.jours
        if args.auto:
            journal = airtable.lire_table(config.TABLE_JOURNAL, [CJ["date_traitee"]])
            dates = []
            for r in journal:
                iso = r["fields"].get(CJ["date_traitee"])
                if iso:
                    a, m, j = iso.split("-")
                    dates.append(dt.date(int(a), int(m), int(j)))
            sauf = {d.strftime("%d-%m-%Y") for d in dates}
            # Profondeur : jusqu'à la plus ancienne date du Journal (les trous
            # entre deux dates traitées sont ainsi couverts), bornée à 7-14 j
            brut = (dt.date.today() - min(dates)).days if dates else 7
            jours = min(14, max(7, brut))
            print(f"--auto : {len(sauf)} dates du Journal exclues, profondeur {jours} jours")
            if brut > 14:
                print(f"⚠️ Fenêtre plafonnée à 14 jours alors que la plus ancienne date "
                      f"du Journal remonte à {brut} jours : des dates plus anciennes ne "
                      f"seront ni sondées ni rattrapées — le signaler dans le rapport.")
        print(json.dumps(sonder(jours, sauf), ensure_ascii=False, indent=1))
        return

    solde = pappers.jetons_restants()
    if solde < 15:
        raise SystemExit(f"STOP : {solde} jetons Pappers restants (< 15). Recharger puis relancer.")
    if solde < 50:
        print(f"⚠️ ALERTE : jetons Pappers bas ({solde} restants), recharger le pay-as-you-go.")

    sortie = pathlib.Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)

    ent = airtable.lire_table(config.TABLE_ENTREPRISES, [CE["siren"]])
    entreprises_connues = {r["fields"][CE["siren"]]: r["id"]
                           for r in ent if r["fields"].get(CE["siren"])}
    fond = airtable.lire_table(config.TABLE_FONDATEURS, [CF["siren_cible"]])
    sirens_traites = {r["fields"].get(CF["siren_cible"])
                      for r in fond if r["fields"].get(CF["siren_cible"])}
    print(f"{len(entreprises_connues)} entreprises connues, "
          f"{len(sirens_traites)} SIREN avec fondateurs rattachés.")

    # Index du Journal pour l'upsert des lignes (une ligne par date). En cas
    # de doublon résiduel, viser la photographie la plus complète.
    journal_existant: dict[str, dict] = {}
    for r in airtable.lire_table(config.TABLE_JOURNAL,
                                 [CJ["date_traitee"], CJ["bruts_coeur"],
                                  CJ["inseres"], CJ["jetons"], CJ["notes"]]):
        iso = r["fields"].get(CJ["date_traitee"])
        deja = journal_existant.get(iso)
        if iso and (not deja or (r["fields"].get(CJ["bruts_coeur"]) or 0)
                    >= (deja["fields"].get(CJ["bruts_coeur"]) or 0)):
            journal_existant[iso] = r

    for date_fr in args.dates:
        stats = traiter_date(date_fr, entreprises_connues, sirens_traites, sortie,
                             args.note, journal_existant)
        print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
