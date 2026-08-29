"""Regles d'aout 2026 : la course a la victoire.

Le moteur recense, pour chaque joueur et chaque condition, ce qui le
rapproche du but. Une menace est retenue des 65 % du chemin parcouru ;
elle devient ``imminente`` quand il ne reste presque rien :

- trois territoires ou moins du seuil des 3/4 ;
- un seul territoire dore manquant ;
- un seul lieu sacre manquant ;
- 90 % du chemin pour la culture, la science et la religion.

Les menaces imminentes declenchent une alerte, repetee a chaque nouveau
tour tant qu'elles durent. Tout se compte par bloc : un Serment d'Orvane
fond l'allie definitif dans son patron.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_menaces_victoire -v
"""

import json
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import mise_en_place
from moteur import regles

RACINE = Path(__file__).resolve().parents[1]
CARTES_DIR = RACINE / "cartes_sauvegardees"


def partie_neuve():
    for chemin in sorted(CARTES_DIR.glob("*.json")):
        try:
            with open(chemin, "r", encoding="utf-8") as handle:
                carte = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(carte, dict) and carte.get("territories"):
            return mise_en_place.nouvelle_partie(
                carte, num_players=4, ai_player_count=0, rng=random.Random(11),
            )
    raise unittest.SkipTest("Aucune carte exploitable dans cartes_sauvegardees/.")


