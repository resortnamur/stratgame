"""Les quatre merveilles des IA : deux chancelleries, une banque, un rempart.

Elles se batissent comme les autres, au prix ordinaire et par n'importe qui,
mais leur effet ne joue qu'entre les mains d'une IA :

* la Chancellerie de Vorlan integre une IA voisine, une chance sur cinq par
  tour de jeu, territoires et regiments d'un bloc ;
* la Banque de Threl met son controleur a l'abri des krachs ;
* le Conclave de Thyr fait comme la Chancellerie, une fois sur dix, et met en
  plus son controleur a l'abri des revoltes, revolutions et trahisons ; les
  deux chancelleries ne se cumulent jamais, et ni l'une ni l'autre n'absorbe
  une Cite commercante ;
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


class TirageEspion(TirageForce):
    """Le meme, mais il note les denominateurs consultes et rate toujours."""

    def __init__(self):
        self.denominateurs = []

    def randint(self, borne_basse, borne_haute):
        self.denominateurs.append(borne_haute)
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
        "thyr_conclave": 32,
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
    """Une chance sur cinq par tour d'avaler une IA voisine."""

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

    def entouree(self, regiments):
        """J0 au centre, une IA de chaque cote, la merveille sur son sol."""
        state = build_state(
            owners=(1, 0, 2), regiments=regiments, ia_players=(0, 1, 2), money=500,
        )
        state.wonder_territories["vorlan_chancellery"] = 1
        return state

    def test_la_plus_faible_des_voisines_est_prise_en_premier(self):
        """Entre deux voisines, la moins armee part la premiere."""
        state = self.entouree(regiments=(9, 5, 3))
        message = self.integrer(state)
        self.assertIn("J3", message)
        self.assertEqual(state.territories[2].owner, 0)
        self.assertEqual(state.territories[0].owner, 1)

    def test_le_choix_ne_suit_pas_l_ordre_des_joueurs(self):
        """Le meme cas, forces inversees : c'est l'autre voisine qui tombe."""
        state = self.entouree(regiments=(3, 5, 9))
        message = self.integrer(state)
        self.assertIn("J2", message)
        self.assertEqual(state.territories[0].owner, 0)
        self.assertEqual(state.territories[2].owner, 2)

    def test_a_regiments_egaux_le_plus_petit_empire_tombe(self):
        state = build_state(
            owners=(1, 0, 2, 2), regiments=(4, 5, 2, 2), ia_players=(0, 1, 2),
            money=500,
        )
        state.wonder_territories["vorlan_chancellery"] = 1
        # J1 et J2 alignent quatre regiments chacun : J1 n'en tient qu'un
        # territoire, J2 deux — c'est J1 qui est integre.
        message = self.integrer(state)
        self.assertIn("J2", message)
        self.assertEqual(state.territories[0].owner, 0)
        self.assertEqual(state.territories[2].owner, 2)

    def test_la_proie_n_est_jamais_tiree_au_sort(self):
        """Le hasard n'intervient que pour le tirage d'une chance sur cinq."""
        state = self.entouree(regiments=(9, 5, 3))

        class TirageSansChoix(TirageForce):
            def choice(self, sequence):
                raise AssertionError("la proie ne se tire pas au sort")

        self.assertIsNotNone(self.integrer(state, TirageSansChoix()))
        self.assertEqual(state.territories[2].owner, 0)

    def test_l_integration_se_rejoue_tour_apres_tour(self):
        """Elle avale ses voisines l'une apres l'autre, jusqu'au plancher."""
        state = self.build(
            owners=(0, 1, 2, 3), regiments=(5, 7, 9, 11), ia_players=(0, 1, 2, 3),
        )
        self.assertIsNotNone(self.integrer(state))
        self.assertIsNotNone(self.integrer(state))
        self.assertEqual(
            [terr.owner for terr in state.territories], [0, 0, 0, 3],
        )
        # Il ne reste que deux joueurs IA : la chancellerie s'arrete la.
        self.assertIsNone(self.integrer(state, TirageInterdit()))


