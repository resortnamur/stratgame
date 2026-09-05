"""Une IA dont la capitale est prisonniere d'une ile isolee demenage.

Une ile de moins de dix territoires ne peut jamais porter le bloc d'un seul
tenant exige par le statut de nation : l'IA qui y garde sa capitale n'a
aucune chance de devenir une nation. Des qu'elle possede un territoire sur
une masse de terre assez grande, elle y deplace sa capitale.

Carte synthetique 4x16 : une ile de trois territoires (cols 0-2), une mer
(cols 3-5) et un continent de dix territoires (cols 6-15).

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

ROWS, COLS = 4, 16
ILE_IDS = (0, 1, 2)                       # cols 0, 1, 2
CONTINENT_IDS = tuple(range(3, 13))       # cols 6 a 15


def build_map_payload():
    """Un territoire par colonne de terre : 3 sur l'ile, 10 sur le continent."""
    grid = [[-1] * COLS for _ in range(ROWS)]
    territories = []
    for index, col in enumerate([0, 1, 2, *range(6, 16)]):
        for row in range(ROWS):
            grid[row][col] = index
        territories.append({
            "id": index,
            "name": f"T{index}",
            "reinforcement_bonus": 1,
        })
    return {
        "kind": "map",
        "map_mode": "standard",
        "rows": ROWS,
        "cols": COLS,
        "grid_territory": grid,
        "territories": territories,
    }


def build_state(territoires_continent=(3,), argent=regles.CHANGE_CAPITAL_COST):
    """L'IA J1 tient l'ile entiere, sa capitale en 0, plus quelques colonies.

    ``territoires_continent`` liste les territoires du continent qu'elle
    possede ; le reste du continent appartient au joueur humain J2.
    """
    state = GameState.from_map_payload(build_map_payload())
    state.num_players = 2
    state.initial_num_players = 2
    state.current_player = 0
    state.turn = 20
    state.phase = "playing"
    state.turn_phase = "attack"
    state.base_ai_players = {0}
    state.ai_player_count = 1
    state.player_money = {0: argent, 1: 0}
    for terr in state.territories:
        if terr.id in ILE_IDS or terr.id in territoires_continent:
            terr.owner = 0
        else:
            terr.owner = 1
        terr.regiments = 3
    state.player_capital_ids = {0: 0, 1: CONTINENT_IDS[-1]}
    return state


class TestGeographie(unittest.TestCase):
    def test_masses_de_terre(self):
        state = build_state()
        self.assertEqual(regles.get_connected_landmass_ids(state, 0), list(ILE_IDS))
        self.assertEqual(
            regles.get_connected_landmass_ids(state, 6), list(CONTINENT_IDS),
        )

    def test_ile_isolee_detectee(self):
        state = build_state()
        for territory_id in ILE_IDS:
            self.assertTrue(regles.is_isolated_island_territory(state, territory_id))
        for territory_id in CONTINENT_IDS:
            self.assertFalse(regles.is_isolated_island_territory(state, territory_id))

    def test_un_pont_rattache_l_ile_au_continent(self):
        """L'adjacence fait la masse de terre : un pont desenclave l'ile."""
        state = build_state()
        state.bridge_links = {(2, 3)}
        state.apply_bridge_links_to_neighbors()
        self.assertFalse(regles.is_isolated_island_territory(state, 0))
        self.assertFalse(regles.ai_should_move_capital_to_mainland(state, 0))


class TestDemenagementIA(unittest.TestCase):
    def test_ia_insulaire_veut_demenager(self):
        state = build_state()
        self.assertTrue(regles.ai_should_move_capital_to_mainland(state, 0))
        cible = regles.choose_ai_mainland_capital_target(state, 0, random.Random(1))
        self.assertIsNotNone(cible)
        self.assertEqual(cible.id, 3, "le seul territoire continental possede")

    def test_pas_de_tete_de_pont_pas_de_demenagement(self):
        """Sans territoire sur le continent, l'IA reste sur son ile."""
        state = build_state(territoires_continent=())
        self.assertFalse(regles.ai_should_move_capital_to_mainland(state, 0))
        self.assertIsNone(regles.choose_ai_mainland_capital_target(state, 0, random.Random(1)))

    def test_capitale_deja_continentale_rien_a_faire(self):
        state = build_state()
        state.player_capital_ids[0] = 3
        self.assertFalse(regles.ai_should_move_capital_to_mainland(state, 0))

    def test_nation_deja_formee_ne_bouge_pas(self):
        """Une nation acquise (Capitole compris) garde sa capitale insulaire."""
        state = build_state()
        state.nation_players = {0}
        self.assertFalse(regles.ai_should_move_capital_to_mainland(state, 0))

    def test_les_humains_ne_sont_pas_concernes(self):
        state = build_state()
        state.base_ai_players = set()
        state.ai_player_count = 0
        self.assertFalse(regles.ai_should_move_capital_to_mainland(state, 0))

    def test_les_cites_commercantes_ne_sont_pas_concernees(self):
        """Leur capitale CC est figee : elles ne demenagent pas."""
        state = build_state()
        state.commercial_city_players = {0}
        state.commercial_city_capital_ids = {0: 0}
        self.assertFalse(regles.ai_should_move_capital_to_mainland(state, 0))

    def test_le_tour_economique_deplace_la_capitale(self):
        # Les merveilles passent avant tout dans un tour economique d'IA, et
        # depuis le tour 12 la Chancellerie de Vorlan est toujours a prendre :
        # il faut de quoi la batir *et* rapatrier la capitale.
        state = build_state(argent=regles.WONDER_COST + regles.CHANGE_CAPITAL_COST)
        actions_faites = regles.execute_ai_economic_actions(state, 0, random.Random(20260728))
        self.assertGreaterEqual(actions_faites, 1)
        self.assertEqual(state.player_capital_ids[0], 3, "capitale rapatriee sur le continent")
        self.assertEqual(state.player_money[0], 0, "le changement de capitale a ete paye")
        self.assertTrue(
            any("ile isolee" in evenement for evenement in state.recent_major_events),
            f"evenement manquant : {state.recent_major_events}",
        )

    def test_sans_argent_la_capitale_reste(self):
        state = build_state(argent=regles.CHANGE_CAPITAL_COST - 1)
        regles.execute_ai_economic_actions(state, 0, random.Random(20260728))
        self.assertEqual(state.player_capital_ids[0], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