class BaseMenaces(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.total = len(self.state.territories)
        self.seuil = math.ceil(self.total * 0.75)
        for joueur in regles.get_active_players(self.state):
            self.state.player_science[joueur] = 0

    def menaces(self, joueur=None, moyen=None):
        retenues = regles.get_victory_threats(self.state)
        if joueur is not None:
            retenues = [m for m in retenues if m["joueur"] == joueur]
        if moyen is not None:
            retenues = [m for m in retenues if m["moyen"] == moyen]
        return retenues

    def fixer_territoires(self, joueur, nombre, rival=None):
        """Donne au joueur exactement ``nombre`` territoires, le reste au rival."""
        if rival is None:
            rival = next(
                autre for autre in regles.get_active_players(self.state)
                if autre != joueur and not regles.is_onu_player(self.state, autre)
            )
        for index, terr in enumerate(self.state.territories):
            terr.owner = joueur if index < nombre else rival
        return rival


class TestRecensement(BaseMenaces):
    """Ce qui est retenu, et ce qui ne l'est pas."""

    def test_au_depart_aucune_alerte(self):
        self.assertEqual(regles.get_imminent_victory_threats(self.state), [])
        # Les grandes conditions ne bougent pas encore. Deux territoires dores
        # sur quatre, en revanche, meritent deja d'etre signales.
        for moyen in ("territoires", "religion", "culture", "science", "lieux_sacres"):
            self.assertEqual(self.menaces(moyen=moyen), [], moyen)

    def test_le_controle_territorial_est_signale_puis_alerte(self):
        joueur = 0
        # La moitie du seuil : encore trop loin pour figurer dans l'encart.
        self.fixer_territoires(joueur, self.seuil // 2)
        self.assertEqual(self.menaces(joueur, "territoires"), [])
        # Les deux tiers du seuil : la menace est retenue, sans alerte.
        self.fixer_territoires(joueur, math.ceil(self.seuil * 0.7))
        menace = self.menaces(joueur, "territoires")
        self.assertEqual(len(menace), 1)
        self.assertFalse(menace[0]["imminent"])
        # A trois territoires du but : alerte.
        self.fixer_territoires(joueur, self.seuil - regles.VICTORY_THREAT_TERRITORY_MARGIN)
        menace = self.menaces(joueur, "territoires")
        self.assertTrue(menace[0]["imminent"])
        self.assertEqual(menace[0]["manque"], regles.VICTORY_THREAT_TERRITORY_MARGIN)

    def test_un_seul_dore_manquant_donne_l_alerte(self):
        dores = sorted(self.state.golden_territory_ids)
        if len(dores) != 4:
            self.skipTest("Cette carte n'a pas quatre territoires dores.")
        joueur = 0
        # Table rase : aucun dore au joueur au depart.
        rival = self.fixer_territoires(joueur, 0)
        for tid in dores:
            self.state.territories[tid].owner = rival
        for tid in dores[:2]:
            self.state.territories[tid].owner = joueur
        menace = self.menaces(joueur, "dores")
        self.assertTrue(menace)
        self.assertFalse(menace[0]["imminent"])
        self.state.territories[dores[2]].owner = joueur
        self.assertTrue(self.menaces(joueur, "dores")[0]["imminent"])

    def test_la_science_apparait_a_partir_des_deux_tiers(self):
        joueur, rival = 0, 1
        self.state.player_science[rival] = 0
        # Plancher a 100 : 65 points, c'est 65 % du chemin.
        self.state.player_science[joueur] = 65
        menace = self.menaces(joueur, "science")
        self.assertTrue(menace)
        self.assertFalse(menace[0]["imminent"])
        self.state.player_science[joueur] = 90
        self.assertTrue(self.menaces(joueur, "science")[0]["imminent"])

    def test_les_menaces_sont_triees_de_la_plus_avancee_a_la_moins(self):
        self.fixer_territoires(0, self.seuil - 1)
        self.state.player_science[0] = 70
        progressions = [m["progression"] for m in regles.get_victory_threats(self.state)]
        self.assertEqual(progressions, sorted(progressions, reverse=True))

    def test_chaque_menace_dit_ce_qui_manque(self):
        self.fixer_territoires(0, self.seuil - 2)
        menace = self.menaces(0, "territoires")[0]
        self.assertEqual(menace["manque"], 2)
        self.assertIn("territoires", menace["detail"])
        self.assertEqual(menace["libelle"], "territoriale")


class TestAlertes(BaseMenaces):
    """L'alerte, repetee a chaque tour tant que la menace dure."""

    def test_aucune_alerte_sans_menace_imminente(self):
        self.assertEqual(regles.record_victory_threat_alerts(self.state), [])

    def test_l_alerte_nomme_le_joueur_et_le_moyen(self):
        self.fixer_territoires(0, self.seuil - 1)
        messages = regles.record_victory_threat_alerts(self.state)
        self.assertTrue(messages)
        self.assertIn("ALERTE", messages[0])
        self.assertIn("J1", messages[0])
        self.assertIn("territoriale", messages[0])

    def test_l_alerte_entre_dans_les_evenements_majeurs(self):
        self.fixer_territoires(0, self.seuil - 1)
        regles.record_victory_threat_alerts(self.state)
        self.assertTrue(
            any("ALERTE" in evenement for evenement in self.state.recent_major_events)
        )

    def test_l_alerte_se_repete_au_tour_suivant(self):
        self.fixer_territoires(0, self.seuil - 1)
        premier = regles.record_victory_threat_alerts(self.state)
        self.state.turn += 1
        second = regles.record_victory_threat_alerts(self.state)
        self.assertTrue(premier and second)
        self.assertNotEqual(premier[0], second[0])  # le numero de tour change

    def test_le_tour_qui_avance_declenche_les_alertes(self):
        from moteur import actions

        self.fixer_territoires(0, self.seuil - 2)
        # Deux territoires manquent encore : le tour s'acheve sans vainqueur,
        # mais la menace est bien la. On se place sur le dernier joueur pour
        # que le tour global bascule.
        self.state.current_player = max(regles.get_active_players(self.state))
        rapport = actions.advance_turn(
            self.state, 1200.0 / self.state.cols, 620.0 / self.state.rows,
            random.Random(5), begin_next_turn=False,
        )
        if rapport.winner is not None:
            self.skipTest("La partie s'est achevee avant l'alerte.")
        self.assertTrue(rapport.victory_alerts)
        self.assertIn("ALERTE", rapport.victory_alerts[0])


class TestMenacesParBloc(BaseMenaces):
    """Le Serment d'Orvane fond l'allie dans son patron."""

    def setUp(self):
        super().setUp()
        self.state.turn = regles.LATE_WONDER_FIRST_TURN
        patron_terr = next(t for t in self.state.territories if t.owner == 0)
        self.assertTrue(
            regles.build_wonder(self.state, patron_terr.id, "orvane_oath", record_event=False)
        )
        self.allie = regles.allocate_rebel_player(self.state, random.Random(3))[0]

    def test_les_territoires_de_l_allie_comptent_pour_le_patron(self):
        moitie = self.seuil // 2
        # Le patron a la moitie du seuil, l'allie complete jusqu'a une menace.
        for index, terr in enumerate(self.state.territories):
            if index < moitie:
                terr.owner = 0
            elif index < self.seuil - 1:
                terr.owner = self.allie
        menace = self.menaces(0, "territoires")
        self.assertTrue(menace)
        self.assertEqual(set(menace[0]["bloc"]), {0, self.allie})
        propres = sum(1 for t in self.state.territories if t.owner == 0)
        self.assertGreater(menace[0]["valeur"], propres)

    def test_l_allie_ne_figure_pas_pour_son_propre_compte(self):
        for terr in self.state.territories:
            if terr.owner != 0:
                terr.owner = self.allie
        self.assertEqual(self.menaces(self.allie), [])
        self.assertTrue(self.menaces(0, "territoires"))


if __name__ == "__main__":
    unittest.main()
