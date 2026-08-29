"""Regles d'aout 2026 sur la culture.

1. Un centre culturel detruit (apres 3 captures) ne disparait plus : il
   devient une ruine. La ruine rapporte 20 ecus et 5 points de culture par
   tour, sans rapport avec les voisins du territoire ni avec l'anciennete
   du batiment, et rien ne la detruit jamais.
2. La ruine occupe la place : on ne rebatit pas de centre culturel dessus.
3. Un joueur gagne s'il a 20 fois plus de culture que n'importe lequel de
   ses adversaires (10 fois pour une IA), a condition d'atteindre aussi le
   plancher de 100 points — sans quoi des rivaux a zero donneraient la
   victoire des le premier tour.

Au passage, la limite « une Cite commercante ne garde qu'un seul centre
culturel » est supprimee : ce test verifie qu'elle ne s'applique plus.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_ruines_culture -v
"""

import json
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


def charger_carte(la_plus_grande=False):
    fichiers = sorted(CARTES_DIR.glob("*.json"))
    cartes = []
    for chemin in fichiers:
        try:
            with open(chemin, "r", encoding="utf-8") as handle:
                carte = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(carte, dict) and carte.get("territories"):
            cartes.append(carte)
    if not cartes:
        raise unittest.SkipTest("Aucune carte exploitable dans cartes_sauvegardees/.")
    if la_plus_grande:
        return max(cartes, key=lambda carte: len(carte["territories"]))
    return cartes[0]


def partie_neuve(la_plus_grande=False):
    return mise_en_place.nouvelle_partie(
        charger_carte(la_plus_grande),
        num_players=4, ai_player_count=0, rng=random.Random(11),
    )


class TestRuine(unittest.TestCase):
    """Un centre culturel detruit laisse une ruine indestructible."""

    def setUp(self):
        self.state = partie_neuve()
        self.terr = next(
            terr for terr in self.state.territories
            if terr.owner >= 0 and not regles.has_ruin(self.state, terr.id)
        )
        self.state.cultural_center_ages.pop(self.terr.id, None)
        regles.add_cultural_center(self.state, self.terr.id, age=0)

    def _trois_captures(self):
        messages = []
        for _ in range(regles.SPECIAL_CAPTURE_LIMIT):
            messages.extend(regles.register_special_capture(self.state, self.terr.id))
        return messages

    def test_la_troisieme_capture_laisse_une_ruine(self):
        messages = self._trois_captures()
        self.assertEqual(regles.get_cultural_center_count(self.state, self.terr.id), 0)
        self.assertTrue(regles.has_ruin(self.state, self.terr.id))
        self.assertTrue(any("ruine" in message for message in messages))

    def test_la_ruine_ne_se_detruit_jamais(self):
        self._trois_captures()
        # Trois captures de plus : la ruine tient bon.
        for _ in range(regles.SPECIAL_CAPTURE_LIMIT):
            regles.register_special_capture(self.state, self.terr.id)
        self.assertTrue(regles.has_ruin(self.state, self.terr.id))

    def test_pas_de_seconde_ruine_sur_le_meme_territoire(self):
        self._trois_captures()
        self.assertFalse(regles.add_ruin(self.state, self.terr.id))
        self.assertEqual(regles.get_player_ruin_count(self.state, self.terr.owner), 1)

    def test_on_ne_rebatit_pas_sur_les_ruines(self):
        self._trois_captures()
        self.assertFalse(regles.can_add_cultural_center(self.state, self.terr.id))
        self.assertFalse(regles.add_cultural_center(self.state, self.terr.id))

    def test_la_ruine_suit_le_territoire_conquis(self):
        self._trois_captures()
        ancien = self.terr.owner
        nouveau = next(
            joueur for joueur in regles.get_active_players(self.state) if joueur != ancien
        )
        self.terr.owner = nouveau
        self.assertEqual(regles.get_player_ruin_count(self.state, ancien), 0)
        self.assertEqual(regles.get_player_ruin_count(self.state, nouveau), 1)

    def test_vingt_ecus_par_tour_quels_que_soient_les_voisins(self):
        joueur = self.terr.owner
        avant = regles.calculate_player_income(self.state, joueur)
        self._trois_captures()
        apres = regles.calculate_player_income(self.state, joueur)
        self.assertEqual(apres - avant, regles.RUIN_INCOME)

    def test_cinq_points_de_culture_sans_voisins_ni_anciennete(self):
        self._trois_captures()
        self.assertEqual(
            regles.calculate_territory_culture(self.state, self.terr),
            regles.RUIN_CULTURE,
        )
        # Un territoire voisin de plus ne change rien au rendement de la ruine.
        autre = next(
            terr for terr in self.state.territories
            if terr.id != self.terr.id
            and terr.owner >= 0
            and len(terr.neighbors) != len(self.terr.neighbors)
            and not regles.has_ruin(self.state, terr.id)
            and not regles.get_cultural_center_count(self.state, terr.id)
        )
        regles.add_ruin(self.state, autre.id)
        self.assertEqual(
            regles.calculate_territory_culture(self.state, autre),
            regles.RUIN_CULTURE,
        )

    def test_la_ruine_survit_a_la_sauvegarde(self):
        self._trois_captures()
        recharge = GameState.from_payload(
            json.loads(json.dumps(self.state.to_payload()))
        )
        self.assertTrue(regles.has_ruin(recharge, self.terr.id))


