"""Le Sceau de l'Apocalypse : le chantier, la course, et l'age de tenebres.

Cinq versements de 300 ecus sur un meme territoire, un par tour, a partir du
tour 60. Chaque versement est annonce a tout le monde. Le premier qui acheve
efface les chantiers des autres et eteint le monde : culture, science et
revenus divises par dix, ressources +5 et mines de minerais precieux
disparues. Seul le territoire du sceau y gagne.

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


def build_state(owners=(0, 1), regiments=(5, 5), ia_players=(), money=10_000, turn=60):
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


def verser(state, territoire_id, joueur=None, tour_suivant=True):
    """Un versement, en avancant d'un tour (une etape par tour)."""
    if joueur is not None:
        state.current_player = joueur
    resultat = achats.construire_merveille(
        state, state.territories[territoire_id], "apocalypse_seal",
    )
    if tour_suivant:
        state.turn += 1
    return resultat


class TestChantier(unittest.TestCase):
    """Cinq versements, un par tour, a partir du tour 60."""

    def test_rien_avant_le_tour_soixante(self):
        state = build_state(turn=regles.APOCALYPSE_FIRST_TURN - 1)
        resultat = verser(state, 0, tour_suivant=False)
        self.assertFalse(resultat.ok)
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 0)
        self.assertEqual(state.player_money[0], 10_000)

    def test_cinq_versements_ferment_le_sceau(self):
        state = build_state()
        for etape in range(1, regles.APOCALYPSE_STAGES):
            resultat = verser(state, 0)
            self.assertTrue(resultat.ok, resultat.message)
            self.assertEqual(regles.get_apocalypse_site_stages(state, 0), etape)
            self.assertFalse(regles.is_apocalypse_active(state))
        resultat = verser(state, 0)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertTrue(regles.is_apocalypse_active(state))
        self.assertEqual(state.wonder_territories["apocalypse_seal"], 0)
        self.assertEqual(state.player_money[0], 10_000 - 5 * regles.WONDER_COST)

    def test_une_seule_etape_par_tour(self):
        state = build_state()
        self.assertTrue(verser(state, 0, tour_suivant=False).ok)
        deuxieme = verser(state, 0, tour_suivant=False)
        self.assertFalse(deuxieme.ok)
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 1)

    def test_chaque_versement_avertit_tout_le_monde(self):
        """L'avertissement part a chaque etape, y compris aux autres joueurs."""
        state = build_state(owners=(0, 1))
        verser(state, 0)
        self.assertTrue(
            any("chantier" in evenement.lower() for evenement in state.recent_major_events),
            state.recent_major_events,
        )
        # J1 est humain : l'evenement l'attend au debut de son tour.
        attendus = state.pending_major_events_for_humans.get(1, [])
        self.assertTrue(any("chantier" in texte.lower() for texte in attendus), attendus)

    def test_l_avertissement_dit_ce_qui_reste_a_verser(self):
        state = build_state()
        resultat = verser(state, 0)
        self.assertIn(f"1/{regles.APOCALYPSE_STAGES}", resultat.message)
        self.assertIn("avant que le monde s'eteigne", resultat.message)

    def test_le_premier_efface_les_chantiers_des_autres(self):
        state = build_state(owners=(0, 1), money=10_000)
        verser(state, 1, joueur=1)
        self.assertEqual(regles.get_apocalypse_site_stages(state, 1), 1)
        for _ in range(regles.APOCALYPSE_STAGES):
            verser(state, 0, joueur=0)
        self.assertTrue(regles.is_apocalypse_active(state))
        self.assertEqual(regles.get_apocalypse_site_stages(state, 1), 0)
        self.assertEqual(state.apocalypse_site_stages, {})

    def test_plus_rien_ne_se_verse_une_fois_le_sceau_ferme(self):
        state = build_state(owners=(0, 1))
        for _ in range(regles.APOCALYPSE_STAGES):
            verser(state, 0, joueur=0)
        refus = verser(state, 1, joueur=1)
        self.assertFalse(refus.ok)


class TestChantierRase(unittest.TestCase):
    """Prendre le territoire detruit le travail : on n'en herite pas."""

    def build(self):
        state = build_state(owners=(0, 1))
        verser(state, 0, joueur=0)
        verser(state, 0, joueur=0)
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 2)
        return state

    def test_le_chantier_ne_vaut_plus_rien_apres_la_prise(self):
        state = self.build()
        state.territories[0].owner = 1
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 0)

    def test_le_balayage_efface_le_chantier_perdu(self):
        state = self.build()
        state.territories[0].owner = 1
        messages = regles.purge_lost_apocalypse_sites(state)
        self.assertEqual(len(messages), 1)
        self.assertIn("rase", messages[0])
        self.assertEqual(state.apocalypse_site_stages, {})

    def test_le_conquerant_repart_de_zero(self):
        state = self.build()
        state.territories[0].owner = 1
        verser(state, 0, joueur=1)
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 1)

    def test_reprendre_sa_terre_ne_rend_pas_le_chantier(self):
        state = self.build()
        state.territories[0].owner = 1
        regles.purge_lost_apocalypse_sites(state)
        state.territories[0].owner = 0
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 0)


