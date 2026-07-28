"""Version simplifiee : une partie uniquement basee sur le combat.

Le cahier des charges de l'option (case « Version simplifiee » du lobby,
question 1 du setup de x45) :

- **disparaissent** : achats et phase d'achats, argent, science, culture,
  capitales, nations, religions et lieux saints, paradis fiscaux (dont le
  bonus de dernier bastion), cites commercantes, mines de minerais,
  industries, temples, universites, centres culturels, merveilles, alliances,
  sedition, revolutions generales des tours multiples de 40 ;
- **restent** : combat (3 des au maximum, faute de science), expeditions
  maritimes, renforts avec bonus +3/+5, territoires ONU (annexion seule),
  territoires dores, ponts aleatoires, forteresses — detruites apres trois
  captures et **remises en jeu** par tirage, faute de boutique — et les
  trahisons/revoltes tous les dix tours.

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
from moteur import actions, mise_en_place, regles

BASE = Path(__file__).resolve().parents[1]
CARTES = BASE / "cartes_sauvegardees"
CARTE_TEST = "ISLA01.json"
GERME = 20260728


def charger_carte(nom=CARTE_TEST):
    with open(CARTES / nom, encoding="utf-8") as handle:
        return json.load(handle)


def nouvelle_partie_simple(joueurs=4, ia=3, germe=GERME, **extra):
    rng = random.Random(germe)
    state = mise_en_place.nouvelle_partie(
        charger_carte(), joueurs, ia, simple_mode=True, rng=rng, **extra,
    )
    return state, rng


def dimensions(state):
    """Les dimensions logiques de cellule du serveur (repere 1200x620)."""
    return 1200 / state.cols, 620 / state.rows


class TestMiseEnPlaceSimplifiee(unittest.TestCase):
    def setUp(self):
        self.state, self.rng = nouvelle_partie_simple()

    def test_le_mode_est_actif_et_serialise(self):
        self.assertTrue(self.state.simple_mode)
        self.assertTrue(self.state.to_payload()["simple_mode"])
        # Aller-retour complet : le mode survit a une sauvegarde.
        recharge = GameState.from_payload(json.loads(json.dumps(self.state.to_payload())))
        self.assertTrue(recharge.simple_mode)

    def test_une_partie_ordinaire_n_emet_pas_la_cle(self):
        """La cle n'existe que si le mode est actif (parite des payloads v13)."""
        rng = random.Random(GERME)
        ordinaire = mise_en_place.nouvelle_partie(charger_carte(), 4, 3, rng=rng)
        self.assertFalse(ordinaire.simple_mode)
        self.assertNotIn("simple_mode", ordinaire.to_payload())

    def test_ni_capitale_ni_cite_commercante(self):
        self.assertEqual(self.state.player_capital_ids, {})
        self.assertEqual(self.state.commercial_city_players, set())
        self.assertEqual(self.state.commercial_city_capital_ids, {})
        # Aucun joueur ajoute pour la cite commercante.
        self.assertEqual(self.state.num_players, 4)

    def test_seules_les_forteresses_sont_posees(self):
        self.assertEqual(
            len(self.state.fortress_territory_ids), mise_en_place.INITIAL_FORTRESS_COUNT,
        )
        self.assertEqual(self.state.factory_territory_ids, set())
        self.assertEqual(self.state.airport_territory_ids, set())
        self.assertEqual(self.state.port_territory_ids, set())
        self.assertEqual(self.state.cultural_center_ages, {})
        self.assertEqual(self.state.temple_territory_ids, set())
        self.assertEqual(self.state.university_territory_ids, set())
        self.assertEqual(self.state.wonder_territories, {})

    def test_bonus_dores_et_sanctuaires_restent(self):
        self.assertEqual(len(self.state.ultra_super_territory_ids), 4)
        self.assertEqual(len(self.state.golden_territory_ids), 4)
        self.assertEqual(len(self.state.sanctuary_territory_ids), 3)
        self.assertEqual(
            sum(1 for terr in self.state.territories if terr.reinforcement_bonus == 3), 4,
        )

    def test_mode_tribus_toujours_disponible(self):
        state, _ = nouvelle_partie_simple(tribes_mode=True)
        self.assertTrue(state.tribes_mode)
        self.assertEqual(state.player_capital_ids, {})
        # Les IA ont bien des blocs : chacune touche au moins un voisin a elle.
        for joueur in sorted(state.base_ai_players):
            possessions = [t for t in state.territories if t.owner == joueur]
            self.assertTrue(possessions)
            self.assertTrue(any(
                any(state.territories[nb].owner == joueur for nb in terr.neighbors)
                for terr in possessions
            ), f"le bloc de J{joueur + 1} n'est pas contigu")

    def test_les_trois_modes_de_difficulte_restent_acceptes(self):
        for niveau in ("normal", "chaos", "gouvernement_mondial"):
            state, _ = nouvelle_partie_simple(difficulty_level=niveau)
            self.assertEqual(state.difficulty_level, niveau)
            self.assertTrue(state.simple_mode)


