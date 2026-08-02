"""Universites et renforts du dernier territoire.

Regle habituelle : un renfort qui tombe sur un territoire a universite est
converti en 10 ecus au lieu d'un regiment. Exception introduite ici : un
joueur reduit a son dernier territoire touche ses renforts en regiments,
meme sous une universite — elle ne doit pas l'asphyxier en le privant de sa
seule source de troupes.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import regles


def build_map_payload():
    """Trois territoires cote a cote, sans mer."""
    rows, cols = 6, 9
    grid = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(3, 6):
            grid[r][c] = 1
        for c in range(6, 9):
            grid[r][c] = 2
    return {
        "kind": "map",
        "map_mode": "standard",
        "rows": rows,
        "cols": cols,
        "grid_territory": grid,
        "territories": [
            {"id": 0, "name": "Alpha", "reinforcement_bonus": 1},
            {"id": 1, "name": "Bravo", "reinforcement_bonus": 1},
            {"id": 2, "name": "Charlie", "reinforcement_bonus": 1},
        ],
    }


def build_state(owners):
    state = GameState.from_map_payload(build_map_payload())
    state.num_players = 2
    state.initial_num_players = 2
    state.current_player = 0
    state.turn = 1
    state.phase = "playing"
    state.turn_phase = "move"
    state.player_money = {0: 0, 1: 0}
    for terr, owner in zip(state.territories, owners):
        terr.owner = owner
        terr.regiments = 3
    return state


class TestConversionHabituelle(unittest.TestCase):
    def test_conversion_en_ecus_avec_plusieurs_territoires(self):
        """Deux territoires ou plus : l'universite convertit toujours."""
        state = build_state(owners=(0, 0, 1))
        alpha = state.territories[0]
        regles.add_university(state, alpha.id)
        converti = regles.place_end_turn_reinforcement(state, alpha, 0)
        self.assertTrue(converti)
        self.assertEqual(alpha.regiments, 3)
        self.assertEqual(state.player_money[0], 10)

    def test_pas_de_conversion_sans_universite(self):
        state = build_state(owners=(0, 0, 1))
        bravo = state.territories[1]
        converti = regles.place_end_turn_reinforcement(state, bravo, 0)
        self.assertFalse(converti)
        self.assertEqual(bravo.regiments, 4)
        self.assertEqual(state.player_money[0], 0)


class TestDernierTerritoire(unittest.TestCase):
    def test_le_dernier_territoire_recoit_ses_regiments(self):
        """Un seul territoire : l'universite n'etouffe plus les renforts."""
        state = build_state(owners=(0, 1, 1))
        alpha = state.territories[0]
        regles.add_university(state, alpha.id)
        converti = regles.place_end_turn_reinforcement(state, alpha, 0)
        self.assertFalse(converti)
        self.assertEqual(alpha.regiments, 4)
        self.assertEqual(state.player_money[0], 0)

    def test_renforts_de_fin_de_tour_sur_le_dernier_territoire(self):
        """grant_reinforcements pose bien des regiments, sans conversion."""
        state = build_state(owners=(0, 1, 1))
        alpha = state.territories[0]
        regles.add_university(state, alpha.id)
        avant = alpha.regiments
        rapport = regles.grant_reinforcements(state, 0, random.Random(1))
        self.assertEqual(rapport.kind, "renforts")
        self.assertGreater(alpha.regiments, avant)
        self.assertEqual(state.player_money[0], 0)
        self.assertNotIn("converti", rapport.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
