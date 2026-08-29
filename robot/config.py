"""Configuration du robot de sourcing.

Les clés API ne sont JAMAIS stockées ici : elles sont lues depuis les
variables d'environnement (secrets GitHub Actions en production).
"""

import os

PAPPERS_API_KEY = os.environ.get("PAPPERS_API_KEY", "")
AIRTABLE_API_KEY = os.environ.get("AIRTABLE_API_KEY", "")
# ANTHROPIC_API_KEY est une variable réservée que la plateforme Claude Code
# filtre (elle écraserait l'authentification de la session) : l'environnement
# d'exécution la fournit sous le nom ROBOT_ANTHROPIC_API_KEY.
ANTHROPIC_API_KEY = (os.environ.get("ROBOT_ANTHROPIC_API_KEY")
                     or os.environ.get("ANTHROPIC_API_KEY", ""))
PHANTOMBUSTER_API_KEY = os.environ.get("PHANTOMBUSTER_API_KEY", "")

# --- Modèle IA (Note IA + contrôle d'identité) ---
# Adoption automatique du Sonnet le plus récent (décision de Samuel, 26/08/2026,
# risques de dérive de calibration et de rupture API acceptés) : à chaque
# exécution, la Models API donne le dernier Sonnet publié. Repli sur le dernier
# modèle connu si l'annuaire est injoignable.
MODELE_IA_DEFAUT = "claude-sonnet-5"
_modele_ia = None


def modele_ia() -> str:
    """Identifiant du Sonnet le plus récent, résolu une fois par exécution
    via GET /v1/models (le plus grand created_at parmi les claude-sonnet-*)."""
    global _modele_ia
    if _modele_ia:
        return _modele_ia
    import json
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/models?limit=100",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=30) as r:
            modeles = json.load(r)["data"]
        sonnets = [m for m in modeles if m["id"].startswith("claude-sonnet-")]
        _modele_ia = max(sonnets, key=lambda m: m["created_at"])["id"]
        print(f"Modèle IA : {_modele_ia} (Sonnet le plus récent selon la Models API)")
    except Exception as e:
        _modele_ia = MODELE_IA_DEFAUT
        print(f"⚠️ Models API injoignable ({str(e)[:120]}) — "
              f"repli sur {MODELE_IA_DEFAUT}. À signaler dans le rapport.")
    return _modele_ia

# --- Airtable (base "Sourcing - principal", ex-"Scrapping Pappers") ---
AIRTABLE_BASE_ID = "appdJUoNvhEi5jsJr"
TABLE_ENTREPRISES = "tblxNwg1hpC3xbVgA"
TABLE_FONDATEURS = "tblBngzHytB48MiDK"
TABLE_SCORING = "tblHdqhFxJsxSLFeR"
TABLE_JOURNAL = "tblbGtPsnQziEQBKu"
TABLE_PROMPTS = "tbldJBKx98TinftI5"

# Le barème de la Note IA vit dans Airtable (table Prompts), éditable par
# Samuel sans toucher au code ; robot/note_ia_prompt.md n'est que la copie
# de secours si Airtable est inaccessible.
NOM_PROMPT_BAREME = "Barème note fondateur /20"
CHAMPS_PROMPTS = {
    "nom": "fldqy8DhVodTXOdPw",
    "contenu": "fld41v3vTeviLavRW",
}