class TestAgeDeTenebres(unittest.TestCase):
    """Ce que le sceau fait au monde une fois ferme."""

    def build(self, owners=(0, 1)):
        state = build_state(owners=owners)
        state.player_science = {joueur: 250 for joueur in range(state.num_players)}
        # Une ressource +5 et une mine ailleurs sur la carte.
        state.territories[1].reinforcement_bonus = 5
        state.bonus_5_spawn_turns[1] = state.turn
        state.precious_mineral_mine_ids.add(1)
        state.precious_mineral_mine_spawn_turns[1] = state.turn
        return state

    def fermer(self, state, territoire_id=0):
        return regles.trigger_apocalypse(state, territoire_id)

    def test_la_science_acquise_est_divisee_une_fois(self):
        state = self.build()
        self.fermer(state)
        for joueur in (0, 1):
            self.assertEqual(state.player_science[joueur], 250 // regles.APOCALYPSE_DIVISOR)

    def test_le_revenu_de_science_est_divise_ensuite(self):
        state = self.build()
        for tid in (0, 1):
            regles.add_university(state, tid)
            state.university_ages[tid] = 100  # 10 points par tour
        avant = regles.calculate_player_science_income(state, 0)
        self.assertEqual(avant, 10)
        self.fermer(state)
        self.assertEqual(regles.calculate_player_science_income(state, 0), 1)

    def test_la_culture_est_divisee(self):
        state = self.build()
        regles.add_cultural_center(state, 0, age=0)
        avant = regles.calculate_player_culture(state, 0)
        self.assertGreater(avant, 0)
        self.fermer(state)
        self.assertEqual(
            regles.calculate_player_culture(state, 0), avant // regles.APOCALYPSE_DIVISOR,
        )

    def test_les_revenus_sont_divises_mais_le_sceau_rapporte(self):
        state = self.build()
        revenu_avant = regles.calculate_player_income(state, 0)
        self.fermer(state)
        attendu = revenu_avant // regles.APOCALYPSE_DIVISOR + regles.APOCALYPSE_TERRITORY_INCOME
        self.assertEqual(regles.calculate_player_income(state, 0), attendu)

    def test_les_autres_n_ont_que_la_division(self):
        state = self.build()
        self.fermer(state)
        revenu = regles.calculate_player_income(state, 1)
        self.assertLess(revenu, regles.APOCALYPSE_TERRITORY_INCOME)

    def test_les_ressources_5_et_les_mines_disparaissent(self):
        state = self.build()
        self.fermer(state)
        self.assertEqual(state.precious_mineral_mine_ids, set())
        self.assertEqual(state.precious_mineral_mine_spawn_turns, {})
        self.assertEqual(state.bonus_5_spawn_turns, {})
        self.assertEqual(state.territories[1].reinforcement_bonus, 1)

    def test_le_territoire_du_sceau_devient_un_plus_cinq(self):
        state = self.build()
        self.fermer(state)
        self.assertEqual(
            state.territories[0].reinforcement_bonus,
            regles.APOCALYPSE_TERRITORY_REINFORCEMENT_BONUS,
        )
        # Meme regle que les ressources +5 : le plafond militaire suit.
        self.assertTrue(regles.player_controls_bonus_5(state, 0))
        self.assertEqual(
            regles.get_reinforcement_regiment_limit(state, 0),
            regles.MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS_WITH_BONUS_5,
        )

    def test_le_plus_cinq_du_sceau_ne_s_epuise_jamais(self):
        """Il ressemble a une ressource +5, il n'en est pas une.

        Traite comme un gisement tardif, il s'eteignait au bout de vingt
        tours — et rien ne pouvait le remplacer, les ressources ne
        repoussant plus sous le sceau. Le proprietaire perdait ses cinq
        renforts pour de bon, sans un mot.
        """
        state = self.build()
        self.fermer(state)
        for _ in range(3 * regles.LATE_RESOURCE_LIFETIME_TURNS):
            state.turn += 1
            regles.rotate_expired_late_resources(state, random.Random(1))
        self.assertEqual(
            state.territories[0].reinforcement_bonus,
            regles.APOCALYPSE_TERRITORY_REINFORCEMENT_BONUS,
        )
        self.assertEqual(state.bonus_5_spawn_turns, {})
        rapport = regles.grant_reinforcements(state, 0, random.Random(1))
        self.assertIn("bonus +5: 5", rapport.message)

    def test_une_partie_deja_abimee_se_repare(self):
        """Les parties commencees avant le correctif retrouvent leur bonus."""
        state = self.build()
        self.fermer(state)
        state.territories[0].reinforcement_bonus = 1  # le degat deja fait
        state.bonus_5_spawn_turns[0] = state.turn - 30
        state.turn += 1
        regles.rotate_expired_late_resources(state, random.Random(1))
        self.assertEqual(
            state.territories[0].reinforcement_bonus,
            regles.APOCALYPSE_TERRITORY_REINFORCEMENT_BONUS,
        )

    def test_plus_aucune_ressource_ne_repousse(self):
        state = self.build()
        self.fermer(state)
        import random as _random
        self.assertIsNone(regles.spawn_bonus_5_resource(state, _random.Random(1)))
        self.assertIsNone(regles.spawn_precious_mineral_mine(state, _random.Random(1)))

    def test_les_religions_ne_bougent_pas(self):
        """Age de tenebres pour les comptes, pas pour les croyances."""
        state = self.build()
        state.religious_influence = {0: 3, 1: 3}
        state.religion_holy_sites = {0: 0}
        state.religion_foundation_turns = {0: 10}
        influence = dict(state.religious_influence)
        sites = dict(state.religion_holy_sites)
        fondations = dict(state.religion_foundation_turns)
        self.fermer(state)
        self.assertEqual(state.religious_influence, influence)
        self.assertEqual(state.religion_holy_sites, sites)
        self.assertEqual(state.religion_foundation_turns, fondations)

    def test_l_evenement_annonce_les_tenebres(self):
        state = self.build()
        message = self.fermer(state)
        self.assertIn("age de tenebres", message)
        self.assertIn(state.recent_major_events[-1], message)


class TestChantierDesIa(unittest.TestCase):
    """Une IA verse aussi, et pas plus d'une fois par tour.

    Le tour economique d'une IA boucle sur les merveilles a batir : sans
    garde-fou, elle payait les cinq etapes d'affilee et fermait le sceau le
    tour meme de son ouverture. Une simulation l'a montre ; ce test le
    verrouille.
    """

    def build(self):
        state = build_state(owners=(0, 1), ia_players=(0,), money=10_000)
        # Toutes les autres merveilles sont deja prises, ailleurs sur la
        # carte : il ne reste que le sceau a batir.
        for wonder_type in regles.WONDER_DEFINITIONS:
            if wonder_type != "apocalypse_seal":
                state.wonder_territories[wonder_type] = 1
        return state

    def test_une_ia_ouvre_un_chantier(self):
        state = self.build()
        regles.execute_ai_economic_actions(state, 0, random.Random(1))
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 1)

    def test_une_ia_ne_verse_qu_une_fois_par_tour(self):
        state = self.build()
        for _ in range(3):
            regles.execute_ai_economic_actions(state, 0, random.Random(1))
        self.assertEqual(regles.get_apocalypse_site_stages(state, 0), 1)
        self.assertFalse(regles.is_apocalypse_active(state))

    def test_une_ia_reprend_son_propre_chantier(self):
        """Cinq tours, cinq versements sur le meme territoire, puis le sceau."""
        state = self.build()
        for _ in range(regles.APOCALYPSE_STAGES):
            # Le tour economique verse ce qui reste en mercenaires : on
            # recredite la caisse, comme le ferait le revenu du tour.
            state.player_money[0] = 10_000
            regles.execute_ai_economic_actions(state, 0, random.Random(1))
            state.turn += 1
        self.assertTrue(regles.is_apocalypse_active(state))
        self.assertEqual(state.wonder_territories["apocalypse_seal"], 0)


class TestSauvegarde(unittest.TestCase):
    """Le chantier traverse une sauvegarde."""

    def test_un_chantier_en_cours_se_recharge(self):
        state = build_state()
        verser(state, 0)
        verser(state, 0)
        payload = state.to_payload()
        self.assertEqual(payload["apocalypse_site_stages"], {"0": 2})
        self.assertEqual(payload["apocalypse_site_owners"], {"0": 0})
        recharge = GameState.from_payload(payload)
        self.assertEqual(regles.get_apocalypse_site_stages(recharge, 0), 2)

    def test_une_sauvegarde_sans_chantier_reste_vide(self):
        state = build_state()
        payload = state.to_payload()
        self.assertEqual(payload["apocalypse_site_stages"], {})
        self.assertEqual(payload["apocalypse_site_owners"], {})


if __name__ == "__main__":
    unittest.main()
