"""Parite moteur <-> x45 ORIGINAL (copie de reference d'avant delegation).

``x45-original.py`` est la copie du jeu telle qu'elle etait avant que x45 ne
delegue quoi que ce soit au moteur : elle ne contient aucune reference a
``moteur/``. C'est la reference de verite ultime : ce test charge chaque
sauvegarde dans l'original et dans le moteur pur, puis simule plusieurs fins
de tour completes (IA economique, renforts, evenements mondiaux, debut de
tour suivant) avec le meme germe aleatoire, et exige un etat serialise
strictement identique apres chaque tour.

Contrairement aux autres tests de parite (qui comparent au x45 delegue), une
reussite ici prouve la fidelite de la transcription elle-meme.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import importlib.util
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
from test_parite_x45 import ALLIANCE_LIST_KEYS, SET_LIKE_KEYS

RACINE = Path(__file__).resolve().parents[1]
SAVES_DIR = RACINE / "parties_en_cours"
ORIGINAL_PATH = RACINE / "x45-original.py"
RANDOM_SEED = 20260722
TURNS_TO_SIMULATE = 6


def iter_save_files():
    return sorted(SAVES_DIR.glob("*.json"))


def import_original_module():
    spec = importlib.util.spec_from_file_location("x45_original", ORIGINAL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["x45_original"] = module
    spec.loader.exec_module(module)
    return module


class TestPariteContreOriginal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
        if not ORIGINAL_PATH.exists():
            raise unittest.SkipTest("x45-original.py absent : reference d'origine indisponible.")
        try:
            original = import_original_module()
        except Exception as exc:
            raise unittest.SkipTest(f"x45-original non importable ici : {exc}")
        # Sans Tkinter, l'original ne peut pas ouvrir de dialogue de
        # soumission : il repond False, comme le moteur sans submit_decider.
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

    def test_chargement_identique_a_l_original(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)
                self.assertEqual(
                    self.as_json(game.build_game_payload()),
                    self.as_json(state.to_payload()),
                    "etat divergent apres chargement",
                )

    def test_fins_de_tour_identiques_a_l_original(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)
                cell_width = game.cell_width
                cell_height = game.cell_height

                for turn_index in range(TURNS_TO_SIMULATE):
                    random.seed(RANDOM_SEED + turn_index)
                    game.complete_turn()
                    original_winner = game.phase == "game_over"

                    random.seed(RANDOM_SEED + turn_index)
                    report = actions.advance_turn(state, cell_width, cell_height)
                    engine_winner = report.winner is not None

                    self.assertEqual(
                        original_winner, engine_winner,
                        f"tour {turn_index + 1}: victoire divergente",
                    )
                    if engine_winner:
                        break

                    self.assertEqual(
                        (game.current_player, game.turn, game.turn_phase),
                        (state.current_player, state.turn, state.turn_phase),
                        f"tour {turn_index + 1}: joueur/tour divergents",
                    )
                    self.assertEqual(
                        self.as_json(game.build_game_payload()),
                        self.as_json(state.to_payload()),
                        f"tour {turn_index + 1}: etat divergent",
                    )

    def test_assauts_identiques_a_l_original(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)

                attack_pair = None
                for src in state.territories:
                    if src.owner != state.current_player:
                        continue
                    for neighbor_id in src.neighbors:
                        dst = state.territories[neighbor_id]
                        if regles.can_attack_specific_target(state, src, dst):
                            attack_pair = (src.id, neighbor_id)
                            break
                    if attack_pair:
                        break
                if attack_pair is None:
                    continue
                a, b = attack_pair

                random.seed(RANDOM_SEED)
                while game.can_attack_specific_target(game.territories[a], game.territories[b]):
                    _att, _deff, conquered = game.resolve_attack_once(
                        game.territories[a], game.territories[b])
                    if conquered:
                        break

                random.seed(RANDOM_SEED)
                while regles.can_attack_specific_target(state, state.territories[a], state.territories[b]):
                    result = regles.resolve_attack_once(
                        state, state.territories[a], state.territories[b])
                    if result.conquered:
                        break

                self.assertEqual(
                    self.as_json(game.build_game_payload()),
                    self.as_json(state.to_payload()),
                    "etat divergent apres l'assaut",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
