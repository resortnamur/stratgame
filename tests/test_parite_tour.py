"""Parite moteur <-> x45 de la boucle de tour (etape 1c.1).

x45 delegue desormais sa boucle de tour au moteur ; ce test verifie que le
chemin x45 (GraphicalGame + wrappers d'interface) et le chemin pur
(GameState + moteur.actions) produisent exactement le meme etat :

- pour chaque sauvegarde, on enchaine plusieurs fins de tour completes
  (``complete_turn`` cote x45, ``advance_turn`` cote moteur) avec le meme
  germe aleatoire, en comparant l'etat serialise apres chaque tour ;
- le vocabulaire d'actions (``apply_action``) est aussi exerce cote moteur :
  transitions de phase, refus attendus, attaque et deplacement.

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
from test_parite_x45 import ALLIANCE_LIST_KEYS, SET_LIKE_KEYS

SAVES_DIR = Path(__file__).resolve().parents[1] / "parties_en_cours"
RANDOM_SEED = 20260722
TURNS_TO_SIMULATE = 6


def iter_save_files():
    return sorted(SAVES_DIR.glob("*.json"))


class TestPariteTour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
        try:
            import x45
        except Exception as exc:
            raise unittest.SkipTest(f"x45 non importable ici : {exc}")
        x45.tk = None
        x45.messagebox = None
        cls.x45 = x45
        cls.game = x45.GraphicalGame()

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

    def test_parite_des_fins_de_tour(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)
                cell_width = game.cell_width
                cell_height = game.cell_height

                for turn_index in range(TURNS_TO_SIMULATE):
                    random.seed(RANDOM_SEED + turn_index)
                    game.complete_turn()
                    x45_winner = game.phase == "game_over"

                    random.seed(RANDOM_SEED + turn_index)
                    report = actions.advance_turn(state, cell_width, cell_height)
                    engine_winner = report.winner is not None

                    self.assertEqual(
                        x45_winner, engine_winner,
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

    def test_vocabulaire_des_actions(self):
        path = self.save_files[0]
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        random.seed(RANDOM_SEED)
        state = GameState.from_payload(payload)
        regles.sanitize_after_load(state)
        cell_width, cell_height = 1200 / state.cols, 620 / state.rows

        def act(action):
            return actions.apply_action(state, action, cell_width, cell_height)

        # Action inconnue et phases invalides.
        self.assertEqual(act({"type": "danser"}).code, "action_inconnue")
        state.turn_phase = "attack"
        self.assertEqual(act({"type": "deplacer", "source": 0, "cible": 1}).code, "phase_invalide")
        self.assertEqual(act({"type": "fin_de_tour"}).code, "phase_invalide")
        self.assertEqual(act({"type": "terminer_achats"}).code, "phase_invalide")

        # Attaque : cible invalide vs cible valide.
        outcome = act({"type": "attaquer", "source": 0, "cible": 99999})
        self.assertEqual(outcome.code, "territoire_invalide")
        attack_pair = None
        for src in state.territories:
            if src.owner != state.current_player:
                continue
            for neighbor_id in src.neighbors:
                dst = state.territories[neighbor_id]
                if regles.can_attack_specific_target(state, src, dst):
                    attack_pair = (src.id, dst.id)
                    break
            if attack_pair:
                break
        if attack_pair:
            outcome = act({"type": "attaquer", "source": attack_pair[0], "cible": attack_pair[1]})
            self.assertTrue(outcome.ok)
            self.assertEqual(len(outcome.attack_passes), 1)

        # Transitions de phase : attaque -> achats (humain) ou deplacement (IA),
        # puis achats -> deplacement, puis fin de tour.
        outcome = act({"type": "terminer_attaque"})
        self.assertTrue(outcome.ok)
        if outcome.next_phase == "shopping":
            self.assertEqual(state.phase, "shopping")
            outcome = act({"type": "terminer_achats"})
            self.assertTrue(outcome.ok)
        self.assertEqual(state.turn_phase, "move")
        self.assertEqual(state.phase, "playing")

        # Deplacement valide si une paire connectee existe.
        move_pair = None
        for src in state.territories:
            if src.owner != state.current_player or src.regiments < 2:
                continue
            for neighbor_id in src.neighbors:
                dst = state.territories[neighbor_id]
                if dst.owner == state.current_player:
                    move_pair = (src.id, dst.id)
                    break
            if move_pair:
                break
        if move_pair:
            before = state.turn_move_count
            outcome = act({"type": "deplacer", "source": move_pair[0], "cible": move_pair[1]})
            self.assertTrue(outcome.ok)
            self.assertEqual(state.turn_move_count, before + 1)

        # Fin de tour : le tour avance et la phase revient a l'attaque.
        previous_player = state.current_player
        outcome = act({"type": "fin_de_tour"})
        self.assertTrue(outcome.ok)
        self.assertIsNotNone(outcome.turn_report)
        self.assertEqual(state.turn_phase, "attack")


if __name__ == "__main__":
    unittest.main(verbosity=2)
