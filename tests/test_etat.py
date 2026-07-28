"""Tests du moteur : fidelite de la serialisation de l'etat de partie.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v

Les tests s'appuient sur les vraies sauvegardes de parties_en_cours/.
Invariants verifies :
1. Chaque sauvegarde se charge sans erreur dans GameState.
2. La serialisation atteint un point fixe : apres un premier aller-retour
   (qui peut normaliser d'anciens formats, comme le fait x45 lui-meme),
   charger puis re-serialiser ne change plus rien, ni a l'etat ni au JSON.
3. Le JSON emis contient toutes les cles du format de sauvegarde courant.
4. La geometrie reconstruite est coherente (partition de la grille,
   voisinages symetriques).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState

SAVES_DIR = Path(__file__).resolve().parents[1] / "parties_en_cours"

# Cles attendues dans un payload de partie (miroir de build_game_payload de x45).
EXPECTED_GAME_KEYS = {
    "schema_version", "kind", "map_mode", "rows", "cols", "grid_territory",
    "territories", "terre_links", "terre_link_points", "bridge_links",
    "fragile_bridge_links", "bridge_link_points",
    "num_players", "initial_num_players", "ai_player_count",
    "initial_ai_player_count", "difficulty_level", "tribes_mode",
    "base_ai_players", "auto_controlled_players", "human_controlled_players",
    "eliminated_human_players", "ai_personalities", "ai_current_behavior",
    "commercial_city_players", "commercial_city_capital_ids",
    "player_capital_ids", "pending_commercial_city_spawns", "nation_players",
    "nation_qualification_start_turns", "nation_capital_loss_start_turns",
    "nation_alliances", "nation_wars", "cold_war_active", "cold_war_nations",
    "cold_war_alliances", "colonized_players", "submitted_territory_ids",
    "submitted_territory_overlords", "submitted_territory_created_turns",
    "vassal_territory_overlords", "vassal_territory_created_turns",
    "vassal_players", "integrated_vassal_territories",
    "integrated_submitted_territories", "union_members",
    "union_original_territories", "final_duel_active", "final_duel_champions",
    "final_duel_alliances", "final_duel_pending_winner", "fast_ai_movements",
    "ai_speed_mode", "current_player", "turn", "turn_phase", "turn_move_count",
    "last_empire_event_turn", "super_territory_ids",
    "ultra_super_territory_ids", "golden_territory_ids",
    "sanctuary_territory_ids", "onu_player_id", "player_money",
    "precious_mineral_mine_ids", "bonus_5_spawn_turns",
    "precious_mineral_mine_spawn_turns", "fortress_territory_ids",
    "fortress_capture_counts", "industry_territory_ids",
    "industry_capture_counts", "factory_territory_ids",
    "airport_territory_ids", "port_territory_ids",
    "industrial_capture_counts", "cultural_center_ages",
    "cultural_capture_counts", "university_territory_ids",
    "university_capture_counts", "university_ages", "temple_territory_ids",
    "temple_capture_counts", "religion_founders", "religion_foundation_turns",
    "religion_last_spread_turns", "religion_holy_sites",
    "religious_influence", "player_science", "culture_expansion_milestones",
    "wonder_territories", "last_stand_bonus_players",
    "last_stand_bonus_territory", "tax_haven_turn_start_territory_counts",
    "active_alliances", "active_ai_alliances", "active_offensive_alliances",
    "recent_major_events", "major_event_modal", "major_event_modal_queue",
    "pending_major_events_for_humans", "replay_history", "territories_state",
}


def iter_save_files():
    return sorted(SAVES_DIR.glob("*.json"))


class TestEtatSerialisation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")

    def load_payload(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def test_chargement_de_toutes_les_sauvegardes(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                state = GameState.from_payload(self.load_payload(path))
                self.assertGreater(state.num_players, 0)
                self.assertGreater(len(state.territories), 0)

    def test_point_fixe_de_la_serialisation(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                state1 = GameState.from_payload(self.load_payload(path))
                payload2 = state1.to_payload()
                # Le payload emis doit etre du JSON pur.
                payload2 = json.loads(json.dumps(payload2))
                state2 = GameState.from_payload(payload2)
                payload3 = state2.to_payload()
                payload3 = json.loads(json.dumps(payload3))
                self.assertEqual(payload2, payload3)
                state3 = GameState.from_payload(payload3)
                self.assertEqual(state2, state3)

    def test_cles_du_payload_completes(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                state = GameState.from_payload(self.load_payload(path))
                payload = state.to_payload()
                self.assertEqual(set(payload.keys()), EXPECTED_GAME_KEYS)

    def test_etat_conserve_apres_aller_retour(self):
        # L'information de jeu essentielle survit au premier aller-retour,
        # meme quand la normalisation ajuste des champs annexes.
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                state1 = GameState.from_payload(self.load_payload(path))
                state2 = GameState.from_payload(state1.to_payload())
                self.assertEqual(
                    [(t.id, t.name, t.owner, t.regiments, t.reinforcement_bonus) for t in state1.territories],
                    [(t.id, t.name, t.owner, t.regiments, t.reinforcement_bonus) for t in state2.territories],
                )
                for champ in (
                    "num_players", "current_player", "turn", "turn_phase",
                    "turn_move_count", "player_money", "player_science",
                    "base_ai_players", "human_controlled_players",
                    "fortress_territory_ids", "factory_territory_ids",
                    "airport_territory_ids", "port_territory_ids",
                    "university_territory_ids", "temple_territory_ids",
                    "cultural_center_ages", "religious_influence",
                    "religion_holy_sites", "wonder_territories",
                    "submitted_territory_ids", "union_members",
                    "active_alliances", "active_offensive_alliances",
                    "sanctuary_territory_ids", "golden_territory_ids",
                    "super_territory_ids", "ultra_super_territory_ids",
                    "precious_mineral_mine_ids", "commercial_city_players",
                ):
                    self.assertEqual(
                        getattr(state1, champ), getattr(state2, champ),
                        f"champ divergent apres aller-retour : {champ}",
                    )

    def test_geometrie_coherente(self):
        for path in self.save_files[:3]:
            with self.subTest(sauvegarde=path.name):
                state = GameState.from_payload(self.load_payload(path))
                # Les cellules des territoires partitionnent les cases >= 0 de la grille.
                grid_cells = {
                    (r, c)
                    for r in range(state.rows)
                    for c in range(state.cols)
                    if state.grid_territory[r][c] >= 0
                }
                territory_cells = [cell for terr in state.territories for cell in terr.cells]
                self.assertEqual(len(territory_cells), len(set(territory_cells)))
                self.assertEqual(set(territory_cells), grid_cells)
                # Voisinages symetriques.
                for terr in state.territories:
                    for neighbor_id in terr.neighbors:
                        self.assertIn(
                            terr.id,
                            state.territories[neighbor_id].neighbors,
                            f"voisinage asymetrique {terr.id} <-> {neighbor_id}",
                        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