class TestConclaveDeThyr(unittest.TestCase):
    """La seconde chancellerie : une fois sur dix, et rien ne la renverse."""

    def build(self, owners=(0, 1, 2), ia_players=(0, 1, 2), chancellerie=None):
        state = build_state(
            owners=owners, regiments=(5, 7, 9)[:len(owners)],
            ia_players=ia_players, money=500,
        )
        state.wonder_territories["thyr_conclave"] = 0
        if chancellerie is not None:
            state.wonder_territories["vorlan_chancellery"] = chancellerie
        return state

    def test_le_tirage_est_une_chance_sur_dix(self):
        state = self.build()
        espion = TirageEspion()
        self.assertIsNone(regles.maybe_integrate_ai_player_with_wonder(state, espion))
        self.assertEqual(espion.denominateurs, [regles.THYR_INTEGRATION_DENOMINATOR])
        self.assertEqual(regles.THYR_INTEGRATION_DENOMINATOR, 10)

    def test_il_integre_une_ia_voisine_comme_la_chancellerie(self):
        state = self.build()
        message = regles.maybe_integrate_ai_player_with_wonder(state, TirageForce())
        self.assertIsNotNone(message)
        self.assertIn(regles.get_wonder_name("thyr_conclave"), message)
        self.assertEqual(state.territories[1].owner, 0)

    def test_un_humain_n_en_tire_rien(self):
        state = self.build(ia_players=(1, 2))
        self.assertIsNone(
            regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
        )
        self.assertFalse(regles.is_player_immune_to_revolt_by_wonder(state, 0))

    def test_l_immunite_suit_le_controleur_ia(self):
        state = self.build()
        self.assertTrue(regles.is_player_immune_to_revolt_by_wonder(state, 0))
        self.assertFalse(regles.is_player_immune_to_revolt_by_wonder(state, 1))
        # Le territoire change de main : l'immunite aussi.
        state.territories[0].owner = 1
        self.assertFalse(regles.is_player_immune_to_revolt_by_wonder(state, 0))
        self.assertTrue(regles.is_player_immune_to_revolt_by_wonder(state, 1))


class TestPasDeCumulEntreLesDeuxChancelleries(unittest.TestCase):
    """Controler la premiere annule entierement la seconde."""

    def build(self, conclave=0, chancellerie=0, ia_players=(0, 1, 2)):
        state = build_state(
            owners=(0, 1, 2), regiments=(5, 7, 9), ia_players=ia_players, money=500,
        )
        state.wonder_territories["thyr_conclave"] = conclave
        state.wonder_territories["vorlan_chancellery"] = chancellerie
        return state

    def test_un_seul_tirage_quand_les_deux_sont_dans_la_meme_main(self):
        state = self.build()
        espion = TirageEspion()
        self.assertIsNone(regles.maybe_integrate_ai_player_with_wonder(state, espion))
        self.assertEqual(
            espion.denominateurs, [regles.AI_WONDER_INTEGRATION_DENOMINATOR],
        )

    def test_l_immunite_tombe_avec_le_reste(self):
        state = self.build()
        self.assertFalse(regles.is_player_immune_to_revolt_by_wonder(state, 0))

    def test_deux_mains_differentes_tirent_chacune(self):
        """J1 tient la Chancellerie, J2 le Conclave : les deux tirages ont lieu."""
        state = self.build(conclave=1, chancellerie=0)
        espion = TirageEspion()
        self.assertIsNone(regles.maybe_integrate_ai_player_with_wonder(state, espion))
        self.assertEqual(
            espion.denominateurs,
            [regles.AI_WONDER_INTEGRATION_DENOMINATOR, regles.THYR_INTEGRATION_DENOMINATOR],
        )
        self.assertTrue(regles.is_player_immune_to_revolt_by_wonder(state, 1))

    def test_la_construction_est_fermee_a_qui_tient_la_chancellerie(self):
        state = build_state(
            owners=(0, 1), regiments=(5, 5), ia_players=(0,),
            money=regles.WONDER_COST, turn=40,
        )
        state.wonder_territories["vorlan_chancellery"] = 0
        self.assertNotIn(
            "thyr_conclave", regles.get_buildable_wonder_types(state, 0),
        )
        resultat = achats.construire_merveille(
            state, state.territories[0], "thyr_conclave",
        )
        self.assertFalse(resultat.ok)
        self.assertNotIn("thyr_conclave", state.wonder_territories)
        self.assertEqual(state.player_money[0], regles.WONDER_COST)

    def test_un_autre_joueur_peut_toujours_le_batir(self):
        state = build_state(
            owners=(0, 1), regiments=(5, 5), ia_players=(0, 1),
            money=regles.WONDER_COST, turn=40,
        )
        state.wonder_territories["vorlan_chancellery"] = 0
        state.current_player = 1
        resultat = achats.construire_merveille(
            state, state.territories[1], "thyr_conclave",
        )
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(state.wonder_territories["thyr_conclave"], 1)


