"""Regles d'aout 2026 : les conditions de victoire deviennent des paliers.

Remplir une condition ne met plus fin a la partie : elle ferme un palier,
rapporte un point de victoire a son auteur, et ne peut plus jamais etre
franchie — ni par lui, ni par personne. La partie s'acheve quand les sept
paliers sont tombes, ou quand il ne reste plus qu'un bloc sur la carte,
faute d'adversaire. Le vainqueur est celui qui compte le plus de points ;
a egalite, le plus grand empire, puis le premier a avoir franchi un palier.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_paliers_victoire -v
"""

import json
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
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


class BasePaliers(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.total = len(self.state.territories)
        self.seuil = math.ceil(self.total * 0.75)
        for joueur in regles.get_active_players(self.state):
            self.state.player_science[joueur] = 0

    def fixer_territoires(self, joueur, nombre, rival=None):
        if rival is None:
            rival = next(
                autre for autre in regles.get_active_players(self.state)
                if autre != joueur and not regles.is_onu_player(self.state, autre)
            )
        for index, terr in enumerate(self.state.territories):
            terr.owner = joueur if index < nombre else rival
        return rival

    def fermer(self, condition, joueur, tour=1):
        """Ferme un palier a la main, comme s'il avait ete franchi."""
        self.state.victory_milestones.append({
            "condition": condition, "joueur": joueur, "tour": tour, "raison": "pour le test",
        })


class TestFranchissement(BasePaliers):
    """Un palier se franchit une fois, et rapporte un point."""

    def test_au_depart_les_sept_conditions_sont_ouvertes(self):
        self.assertEqual(self.state.victory_milestones, [])
        self.assertEqual(
            len(regles.get_remaining_victory_conditions(self.state)),
            len(regles.VICTORY_CONDITIONS),
        )

    def test_remplir_une_condition_ferme_le_palier_et_donne_un_point(self):
        self.fixer_territoires(0, self.seuil)
        nouveaux = regles.register_victory_milestones(self.state)
        conditions = {palier["condition"] for palier in nouveaux}
        self.assertIn("territoires", conditions)
        self.assertEqual(regles.get_victory_points(self.state, 0), len(nouveaux))
        self.assertIn("territoires", regles.get_crossed_victory_conditions(self.state))
        self.assertNotIn("territoires", regles.get_remaining_victory_conditions(self.state))

    def test_le_palier_est_annonce_dans_les_evenements_majeurs(self):
        self.fixer_territoires(0, self.seuil)
        regles.register_victory_milestones(self.state)
        self.assertTrue(
            any("PALIER DE VICTOIRE" in evenement
                for evenement in self.state.recent_major_events)
        )

    def test_un_palier_ferme_ne_se_rejoue_pas_pour_le_meme_joueur(self):
        self.fixer_territoires(0, self.seuil)
        regles.register_victory_milestones(self.state)
        points = regles.get_victory_points(self.state, 0)
        self.assertEqual(regles.register_victory_milestones(self.state), [])
        self.assertEqual(regles.get_victory_points(self.state, 0), points)

    def test_un_palier_ferme_ne_se_rejoue_pas_pour_un_autre_joueur(self):
        dores = sorted(self.state.golden_territory_ids)
        if len(dores) != 4:
            self.skipTest("Cette carte n'a pas quatre territoires dores.")
        # La carte se partage en deux : personne ne conquiert tout, personne
        # n'atteint les 3/4. Seul le palier des dores est en jeu.
        self.fixer_territoires(0, self.total // 2, rival=1)
        for tid in dores:
            self.state.territories[tid].owner = 0
        regles.register_victory_milestones(self.state)
        self.assertEqual(regles.get_victory_points(self.state, 0), 1)
        # Un rival reprend les quatre dores : le palier reste ferme.
        rival = 1
        for tid in dores:
            self.state.territories[tid].owner = rival
        self.assertEqual(regles.register_victory_milestones(self.state), [])
        self.assertEqual(regles.get_victory_points(self.state, rival), 0)

    def test_les_paliers_survivent_a_la_sauvegarde(self):
        self.fixer_territoires(0, self.seuil)
        regles.register_victory_milestones(self.state)
        recharge = GameState.from_payload(json.loads(json.dumps(self.state.to_payload())))
        self.assertEqual(
            regles.get_crossed_victory_conditions(recharge),
            regles.get_crossed_victory_conditions(self.state),
        )
        self.assertEqual(regles.get_victory_points(recharge, 0), 1)


class TestFinDePartie(BasePaliers):
    """La partie ne s'acheve qu'a court de paliers."""

    def test_un_palier_franchi_n_arrete_pas_la_partie(self):
        self.fixer_territoires(0, self.seuil)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertIsNone(gagnant)
        self.assertTrue(regles.get_victory_points(self.state, 0) >= 1)

    def test_tous_les_paliers_franchis_achevent_la_partie(self):
        self.fixer_territoires(0, self.seuil)
        for index, condition in enumerate(regles.VICTORY_CONDITIONS):
            self.fermer(condition, 0 if index < 4 else 1, tour=index + 1)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)
        self.assertIn("4 point(s)", raison)

    def test_le_plus_de_points_l_emporte_meme_avec_moins_de_territoires(self):
        # Le joueur 1 tient la carte, le joueur 0 a rafle les paliers.
        self.fixer_territoires(1, self.seuil, rival=0)
        for index, condition in enumerate(regles.VICTORY_CONDITIONS):
            self.fermer(condition, 0 if index < 5 else 1, tour=index + 1)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)

    def test_a_egalite_de_points_le_plus_grand_empire(self):
        # Trois paliers chacun pour les joueurs 0 et 1, le septieme au 2.
        rival, tiers = 1, 2
        for index, terr in enumerate(self.state.territories):
            if index < self.total - 6:
                terr.owner = 0
            elif index < self.total - 1:
                terr.owner = rival
            else:
                terr.owner = tiers
        for index, condition in enumerate(regles.VICTORY_CONDITIONS[:6]):
            self.fermer(condition, 0 if index < 3 else rival, tour=index + 1)
        self.fermer(regles.VICTORY_CONDITIONS[6], tiers, tour=7)
        self.assertEqual(regles.get_victory_points(self.state, 0), 3)
        self.assertEqual(regles.get_victory_points(self.state, rival), 3)
        # A egalite de points, c'est le plus grand empire qui l'emporte.
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)
        self.assertIn("3 point(s)", raison)

    def test_tenir_toute_la_carte_acheve_la_partie(self):
        for terr in self.state.territories:
            terr.owner = 0
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)
        self.assertTrue(raison)
        # Les paliers atteignables au passage lui sont bien credites.
        self.assertGreaterEqual(regles.get_victory_points(self.state, 0), 1)

    def test_un_elimine_ne_remporte_pas_la_partie(self):
        for index, condition in enumerate(regles.VICTORY_CONDITIONS):
            self.fermer(condition, 3, tour=index + 1)
        # Le joueur 3 n'a plus rien : c'est un survivant qui l'emporte.
        self.fixer_territoires(0, self.total, rival=1)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)


class TestMenacesEtPaliersFermes(BasePaliers):
    """Un palier ferme ne menace plus personne."""

    def test_la_condition_fermee_disparait_de_l_encart(self):
        self.fixer_territoires(0, self.seuil - 2)
        moyens = {menace["moyen"] for menace in regles.get_victory_threats(self.state)}
        self.assertIn("territoires", moyens)
        self.fermer("territoires", 1)
        moyens = {menace["moyen"] for menace in regles.get_victory_threats(self.state)}
        self.assertNotIn("territoires", moyens)

    def test_aucune_alerte_sur_un_palier_ferme(self):
        self.fixer_territoires(0, self.seuil - 1)
        self.assertTrue(regles.get_imminent_victory_threats(self.state))
        for condition in regles.VICTORY_CONDITIONS:
            self.fermer(condition, 1)
        self.assertEqual(regles.get_imminent_victory_threats(self.state), [])
        self.assertEqual(regles.record_victory_threat_alerts(self.state), [])


if __name__ == "__main__":
    unittest.main()
