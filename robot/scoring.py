"""Étape 5 du robot : scoring déterministe d'un profil LinkedIn.

Principe : chaque école ou entreprise de la table Airtable « Scoring »
(base Sourcing - principal) présente sur le profil du fondateur lui apporte
les points de la ligne (1 par défaut), plus 1 point pour un doctorat.

Matching tolérant (règle de Samuel : ne jamais enterrer un bon profil sur
une variante d'orthographe — un faux positif ne coûte qu'une Note IA) :
  - normalisation : minuscules, accents et ponctuation retirés, espaces
    réduits (« École Centrale  Paris » = « ecole centrale paris ») ;
  - égalité des formes normalisées ;
  - sinon l'entrée du référentiel au DÉBUT du libellé, en mots entiers
    (« Uber » ↔ « Uber Eats », « Amazon Web Services » ↔ « Amazon Web
    Services (AWS) », « INSA Lyon » ↔ « INSA Lyon - Institut National… ») ;
  - sinon le libellé au début d'une entrée, en mots entiers et s'il n'est
    pas générique (« ESCP » ↔ « ESCP Business School ») ;
  - les lycées (prépas) ne matchent qu'à l'égalité : deux lycées partagent
    souvent le début de leur nom.
Un libellé ne rapporte qu'un item (le plus long qui matche), et un même
item ne compte qu'une fois par profil. Les variantes rencontrées peuvent
toujours être ajoutées comme lignes distinctes du référentiel.
"""

import re
import unicodedata

# Programmes non diplômants ou faiblement sélectifs : la présence de l'école
# ne compte pas si le libellé du diplôme matche (aligné sur le barème de la
# Note IA : le concours est le signal, pas le nom de l'école).
DIPLOMES_NON_QUALIFIANTS = re.compile(
    r"certificat|certificate|mooc|online|executive|summer|bootcamp|open.?class",
    re.IGNORECASE,
)

# Doctorat (PhD), fini ou en cours. Le libellé de diplôme est fiable ; le
# titre et les intitulés de poste aussi quand ils disent PhD / doctorant.
# Les doctorats d'exercice (médecine, pharmacie, dentaire, vétérinaire,
# droit) ne sont pas des doctorats de recherche.
DOCTORAT_DIPLOME = re.compile(
    r"\bph\.?\s?d\b|doctor of philosophy|doctorat|doctorate|doctoral|doctor'?s degree|"
    r"\bdocteur\b|\bdoctorant",
    re.IGNORECASE,
)
DOCTORAT_TITRE = re.compile(r"\bph\.?\s?d\b|\bdoctorant|\bdocteur en\b", re.IGNORECASE)
DOCTORAT_EXERCICE = re.compile(
    r"m[ée]decin|medicine|medical|pharma|dentaire|dental|dentist|v[ée]t[ée]rinaire|"
    r"veterinary|juris|\bmd\b",
    re.IGNORECASE,
)
ITEM_DOCTORAT = "Doctorat (PhD)"

# Libellés trop génériques pour matcher le début d'une entrée du référentiel.
GENERIQUES = {
    "universite", "university", "ecole", "school", "institut", "institute",
    "lycee", "college", "groupe", "group", "freelance", "independant",
    "independent", "self employed", "stealth", "confidential", "paris",
    "france", "business school", "ecole d ingenieurs", "iut", "cpge",
}


def normaliser(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def ecoles_diplomantes(paires: list[tuple[str | None, str | None]]) -> list[str]:
    """paires : [(nom d'école, libellé du diplôme), ...] tels que scrapés.
    Écarte les écoles dont le diplôme est un MOOC / certificat / programme
    executive — un libellé absent ne disqualifie pas."""
    return [nom for nom, diplome in paires
            if nom and not (diplome and DIPLOMES_NON_QUALIFIANTS.search(diplome))]


def a_un_doctorat(diplomes: list[str | None], titres: list[str | None]) -> bool:
    """diplomes : libellés de diplôme scrapés ; titres : titre du profil et
    intitulés de poste."""
    for texte, motif in [(d, DOCTORAT_DIPLOME) for d in diplomes] + [(t, DOCTORAT_TITRE) for t in titres]:
        if texte and motif.search(texte) and not DOCTORAT_EXERCICE.search(texte):
            return True
    return False


def construire_referentiel(lignes_scoring: list[dict]) -> dict[str, dict]:
    """lignes_scoring : [{"nom": ..., "points": ..., "type": ...}, ...]
    Retourne un index {nom normalisé -> ligne}."""
    ref = {}
    for ligne in lignes_scoring:
        cle = normaliser(ligne["nom"])
        if cle and cle not in ref:
            ref[cle] = ligne
    return ref


def _debute_par(texte: str, debut: str) -> bool:
    return texte == debut or texte.startswith(debut + " ")


def trouver(referentiel: dict[str, dict], libelle: str) -> str | None:
    """Clé du référentiel qui matche le libellé (None sinon)."""
    cle = normaliser(libelle)
    if not cle:
        return None
    if cle in referentiel:
        return cle
    if cle.startswith("lycee "):  # « Lycée du Parc » ≠ « Lycée du Parc des Loges »
        return None
    candidates = [r for r in referentiel if len(r) >= 2 and _debute_par(cle, r)]
    if not candidates and cle not in GENERIQUES and len(cle) >= 4:
        candidates = [r for r in referentiel if _debute_par(r, cle)]
    return max(candidates, key=len) if candidates else None


def scorer_profil(referentiel: dict[str, dict], ecoles: list[str], entreprises: list[str],
                  doctorat: bool = False) -> tuple[int, list[str]]:
    """ecoles / entreprises : libellés exacts extraits du profil LinkedIn scrapé.

    Retourne (score, détail) où détail liste les items qui ont matché.
    Un même item du référentiel ne compte qu'une fois par profil.
    """
    matches: dict[str, dict] = {}
    for libelle in list(ecoles) + list(entreprises):
        cle = trouver(referentiel, libelle)
        if cle and cle not in matches:
            matches[cle] = referentiel[cle]
    score = sum(int(m.get("points") or 1) for m in matches.values())
    detail = [m["nom"] for m in matches.values()]
    if doctorat:
        score += 1
        detail.append(ITEM_DOCTORAT)
    return score, detail
