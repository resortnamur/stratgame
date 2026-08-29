"""Regles d'aout 2026 sur les religions nationales.

Trois nouveautes, valables pour les seules religions nationales (celle que
fonde le premier temple d'un joueur) et jamais pour Elyrion, la religion de
la merveille :

1. un territoire sous l'influence de la religion nationale de son
   proprietaire ne se revolte jamais : ni revolte, ni revolution, ni
   trahison, ni sedition ;
2. la mission (200 ecus) convertit a la religion nationale de l'acheteur
   n'importe quel territoire de la carte du monde ;
3. un joueur gagne si sa religion nationale s'etend sur neuf dixiemes des
   territoires — trois quarts si le fondateur est une IA.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_religion_nationale -v
"""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import achats
from moteur import mise_en_place
from moteur import regles

RACINE = Path(__file__).resolve().parents[1]
CARTES_DIR = RACINE / "cartes_sauvegardees"


def partie_neuve(num_players=4, ai_player_count=0):
    fichiers = sorted(CARTES_DIR.glob("*.json"))
    if not fichiers:
        raise unittest.SkipTest("Aucune carte dans cartes_sauvegardees/.")
    with open(fichiers[0], "r", encoding="utf-8") as handle:
        carte = json.load(handle)
    return mise_en_place.nouvelle_partie(
        carte, num_players=num_players, ai_player_count=ai_player_count,
        rng=random.Random(11),
    )


def fonder_religion(state, joueur, religion_id=0):
    """Installe une religion nationale sans passer par l'achat d'un temple."""
    state.religion_founders[joueur] = religion_id
    state.religion_foundation_turns[religion_id] = state.turn
    state.religion_last_spread_turns[religion_id] = state.turn
    return religion_id


class TestImmuniteAuxRevoltes(unittest.TestCase):
    """La foi du proprietaire tient le territoire."""

    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 0
        self.religion = fonder_religion(self.state, self.joueur)
        self.possedes = [
            terr for terr in self.state.territories
            if terr.owner == self.joueur
            and not regles.is_active_regular_capital(self.state, terr.id)
        ]
        if not self.possedes:
            self.skipTest("Le joueur 0 n'a aucun territoire hors capitale.")

    def test_influence_nationale_du_proprietaire_protege(self):
        terr = self.possedes[0]
        self.state.religious_influence[terr.id] = self.religion
        self.assertTrue(
            regles.is_protected_from_revolt_by_national_religion(self.state, terr.id)
        )

    def test_religion_etrangere_ne_protege_pas(self):
        terr = self.possedes[0]
        autre = fonder_religion(self.state, 1, religion_id=1)
        self.state.religious_influence[terr.id] = autre
        self.assertFalse(
            regles.is_protected_from_revolt_by_national_religion(self.state, terr.id)
        )

    def test_religion_de_la_merveille_ne_protege_pas(self):
        terr = self.possedes[0]
        # Elyrion appartient a un controleur de merveille, jamais a un fondateur.
        self.state.religion_founders[self.joueur] = regles.WONDER_RELIGION_ID
        self.state.religious_influence[terr.id] = regles.WONDER_RELIGION_ID
        self.assertFalse(
            regles.is_protected_from_revolt_by_national_religion(self.state, terr.id)
        )
        self.assertIsNone(
            regles.get_player_national_religion_id(self.state, self.joueur)
        )

    def test_bloc_de_revolte_ecarte_les_territoires_convertis(self):
        for terr in self.possedes:
            self.state.religious_influence[terr.id] = self.religion
        choisis = regles.choose_owned_contiguous_block(
            self.state, self.joueur, 3, random.Random(3),
            exclude_religion_protected=True,
        )
        self.assertEqual(choisis, [])
        # Sans le drapeau (chaos mondial), le tirage reste possible.
        self.assertTrue(regles.choose_owned_contiguous_block(
            self.state, self.joueur, 3, random.Random(3),
        ))

    def test_sedition_impossible_sur_un_territoire_converti(self):
        terr = max(self.possedes, key=lambda t: t.regiments)
        terr.regiments = 40
        self.assertGreater(
            regles.calculate_sedition_chance_points(self.state, terr), 0
        )
        self.state.religious_influence[terr.id] = self.religion
        self.assertEqual(
            regles.calculate_sedition_chance_points(self.state, terr), 0
        )

    def test_revolte_financee_refusee_si_tout_est_converti(self):
        cible = 1
        fonder_religion(self.state, cible, religion_id=1)
        for terr in self.state.territories:
            if terr.owner == cible:
                self.state.religious_influence[terr.id] = 1
        acheteur = 0
        self.state.current_player = acheteur
        regles.ensure_player_economy(self.state, acheteur)
        self.state.player_money[acheteur] = 10_000
        victime = next(t for t in self.state.territories if t.owner == cible)
        resultat = achats.financer_revolte(self.state, victime, random.Random(5))
        self.assertFalse(resultat.ok)
        self.assertIn("religion nationale", resultat.message)
        # L'argent est rendu : la revolte n'a pas eu lieu.
        self.assertEqual(self.state.player_money[acheteur], 10_000)


