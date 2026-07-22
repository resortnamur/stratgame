"""Parite moteur <-> x45 ORIGINAL du tour IA complet (etape 1c.3).

Pour chaque sauvegarde : le premier joueur IA actif devient le joueur
courant des deux cotes, puis le tour IA entier est joue avec le meme germe
aleatoire — attaques (simples et totales), concentration de fin de tour,
fin de tour et debut du tour suivant.

Cote original, la machine a etats de process_ai_turn est deroulee en mode
"instant" ; cote moteur, ``actions.play_ai_turn`` fait tout d'un bloc.
Les etats doivent rester strictement identiques.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import json
import os
import random
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import actions
from moteur import regles

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_parite_original import import_original_module, ORIGINAL_PATH
from test_parite_x45 import ALLIANCE_LIST_KEYS, SET_LIKE_KEYS

SAVES_DIR = Path(__file__).resolve().parents[1] / "parties_en_cours"
RANDOM_SEED = 20260722
MAX_AI_STEPS = 3000


def iter_save_files():
    return sorted(SAVES_DIR.glob("*.json"))


class TestPariteTourIA(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
        if not ORIGINAL_PATH.exists():
            raise unittest.SkipTest("x45-original.py absent.")
        try:
            if "x45_original" in sys.modules:
                original = sys.modules["x45_original"]
            else:
                original = import_original_module()
        except Exception as exc:
            raise unittest.SkipTest(f"x45-original non importable ici : {exc}")
        original.tk = None
        original.messagebox = None
        cls.original = original
        cls.game = original.GraphicalGame()

    def load_both(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        random.seed(RANDOM_SEED)
        self.game.phase = "setup"
        self.game.apply_saved_game_state(json.loads(json.dumps(payload)))
        random.seed(RANDOM_SEED)
        state = GameState.from_payload(payload)
        regles.sanitize_after_load(state)
        return self.game, state

    def as_json(self, payload):
        payload = json.loads(json.dumps(payload))
        for key in SET_LIKE_KEYS:
            if isinstance(payload.get(key), list):
                payload[key] = sorted(payload[key])
        for key, sort_fields in ALLIANCE_LIST_KEYS.items():
            if isinstance(payload.get(key), list):
                payload[key] = sorted(
                    payload[key],
                    key=lambda item: tuple(item.get(field) for field in sort_fields),
                )
        return payload

    def first_active_ai(self, state):
        for player in regles.get_active_players(state):
            if regles.is_ai_player(state, player):
                return player
        return None

    def test_tour_ia_identique_a_l_original(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)
                ai_player = self.first_active_ai(state)
                if ai_player is None:
                    continue

                # Le joueur IA devient le joueur courant des deux cotes, avec
                # le meme tirage de comportement pour les profils "variable".
                game.current_player = ai_player
                game.ai_speed_mode = "instant"
                game.fast_ai_movements = True
                random.seed(RANDOM_SEED)
                game.reset_ai_turn_state()

                state.current_player = ai_player
                state.ai_speed_mode = "instant"
                state.fast_ai_movements = True
                random.seed(RANDOM_SEED)
                regles.prepare_ai_behavior_for_turn(state, ai_player)

                # Original : machine a etats deroulee pas a pas.
                random.seed(RANDOM_SEED + 1)
                for _ in range(MAX_AI_STEPS):
                    if game.phase != "playing" or game.current_player != ai_player:
                        break
                    game.ai_next_action_time = 0
                    game.process_ai_turn()
                original_winner = game.phase == "game_over"

                # Moteur : tour IA d'un bloc.
                random.seed(RANDOM_SEED + 1)
                report = actions.play_ai_turn(state, game.cell_width, game.cell_height)
                engine_winner = report.winner is not None

                self.assertFalse(report.skipped, "le moteur a saute le tour IA")
                self.assertEqual(
                    original_winner, engine_winner,
                    "victoire divergente pendant le tour IA",
                )
                if engine_winner:
                    continue

                self.assertEqual(
                    (game.current_player, game.turn, game.turn_phase),
                    (state.current_player, state.turn, state.turn_phase),
                    "joueur/tour divergents apres le tour IA",
                )
                self.assertEqual(
                    self.as_json(game.build_game_payload()),
                    self.as_json(state.to_payload()),
                    "etat divergent apres le tour IA",
                )

    def test_le_moteur_joue_seul(self):
        """Le moteur enchaine des tours complets sans x45 ni pygame.

        Les tours IA passent par play_ai_turn, les tours humains par le
        vocabulaire d'actions (fin de phase, fin d'achats, fin de tour).
        La partie doit avancer sans erreur et l'etat rester serialisable.
        """
        for path in self.save_files[:3]:
            with self.subTest(sauvegarde=path.name):
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                random.seed(RANDOM_SEED)
                state = GameState.from_payload(payload)
                regles.sanitize_after_load(state)
                cell_width, cell_height = 1200 / state.cols, 620 / state.rows

                starting_turn = state.turn
                for _ in range(60):
                    if state.phase != "playing":
                        break
                    if regles.is_ai_player(state, state.current_player):
                        report = actions.play_ai_turn(state, cell_width, cell_height)
                        if report.winner is not None:
                            break
                    else:
                        outcome = actions.apply_action(
                            state, {"type": "terminer_attaque"}, cell_width, cell_height)
                        self.assertTrue(outcome.ok)
                        if outcome.next_phase == "shopping":
                            outcome = actions.apply_action(
                                state, {"type": "terminer_achats"}, cell_width, cell_height)
                            self.assertTrue(outcome.ok)
                        outcome = actions.apply_action(
                            state, {"type": "fin_de_tour"}, cell_width, cell_height)
                        self.assertTrue(outcome.ok)
                        if outcome.winner is not None:
                            break

                # La partie a bien avance et l'etat reste serialisable.
                self.assertGreater(state.turn, starting_turn)
                json.dumps(state.to_payload())


if __name__ == "__main__":
    unittest.main(verbosity=2)