# IDs de champs (stables tant que les colonnes ne sont pas supprimées).
# Les payloads REST utilisent ces IDs, jamais les noms.
CHAMPS_ENTREPRISES = {
    "denomination": "fldfTLBoSAhwy8qyw",
    "siren": "fldhrLcB6coMEvZze",
    "date_immat": "fldExc1B8lRcCCtw4",
    "date_creation": "fldYRFPsDP64OLGki",
    "forme": "fldTeHoJqyTajFVn9",
    "naf": "fldlIcLOcqlSDpkMw",
    "libelle_naf": "fldRm89qChDwSNrlC",
    "ville": "fld6rNg3xPODZyPsk",
    "dept": "fldYSUDBnaAQPiKBF",
    "capital": "fldQboySuwu1YdkT8",
    "cercle": "fldHbV0YbbEEoU096",
    "lien_pappers": "fldBRVa9S7lEttRhP",
}
CHAMPS_FONDATEURS = {
    "nom_complet": "fld7WKOhWhnUMDQMo",
    "prenom": "fldCh0cSd09qsCyW0",
    "nom": "fldUVawLlUI8jCOqs",
    "age": "fld4aLcd12SoatOec",
    "qualite": "fldXs4LLWRFCzZ4vX",
    "ville": "fldFMhPBQaBibMqgx",
    "entreprise": "fldNFWeKSmZ5U6M7V",
    "linkedin_url": "fldOuQobUTZdWT8iz",
    "statut": "flddKwLMI63aBsSZQ",
    "methode": "fldgf0zCUWs3jT2qB",
    "score": "fld9vwNO3qNOoqbe4",
    "detail": "fldI248T6i6a9qvYA",
    "resume": "fldcCc78Gb1WGWoUL",
    "siren_cible": "fldJAGwDDXJBbT8fZ",
    "json": "fldPNLJDDdWPWvAMg",
    "note_ia": "fldDARjR1pwhcxxxM",
    "justification": "fldyQkdNmlJWjLXxv",
    "anomalie": "flddifOPKnUCBSfC4",
}
# --- Table Revue (vue unique du matin, peuplée par robot/revue.py) ---
TABLE_REVUE = "tblcAnzoiOw7qt8WA"
CHAMPS_REVUE = {
    "nom": "flddePs8CZVZSaBrb",
    "jour": "fld6t6EznkJZHdeoI",
    "vu": "fldKWtoL0YIjzacas",
    "slug": "fldKcKG8qWrvJMH9j",
    "societe": "fldfp6DWTzXQC5pf0",
    "role": "fld4jtjTyenRAV7z2",
    "ville": "fldSCH5y0u0JHpz5V",
    "url": "fldpoXEPm8jKOHlCV",
    "resume": "fldGnmzJ2ONfbvhKt",
}
# Les 4 canaux sources de la Revue. Par canal : la table, le champ lien dans
# Revue, et les champs lus par robot/revue.py. Le « Jour » d'une ligne Revue
# est la date du run qui l'a découverte (pas une date lue dans le canal).
CANAUX_REVUE = {
    "Pappers": {
        "table": TABLE_FONDATEURS, "lien": "fldSUju9p2xxMxN8q",
        "slug": "fldKJi3KPb9iayqF9", "nom": "fld7WKOhWhnUMDQMo",
        "societe": None,  # résolue via SIREN cible -> table Entreprises
        "siren": "fldJAGwDDXJBbT8fZ",
        "role": "fldXs4LLWRFCzZ4vX", "ville": "fldFMhPBQaBibMqgx",
        "url": "fldOuQobUTZdWT8iz", "resume": "fldcCc78Gb1WGWoUL",
    },
    "Evertrace": {
        "table": "tblaGXJ4SVt6e2fiZ", "lien": "fld4bea7jnTcJtd0o",
        "slug": "fld8VNAClakASMQD0", "nom": "fldZOghQZeIbXmaaw",
        "societe": "fldHd5nMMarZXJfBr", "siren": None,
        "role": "fldYLO4a0f1QvbUSP", "ville": "fld5sIZkwdRiW8Ryn",
        "url": "fldi3bz9aD7JKllBO", "resume": None,
    },
    "The Veck FR": {
        "table": "tblVJTIAezbM0Ab3H", "lien": "fldHxjvsEVyA3M3tx",
        "slug": "fldNJmSiYyqNKl7Ne", "nom": "fldqipns2LcS1pqKl",
        "societe": "fldn2XYF87r7FxFDd", "siren": None,
        "role": "fldUg89nFyAmAeS7A", "ville": "fldMwjqqFtwqfRo2U",
        "url": "fldvwnMeeEWDKvDTu", "resume": "fldDZS49vHPlQ8KWi",
    },
    "The Veck INT": {
        "table": "tbl4pb4ypjImweUYw", "lien": "fldCqG5KCs8l3eMRH",
        "slug": "fldyf6j8piyVx1nzl", "nom": "fldcUAt9KPXDMkPK0",
        "societe": "fldLk3r4GnBMyb0rW", "siren": None,
        "role": "fldY8fActQC9M56qV", "ville": "fldvopfGFV4040ecp",
        "url": "fldMwAIZbkxpdj6nf", "resume": "fldrU1YQqBo04plxx",
    },
}
# Champs « Vu » des 4 tables sources (pour marquer une ligne Revue déjà vue
# dès sa création, sans dépendre de l'ordre d'activation des automatisations)
VU_SOURCES_REVUE = {
    "Pappers": "fldEFrlCmXUUXVKPb", "Evertrace": "fldtqIag2QHUovJOm",
    "The Veck FR": "fldzzgO6aNt9EBxmy", "The Veck INT": "fldM0T13qJo1HLF9e",
}

CHAMPS_SCORING = {
    "nom": "fldvdr7IADGRDYyG6",
    "points": "fldYH2QUzs5ewKsap",
}
CHAMPS_JOURNAL = {
    "date_traitee": "fldKieRbvDVm3Dco8",
    "bruts": "fldLxXqXkAbGR1lU2",
    "bruts_coeur": "fld6rwWkS7lnBmbgV",
    "gardes": "fldO2aWpzwENTtqGT",
    "inseres": "fldxKHj8ggInGxFJJ",
    "jetons": "fldwxew9bvypCXTH8",
    "notes": "fldIUKYqke6xnHAX4",
}