class TestMission(unittest.TestCase):
    """La mission : 200 ecus, un clic, n'importe ou sur la carte."""

    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 0
        self.state.current_player = self.joueur
        regles.ensure_player_economy(self.state, self.joueur)
        self.state.player_money[self.joueur] = 1_000
        self.religion = fonder_religion(self.state, self.joueur)

    def _territoire_adverse(self):
        for terr in self.state.territories:
            if terr.owner not in (self.joueur, -1) and not \
                    regles.is_territory_tax_haven_immune_to_religion(self.state, terr.id):
                return terr
        self.skipTest("Aucun territoire adverse convertible.")

    def test_convertit_un_territoire_adverse(self):
        terr = self._territoire_adverse()
        resultat = achats.envoyer_mission(self.state, terr)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(self.state.religious_influence[terr.id], self.religion)
        self.assertEqual(self.state.player_money[self.joueur], 1_000 - regles.MISSION_COST)

    def test_ecrase_une_religion_deja_installee(self):
        terr = self._territoire_adverse()
        self.state.religious_influence[terr.id] = regles.WONDER_RELIGION_ID
        resultat = achats.envoyer_mission(self.state, terr)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(self.state.religious_influence[terr.id], self.religion)

    def test_refusee_sans_religion_nationale(self):
        self.state.religion_founders.pop(self.joueur)
        terr = self._territoire_adverse()
        resultat = achats.envoyer_mission(self.state, terr)
        self.assertFalse(resultat.ok)
        self.assertEqual(self.state.player_money[self.joueur], 1_000)

    def test_refusee_pour_la_religion_de_la_merveille(self):
        self.state.religion_founders[self.joueur] = regles.WONDER_RELIGION_ID
        terr = self._territoire_adverse()
        resultat = achats.envoyer_mission(self.state, terr)
        self.assertFalse(resultat.ok)
        self.assertEqual(self.state.player_money[self.joueur], 1_000)

    def test_refusee_faute_d_ecus(self):
        self.state.player_money[self.joueur] = regles.MISSION_COST - 1
        terr = self._territoire_adverse()
        resultat = achats.envoyer_mission(self.state, terr)
        self.assertFalse(resultat.ok)
        self.assertNotIn(terr.id, self.state.religious_influence)

    def test_paradis_fiscal_impermeable(self):
        capitales = regles.get_all_tax_haven_capital_ids(self.state)
        if not capitales:
            self.skipTest("Aucun paradis fiscal sur cette carte.")
        tid = sorted(capitales)[0]
        resultat = achats.envoyer_mission(self.state, self.state.territories[tid])
        self.assertFalse(resultat.ok)
        self.assertEqual(self.state.player_money[self.joueur], 1_000)


class TestVictoireReligieuse(unittest.TestCase):
    """Neuf dixiemes de la carte pour un humain, trois quarts pour une IA."""

    def setUp(self):
        self.state = partie_neuve()
        self.total = len(self.state.territories)

    def _repandre(self, religion_id, nombre):
        self.state.religious_influence = {
            terr.id: religion_id for terr in self.state.territories[:nombre]
        }

    def test_seuils_humain_et_ia(self):
        humain = 0
        ia = 1
        self.state.base_ai_players.add(ia)
        self.state.human_controlled_players.discard(ia)
        import math
        self.assertEqual(
            regles.get_required_influence_count_for_religion_victory(self.state, humain),
            math.ceil(self.total * 0.9),
        )
        self.assertEqual(
            regles.get_required_influence_count_for_religion_victory(self.state, ia),
            math.ceil(self.total * 0.75),
        )

    def test_neuf_dixiemes_font_gagner_un_humain(self):
        joueur = 0
        religion = fonder_religion(self.state, joueur)
        requis = regles.get_required_influence_count_for_religion_victory(self.state, joueur)
        self._repandre(religion, requis - 1)
        self.assertIsNone(regles.evaluate_winner(self.state)[0])
        self._repandre(religion, requis)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, joueur)
        self.assertIn("9/10", raison)

    def test_trois_quarts_suffisent_a_une_ia(self):
        ia = 1
        self.state.base_ai_players.add(ia)
        self.state.human_controlled_players.discard(ia)
        religion = fonder_religion(self.state, ia, religion_id=1)
        requis = regles.get_required_influence_count_for_religion_victory(self.state, ia)
        self._repandre(religion, requis)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, ia)
        self.assertIn("3/4", raison)

    def test_la_religion_de_la_merveille_ne_fait_pas_gagner(self):
        self._repandre(regles.WONDER_RELIGION_ID, self.total)
        # Personne ne fonde Elyrion : aucun fondateur, donc aucune victoire
        # religieuse (la victoire territoriale, elle, garde ses regles).
        for joueur, religion_id in list(self.state.religion_founders.items()):
            self.assertNotEqual(religion_id, regles.WONDER_RELIGION_ID)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertNotIn("Elyrion", raison)

    def test_un_fondateur_elimine_ne_gagne_pas(self):
        joueur = 0
        religion = fonder_religion(self.state, joueur)
        for terr in self.state.territories:
            if terr.owner == joueur:
                terr.owner = 1
        self._repandre(religion, self.total)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertNotEqual(gagnant, joueur)


class TestMissionParLActionEnLigne(unittest.TestCase):
    """La version en ligne passe par ``moteur.actions`` : l'achat doit exister."""

    def setUp(self):
        self.state = partie_neuve()
        self.state.phase = "shopping"
        self.state.current_player = 0
        regles.ensure_player_economy(self.state, 0)
        self.state.player_money[0] = 1_000
        self.religion = fonder_religion(self.state, 0)

    def test_achat_mission_declare_et_aiguille(self):
        from moteur import actions
        self.assertIn("mission", actions.ACHATS)
        cible = next(
            terr for terr in self.state.territories
            if terr.owner not in (0, -1)
            and not regles.is_territory_tax_haven_immune_to_religion(self.state, terr.id)
        )
        outcome = actions.apply_action(
            self.state,
            {"type": "acheter", "achat": "mission", "territoire": cible.id},
            1200.0 / self.state.cols, 620.0 / self.state.rows,
            random.Random(2),
        )
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(self.state.religious_influence[cible.id], self.religion)


if __name__ == "__main__":
    unittest.main()
