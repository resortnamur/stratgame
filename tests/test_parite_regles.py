"""Parite moteur <-> x45 des regles de jeu (etape 1b.2, tranche A).

Pour chaque sauvegarde, l'etat est charge des deux cotes (x45 headless et
moteur) puis les regles portees sont comparees :
- revenus (``calculate_player_income``) pour chaque joueur, ONU compris ;
- limite de deplacements et connectivite (``can_move_between``) ;
- detection du vainqueur (``check_winner`` + raison) ;
- renforts de fin de tour (``grant_reinforcements``) : meme germe aleatoire
  des deux cotes, comparaison des messages puis de l'etat complet.

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
from moteur import regles

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_parite_x45 import ALLIANCE_LIST_KEYS, SET_LIKE_KEYS

SAVES_DIR = Path(__file__).resolve().parents[1] / "parties_en_cours"
RANDOM_SEED = 20260722


def iter_save_files():
    return sorted(SAVES_DIR.glob("*.json"))


class TestPariteRegles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
        try:
            import x45
        except Exception as exc:
            raise unittest.SkipTest(f"x45 non importable ici : {exc}")
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
        # Meme normalisation d'ordre que test_parite_x45 : les ensembles et
        # listes d'alliances sont compares independamment de leur ordre.
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

    def test_parite_des_regles(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)

                # --- Revenus ---
                for player in [*range(state.num_players), state.onu_player_id]:
                    self.assertEqual(
                        game.calculate_player_income(player),
                        regles.calculate_player_income(state, player),
                        f"revenu divergent pour J{player + 1}",
                    )

                # --- Limite de deplacements ---
                for player in range(state.num_players):
                    self.assertEqual(
                        game.get_end_turn_move_limit(player),
                        regles.get_end_turn_move_limit(state, player),
                        f"limite de deplacements divergente pour J{player + 1}",
                    )

                # --- Connectivite des deplacements ---
                owned_ids = [
                    terr.id for terr in state.territories
                    if terr.owner == state.current_player
                ][:10]
                sample_pairs = [(a, b) for a in owned_ids for b in owned_ids]
                sample_pairs += [(a, b) for a in range(5) for b in range(5, 10)
                                 if b < len(state.territories)]
                for a, b in sample_pairs:
                    self.assertEqual(
                        game.can_move_between(game.territories[a], game.territories[b]),
                        regles.can_move_between(state, state.territories[a], state.territories[b]),
                        f"connectivite divergente {a} -> {b}",
                    )

                # --- Vainqueur ---
                x45_winner = game.check_winner()
                engine_winner, engine_reason = regles.evaluate_winner(state)
                self.assertEqual(x45_winner, engine_winner, "vainqueur divergent")
                self.assertEqual(
                    game.last_victory_reason, engine_reason,
                    "raison de victoire divergente",
                )

                # --- Renforts (mutation, en dernier) ---
                for player in regles.get_active_players(state):
                    game.message = ""
                    random.seed(RANDOM_SEED + player)
                    game.grant_reinforcements(player)
                    x45_message = game.message

                    random.seed(RANDOM_SEED + player)
                    report = regles.grant_reinforcements(state, player)
                    engine_message = report.message if report else ""
                    self.assertEqual(
                        x45_message, engine_message,
                        f"message de renforts divergent pour J{player + 1}",
                    )

                self.assertEqual(
                    self.as_json(game.build_game_payload()),
                    self.as_json(state.to_payload()),
                    "etat divergent apres les renforts",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
