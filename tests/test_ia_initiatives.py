"""Initiatives economiques des IA : garnisons, forteresses, savoir.

Trois durcissements de l'IA reguliere, testes ici :

* les mercenaires achetes ne sont plus saupoudres au hasard mais poses sur
  les territoires sous pression, du plus mal garni au moins mal garni ;
* les forteresses ne s'arretent plus a un seul mur : la capitale d'abord,
  puis les frontieres chaudes, dans la limite d'un quota qui grandit avec
  l'empire ;
* les universites et les centres culturels ne sont plus limites a un par
  bloc national, ce qui ouvre enfin aux IA les paliers de science et les
  annexations culturelles.

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


NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]


def build_map_payload(count):
    """``count`` territoires alignes, chacun voisin du suivant, sans mer."""
    rows, cols = 6, 3 * count
    grid = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for index in range(count):
            for c in range(3 * index, 3 * index + 3):
                grid[r][c] = index
    return {
        "kind": "map",
        "map_mode": "standard",
        "rows": rows,
        "cols": cols,
        "grid_territory": grid,
        "territories": [
            {
                "id": index,
                "name": NAMES[index] if index < len(NAMES) else f"Terr{index}",
                "reinforcement_bonus": 1,
            }
            for index in range(count)
        ],
    }


def build_state(owners, regiments, money=0):
    """Une partie minimale ou le joueur 0 est une IA et le joueur 1 un humain."""
    state = GameState.from_map_payload(build_map_payload(len(owners)))
    state.num_players = 2
    state.initial_num_players = 2
    state.current_player = 0
    state.turn = 1
    state.phase = "playing"
    state.turn_phase = "attack"
    state.base_ai_players = {0}
    state.player_money = {0: money, 1: 0}
    for terr, owner, count in zip(state.territories, owners, regiments):
        terr.owner = owner
        terr.regiments = count
    return state


class TestPlacementDesMercenaires(unittest.TestCase):
    def test_les_renforts_vont_sur_la_frontiere_menacee(self):
        """Charlie touche l'ennemi : les quatre mercenaires y atterrissent."""
        state = build_state(owners=(0, 0, 0, 1), regiments=(1, 1, 1, 20))
        owned = [terr for terr in state.territories if terr.owner == 0]
        regles.add_regular_ai_mercenaries(state, owned, 4, random.Random(1))
        self.assertEqual(
            [terr.regiments for terr in state.territories[:3]], [1, 1, 5],
        )

    def test_les_renforts_rebouchent_le_point_le_plus_faible(self):
        """Deux fronts : le plus deficitaire se sert en premier."""
        # Alpha (10 ennemis) menace Bravo, Echo (6 ennemis) menace Delta.
        state = build_state(owners=(1, 0, 0, 0, 1), regiments=(10, 1, 1, 4, 6))
        owned = [terr for terr in state.territories if terr.owner == 0]
        regles.add_regular_ai_mercenaries(state, owned, 3, random.Random(1))
        bravo, charlie, delta = state.territories[1], state.territories[2], state.territories[3]
        self.assertEqual(bravo.regiments, 4)
        self.assertEqual(charlie.regiments, 1)  # l'interieur ne recoit rien
        self.assertEqual(delta.regiments, 4)

    def test_sans_frontiere_le_tirage_au_hasard_reste(self):
        """Une IA seule sur la carte repartit au hasard, sans en perdre un."""
        state = build_state(owners=(0, 0, 0), regiments=(1, 1, 1))
        owned = list(state.territories)
        regles.add_regular_ai_mercenaries(state, owned, 5, random.Random(7))
        self.assertEqual(sum(terr.regiments for terr in state.territories), 8)

    def test_un_allie_ne_compte_pas_comme_une_menace(self):
        """Pacte entre IA : Charlie n'est plus une frontiere chaude.

        Une alliance defensive achetee par un humain, elle, ne desarme
        rien : l'humain garde le droit d'attaquer (au prix de la rupture),
        la menace reste donc entiere.
        """
        state = build_state(owners=(0, 0, 0, 1), regiments=(1, 1, 1, 20))
        charlie = state.territories[2]
        self.assertEqual(regles.get_ai_territory_threat(state, charlie, 0), 20)

        state.base_ai_players = {0, 1}
        key = regles.normalize_ai_alliance_key(0, 1)
        state.active_ai_alliances[key] = state.turn + regles.ALLIANCE_DURATION_TURNS
        self.assertEqual(regles.get_ai_territory_threat(state, charlie, 0), 0)