# Champs utiles d'un profil LinkedIn scrapé (PhantomBuster) — partagés par
# le scraping (détection des scrapes vides), le contrôle d'identité et la
# Note IA (extrait compact envoyé aux modèles).
CHAMPS_PROFIL = [
    "linkedinHeadline", "location", "companyName", "linkedinJobTitle",
    "linkedinJobDateRange", "previousCompanyName", "linkedinPreviousJobTitle",
    "linkedinPreviousJobDateRange", "linkedinSchoolName", "linkedinSchoolDegree",
    "linkedinSchoolDateRange", "linkedinPreviousSchoolName",
    "linkedinPreviousSchoolDegree", "linkedinDescription",
    "linkedinFollowersCount", "linkedinConnectionsCount",
]

# --- PhantomBuster (agents existants du compte) ---
PHANTOM_URL_FINDER_ID = "6409925669476364"   # Deal Flow - Linkedin Profile URL Finder
PHANTOM_SCRAPER_ID = "4668942683298432"      # Deal Flow - Linkedin Profile Scraper
# Plafond de profils scrapés par jour. PhantomBuster indique 1000-1500/jour
# sans risque sur un compte LinkedIn standard ; 250 garde une marge x4-6
# (compte partagé avec d'autres automatisations). Toujours séquentiel.
SCRAPE_DAILY_CAP = 250

# --- Périmètre Pappers ---
# Formes juridiques : SAS (5710) et SASU (5720)
CATEGORIES_JURIDIQUES = "5710,5720"

# Cercle cœur : inclus d'office
NAF_COEUR = [
    "5821Z",  # Édition de jeux électroniques
    "5829A", "5829B", "5829C",  # Édition de logiciels
    "6201Z",  # Programmation informatique
    "6202A", "6202B",  # Conseil informatique / maintenance
    "6203Z", "6209Z",  # Gestion d'installations / autres activités informatiques
    "6311Z", "6312Z",  # Data, hébergement, portails internet
    "7211Z",  # R&D biotechnologie
    "7219Z",  # R&D autres sciences physiques et naturelles (deeptech)
    "2611Z", "2620Z", "2630Z", "2651B",  # Hardware / électronique / instrumentation
    "2720Z",  # Batteries
    "3030Z",  # Aéronautique / spatial
    "2110Z",  # Pharma
]

# Cercle périphérie : inclus seulement si l'objet social matche un mot-clé tech
# (requêtes serveur Pappers : 1 requête par mot-clé, dédupliquées par SIREN)
NAF_PERIPHERIE = [
    "7022Z",  # Conseil pour les affaires (gros gisement caché)
    "7490B",  # Activités scientifiques et techniques diverses
    "7112B",  # Ingénierie, études techniques
    "6419Z", "6499Z", "6630Z",  # Fintech
    "4791A", "4791B",  # E-commerce / D2C
    "8690F", "8610Z",  # Santé
    "7220Z",  # R&D sciences humaines
    "8559A", "8559B",  # Edtech
]

MOTS_CLES_OBJET_SOCIAL = [
    "logiciel", "plateforme", "application", "intelligence artificielle",
    "saas", "algorithme", "data", "robot", "biotech", "medtech", "healthtech",
    "fintech", "paiement", "crypto", "blockchain", "marketplace", "e-commerce",
    "cybersécurité", "cloud", "capteur", "dispositif médical", "numérique",
    "digital", "technologie",
]

# --- Filtres fondateurs ---
AGE_MAX = 45           # exclu si âge >= AGE_MAX ; conservé si âge inconnu
SERIAL_GERANT_MIN = 6  # exclu si la personne dirige déjà >= N sociétés
QUALITES_EXCLUES = {
    "Commissaire aux comptes titulaire",
    "Commissaire aux comptes suppléant",
}

# Liste noire : mots (sans accents, majuscules) cherchés dans la dénomination sociale.
# S'enrichit au fil de l'eau en observant les faux positifs.
BLACKLIST_DENOMINATION = [
    "HOLDING", "IMMOBILI", "PATRIMOINE", "MARCHAND DE BIENS", "FONCIER",
    "LOCATI", "CONCIERGERIE", "VTC", "TAXI", "SECURITE", "NETTOYAGE",
    "COIFF", "ESTHETIQ", "BOULANGER", "PIZZA", "RESTAURANT", "GARAGE",
    "RENOVATION", "MACONNERIE", "BATIMENT", "PLOMBERIE", "ELAGAGE",
    "AUTO-ECOLE", "TRANSPORT",
]

# --- Fenêtres de tirage (anti-doublons, voir docs/PILOTE.md) ---
# Tirage quotidien : immatriculations de J-2 (une seule fois par date).
# Rattrapage hebdomadaire : re-balayage des 7 derniers jours, doublons écartés par SIREN.
JOURS_DECALAGE = 2
