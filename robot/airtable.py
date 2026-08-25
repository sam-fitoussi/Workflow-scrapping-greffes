"""Client Airtable REST minimal (clé PAT dans AIRTABLE_API_KEY).

Raison d'être : le connecteur MCP oblige à faire transiter chaque payload
par le contexte du modèle (lecture puis ré-émission inline). En passant par
l'API REST avec des fichiers JSON sur disque, les payloads ne coûtent plus
aucun token et ne risquent aucune erreur de transcription.

Limites REST : 10 enregistrements par requête, ~5 requêtes/s. Les fonctions
gèrent le découpage et la cadence.

Usage en ligne de commande (les données restent sur disque) :
    python3 -m robot.airtable lire     <table_id> <sortie.json> [champ_id ...]
    python3 -m robot.airtable inserer  <table_id> <payload.json> <sortie.json>
    python3 -m robot.airtable maj      <table_id> <payload.json>

Formats fichiers :
    inserer : [{"fields": {"fldXXX": ...}}, ...]  → sortie: [{"id": "recXXX", ...}]
    maj     : [{"id": "recXXX", "fields": {...}}, ...]
"""

import json
import sys
import time
import urllib.parse
import urllib.request

from . import config

BASE = "https://api.airtable.com/v0"
LOT = 10  # maximum autorisé par l'API REST


def _call(methode: str, chemin: str, payload: dict | None = None, params: dict | None = None) -> dict:
    if not config.AIRTABLE_API_KEY:
        raise SystemExit("AIRTABLE_API_KEY absent : exporter le PAT Airtable, ou repasser par le MCP.")
    url = f"{BASE}/{chemin}"
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=methode, headers={
        "Authorization": f"Bearer {config.AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    })
    for tentative in range(4):
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and tentative < 3:  # rate limit : attendre et réessayer
                time.sleep(31)
                continue
            raise SystemExit(f"Airtable {e.code} sur {chemin} : {e.read().decode()[:500]}")
    raise SystemExit("inatteignable")


def lire_table(table_id: str, champs: list[str] | None = None) -> list[dict]:
    """Tous les enregistrements d'une table (paginé). Retourne la liste brute
    [{"id": ..., "fields": {...}}]. `champs` : IDs de champs à inclure."""
    records, offset = [], None
    while True:
        params = {"pageSize": 100, "returnFieldsByFieldId": "true"}
        if champs:
            params["fields[]"] = champs
        if offset:
            params["offset"] = offset
        d = _call("GET", f"{config.AIRTABLE_BASE_ID}/{table_id}", params=params)
        records.extend(d.get("records", []))
        offset = d.get("offset")
        if not offset:
            return records
        time.sleep(0.25)


def inserer(table_id: str, enregistrements: list[dict]) -> list[dict]:
    """Crée les enregistrements par lots de 10. Retourne les records créés
    (avec leur id), dans le même ordre que l'entrée."""
    crees = []
    for i in range(0, len(enregistrements), LOT):
        d = _call("POST", f"{config.AIRTABLE_BASE_ID}/{table_id}", payload={
            "records": enregistrements[i:i + LOT],
            "typecast": True,
        })
        crees.extend(d["records"])
        time.sleep(0.25)
    return crees


def mettre_a_jour(table_id: str, enregistrements: list[dict]) -> int:
    """PATCH par lots de 10 : [{"id": ..., "fields": {...}}, ...]."""
    for i in range(0, len(enregistrements), LOT):
        _call("PATCH", f"{config.AIRTABLE_BASE_ID}/{table_id}", payload={
            "records": enregistrements[i:i + LOT],
            "typecast": True,
        })
        time.sleep(0.25)
    return len(enregistrements)


def main(argv: list[str]) -> None:
    action, table = argv[0], argv[1]
    if action == "lire":
        sortie = argv[2]
        champs = argv[3:] or None
        records = lire_table(table, champs)
        json.dump(records, open(sortie, "w"), ensure_ascii=False)
        print(f"{len(records)} enregistrements -> {sortie}")
    elif action == "inserer":
        payload, sortie = argv[2], argv[3]
        crees = inserer(table, json.load(open(payload)))
        json.dump(crees, open(sortie, "w"), ensure_ascii=False)
        print(f"{len(crees)} créés -> {sortie}")
    elif action == "maj":
        n = mettre_a_jour(table, json.load(open(argv[2])))
        print(f"{n} mis à jour")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