class TestCiteCommercanteSansLimiteCulturelle(unittest.TestCase):
    """La limite d'un seul centre culturel par Cite commercante est levee."""

    def test_une_cite_garde_plusieurs_centres(self):
        state = partie_neuve()
        cc_joueurs = sorted(state.commercial_city_players)
        if not cc_joueurs:
            self.skipTest("Aucune Cite commercante sur cette carte.")
        cc = cc_joueurs[0]
        possedes = [terr.id for terr in state.territories if terr.owner == cc]
        if not possedes:
            self.skipTest("Cite commercante sans territoire.")
        # Une cite de depart n'a souvent qu'une seule cellule : on lui en
        # donne une seconde, le but etant de verifier qu'elle garde bien
        # deux centres culturels.
        if len(possedes) < 2:
            voisin = next(
                (tid for tid in state.territories[possedes[0]].neighbors
                 if 0 <= tid < len(state.territories)),
                None,
            )
            if voisin is None:
                self.skipTest("Cite commercante isolee.")
            state.territories[voisin].owner = cc
            possedes.append(voisin)
        for tid in possedes[:2]:
            state.cultural_center_ages.pop(tid, None)
            state.ruin_territory_ids.discard(tid)
            self.assertTrue(regles.add_cultural_center(state, tid))
        regles.sanitize_after_load(state)
        self.assertEqual(
            sum(regles.get_cultural_center_count(state, tid) for tid in possedes[:2]), 2,
        )


class TestVictoireCulturelle(unittest.TestCase):
    """Ecraser la culture de tous ses rivaux, avec un plancher a franchir."""

    def setUp(self):
        # La plus grande carte du catalogue : poser 200 points de culture
        # demande 40 ruines, donc 40 territoires, sans pour autant franchir
        # les 3/4 qui declencheraient la victoire territoriale.
        self.state = partie_neuve(la_plus_grande=True)
        # Table rase : la culture de chaque joueur est ensuite posee a la main
        # par des ruines, dont le rendement est fixe et donc previsible.
        self.state.cultural_center_ages = {}
        self.state.cultural_capture_counts = {}
        self.state.ruin_territory_ids = set()
        self.joueurs = [
            joueur for joueur in regles.get_active_players(self.state)
            if not regles.is_onu_player(self.state, joueur)
        ]
        if len(self.joueurs) < 2:
            self.skipTest("Il faut au moins deux joueurs actifs.")

    def _poser_culture(self, joueur, points):
        """Porte la culture de ``joueur`` a ``points`` exactement.

        Les ruines rendent 5 points chacune, quel que soit le territoire :
        il suffit d'en poser le bon nombre, en donnant au joueur autant de
        territoires que necessaire.
        """
        assert points % regles.RUIN_CULTURE == 0
        besoin = points // regles.RUIN_CULTURE
        possedes = [terr.id for terr in self.state.territories if terr.owner == joueur]
        if len(possedes) < besoin:
            # On prend chez les joueurs qui ne servent pas au test.
            neutres = [
                terr for terr in self.state.territories
                if terr.owner not in (joueur, *self.joueurs[:2])
            ] + [
                terr for terr in self.state.territories
                if terr.owner in self.joueurs[2:]
            ]
            for terr in neutres:
                if len(possedes) >= besoin:
                    break
                if terr.id in possedes:
                    continue
                terr.owner = joueur
                possedes.append(terr.id)
        if len(possedes) < besoin:
            self.skipTest(f"Pas assez de territoires pour {points} points de culture.")
        for tid in possedes[:besoin]:
            regles.add_ruin(self.state, tid)
        self.assertEqual(regles.calculate_player_culture(self.state, joueur), points)

    def test_le_plancher_empeche_la_victoire_face_a_des_rivaux_a_zero(self):
        meneur = self.joueurs[0]
        self._poser_culture(meneur, regles.CULTURE_VICTORY_MIN_POINTS - regles.RUIN_CULTURE)
        for rival in self.joueurs[1:]:
            self.assertEqual(regles.calculate_player_culture(self.state, rival), 0)
        self.assertIsNone(regles.evaluate_winner(self.state)[0])

    def test_le_plancher_atteint_face_a_des_rivaux_a_zero_fait_gagner(self):
        meneur = self.joueurs[0]
        self._poser_culture(meneur, regles.CULTURE_VICTORY_MIN_POINTS)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, meneur)
        self.assertIn("culture", raison)

    def test_un_rival_a_dix_points_exige_deux_cents_points(self):
        meneur, rival = self.joueurs[0], self.joueurs[1]
        self._poser_culture(rival, 10)
        self._poser_culture(meneur, 195)
        self.assertIsNone(regles.evaluate_winner(self.state)[0])
        self._poser_culture(meneur, 200)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, meneur)

    def test_une_ia_se_contente_du_facteur_dix(self):
        meneur, rival = self.joueurs[0], self.joueurs[1]
        self.state.base_ai_players.add(meneur)
        self.state.human_controlled_players.discard(meneur)
        self._poser_culture(rival, 10)
        self._poser_culture(meneur, 100)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, meneur)
        self.assertIn("10 fois", raison)


if __name__ == "__main__":
    unittest.main()
