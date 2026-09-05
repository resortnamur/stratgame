"""Les trois merveilles des IA : chancellerie, banque, rempart d'obsidienne.

Elles se batissent comme les autres, au prix ordinaire et par n'importe qui,
mais leur effet ne joue qu'entre les mains d'une IA :

* la Chancellerie de Vorlan integre une IA voisine, une chance sur dix par
  tour de jeu, territoires et regiments d'un bloc ;
* la Banque de Threl met son controleur a l'abri des krachs ;
* le Rempart d'Obsidienne ferme son territoire aux attaques humaines.

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
LARGEUR_CELLULE = 20.0
HAUTEUR_CELLULE = 20.0


class TirageForce:
    """Un rng dont ``randint`` retourne toujours la borne basse : ca passe."""

    def randint(self, borne_basse, borne_haute):
        return borne_basse

    def random(self):
        return 0.5

    def choice(self, sequence):
        return sequence[0]

    def shuffle(self, sequence):
        pass


class TirageBloque(TirageForce):
    """Le meme, mais ``randint`` rate toujours."""

    def randint(self, borne_basse, borne_haute):
        return borne_haute if borne_haute != borne_basse else borne_basse


class TirageInterdit(TirageForce):
    """Un rng qui refuse d'etre consulte : le moindre tirage leve."""

    def randint(self, borne_basse, borne_haute):
        raise AssertionError("le hasard ne doit pas etre consulte ici")

    def choice(self, sequence):
        raise AssertionError("le hasard ne doit pas etre consulte ici")


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


def build_state(owners, regiments, ia_players=(0,), money=0, turn=40):
    """Partie minimale : ``ia_players`` sont des IA, les autres des humains."""
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
    for terr, owner, count in zip(state.territories, owners, regiments):
        terr.owner = owner
        terr.regiments = count
    return state


class TestConstruction(unittest.TestCase):
    """Tout le monde les batit, au prix ordinaire, mais pas avant leur tour."""

    TOURS = {
        "vorlan_chancellery": 12,
        "threl_bank": 24,
        "obsidian_rampart": 36,
    }

    def test_les_trois_merveilles_existent_avec_leur_tour(self):
        for wonder_type, tour in self.TOURS.items():
            with self.subTest(merveille=wonder_type):
                self.assertTrue(regles.is_ai_wonder_type(wonder_type))
                self.assertEqual(regles.get_ai_wonder_first_turn(wonder_type), tour)

    def test_le_prix_est_le_meme_pour_tous(self):
        state = build_state(owners=(0, 1), regiments=(5, 5), ia_players=(0,))
        for wonder_type in self.TOURS:
            with self.subTest(merveille=wonder_type):
                self.assertEqual(
                    regles.get_wonder_cost(state, 0, wonder_type), regles.WONDER_COST,
                )
                self.assertEqual(
                    regles.get_wonder_cost(state, 1, wonder_type), regles.WONDER_COST,
                )
                self.assertEqual(regles.WONDER_COST, 300)

    def test_rien_avant_le_tour_d_ouverture(self):
        for wonder_type, tour in self.TOURS.items():
            with self.subTest(merveille=wonder_type):
                state = build_state(
                    owners=(0, 1), regiments=(5, 5), ia_players=(1,),
                    money=regles.WONDER_COST, turn=tour - 1,
                )
                resultat = achats.construire_merveille(state, state.territories[0], wonder_type)
                self.assertFalse(resultat.ok)
                self.assertNotIn(wonder_type, state.wonder_territories)
                self.assertEqual(state.player_money[0], regles.WONDER_COST)

    def test_un_humain_sans_science_ni_culture_peut_batir(self):
        """Aucun seuil : seul le tour compte, meme pour un humain a zero."""
        for wonder_type, tour in self.TOURS.items():
            with self.subTest(merveille=wonder_type):
                state = build_state(
                    owners=(0, 1), regiments=(5, 5), ia_players=(1,),
                    money=regles.WONDER_COST, turn=tour,
                )
                resultat = achats.construire_merveille(state, state.territories[0], wonder_type)
                self.assertTrue(resultat.ok, resultat.message)
                self.assertEqual(state.wonder_territories.get(wonder_type), 0)
                self.assertEqual(state.player_money[0], 0)


