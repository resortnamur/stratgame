"""Parite de la mise en place d'une nouvelle partie contre x45-original.

``moteur/mise_en_place.py`` transcrit la sequence de ``start_game_session``
(x45) pour une carte sauvegardee. Ce test rejoue la meme sequence des deux
cotes avec le meme germe aleatoire — configuration des joueurs, cites
commercantes, distribution des territoires et armees (modes aleatoire et
Tribus), bonus, territoires dores, sanctuaires, economie initiale,
structures, premier debut de tour — et exige un etat serialise identique.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_parite_mise_en_place -v
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

from moteur import actions, mise_en_place

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_parite_x45 import ALLIANCE_LIST_KEYS, SET_LIKE_KEYS

RACINE = Path(__file__).resolve().parents[1]
MAPS_DIR = RACINE / "cartes_sauvegardees"
ORIGINAL_PATH = RACINE / "x45-original.py"
RANDOM_SEED = 20260723

# Un echantillon de cartes representatif (continents, continents denses,
# custom toroidales petites et grandes) et trois configurations de partie.
MAP_FILES = ["Alpha.json", "JOY.json", "CRAB01.json", "GIGA02.json", "TOILE01.json", "Zwin.json"]
CONFIGS = [
    {"num_players": 4, "ai_player_count": 2, "difficulty_level": "normal", "tribes_mode": False},
    {"num_players": 5, "ai_player_count": 3, "difficulty_level": "chaos", "tribes_mode": True},
    {"num_players": 2, "ai_player_count": 0, "difficulty_level": "gouvernement_mondial", "tribes_mode": False},
]


def import_original_module():
    spec = importlib.util.spec_from_file_location("x45_original", ORIGINAL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["x45_original"] = module
    spec.loader.exec_module(module)
    return module


def setup_original_game(game, map_payload, num_players, ai_player_count,
                        difficulty_level, tribes_mode) -> None:
    """Rejoue start_game_session sur l'original, questions remplacees par
    les parametres (miroir exact de setup_players + start_game_session)."""
    game.phase = "setup"
    game.num_players = num_players
    game.ai_player_count = ai_player_count
    game.initial_num_players = num_players
    game.initial_ai_player_count = ai_player_count
    game.difficulty_level = difficulty_level
    game.tribes_mode = tribes_mode and ai_player_count > 0
    game.base_ai_players = set(range(ai_player_count))
    game.auto_controlled_players = set()
    game.commercial_city_players = set()
    game.commercial_city_capital_ids = {}
    game.player_capital_ids = {}
    game.pending_commercial_city_spawns = 0
    game.nation_players = set()
    game.nation_qualification_start_turns = {}
    game.nation_capital_loss_start_turns = {}
    game.nation_alliances = set()
    game.nation_wars = set()
    game.cold_war_active = False
    game.cold_war_nations = None
    game.cold_war_alliances = {}
    game.colonized_players = set()
    game.submitted_territory_ids = set()
    game.submitted_territory_overlords = {}
    game.submitted_territory_created_turns = {}
    game.vassal_territory_overlords = {}
    game.vassal_territory_created_turns = {}
    game.vassal_players = {}
    game.integrated_vassal_territories = {}
    game.integrated_submitted_territories = {}
    game.union_members = {}
    game.union_original_territories = {}
    game.final_duel_active = False
    game.final_duel_champions = None
    game.final_duel_alliances = {}
    game.final_duel_pending_winner = None
    game.assign_ai_personalities()

    game.apply_saved_map(json.loads(json.dumps(map_payload)))
    game.eliminated_human_players = set()
    game.human_controlled_players = set()
    game.prepare_initial_commercial_cities()
    game.assign_initial_ownership_and_armies()
    game.assign_random_bonus_territories()
    game.assign_golden_territories()
    game.assign_sanctuary_territories()
    game.reset_economy_state()
    game.assign_initial_economic_structures()
    game.last_victory_reason = ""
    game.victory_winner = None
    game.victory_summary = {}
    game.replay_history = []
    game.replay_restore_state = None
    game.confetti_particles = []
    game.phase = "playing"
    game.turn_phase = "attack"
    game.turn_move_count = 0
    game.geopolitical_panel_visible = False
    game.geopolitical_panel_page = 0
    game.empire_panel_visible = False
    game.empire_panel_page = 0
    game.last_empire_event_turn = 0
    game.snapshot_tax_haven_turn_start_territory_counts()
    game.current_player = 0
    game.turn = 1
    game.selected_source = None
    game.selected_target = None
    game.record_replay_snapshot("Debut de la partie", force=True)
    game.begin_player_turn(game.current_player)


class TestPariteMiseEnPlace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ORIGINAL_PATH.exists():
            raise unittest.SkipTest("x45-original.py absent.")
        cls.map_files = [MAPS_DIR / name for name in MAP_FILES if (MAPS_DIR / name).exists()]
        if not cls.map_files:
            raise unittest.SkipTest("Aucune carte de test dans cartes_sauvegardees/.")
        try:
            original = import_original_module()
        except Exception as exc:
            raise unittest.SkipTest(f"x45-original non importable ici : {exc}")
        original.tk = None
        original.messagebox = None
        cls.game = original.GraphicalGame()

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

    def test_mise_en_place_identique_a_l_original(self):
        for path in self.map_files:
            with open(path, "r", encoding="utf-8") as handle:
                map_payload = json.load(handle)
            for config in CONFIGS:
                with self.subTest(carte=path.name, **config):
                    random.seed(RANDOM_SEED)
                    setup_original_game(self.game, map_payload, **config)

                    random.seed(RANDOM_SEED)
                    state = mise_en_place.nouvelle_partie(
                        json.loads(json.dumps(map_payload)), **config,
                    )
                    actions.begin_player_turn(state, state.current_player)

                    self.assertEqual(
                        self.as_json(self.game.build_game_payload()),
                        self.as_json(state.to_payload()),
                        "etat divergent apres la mise en place",
                    )

    def test_partie_neuve_jouable_par_le_moteur(self):
        """La partie creee se joue toute seule quelques tours (moteur pur)."""
        from moteur import regles

        path = self.map_files[0]
        with open(path, "r", encoding="utf-8") as handle:
            map_payload = json.load(handle)
        random.seed(RANDOM_SEED)
        state = mise_en_place.nouvelle_partie(map_payload, 4, 2)
        actions.begin_player_turn(state, state.current_player)
        cell_width, cell_height = 1200 / state.cols, 620 / state.rows

        for _ in range(20):
            if state.phase != "playing":
                break
            if regles.is_ai_player(state, state.current_player):
                if actions.play_ai_turn(state, cell_width, cell_height).winner is not None:
                    break
            else:
                outcome = actions.apply_action(
                    state, {"type": "terminer_attaque"}, cell_width, cell_height)
                self.assertTrue(outcome.ok)
                if outcome.next_phase == "shopping":
                    self.assertTrue(actions.apply_action(
                        state, {"type": "terminer_achats"}, cell_width, cell_height).ok)
                outcome = actions.apply_action(
                    state, {"type": "fin_de_tour"}, cell_width, cell_height)
                self.assertTrue(outcome.ok)
                if outcome.winner is not None:
                    break

        self.assertGreaterEqual(state.turn, 2)
        json.dumps(state.to_payload())


if __name__ == "__main__":
    unittest.main(verbosity=2)
