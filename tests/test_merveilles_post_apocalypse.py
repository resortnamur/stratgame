"""Les deux merveilles d'apres la fin : Bastion de Cendres, Gouffre de Diamant.

Rien ne les ouvre tant que le Sceau de l'Apocalypse n'est pas ferme. Une fois
le monde eteint, elles se batissent comme les autres, 300 ecus, sans seuil de
science ni de culture, par n'importe qui :

* le Bastion de Cendres donne cinq renforts par tour a son territoire, et ce
  gisement-la ne s'epuise pas au bout de vingt tours ;
* le Gouffre de Diamant rapporte cent ecus par tour, hors de la division par
  dix de l'age de tenebres, comme une mine de minerais precieux.

Les deux suivent leur territoire : les prendre, c'est les prendre.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import achats
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


def build_state(owners=(0, 1, 0, 1), ia_players=(1,), money=10_000, turn=70, sceau=None):
    """Partie minimale ; ``sceau`` ferme l'Apocalypse sur ce territoire."""
    state = GameState.from_map_payload(build_map_payload(len(owners)))
    state.num_players = max(owners) + 1
    state.initial_num_players = state.num_players
    state.current_player = 0
    state.turn = turn
    state.phase = "playing"
    state.turn_phase = "attack"
    state.base_ai_players = set(ia_players)
    state.player_money = {joueur: money for joueur in range(state.num_players)}
    state.player_science = {joueur: 0 for joueur in range(state.num_players)}
    for terr, owner in zip(state.territories, owners):
        terr.owner = owner
        terr.regiments = 5
    if sceau is not None:
        state.wonder_territories["apocalypse_seal"] = sceau
        state.territories[sceau].reinforcement_bonus = (
            regles.APOCALYPSE_TERRITORY_REINFORCEMENT_BONUS
        )
    return state


def batir(state, territoire_id, wonder_type, joueur=None):
    if joueur is not None:
        state.current_player = joueur
    return achats.construire_merveille(state, state.territories[territoire_id], wonder_type)


class TestOuverture(unittest.TestCase):
    """Le Sceau ferme est leur seule condition — mais il est obligatoire."""

    MERVEILLES = ("cinder_bastion", "diamond_chasm")

    def test_ce_sont_bien_des_merveilles_d_apres_la_fin(self):
        for wonder_type in self.MERVEILLES:
            with self.subTest(merveille=wonder_type):
                self.assertTrue(regles.is_post_apocalypse_wonder_type(wonder_type))
                self.assertFalse(regles.is_ai_wonder_type(wonder_type))
                self.assertFalse(regles.is_late_wonder_type(wonder_type))
                self.assertFalse(regles.is_cultural_wonder_type(wonder_type))

    def test_rien_tant_que_le_sceau_n_est_pas_ferme(self):
        """Meme au tour 200, un monde debout ne les connait pas."""
        for wonder_type in self.MERVEILLES:
            with self.subTest(merveille=wonder_type):
                state = build_state(turn=200)
                self.assertNotIn(wonder_type, regles.get_buildable_wonder_types(state, 0))
                resultat = batir(state, 0, wonder_type)
                self.assertFalse(resultat.ok)
                self.assertNotIn(wonder_type, state.wonder_territories)
                self.assertEqual(state.player_money[0], 10_000)

    def test_le_sceau_ferme_les_ouvre_a_tous(self):
        """Ni science ni culture : un humain a zero les batit comme une IA."""
        for wonder_type in self.MERVEILLES:
            for joueur, territoire in ((0, 0), (1, 1)):
                with self.subTest(merveille=wonder_type, joueur=joueur):
                    state = build_state(sceau=3)
                    self.assertIn(
                        wonder_type, regles.get_buildable_wonder_types(state, joueur),
                    )
                    resultat = batir(state, territoire, wonder_type, joueur=joueur)
                    self.assertTrue(resultat.ok, resultat.message)
                    self.assertEqual(state.wonder_territories[wonder_type], territoire)

    def test_le_prix_est_de_trois_cents_pour_tous(self):
        state = build_state(sceau=3)
        for wonder_type in self.MERVEILLES:
            for joueur in (0, 1):
                with self.subTest(merveille=wonder_type, joueur=joueur):
                    self.assertEqual(
                        regles.get_wonder_cost(state, joueur, wonder_type),
                        regles.WONDER_COST,
                    )
        self.assertEqual(regles.WONDER_COST, 300)

    def test_une_seule_merveille_par_tour(self):
        state = build_state(sceau=3)
        self.assertTrue(batir(state, 0, "cinder_bastion").ok)
        deuxieme = batir(state, 2, "diamond_chasm")
        self.assertFalse(deuxieme.ok)
        state.turn += 1
        self.assertTrue(batir(state, 2, "diamond_chasm").ok)