class TestChancellerieDeVorlan(unittest.TestCase):
    """Une chance sur dix par tour d'avaler une IA voisine."""

    def build(self, owners=(0, 1, 2), regiments=(5, 7, 9), ia_players=(0, 1, 2)):
        state = build_state(
            owners=owners, regiments=regiments, ia_players=ia_players, money=500,
        )
        state.wonder_territories["vorlan_chancellery"] = 0
        return state

    def integrer(self, state, rng=None):
        return regles.maybe_integrate_ai_player_with_wonder(state, rng or TirageForce())

    def test_l_ia_voisine_est_integree(self):
        state = self.build()
        message = self.integrer(state)
        self.assertIsNotNone(message)
        self.assertEqual(state.territories[1].owner, 0)
        self.assertEqual(state.territories[1].regiments, 7)
        self.assertNotIn(1, regles.get_active_players(state))

    def test_l_argent_et_la_science_ne_se_transmettent_pas(self):
        state = self.build()
        state.player_money[1] = 900
        state.player_science[1] = 120
        argent_avant = state.player_money[0]
        science_avant = state.player_science[0]
        self.assertIsNotNone(self.integrer(state))
        self.assertEqual(state.player_money[0], argent_avant)
        self.assertEqual(state.player_science[0], science_avant)

    def test_le_tirage_peut_faire_manquer_le_tour(self):
        state = self.build()
        self.assertIsNone(self.integrer(state, TirageBloque()))
        self.assertEqual(state.territories[1].owner, 1)

    def test_un_humain_n_en_tire_rien(self):
        """La merveille entre des mains humaines est une merveille morte."""
        state = self.build(ia_players=(1, 2))
        self.assertIsNone(self.integrer(state))
        self.assertEqual(state.territories[1].owner, 1)

    def test_un_voisin_humain_n_est_pas_integre(self):
        state = self.build(ia_players=(0, 2))
        # Seul J1 (humain) touche J0 : la Chancellerie reste sans emploi.
        self.assertIsNone(self.integrer(state))
        self.assertEqual(state.territories[1].owner, 1)

    def test_une_ia_lointaine_n_est_pas_integree(self):
        """J2 ne touche pas J0 : c'est J1, entre les deux, qui est pris."""
        state = self.build(owners=(0, 1, 2), regiments=(5, 7, 9))
        self.assertIsNotNone(self.integrer(state))
        self.assertEqual(state.territories[1].owner, 0)
        self.assertEqual(state.territories[2].owner, 2)

    def test_sans_merveille_aucun_tirage_n_est_consomme(self):
        """Une partie sans Chancellerie deroule le meme hasard qu'avant."""
        state = self.build()
        state.wonder_territories.pop("vorlan_chancellery")
        self.assertIsNone(
            regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
        )

    def test_sans_voisin_a_prendre_aucun_tirage_n_est_consomme(self):
        state = self.build(owners=(0, 0, 0))
        self.assertIsNone(
            regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
        )

    def test_l_integration_se_rejoue_tour_apres_tour(self):
        """Rien ne l'arrete : elle avale ses voisines l'une apres l'autre."""
        state = self.build(owners=(0, 1, 2), regiments=(5, 7, 9))
        self.assertIsNotNone(self.integrer(state))
        self.assertIsNotNone(self.integrer(state))
        self.assertEqual(
            [terr.owner for terr in state.territories], [0, 0, 0],
        )


class TestBanqueDeThrel(unittest.TestCase):
    """Krach et crise passent a cote de son controleur IA."""

    def build(self, ia_players=(0,)):
        state = build_state(
            owners=(0, 1), regiments=(5, 5), ia_players=ia_players, money=900,
        )
        state.wonder_territories["threl_bank"] = 0
        return state

    def test_le_controleur_ia_ne_perd_rien(self):
        state = self.build()
        message = regles.maybe_trigger_market_event(state, TirageForce())
        self.assertIsNotNone(message)
        self.assertEqual(state.player_money[0], 900)
        self.assertLess(state.player_money[1], 900)

    def test_un_controleur_humain_perd_comme_les_autres(self):
        state = self.build(ia_players=(1,))
        message = regles.maybe_trigger_market_event(state, TirageForce())
        self.assertIsNotNone(message)
        self.assertLess(state.player_money[0], 900)
        self.assertLess(state.player_money[1], 900)

    def test_sans_la_banque_tout_le_monde_perd(self):
        state = self.build()
        state.wonder_territories.pop("threl_bank")
        regles.maybe_trigger_market_event(state, TirageForce())
        self.assertLess(state.player_money[0], 900)
        self.assertLess(state.player_money[1], 900)


class TestRempartDObsidienne(unittest.TestCase):
    """Le miroir du Rempart d'Ivoire : il ferme la porte aux humains."""

    def build(self, ia_players=(1,)):
        # J0 (humain) voisin de J1 (IA), qui abrite le rempart.
        state = build_state(
            owners=(0, 1), regiments=(9, 5), ia_players=ia_players,
        )
        state.wonder_territories["obsidian_rampart"] = 1
        return state

    def test_l_humain_ne_peut_pas_attaquer(self):
        state = self.build()
        state.current_player = 0
        self.assertTrue(regles.is_territory_protected_from_human_attacks(state, 1))
        self.assertFalse(regles.can_attack_specific_target(
            state, state.territories[0], state.territories[1],
        ))

    def test_l_attaque_forcee_est_refusee(self):
        state = self.build()
        state.current_player = 0
        resultat = regles.resolve_attack_once(
            state, state.territories[0], state.territories[1], random.Random(1),
        )
        self.assertFalse(resultat.conquered)
        self.assertIn("Obsidienne", resultat.def_text)
        self.assertEqual(state.territories[1].owner, 1)

    def test_l_expedition_humaine_est_refusee(self):
        state = build_state(owners=(0, 1, 1), regiments=(9, 5, 5), ia_players=(1,))
        state.wonder_territories["obsidian_rampart"] = 2
        state.current_player = 0
        self.assertFalse(regles.can_launch_expedition(
            state, state.territories[0], state.territories[2],
            LARGEUR_CELLULE, HAUTEUR_CELLULE,
        ))

    def test_une_ia_passe_toujours(self):
        state = build_state(owners=(0, 1), regiments=(9, 5), ia_players=(0, 1))
        state.wonder_territories["obsidian_rampart"] = 1
        state.current_player = 0
        self.assertTrue(regles.can_attack_specific_target(
            state, state.territories[0], state.territories[1],
        ))

    def test_entre_des_mains_humaines_il_ne_protege_personne(self):
        state = self.build(ia_players=())
        state.current_player = 0
        self.assertFalse(regles.is_territory_protected_from_human_attacks(state, 1))
        self.assertTrue(regles.can_attack_specific_target(
            state, state.territories[0], state.territories[1],
        ))


if __name__ == "__main__":
    unittest.main()
