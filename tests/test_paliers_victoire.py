"""Regles d'aout 2026 : les conditions de victoire deviennent des paliers.

Remplir une condition ne met plus fin a la partie : elle ferme un palier,
rapporte un point de victoire a son auteur, et ne peut plus jamais etre
franchie — ni par lui, ni par personne. La partie s'acheve quand les
paliers necessaires sont tombes, ou quand il ne reste plus qu'un bloc sur la carte,
faute d'adversaire. Le vainqueur est celui qui compte le plus de points ;
a egalite, le plus grand empire, puis le premier a avoir franchi un palier.
Depuis le 07/11/2026, un joueur elimine garde ses paliers et peut l'emporter.

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

    def viser(self, condition):
        """Fait de cette condition l'objectif en cours.

        Depuis novembre 2026, une seule condition de victoire est ouverte a
        la fois : remplir les autres ne rapporte rien tant qu'elles n'ont pas
        ete tirees. Un test qui veut franchir un palier precis doit donc le
        mettre a l'ordre du jour.
        """
        self.state.victory_objective = condition
        self.state.victory_objective_turn = self.state.turn
        return condition


class TestFranchissement(BasePaliers):
    """Un palier se franchit une fois, et rapporte un point."""

    def test_au_depart_les_six_conditions_sont_ouvertes(self):
        self.assertEqual(self.state.victory_milestones, [])
        self.assertEqual(
            len(regles.get_remaining_victory_conditions(self.state)),
            len(regles.VICTORY_CONDITIONS),
        )

    def test_remplir_une_condition_ferme_le_palier_et_donne_un_point(self):
        self.viser("territoires")
        self.fixer_territoires(0, self.seuil)
        nouveaux = regles.register_victory_milestones(self.state)
        conditions = {palier["condition"] for palier in nouveaux}
        self.assertIn("territoires", conditions)
        self.assertEqual(regles.get_victory_points(self.state, 0), len(nouveaux))
        self.assertIn("territoires", regles.get_crossed_victory_conditions(self.state))
        self.assertNotIn("territoires", regles.get_remaining_victory_conditions(self.state))

    def test_le_palier_est_annonce_dans_les_evenements_majeurs(self):
        self.viser("territoires")
        self.fixer_territoires(0, self.seuil)
        regles.register_victory_milestones(self.state)
        self.assertTrue(
            any("PALIER DE VICTOIRE" in evenement
                for evenement in self.state.recent_major_events)
        )

    def test_un_palier_ferme_ne_se_rejoue_pas_pour_le_meme_joueur(self):
        self.viser("territoires")
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
        self.viser("dores")
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
        self.viser("territoires")
        self.fixer_territoires(0, self.seuil)
        regles.register_victory_milestones(self.state)
        recharge = GameState.from_payload(json.loads(json.dumps(self.state.to_payload())))
        self.assertEqual(
            regles.get_crossed_victory_conditions(recharge),
            regles.get_crossed_victory_conditions(self.state),
        )
        self.assertEqual(regles.get_victory_points(recharge, 0), 1)


class TestObjectifUnique(BasePaliers):
    """Regle du 14/11/2026 : une seule condition de victoire a la fois.

    La partie tire un objectif au depart, l'annonce, et n'en ouvre pas
    d'autre tant qu'il n'est pas tombe. Le palier franchi, le programme tire
    le suivant parmi ceux qui restent.
    """

    def test_la_partie_commence_avec_un_objectif_tire(self):
        objectif = regles.get_current_victory_objective(self.state)
        self.assertIn(objectif, regles.VICTORY_CONDITIONS)
        self.assertEqual(self.state.victory_objective, objectif)

    def test_l_objectif_est_annonce_des_le_depart(self):
        annonces = [
            evenement for evenement in self.state.recent_major_events
            if "OBJECTIF DE LA PARTIE" in evenement
        ]
        self.assertEqual(len(annonces), 1)
        libelle = regles.VICTORY_CONDITION_LABELS[self.state.victory_objective]
        self.assertIn(libelle, annonces[0])

    def test_une_condition_hors_objectif_ne_rapporte_rien(self):
        self.viser("culture")
        self.fixer_territoires(0, self.seuil)
        self.assertEqual(regles.register_victory_milestones(self.state), [])
        self.assertEqual(regles.get_victory_points(self.state, 0), 0)
        self.assertNotIn("territoires", regles.get_crossed_victory_conditions(self.state))
        # L'objectif n'a pas bouge : il attend toujours d'etre rempli.
        self.assertEqual(regles.get_current_victory_objective(self.state), "culture")

    def test_le_palier_franchi_ouvre_un_autre_objectif(self):
        self.viser("territoires")
        self.fixer_territoires(0, self.seuil)
        nouveaux = regles.register_victory_milestones(self.state, random.Random(7))
        self.assertEqual([palier["condition"] for palier in nouveaux], ["territoires"])
        suivant = regles.get_current_victory_objective(self.state)
        self.assertIn(suivant, regles.VICTORY_CONDITIONS)
        self.assertNotEqual(suivant, "territoires")
        self.assertEqual(nouveaux[0]["objectif_suivant"], suivant)

    def test_le_nouvel_objectif_est_annonce(self):
        self.viser("territoires")
        self.fixer_territoires(0, self.seuil)
        regles.register_victory_milestones(self.state, random.Random(7))
        annonces = [
            evenement for evenement in self.state.recent_major_events
            if "NOUVEL OBJECTIF" in evenement
        ]
        self.assertTrue(annonces)
        libelle = regles.VICTORY_CONDITION_LABELS[self.state.victory_objective]
        self.assertIn(libelle, annonces[-1])

    def test_l_objectif_n_est_jamais_une_condition_deja_fermee(self):
        for condition in ("lieux_sacres", "culture", "science", "dores"):
            self.fermer(condition, 1)
        self.state.victory_objective = "culture"  # ferme entre-temps
        objectif = regles.ensure_victory_objective(self.state)
        self.assertIn(objectif, ("religion", "territoires"))

    def test_plus_d_objectif_quand_tout_est_tombe(self):
        for condition in regles.VICTORY_CONDITIONS:
            self.fermer(condition, 1)
        self.assertIsNone(regles.ensure_victory_objective(self.state))
        self.assertEqual(regles.register_victory_milestones(self.state), [])

    def test_l_objectif_survit_a_la_sauvegarde(self):
        self.viser("dores")
        recharge = GameState.from_payload(json.loads(json.dumps(self.state.to_payload())))
        self.assertEqual(regles.get_current_victory_objective(recharge), "dores")
        self.assertEqual(recharge.victory_objective_turn, self.state.victory_objective_turn)

    def test_une_vieille_partie_recoit_un_objectif(self):
        self.state.victory_objective = None
        objectif = regles.ensure_victory_objective(self.state)
        self.assertIn(objectif, regles.VICTORY_CONDITIONS)

    def test_le_tirage_est_reproductible(self):
        self.state.victory_objective = None
        premier = regles.draw_victory_objective(self.state)
        self.state.victory_objective = None
        self.assertEqual(regles.draw_victory_objective(self.state), premier)

    def test_plus_aucune_condition_facultative(self):
        self.assertEqual(regles.OPTIONAL_VICTORY_CONDITIONS, ())
        self.assertEqual(
            regles.REQUIRED_VICTORY_CONDITIONS, regles.VICTORY_CONDITIONS,
        )
        for condition in regles.VICTORY_CONDITIONS:
            self.assertFalse(regles.is_optional_victory_condition(condition))

    def test_chaque_condition_sait_se_dire(self):
        for condition in regles.VICTORY_CONDITIONS:
            with self.subTest(condition=condition):
                self.assertIn(condition, regles.VICTORY_CONDITION_LABELS)
                self.assertIn(condition, regles.VICTORY_CONDITION_GOALS)
                self.assertIn(
                    regles.VICTORY_CONDITION_LABELS[condition],
                    regles.describe_victory_objective(condition),
                )


class TestFinDePartie(BasePaliers):
    """La partie ne s'acheve qu'a court de paliers necessaires."""

    def test_un_palier_franchi_n_arrete_pas_la_partie(self):
        self.viser("territoires")
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
        self.assertIn("4 sur 6", raison)

    def test_le_plus_de_points_l_emporte_meme_avec_moins_de_territoires(self):
        # Le joueur 1 tient la carte, le joueur 0 a rafle les paliers.
        self.fixer_territoires(1, self.seuil, rival=0)
        for index, condition in enumerate(regles.VICTORY_CONDITIONS):
            self.fermer(condition, 0 if index < 5 else 1, tour=index + 1)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)

    def test_a_egalite_de_points_le_plus_grand_empire(self):
        # Deux paliers chacun pour les joueurs 0 et 1, le cinquieme et le
        # sixieme au 2.
        rival, tiers = 1, 2
        for index, terr in enumerate(self.state.territories):
            if index < self.total - 6:
                terr.owner = 0
            elif index < self.total - 1:
                terr.owner = rival
            else:
                terr.owner = tiers
        for index, condition in enumerate(regles.VICTORY_CONDITIONS[:4]):
            self.fermer(condition, 0 if index < 2 else rival, tour=index + 1)
        self.fermer(regles.VICTORY_CONDITIONS[4], tiers, tour=5)
        self.fermer(regles.VICTORY_CONDITIONS[5], tiers, tour=6)
        self.assertEqual(regles.get_victory_points(self.state, 0), 2)
        self.assertEqual(regles.get_victory_points(self.state, rival), 2)
        # A egalite de points, c'est le plus grand empire qui l'emporte.
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)
        self.assertIn("2 palier(s)", raison)
        self.assertIn("egalite de paliers", raison)

    def test_tenir_toute_la_carte_acheve_la_partie(self):
        self.viser("territoires")
        for terr in self.state.territories:
            terr.owner = 0
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)
        self.assertTrue(raison)
        # Les paliers atteignables au passage lui sont bien credites.
        self.assertGreaterEqual(regles.get_victory_points(self.state, 0), 1)

    def test_un_elimine_garde_ses_paliers_et_peut_l_emporter(self):
        """Regle du 07/11/2026 : le vainqueur est celui qui a franchi le plus
        de paliers, meme si son empire a disparu depuis."""
        for index, condition in enumerate(regles.VICTORY_CONDITIONS):
            self.fermer(condition, 3 if index < 3 else index - 3, tour=index + 1)
        # Le joueur 3 (3 paliers) n'a plus rien, le joueur 0 (1 palier) tient tout.
        self.fixer_territoires(0, self.total, rival=1)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 3)
        self.assertIn("3 palier(s)", raison)
        self.assertIn("empire ait disparu", raison)

    def test_le_classement_suit_les_paliers_et_non_les_territoires(self):
        for index, condition in enumerate(regles.VICTORY_CONDITIONS):
            self.fermer(condition, (2, 2, 2, 1, 1, 0)[index], tour=index + 1)
        self.fixer_territoires(0, self.total - 1, rival=1)
        classement = regles.get_victory_ranking(self.state)
        self.assertEqual([ligne["joueur"] for ligne in classement[:3]], [2, 1, 0])
        self.assertEqual([ligne["points"] for ligne in classement[:3]], [3, 2, 1])
        self.assertTrue(classement[0]["elimine"])


class TestMajoriteDesPaliers(BasePaliers):
    """Regle du 06/11/2026 : plus de la moitie des paliers arrete la partie."""

    def test_le_seuil_est_quatre_sur_six(self):
        self.assertEqual(regles.get_victory_majority_threshold(), 4)

    def test_trois_paliers_ne_suffisent_pas(self):
        for index, condition in enumerate(regles.REQUIRED_VICTORY_CONDITIONS[:3]):
            self.fermer(condition, 0, tour=index + 1)
        self.assertIsNone(regles.evaluate_winner(self.state)[0])

    def test_quatre_paliers_arretent_la_partie(self):
        # Un palier necessaire reste ouvert : sans la majorite, on jouerait.
        for index, condition in enumerate(regles.REQUIRED_VICTORY_CONDITIONS[:3]):
            self.fermer(condition, 2, tour=index + 1)
        self.fermer("religion", 2, tour=4)
        self.assertTrue(regles.get_remaining_required_victory_conditions(self.state))
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 2)
        self.assertIn("majorite des paliers (4 sur 6)", raison)

    def test_un_elimine_majoritaire_arrete_aussi_la_partie(self):
        for index, condition in enumerate(regles.REQUIRED_VICTORY_CONDITIONS[:4]):
            self.fermer(condition, 3, tour=index + 1)
        self.fixer_territoires(0, self.total // 2, rival=1)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 3)

    def test_le_palier_majoritaire_ne_scinde_pas(self):
        """Le quatrieme palier franchi en jeu acheve la partie sans scission."""
        self.fixer_territoires(0, self.seuil)
        for index, condition in enumerate(("lieux_sacres", "culture", "science")):
            self.fermer(condition, 0, tour=index + 1)
        avant = len(regles.get_active_players(self.state))
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)
        nouveau = self.state.victory_milestones[-1]
        self.assertEqual(nouveau["condition"], "territoires")
        self.assertNotIn("scissions", nouveau)
        self.assertEqual(len(regles.get_active_players(self.state)), avant)
        self.assertTrue(any(
            "victoire finale est acquise" in evenement
            for evenement in self.state.recent_major_events
        ))


class TestMenacesEtPaliersFermes(BasePaliers):
    """Un palier ferme ne menace plus personne."""

    def test_la_condition_fermee_disparait_de_l_encart(self):
        self.viser("territoires")
        self.fixer_territoires(0, self.seuil - 2)
        moyens = {menace["moyen"] for menace in regles.get_victory_threats(self.state)}
        self.assertIn("territoires", moyens)
        self.fermer("territoires", 1)
        moyens = {menace["moyen"] for menace in regles.get_victory_threats(self.state)}
        self.assertNotIn("territoires", moyens)

    def test_aucune_alerte_sur_un_palier_ferme(self):
        self.viser("territoires")
        self.fixer_territoires(0, self.seuil - 1)
        self.assertTrue(regles.get_imminent_victory_threats(self.state))
        for condition in regles.VICTORY_CONDITIONS:
            self.fermer(condition, 1)
        self.assertEqual(regles.get_imminent_victory_threats(self.state), [])
        self.assertEqual(regles.record_victory_threat_alerts(self.state), [])


if __name__ == "__main__":
    unittest.main()
