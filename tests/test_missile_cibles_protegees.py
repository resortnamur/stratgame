"""Cibles interdites au missile (regle du 06/11/2026).

Un missile ne peut frapper ni une capitale active, ni la ville x10 d'un
paradis fiscal ou d'une cite commercante, ni un territoire de l'ONU. Le
refus ne coute rien ; la doctrine IA ne vise pas non plus ces cibles.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_missile_cibles_protegees -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import achats
from moteur import ia
from moteur import regles
from tests.test_ia_doctrine_missile import (
    HAUTEUR_CELLULE, LARGEUR_CELLULE, TirageForce, build_state,
)

ARGENT = 10_000


class TestTirJoueur(unittest.TestCase):
    """J0 (humain, science maximale) vise Bravo (J1)."""

    def setUp(self):
        self.state = build_state(
            owners=(0, 1, 2), regiments=(5, 20, 30), ia_players=(), money=ARGENT,
        )
        self.state.player_science[0] = regles.SCIENCE_MISSILE_TOTAL_THRESHOLD
        self.cible = self.state.territories[1]

    def tirer(self):
        return achats.tirer_missile(self.state, self.cible, LARGEUR_CELLULE, HAUTEUR_CELLULE)

    def assert_refuse(self):
        resultat = self.tirer()
        self.assertFalse(resultat.ok)
        self.assertIn("hors d'atteinte", resultat.message)
        self.assertEqual(self.cible.regiments, 20)
        self.assertEqual(self.state.player_money[0], ARGENT)

    def test_territoire_ordinaire_atteignable(self):
        self.assertTrue(self.tirer().ok)

    def test_capitale_active(self):
        self.state.player_capital_ids[1] = 1
        self.assert_refuse()

    def test_ancienne_capitale_reste_une_cible(self):
        # Capitale de J2 prise par J1 : elle n'est plus active.
        self.state.player_capital_ids[2] = 1
        self.assertTrue(self.tirer().ok)

    def test_ville_x10_paradis_fiscal(self):
        regles.add_tax_haven_capital(self.state, 1, 1)
        self.assert_refuse()

    def test_ville_x10_cite_commercante(self):
        self.state.commercial_city_players.add(1)
        self.state.commercial_city_capital_ids[1] = 1
        self.assert_refuse()

    def test_territoire_onu(self):
        self.state.onu_player_id = 1
        self.assert_refuse()


class TestDoctrineIa(unittest.TestCase):
    """J0 (IA) face au seul humain J1 : la capitale de J1 n'est pas visee."""

    def test_l_ia_ne_vise_pas_une_capitale(self):
        state = build_state(
            owners=(0, 1), regiments=(5, 20), ia_players=(0,), money=regles.MISSILE_COST,
        )
        state.player_science[0] = regles.SCIENCE_MISSILE_THRESHOLD
        args = (state, LARGEUR_CELLULE, HAUTEUR_CELLULE, TirageForce())
        self.assertIsNotNone(ia.find_ai_missile_target(*args))
        state.player_capital_ids[1] = 1
        self.assertIsNone(ia.find_ai_missile_target(*args))


if __name__ == "__main__":
    unittest.main()