class TestToursSimplifies(unittest.TestCase):
    def setUp(self):
        self.state, self.rng = nouvelle_partie_simple()
        self.cw, self.ch = dimensions(self.state)
        actions.begin_player_turn(self.state, self.state.current_player, self.rng)

    def test_pas_de_phase_d_achats_pour_les_humains(self):
        state = self.state
        # Le siege 3 est humain (3 IA sur 4 joueurs).
        state.current_player = 3
        state.turn_phase = "attack"
        resultat = actions.apply_action(
            state, {"type": "terminer_attaque"}, self.cw, self.ch, self.rng,
        )
        self.assertTrue(resultat.ok)
        self.assertEqual(resultat.next_phase, "move")
        self.assertEqual(state.phase, "playing")

    def test_tout_achat_est_refuse(self):
        state = self.state
        state.current_player = 3
        state.player_money[3] = 100000
        for achat in actions.ACHATS:
            resultat = actions.apply_action(
                state, {"type": "acheter", "achat": achat, "territoire": 0,
                        "territoire_b": 1, "quantite": 1, "joueur": 0, "montant": 10,
                        "allie": 0, "cible": 1, "merveille": "aurelia_capitol"},
                self.cw, self.ch, self.rng,
            )
            self.assertFalse(resultat.ok, f"l'achat '{achat}' a ete accepte")
            self.assertEqual(resultat.code, "phase_invalide")

    def test_aucun_revenu_ni_science_ni_culture(self):
        state = self.state
        for joueur in regles.get_active_players(state):
            rapport = actions.begin_player_turn(state, joueur, self.rng)
            self.assertEqual(rapport.income, 0)
            self.assertEqual(rapport.science_income, 0)
            self.assertEqual(rapport.culture, 0)
            self.assertEqual(state.player_money.get(joueur, 0), 0)

    def test_trois_des_au_maximum_en_attaque(self):
        """Sans science, personne ne debloque le quatrieme de."""
        state = self.state
        for joueur in range(state.num_players):
            self.assertFalse(regles.can_player_attack_with_four_dice(state, joueur))

    def test_pas_de_dernier_bastion(self):
        """Un joueur reduit a un territoire ne recoit ni revenu x10 ni forteresse."""
        state = self.state
        cible = next(t for t in state.territories if t.owner == 3)
        for terr in state.territories:
            if terr.owner == 3 and terr.id != cible.id:
                terr.owner = 0
        forteresses_avant = set(state.fortress_territory_ids)
        note = regles.activate_last_stand_bonus_if_needed(state, 3)
        self.assertIsNone(note)
        self.assertEqual(state.last_stand_bonus_players, set())
        self.assertEqual(state.fortress_territory_ids, forteresses_avant)

    def test_pas_de_soumission_onu_a_la_conquete(self):
        """Sans nation, la conquete est toujours une annexion (jamais un tribut)."""
        state = self.state
        appels = []

        def decideur(*args):
            appels.append(args)
            return True

        state.current_player = 3
        paire = None
        for src in state.territories:
            if src.owner != 3:
                continue
            for nb in src.neighbors:
                if regles.can_attack_specific_target(state, src, state.territories[nb]):
                    paire = (src, state.territories[nb])
                    break
            if paire:
                break
        self.assertIsNotNone(paire, "aucune attaque possible pour le test")
        src, dst = paire
        src.regiments = 40
        dst.regiments = 1
        while regles.can_attack_specific_target(state, src, dst):
            resultat = regles.resolve_attack_once(
                state, src, dst, self.rng, submit_decider=decideur,
            )
            if resultat.conquered:
                break
        self.assertEqual(appels, [], "la question soumettre/annexer a ete posee")
        self.assertEqual(state.submitted_territory_ids, set())