class TestForteressesDesIa(unittest.TestCase):
    def test_le_quota_grandit_avec_l_empire(self):
        self.assertEqual(regles.get_ai_fortress_quota(3), 1)
        self.assertEqual(regles.get_ai_fortress_quota(10), 3)
        self.assertEqual(regles.get_ai_fortress_quota(20), 5)

    def test_la_capitale_passe_avant_la_frontiere(self):
        state = build_state(owners=(0, 0, 0, 1), regiments=(1, 1, 1, 20))
        state.player_capital_ids[0] = 0
        owned = [terr for terr in state.territories if terr.owner == 0]
        action = regles.find_regular_ai_fortress_purchase(state, 0, owned, random.Random(1))
        self.assertIsNotNone(action)
        cost, callback = action
        self.assertEqual(cost, regles.FORTRESS_COST)
        callback()
        self.assertIn(0, state.fortress_territory_ids)

    def test_le_premier_mur_ne_se_repete_pas(self):
        """La priorite absolue s'arrete au premier mur : la suite est du superflu."""
        state = build_state(owners=(0, 0, 0, 0, 0, 0, 1), regiments=(1, 1, 1, 1, 1, 1, 20))
        state.player_capital_ids[0] = 0
        regles.add_regular_ai_fortress(state, 0)
        owned = [terr for terr in state.territories if terr.owner == 0]
        self.assertIsNone(
            regles.find_regular_ai_fortress_purchase(state, 0, owned, random.Random(1))
        )

    def test_la_deuxieme_forteresse_va_a_la_frontiere(self):
        """Capitale deja muree : le mur suivant protege le territoire expose."""
        state = build_state(
            owners=(0, 0, 0, 0, 0, 0, 1), regiments=(1, 1, 1, 1, 1, 1, 20),
            money=10 * regles.FORTRESS_COST,
        )
        state.player_capital_ids[0] = 0
        regles.add_regular_ai_fortress(state, 0)
        owned = [terr for terr in state.territories if terr.owner == 0]
        action = regles.find_regular_ai_extra_fortress_purchase(state, 0, owned, random.Random(1))
        self.assertIsNotNone(action)
        action[1]()
        self.assertIn(5, state.fortress_territory_ids)

    def test_l_interieur_des_terres_ne_recoit_pas_de_mur_supplementaire(self):
        """Aucune frontiere chaude : l'IA garde son argent apres le premier mur."""
        state = build_state(
            owners=(0, 0, 0), regiments=(1, 1, 1), money=10 * regles.FORTRESS_COST,
        )
        state.player_capital_ids[0] = 0
        regles.add_regular_ai_fortress(state, 0)
        owned = list(state.territories)
        self.assertIsNone(
            regles.find_regular_ai_extra_fortress_purchase(state, 0, owned, random.Random(1))
        )

    def test_la_reserve_de_mercenaires_est_intouchable(self):
        """Juste de quoi payer le mur : l'IA renonce et arme a la place."""
        state = build_state(
            owners=(0, 0, 0, 0, 0, 0, 1), regiments=(1, 1, 1, 1, 1, 1, 20),
            money=regles.FORTRESS_COST,
        )
        state.player_capital_ids[0] = 0
        regles.add_regular_ai_fortress(state, 0)
        owned = [terr for terr in state.territories if terr.owner == 0]
        self.assertIsNone(
            regles.find_regular_ai_extra_fortress_purchase(state, 0, owned, random.Random(1))
        )

    def test_le_quota_arrete_la_construction(self):
        state = build_state(
            owners=(0, 0, 0, 1), regiments=(1, 1, 1, 20), money=10 * regles.FORTRESS_COST,
        )
        state.player_capital_ids[0] = 0
        regles.add_regular_ai_fortress(state, 0)
        owned = [terr for terr in state.territories if terr.owner == 0]
        # Trois territoires : le quota vaut 1, la capitale l'a consomme.
        self.assertIsNone(
            regles.find_regular_ai_extra_fortress_purchase(state, 0, owned, random.Random(1))
        )