class TestBastionDeCendres(unittest.TestCase):
    """Un +5 que le temps n'epuise pas, dans un monde ou rien ne repousse."""

    def build(self):
        state = build_state(sceau=3)
        self.assertTrue(batir(state, 0, "cinder_bastion").ok)
        return state

    def test_le_territoire_passe_a_cinq_renforts(self):
        state = self.build()
        self.assertEqual(state.territories[0].reinforcement_bonus, 5)

    def test_le_gisement_ne_s_epuise_pas_apres_vingt_tours(self):
        state = self.build()
        state.turn += regles.LATE_RESOURCE_LIFETIME_TURNS + 1
        regles.rotate_expired_late_resources(state, random.Random(7))
        self.assertEqual(state.territories[0].reinforcement_bonus, 5)
        self.assertNotIn(0, state.bonus_5_spawn_turns)

    def test_aucun_compteur_de_duree_de_vie_ne_le_suit(self):
        state = self.build()
        regles.sync_late_resource_lifetimes(state)
        self.assertNotIn(0, state.bonus_5_spawn_turns)

    def test_le_bonus_est_restaure_s_il_a_ete_perdu(self):
        state = self.build()
        state.territories[0].reinforcement_bonus = 1
        regles.sync_late_resource_lifetimes(state)
        self.assertEqual(state.territories[0].reinforcement_bonus, 5)

    def test_il_suit_son_territoire(self):
        """Le prendre, c'est le prendre : le +5 ne revient pas au batisseur."""
        state = self.build()
        state.territories[0].owner = 1
        regles.sync_late_resource_lifetimes(state)
        self.assertEqual(state.territories[0].reinforcement_bonus, 5)
        self.assertTrue(regles.is_permanent_bonus_5_wonder_territory(state, 0))


class TestGouffreDeDiamant(unittest.TestCase):
    """Cent ecus par tour, hors de la division de l'age de tenebres."""

    def test_cent_ecus_de_plus_pour_son_controleur(self):
        state = build_state(sceau=3)
        avant = regles.calculate_player_income(state, 0)
        self.assertTrue(batir(state, 0, "diamond_chasm").ok)
        apres = regles.calculate_player_income(state, 0)
        self.assertEqual(apres - avant, regles.POST_APOCALYPSE_MINE_INCOME)
        self.assertEqual(regles.POST_APOCALYPSE_MINE_INCOME, 100)

    def test_le_revenu_echappe_a_la_division_par_dix(self):
        """Comme les mines : cent ecus pleins, pas dix."""
        state = build_state(sceau=3)
        state.wonder_territories["diamond_chasm"] = 0
        self.assertTrue(regles.is_apocalypse_active(state))
        self.assertGreaterEqual(
            regles.calculate_player_income(state, 0),
            regles.POST_APOCALYPSE_MINE_INCOME,
        )

    def test_il_suit_son_territoire(self):
        state = build_state(sceau=3)
        state.wonder_territories["diamond_chasm"] = 0
        avant_j2 = regles.calculate_player_income(state, 1)
        state.territories[0].owner = 1
        self.assertEqual(regles.get_post_apocalypse_mine_income(state, 0), 0)
        self.assertEqual(
            regles.get_post_apocalypse_mine_income(state, 1),
            regles.POST_APOCALYPSE_MINE_INCOME,
        )
        self.assertGreater(regles.calculate_player_income(state, 1), avant_j2)


if __name__ == "__main__":
    unittest.main()