class TestForteressesRecurrentes(unittest.TestCase):
    def setUp(self):
        self.state, self.rng = nouvelle_partie_simple()

    def test_une_forteresse_reapparait_sous_la_cible(self):
        state = self.state
        state.fortress_territory_ids = set()
        state.fortress_capture_counts = {}
        # Un tirage qui donne 1 sur le premier randint : la forteresse tombe.
        message = regles.maybe_spawn_random_fortress(state, random.Random(1))
        essais = 0
        while message is None and essais < 200:
            message = regles.maybe_spawn_random_fortress(state, self.rng)
            essais += 1
        self.assertIsNotNone(message, "aucune forteresse n'est reapparue en 200 tours")
        self.assertEqual(len(state.fortress_territory_ids), 1)
        tid = next(iter(state.fortress_territory_ids))
        self.assertEqual(state.fortress_capture_counts[tid], 0)
        self.assertIn(message, state.recent_major_events)

    def test_pas_de_reapparition_a_la_cible(self):
        state = self.state
        self.assertEqual(
            len(state.fortress_territory_ids), regles.SIMPLE_FORTRESS_TARGET_COUNT,
        )
        for _ in range(200):
            self.assertIsNone(regles.maybe_spawn_random_fortress(state, self.rng))

    def test_aucune_reapparition_en_partie_ordinaire(self):
        rng = random.Random(GERME)
        ordinaire = mise_en_place.nouvelle_partie(charger_carte(), 4, 3, rng=rng)
        ordinaire.fortress_territory_ids = set()
        for _ in range(200):
            self.assertIsNone(regles.maybe_spawn_random_fortress(ordinaire, rng))

    def test_detruite_apres_trois_captures(self):
        state = self.state
        tid = sorted(state.fortress_territory_ids)[0]
        for capture in (1, 2):
            messages = regles.register_special_capture(state, tid)
            self.assertIn(f"capture {capture}/3", " ".join(messages))
            self.assertIn(tid, state.fortress_territory_ids)
        messages = regles.register_special_capture(state, tid)
        self.assertIn("detruite apres 3 captures", " ".join(messages))
        self.assertNotIn(tid, state.fortress_territory_ids)