class TestSuperfluDesIa(unittest.TestCase):
    """Le chantier le plus en retard sur son quota passe devant."""

    def build(self):
        state = build_state(
            owners=(0,) * 6 + (1,), regiments=(1,) * 6 + (20,),
            money=20 * regles.UNIVERSITY_COST,
        )
        state.player_capital_ids[0] = 0
        regles.add_regular_ai_fortress(state, 0)
        return state, [terr for terr in state.territories if terr.owner == 0]

    def test_les_murs_passent_devant_quand_le_savoir_a_de_l_avance(self):
        state, owned = self.build()
        regles.add_university(state, 1)
        action = regles.find_regular_ai_surplus_development(state, 0, owned, random.Random(1))
        self.assertIsNotNone(action)
        self.assertEqual(action[0], regles.FORTRESS_COST)

    def test_le_savoir_passe_devant_quand_les_murs_ont_de_l_avance(self):
        state, owned = self.build()
        regles.add_regular_ai_fortress(state, 5)
        action = regles.find_regular_ai_surplus_development(state, 0, owned, random.Random(1))
        self.assertIsNotNone(action)
        self.assertEqual(action[0], regles.UNIVERSITY_COST)

    def test_tout_au_quota_ne_laisse_plus_rien_a_batir(self):
        state, owned = self.build()
        regles.add_regular_ai_fortress(state, 5)
        regles.add_university(state, 1)
        regles.add_cultural_center(state, 2)
        self.assertIsNone(
            regles.find_regular_ai_surplus_development(state, 0, owned, random.Random(1))
        )


class TestExpansionDuSavoir(unittest.TestCase):
    def setUp(self):
        self.state = build_state(
            owners=(0,) * 8, regiments=(1,) * 8,
            money=10 * regles.UNIVERSITY_COST,
        )
        self.owned = list(self.state.territories)

    def test_le_quota_grandit_avec_l_empire(self):
        self.assertEqual(regles.get_ai_knowledge_quota(3), 1)
        self.assertEqual(regles.get_ai_knowledge_quota(8), 2)
        self.assertEqual(regles.get_ai_knowledge_quota(20), 5)

    def test_la_science_passe_en_premier(self):
        action = regles.find_regular_ai_knowledge_expansion(
            self.state, 0, self.owned, random.Random(1),
        )
        self.assertIsNotNone(action)
        self.assertEqual(action[0], regles.UNIVERSITY_COST)

    def test_science_et_culture_alternent(self):
        """Une universite batie, le centre culturel prend son tour."""
        regles.add_university(self.state, 1)
        action = regles.find_regular_ai_knowledge_expansion(
            self.state, 0, self.owned, random.Random(1),
        )
        self.assertIsNotNone(action)
        self.assertEqual(action[0], regles.CULTURAL_CENTER_COST)

    def test_la_reserve_de_mercenaires_est_intouchable(self):
        """Juste de quoi payer l'universite : l'IA renonce et arme a la place."""
        self.state.player_money[0] = regles.UNIVERSITY_COST
        self.assertIsNone(
            regles.find_regular_ai_knowledge_expansion(
                self.state, 0, self.owned, random.Random(1),
            )
        )

    def test_le_quota_arrete_l_expansion(self):
        """Huit territoires, quota de deux : deux universites et deux centres."""
        regles.add_university(self.state, 1)
        regles.add_university(self.state, 2)
        regles.add_cultural_center(self.state, 3)
        regles.add_cultural_center(self.state, 4)
        self.assertIsNone(
            regles.find_regular_ai_knowledge_expansion(
                self.state, 0, self.owned, random.Random(1),
            )
        )

    def test_l_universite_supplementaire_fait_monter_la_science(self):
        """Deux universites rapportent deux fois plus par tour qu'une seule."""
        regles.add_university(self.state, 1)
        avec_une = regles.calculate_player_science_income(self.state, 0)
        regles.add_university(self.state, 2)
        self.assertEqual(regles.calculate_player_science_income(self.state, 0), 2 * avec_une)


if __name__ == "__main__":
    unittest.main()
