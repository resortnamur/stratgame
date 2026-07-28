"""Ressources tardives : trois de chaque, et vingt tours de duree de vie.

Les ressources +5 et les mines de minerais precieux apparaissent en trois
exemplaires (tours 35/43/51 et 37/45/53). Chacune s'epuise vingt tours apres
son apparition et reapparait aussitot sur un AUTRE territoire tire au
hasard : le nombre en jeu reste constant, mais aucune position n'est acquise.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import regles

ROWS, COLS = 3, 24


def build_map_payload():
    """Vingt-quatre territoires en colonnes, tous voisins : de quoi tirer."""
    grid = [[-1] * COLS for _ in range(ROWS)]
    territories = []
    for col in range(COLS):
        for row in range(ROWS):
            grid[row][col] = col
        territories.append({"id": col, "name": f"T{col}", "reinforcement_bonus": 1})
    return {
        "kind": "map",
        "map_mode": "standard",
        "rows": ROWS,
        "cols": COLS,
        "grid_territory": grid,
        "territories": territories,
    }


def build_state(turn=34):
    state = GameState.from_map_payload(build_map_payload())
    state.num_players = 2
    state.initial_num_players = 2
    state.current_player = 0
    state.turn = turn
    state.phase = "playing"
    state.player_money = {0: 0, 1: 0}
    for terr in state.territories:
        terr.owner = terr.id % 2
        terr.regiments = 3
    return state


def bonus_5_ids(state):
    return {terr.id for terr in state.territories if terr.reinforcement_bonus == 5}


def jouer_jusqu_au_tour(state, dernier_tour, rng):
    """Avance tour par tour comme le fait actions.advance_turn."""
    journal = {}
    while state.turn < dernier_tour:
        state.turn += 1
        messages = regles.maybe_spawn_scheduled_resources(state, rng)
        if messages:
            journal[state.turn] = messages
    return journal


class TestNombreDeRessources(unittest.TestCase):
    def test_trois_apparitions_programmees(self):
        self.assertEqual(len(regles.BONUS_5_SPAWN_TURNS), 3)
        self.assertEqual(len(regles.PRECIOUS_MINERAL_MINE_SPAWN_TURNS), 3)
        self.assertEqual(regles.LATE_RESOURCE_LIFETIME_TURNS, 20)

    def test_jamais_plus_de_trois_de_chaque(self):
        state = build_state()
        rng = random.Random(20260728)
        maxi_bonus = maxi_mines = 0
        while state.turn < 140:
            state.turn += 1
            regles.maybe_spawn_scheduled_resources(state, rng)
            maxi_bonus = max(maxi_bonus, len(bonus_5_ids(state)))
            maxi_mines = max(maxi_mines, len(state.precious_mineral_mine_ids))
        self.assertEqual(maxi_bonus, 3, "il ne doit jamais y avoir plus de trois +5")
        self.assertEqual(maxi_mines, 3, "il ne doit jamais y avoir plus de trois mines")

    def test_montee_en_puissance_puis_plateau(self):
        state = build_state()
        rng = random.Random(7)
        jouer_jusqu_au_tour(state, 35, rng)
        self.assertEqual(len(bonus_5_ids(state)), 1)
        jouer_jusqu_au_tour(state, 43, rng)
        self.assertEqual(len(bonus_5_ids(state)), 2)
        jouer_jusqu_au_tour(state, 53, rng)
        self.assertEqual(len(bonus_5_ids(state)), 3)
        self.assertEqual(len(state.precious_mineral_mine_ids), 3)
        # Le plateau tient : les rotations remplacent, elles n'ajoutent pas.
        jouer_jusqu_au_tour(state, 120, rng)
        self.assertEqual(len(bonus_5_ids(state)), 3)
        self.assertEqual(len(state.precious_mineral_mine_ids), 3)


class TestDureeDeVie(unittest.TestCase):
    def test_le_bonus_5_change_de_territoire_apres_vingt_tours(self):
        state = build_state()
        rng = random.Random(11)
        jouer_jusqu_au_tour(state, 35, rng)
        premier = bonus_5_ids(state)
        self.assertEqual(len(premier), 1)
        origine = next(iter(premier))
        self.assertEqual(state.bonus_5_spawn_turns[origine], 35)

        # Tour 54 : encore la (dix-neuf tours seulement), avec ses deux cadettes.
        jouer_jusqu_au_tour(state, 54, rng)
        self.assertIn(origine, bonus_5_ids(state))
        avant = bonus_5_ids(state)
        self.assertEqual(len(avant), 3)

        # Tour 55 : epuisee, remplacee ailleurs, le compte ne change pas.
        journal = jouer_jusqu_au_tour(state, 55, rng)
        self.assertNotIn(origine, bonus_5_ids(state))
        self.assertEqual(state.territories[origine].reinforcement_bonus, 1)
        self.assertNotIn(origine, state.bonus_5_spawn_turns)
        self.assertEqual(len(bonus_5_ids(state)), 3)
        message = " ".join(journal.get(55, []))
        self.assertIn("epuisee", message)
        self.assertIn("apparait", message, "un equivalent doit apparaitre aussitot")
        # Le remplacant est ailleurs, et repart pour vingt tours.
        remplacants = bonus_5_ids(state) - avant
        self.assertEqual(len(remplacants), 1)
        nouveau = next(iter(remplacants))
        self.assertNotEqual(nouveau, origine, "la ressource ne se rallume pas sur place")
        self.assertEqual(state.bonus_5_spawn_turns[nouveau], 55)

    def test_la_mine_change_de_territoire_apres_vingt_tours(self):
        state = build_state()
        rng = random.Random(13)
        jouer_jusqu_au_tour(state, 37, rng)
        origine = next(iter(state.precious_mineral_mine_ids))
        self.assertEqual(state.precious_mineral_mine_spawn_turns[origine], 37)

        jouer_jusqu_au_tour(state, 56, rng)
        self.assertIn(origine, state.precious_mineral_mine_ids)
        avant = set(state.precious_mineral_mine_ids)
        self.assertEqual(len(avant), 3)

        journal = jouer_jusqu_au_tour(state, 57, rng)
        self.assertNotIn(origine, state.precious_mineral_mine_ids)
        self.assertEqual(len(state.precious_mineral_mine_ids), 3, "le compte reste a trois")
        remplacants = state.precious_mineral_mine_ids - avant
        self.assertEqual(len(remplacants), 1)
        nouveau = next(iter(remplacants))
        self.assertNotEqual(nouveau, origine, "la mine ne se reouvre pas sur place")
        self.assertEqual(state.precious_mineral_mine_spawn_turns[nouveau], 57)
        self.assertIn("epuisee", " ".join(journal.get(57, [])))

    def test_rotation_perpetuelle(self):
        """Chaque ressource tourne indefiniment, jamais plus de vingt tours."""
        state = build_state()
        rng = random.Random(17)
        jouer_jusqu_au_tour(state, 53, rng)
        for _ in range(80):
            state.turn += 1
            regles.maybe_spawn_scheduled_resources(state, rng)
            for tid, depart in state.bonus_5_spawn_turns.items():
                self.assertLess(
                    state.turn - depart, regles.LATE_RESOURCE_LIFETIME_TURNS,
                    f"le +5 de T{tid} a depasse sa duree de vie",
                )
            for tid, depart in state.precious_mineral_mine_spawn_turns.items():
                self.assertLess(
                    state.turn - depart, regles.LATE_RESOURCE_LIFETIME_TURNS,
                    f"la mine de T{tid} a depasse sa duree de vie",
                )

    def test_ressource_sans_compteur_repart_pour_un_cycle(self):
        """Sauvegarde anterieure a la regle : le compte a rebours demarre."""
        state = build_state(turn=80)
        state.territories[4].reinforcement_bonus = 5
        state.precious_mineral_mine_ids.add(9)
        self.assertEqual(state.bonus_5_spawn_turns, {})

        rng = random.Random(3)
        state.turn += 1
        regles.maybe_spawn_scheduled_resources(state, rng)
        self.assertEqual(state.bonus_5_spawn_turns, {4: 81})
        self.assertEqual(state.precious_mineral_mine_spawn_turns, {9: 81})

        # ... et vingt tours plus tard, elle tourne.
        jouer_jusqu_au_tour(state, 101, rng)
        self.assertNotIn(4, state.bonus_5_spawn_turns)
        self.assertNotIn(9, state.precious_mineral_mine_ids)

    def test_compteur_orphelin_oublie(self):
        """Une ressource retiree par une autre mecanique ne laisse pas de trace."""
        state = build_state(turn=60)
        state.bonus_5_spawn_turns = {5: 50}
        state.precious_mineral_mine_spawn_turns = {6: 50}
        state.turn += 1
        regles.maybe_spawn_scheduled_resources(state, random.Random(5))
        self.assertNotIn(5, state.bonus_5_spawn_turns, "compteur sans ressource")
        self.assertNotIn(6, state.precious_mineral_mine_spawn_turns)


class TestPartieCommenceeAvecQuatre(unittest.TestCase):
    """Une partie de l'ancienne regle retombe d'elle-meme a trois."""

    def build_state_a_quatre(self, turn=107):
        state = build_state(turn=turn)
        for index, tid in enumerate((3, 6, 9, 12)):
            state.territories[tid].reinforcement_bonus = 5
            state.bonus_5_spawn_turns[tid] = turn - 18 + index
        for index, tid in enumerate((4, 7, 10, 13)):
            state.precious_mineral_mine_ids.add(tid)
            state.precious_mineral_mine_spawn_turns[tid] = turn - 18 + index
        return state

    def test_le_surnombre_n_est_pas_remplace(self):
        state = self.build_state_a_quatre()
        rng = random.Random(29)
        self.assertEqual(len(bonus_5_ids(state)), 4)

        # Le premier gisement arrive a echeance n'est pas remplace.
        journal = jouer_jusqu_au_tour(state, 110, rng)
        self.assertEqual(len(bonus_5_ids(state)), 3, "on doit redescendre a trois")
        self.assertEqual(len(state.precious_mineral_mine_ids), 3)
        messages = " ".join(m for msgs in journal.values() for m in msgs)
        self.assertIn("n'est pas remplacee", messages)

        # Ensuite le regime de croisiere reprend : toujours trois.
        jouer_jusqu_au_tour(state, 200, rng)
        self.assertEqual(len(bonus_5_ids(state)), 3)
        self.assertEqual(len(state.precious_mineral_mine_ids), 3)

    def test_apparition_programmee_bloquee_au_plafond(self):
        """Meme un tour d'apparition prevu n'ajoute rien au-dela de trois."""
        state = self.build_state_a_quatre(turn=50)
        rng = random.Random(31)
        avant = len(bonus_5_ids(state))
        jouer_jusqu_au_tour(state, 51, rng)   # tour d'apparition d'un +5
        self.assertEqual(len(bonus_5_ids(state)), avant, "aucun ajout au-dela du plafond")


class TestSerialisation(unittest.TestCase):
    def test_les_compteurs_survivent_a_un_aller_retour(self):
        state = build_state()
        rng = random.Random(23)
        jouer_jusqu_au_tour(state, 55, rng)
        self.assertTrue(state.bonus_5_spawn_turns)
        self.assertTrue(state.precious_mineral_mine_spawn_turns)

        payload = json.loads(json.dumps(state.to_payload()))
        self.assertIn("bonus_5_spawn_turns", payload)
        self.assertIn("precious_mineral_mine_spawn_turns", payload)
        recharge = GameState.from_payload(payload)
        regles.sanitize_after_load(recharge)
        self.assertEqual(recharge.bonus_5_spawn_turns, state.bonus_5_spawn_turns)
        self.assertEqual(
            recharge.precious_mineral_mine_spawn_turns,
            state.precious_mineral_mine_spawn_turns,
        )
        self.assertEqual(recharge.to_payload(), payload, "aller-retour non idempotent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