class TestEvenementsSimplifies(unittest.TestCase):
    def setUp(self):
        self.state, self.rng = nouvelle_partie_simple()
        self.cw, self.ch = dimensions(self.state)

    def test_pas_de_sedition(self):
        state = self.state
        # Une sedition serait visible dans le rapport de fin de tour.
        for _ in range(40):
            rapport = actions.advance_turn(state, self.cw, self.ch, self.rng)
            self.assertIsNone(rapport.sedition_message)
            self.assertIsNone(rapport.market_message)
            self.assertEqual(rapport.religion_messages, [])

    def test_pas_de_revolution_generale_au_tour_40(self):
        state = self.state
        state.turn = 40
        state.last_empire_event_turn = 39
        messages = regles.maybe_trigger_empire_event(state, self.rng)
        joints = " ".join(messages)
        self.assertNotIn("revolution", joints)
        # Le tour 40 devient un evenement d'empire ordinaire.
        self.assertTrue(
            any(mot in joints for mot in ("trahison", "revolte", "evenement d'empire"))
            or joints == "",
            joints,
        )

    def test_les_messages_ne_parlent_plus_de_culture(self):
        state = self.state
        state.turn = 10
        state.last_empire_event_turn = 9
        messages = regles.maybe_trigger_empire_event(state, self.rng)
        self.assertNotIn("culture", " ".join(messages))

    def test_pas_de_mine_mais_des_ressources_5(self):
        state = self.state
        state.turn = 37  # tour d'apparition d'une mine
        self.assertEqual(regles.maybe_spawn_scheduled_resources(state, self.rng), [])
        self.assertEqual(state.precious_mineral_mine_ids, set())
        state.turn = 35  # tour d'apparition d'une ressource +5
        messages = regles.maybe_spawn_scheduled_resources(state, self.rng)
        self.assertTrue(any("+5" in message for message in messages), messages)

    def test_les_evenements_onu_continuent(self):
        state = self.state
        apparitions = 0
        for tour in range(2, 60):
            state.turn = tour
            state.last_empire_event_turn = tour - 1
            messages = regles.maybe_trigger_empire_event(state, self.rng)
            apparitions += sum(1 for message in messages if "ONU" in message)
        self.assertGreater(apparitions, 0, "aucun evenement ONU en 58 tours")


class TestPartieSimplifieeAutonome(unittest.TestCase):
    def test_le_moteur_joue_seul_en_version_simplifiee(self):
        """Soixante tours complets : IA au moteur, humains au vocabulaire d'actions."""
        state, rng = nouvelle_partie_simple()
        cw, ch = dimensions(state)
        actions.begin_player_turn(state, state.current_player, rng)

        forteresses_vues = set(state.fortress_territory_ids)
        tours_joues = 0
        while state.turn <= 60 and state.phase == "playing":
            if regles.is_ai_player(state, state.current_player):
                rapport = actions.play_ai_turn(state, cw, ch, rng)
                if rapport.winner is not None:
                    break
            else:
                resultat = actions.apply_action(
                    state, {"type": "terminer_attaque"}, cw, ch, rng)
                self.assertTrue(resultat.ok, resultat.code)
                self.assertEqual(resultat.next_phase, "move")
                resultat = actions.apply_action(
                    state, {"type": "fin_de_tour"}, cw, ch, rng)
                self.assertTrue(resultat.ok, resultat.code)
                if resultat.winner is not None:
                    break
            forteresses_vues |= set(state.fortress_territory_ids)
            tours_joues += 1
            self.assertLess(tours_joues, 2000, "la partie ne progresse plus")

        # Rien d'economique n'a pu naitre en chemin.
        self.assertEqual(state.commercial_city_players, set())
        self.assertEqual(state.player_capital_ids, {})
        self.assertEqual(state.nation_players, set())
        self.assertEqual(state.religion_founders, {})
        self.assertEqual(state.last_stand_bonus_players, set())
        self.assertEqual(state.precious_mineral_mine_ids, set())
        self.assertEqual(state.submitted_territory_ids, set())
        self.assertEqual(state.temple_territory_ids, set())
        self.assertEqual(state.university_territory_ids, set())
        self.assertEqual(state.cultural_center_ages, {})
        self.assertEqual(state.wonder_territories, {})
        self.assertEqual(state.factory_territory_ids, set())
        self.assertFalse(any(state.player_money.values()), state.player_money)
        self.assertFalse(any(state.player_science.values()), state.player_science)
        # Et le militaire a bien vecu.
        self.assertGreater(state.turn, 10)
        self.assertGreater(
            len(forteresses_vues), regles.SIMPLE_FORTRESS_TARGET_COUNT,
            "aucune forteresse n'a ete remise en jeu en 60 tours",
        )
        # L'etat reste serialisable et rechargeable a l'identique.
        payload = json.loads(json.dumps(state.to_payload()))
        recharge = GameState.from_payload(payload)
        regles.sanitize_after_load(recharge, random.Random(GERME))
        self.assertTrue(recharge.simple_mode)
        self.assertEqual(recharge.player_capital_ids, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
