"""Étape 5 du robot : scoring déterministe d'un profil LinkedIn.

Principe : chaque école ou entreprise de la table Airtable « Scoring »
(base Scrapping Pappers) présente sur le profil du fondateur lui apporte
les points de la ligne (1 par défaut).

Matching déterministe : égalité de chaînes après normalisation légère
(minuscules, espaces multiples réduits, espaces de bord retirés). Les
accents sont CONSERVÉS : les variantes d'orthographe rencontrées sur
LinkedIn figurent comme lignes distinctes du référentiel.
"""

import re


def normaliser(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


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