class TestCitesCommercantesEpargnees(unittest.TestCase):
    """Une CC n'est pas une IA comme les autres : aucune chancellerie ne la prend."""

    CHANCELLERIES = ("vorlan_chancellery", "thyr_conclave")

    def build(self, owners, cites, chancellerie):
        state = build_state(
            owners=owners, regiments=(5,) * len(owners),
            ia_players=tuple(range(max(owners) + 1)), money=500,
        )
        state.commercial_city_players.update(cites)
        state.wonder_territories[chancellerie] = 0
        return state

    def test_une_cc_voisine_n_est_jamais_fusionnee(self):
        """Seule voisine : la chancellerie n'a rien a prendre, rien n'est tire."""
        for chancellerie in self.CHANCELLERIES:
            with self.subTest(merveille=chancellerie):
                state = self.build(
                    owners=(0, 1, 2), cites=(1,), chancellerie=chancellerie,
                )
                self.assertTrue(regles.is_commercial_city_player(state, 1))
                self.assertEqual(
                    regles.find_ai_wonder_integration_candidates(state, 0), [],
                )
                self.assertIsNone(
                    regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
                )
                self.assertEqual(state.territories[1].owner, 1)

    def test_l_ia_ordinaire_est_prise_mais_pas_la_cc(self):
        """J1 est une CC, J2 une IA ordinaire : seule J2 change de main."""
        for chancellerie in self.CHANCELLERIES:
            with self.subTest(merveille=chancellerie):
                # J3, IA ordinaire et lointaine, tient le plancher des trois
                # joueurs IA : une Cite commercante n'y compte pas.
                state = self.build(
                    owners=(0, 1, 0, 2, 3), cites=(1,), chancellerie=chancellerie,
                )
                self.assertEqual(
                    regles.find_ai_wonder_integration_candidates(state, 0), [2],
                )
                message = regles.maybe_integrate_ai_player_with_wonder(state, TirageForce())
                self.assertIsNotNone(message)
                self.assertEqual(state.territories[3].owner, 0)
                self.assertEqual(state.territories[1].owner, 1)

    def test_sans_le_statut_de_cc_la_voisine_est_bien_prise(self):
        """Le temoin : c'est le statut de Cite commercante qui la sauve."""
        for chancellerie in self.CHANCELLERIES:
            with self.subTest(merveille=chancellerie):
                state = self.build(
                    owners=(0, 1, 2, 3), cites=(), chancellerie=chancellerie,
                )
                self.assertIsNotNone(
                    regles.maybe_integrate_ai_player_with_wonder(state, TirageForce()),
                )
                self.assertEqual(state.territories[1].owner, 0)


