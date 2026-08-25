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

# --- Airtable (base "Scrapping Pappers") ---
AIRTABLE_BASE_ID = "appdJUoNvhEi5jsJr"
TABLE_ENTREPRISES = "tblxNwg1hpC3xbVgA"
TABLE_FONDATEURS = "tblBngzHytB48MiDK"
TABLE_SCORING = "tblHdqhFxJsxSLFeR"
TABLE_JOURNAL = "tblbGtPsnQziEQBKu"

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

# --- PhantomBuster (agents existants du compte) ---
PHANTOM_URL_FINDER_ID = "6409925669476364"   # Deal Flow - Linkedin Profile URL Finder
PHANTOM_SCRAPER_ID = "4668942683298432"      # Deal Flow - Linkedin Profile Scraper
SCRAPE_DAILY_CAP = 80  # plafond de profils scrapés par jour (protection du compte LinkedIn)

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
