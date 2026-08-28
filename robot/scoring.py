"""Étape 5 du robot : scoring déterministe d'un profil LinkedIn.

Principe : chaque école ou entreprise de la table Airtable « Scoring »
(base Sourcing - principal) présente sur le profil du fondateur lui apporte
les points de la ligne (1 par défaut).

Matching déterministe : égalité de chaînes après normalisation légère
(minuscules, espaces multiples réduits, espaces de bord retirés). Les
accents sont CONSERVÉS : les variantes d'orthographe rencontrées sur
LinkedIn figurent comme lignes distinctes du référentiel.
"""

import re

# Programmes non diplômants ou faiblement sélectifs : la présence de l'école
# ne compte pas si le libellé du diplôme matche (aligné sur le barème de la
# Note IA : le concours est le signal, pas le nom de l'école).
DIPLOMES_NON_QUALIFIANTS = re.compile(
    r"certificat|certificate|mooc|online|executive|summer|bootcamp|open.?class",
    re.IGNORECASE,
)


def normaliser(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def ecoles_diplomantes(paires: list[tuple[str | None, str | None]]) -> list[str]:
    """paires : [(nom d'école, libellé du diplôme), ...] tels que scrapés.
    Écarte les écoles dont le diplôme est un MOOC / certificat / programme
    executive — un libellé absent ne disqualifie pas."""
    return [nom for nom, diplome in paires
            if nom and not (diplome and DIPLOMES_NON_QUALIFIANTS.search(diplome))]


def construire_referentiel(lignes_scoring: list[dict]) -> dict[str, dict]:
    """lignes_scoring : [{"nom": ..., "points": ..., "type": ...}, ...]
    Retourne un index {nom normalisé -> ligne}."""
    ref = {}
    for ligne in lignes_scoring:
        cle = normaliser(ligne["nom"])
        if cle and cle not in ref:
            ref[cle] = ligne
    return ref


def scorer_profil(referentiel: dict[str, dict], ecoles: list[str], entreprises: list[str]) -> tuple[int, list[str]]:
    """ecoles / entreprises : libellés exacts extraits du profil LinkedIn scrapé.

    Retourne (score, détail) où détail liste les items qui ont matché.
    Un même item du référentiel ne compte qu'une fois par profil.
    """
    matches: dict[str, dict] = {}
    for libelle in list(ecoles) + list(entreprises):
        cle = normaliser(libelle)
        if cle in referentiel and cle not in matches:
            matches[cle] = referentiel[cle]
    score = sum(int(m.get("points") or 1) for m in matches.values())
    detail = [m["nom"] for m in matches.values()]
    return score, detail