class TestPlancherDeDeuxJoueursIA(unittest.TestCase):
    """A deux joueurs IA sur la carte, les chancelleries ne prennent plus rien."""

    CHANCELLERIES = ("vorlan_chancellery", "thyr_conclave")

    def build(self, owners, ia_players, cites=(), chancellerie="vorlan_chancellery"):
        state = build_state(
            owners=owners, regiments=(5,) * len(owners), ia_players=ia_players,
            money=500,
        )
        state.commercial_city_players.update(cites)
        state.wonder_territories[chancellerie] = 0
        return state

    def test_deux_ia_seules_ne_donnent_plus_rien(self):
        """Face a face : aucune integration, et aucun tirage consomme."""
        for chancellerie in self.CHANCELLERIES:
            with self.subTest(merveille=chancellerie):
                state = self.build(
                    owners=(0, 1), ia_players=(0, 1), chancellerie=chancellerie,
                )
                self.assertEqual(regles.count_ai_players_on_map(state), 2)
                self.assertFalse(regles.are_ai_integration_wonders_active(state))
                self.assertIsNone(
                    regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
                )
                self.assertEqual(state.territories[1].owner, 1)

    def test_une_troisieme_ia_rouvre_la_chancellerie(self):
        for chancellerie in self.CHANCELLERIES:
            with self.subTest(merveille=chancellerie):
                state = self.build(
                    owners=(0, 1, 2), ia_players=(0, 1, 2), chancellerie=chancellerie,
                )
                self.assertTrue(regles.are_ai_integration_wonders_active(state))
                self.assertIsNotNone(
                    regles.maybe_integrate_ai_player_with_wonder(state, TirageForce()),
                )

    def test_les_humains_ne_comptent_pas_dans_le_plancher(self):
        """Deux IA au milieu d'une foule humaine : la chancellerie se tait."""
        state = self.build(owners=(0, 1, 2, 3), ia_players=(0, 1))
        self.assertEqual(regles.count_ai_players_on_map(state), 2)
        self.assertIsNone(
            regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
        )

    def test_une_cite_commercante_ne_compte_pas_dans_le_plancher(self):
        """Elle n'est jamais une proie : elle ne tient pas lieu de troisieme IA."""
        state = self.build(owners=(0, 1, 2), ia_players=(0, 1, 2), cites=(2,))
        self.assertTrue(regles.is_commercial_city_player(state, 2))
        self.assertEqual(regles.count_ai_players_on_map(state), 2)
        self.assertIsNone(
            regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
        )

    def test_une_ia_disparue_de_la_carte_ne_compte_plus(self):
        """Le decompte se lit sur la carte, pas sur le nombre de joueurs."""
        state = self.build(owners=(0, 1, 2), ia_players=(0, 1, 2))
        state.territories[2].owner = 1
        self.assertEqual(regles.count_ai_players_on_map(state), 2)
        self.assertIsNone(
            regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
        )

    def test_l_immunite_du_conclave_survit_au_plancher(self):
        """Seule l'integration s'arrete : le reste de la merveille tient."""
        state = self.build(
            owners=(0, 1), ia_players=(0, 1), chancellerie="thyr_conclave",
        )
        self.assertIsNone(
            regles.maybe_integrate_ai_player_with_wonder(state, TirageInterdit()),
        )
        self.assertTrue(regles.is_player_immune_to_revolt_by_wonder(state, 0))


class TestImmuniteAuxRevoltes(unittest.TestCase):
    """Ni revolte financee, ni trahison, ni revolution generale."""

    def build(self, turn, conclave=True):
        state = build_state(
            owners=(0, 0, 0, 0, 1, 1, 1, 2, 2),
            regiments=(5,) * 9, ia_players=(0, 1, 2), money=10_000, turn=turn,
        )
        if conclave:
            state.wonder_territories["thyr_conclave"] = 0
        return state

    def terres(self, state, joueur):
        return [terr.id for terr in state.territories if terr.owner == joueur]

    def test_la_revolte_financee_est_refusee(self):
        state = self.build(turn=40)
        state.current_player = 1
        resultat = achats.financer_revolte(state, state.territories[0], TirageForce())
        self.assertFalse(resultat.ok)
        self.assertIn(regles.get_wonder_name("thyr_conclave"), resultat.message)
        self.assertEqual(self.terres(state, 0), [0, 1, 2, 3])
        self.assertEqual(state.player_money[1], 10_000)

    def test_la_revolte_financee_passe_sans_la_merveille(self):
        state = self.build(turn=40, conclave=False)
        state.current_player = 1
        resultat = achats.financer_revolte(state, state.territories[0], TirageForce())
        self.assertTrue(resultat.ok, resultat.message)
        self.assertLess(len(self.terres(state, 0)), 4)

    def test_la_trahison_ne_le_cible_pas(self):
        """Tour 50 : l'evenement d'empire va au plus gros non immunise."""
        state = self.build(turn=50)
        messages = " | ".join(regles.maybe_trigger_empire_event(state, TirageBloque()))
        self.assertEqual(self.terres(state, 0), [0, 1, 2, 3])
        self.assertNotIn("J1 perd", messages)

    def test_sans_la_merveille_la_trahison_vise_le_plus_gros(self):
        state = self.build(turn=50, conclave=False)
        regles.maybe_trigger_empire_event(state, TirageBloque())
        self.assertLess(len(self.terres(state, 0)), 4)

    def test_la_revolution_generale_le_saute(self):
        """Tour 80 : tout le monde se coupe en deux, sauf lui."""
        state = self.build(turn=80)
        regles.maybe_trigger_empire_event(state, TirageBloque())
        self.assertEqual(self.terres(state, 0), [0, 1, 2, 3])
        self.assertLess(len(self.terres(state, 1)), 3)

    def test_sans_la_merveille_la_revolution_le_touche(self):
        state = self.build(turn=80, conclave=False)
        regles.maybe_trigger_empire_event(state, TirageBloque())
        self.assertLess(len(self.terres(state, 0)), 4)


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
