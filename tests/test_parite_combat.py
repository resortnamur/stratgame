"""Parite moteur <-> x45 du combat (etape 1b.2, tranche B).

Pour chaque sauvegarde :
- ``can_attack_specific_target`` est compare sur toutes les paires voisines
  du joueur courant ;
- un assaut complet (attaques repetees jusqu'a conquete ou epuisement) est
  resolu des deux cotes avec le meme germe aleatoire, en comparant a chaque
  passe les des, la conquete et les messages speciaux, puis l'etat complet.

Tkinter est neutralise cote x45 : la question "soumettre ?" d'une nation
humaine repond alors False, comme le moteur sans ``submit_decider``.

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
MAX_ASSAULT_PASSES = 300


def iter_save_files():
    return sorted(SAVES_DIR.glob("*.json"))


class TestPariteCombat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
        try:
            import x45
        except Exception as exc:
            raise unittest.SkipTest(f"x45 non importable ici : {exc}")
        # Sans Tkinter, x45 n'ouvre pas de dialogue de soumission et repond
        # False — meme comportement que le moteur sans submit_decider.
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

    def attackable_pairs(self, state):
        pairs = []
        for src in state.territories:
            if src.owner != state.current_player:
                continue
            for neighbor_id in src.neighbors:
                pairs.append((src.id, neighbor_id))
        return pairs

    def test_parite_du_combat(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)

                # --- Cibles d'attaque valides ---
                valid_pairs = []
                for a, b in self.attackable_pairs(state):
                    x45_ok = game.can_attack_specific_target(
                        game.territories[a], game.territories[b])
                    engine_ok = regles.can_attack_specific_target(
                        state, state.territories[a], state.territories[b])
                    self.assertEqual(
                        x45_ok, engine_ok,
                        f"cible d'attaque divergente {a} -> {b}",
                    )
                    if engine_ok:
                        valid_pairs.append((a, b))

                if not valid_pairs:
                    continue

                # --- Assaut complet sur la premiere cible valide ---
                a, b = valid_pairs[0]
                random.seed(RANDOM_SEED)
                x45_passes = []
                for _ in range(MAX_ASSAULT_PASSES):
                    src, dst = game.territories[a], game.territories[b]
                    if not game.can_attack_specific_target(src, dst):
                        break
                    game.message = ""
                    att, deff, conquered = game.resolve_attack_once(src, dst)
                    x45_passes.append((
                        att, deff, conquered,
                        game.last_special_conquest_message,
                        game.last_alliance_break_message,
                        game.message,
                    ))
                    if conquered:
                        break

                random.seed(RANDOM_SEED)
                engine_passes = []
                for _ in range(MAX_ASSAULT_PASSES):
                    src, dst = state.territories[a], state.territories[b]
                    if not regles.can_attack_specific_target(state, src, dst):
                        break
                    result = regles.resolve_attack_once(state, src, dst)
                    engine_passes.append((
                        result.att_text, result.def_text, result.conquered,
                        result.special_conquest_message,
                        result.alliance_break_message,
                        result.elimination_message or "",
                    ))
                    if result.conquered:
                        break

                self.assertEqual(
                    len(x45_passes), len(engine_passes),
                    "nombre de passes d'assaut divergent",
                )
                for index, (x45_pass, engine_pass) in enumerate(zip(x45_passes, engine_passes)):
                    self.assertEqual(
                        x45_pass, engine_pass,
                        f"passe d'assaut {index + 1} divergente",
                    )

                self.assertEqual(
                    self.as_json(game.build_game_payload()),
                    self.as_json(state.to_payload()),
                    "etat divergent apres l'assaut",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
