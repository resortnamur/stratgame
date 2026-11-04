"""Regle du 04/11/2026 : un joueur en paradis fiscal corrompt a moitie prix.

La reduction porte sur le total (base par regiment + surcouts) et vaut
aussi pour l'apercu de prix affiche avant confirmation dans le client.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_corruption_pf -v
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from moteur import achats, actions, regles
from test_pf_fin_de_tour import partie_neuve


class CorruptionMoitiePrixEnPf(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 1
        siens = [t for t in self.state.territories if t.owner == self.joueur]
        for terr in siens[1:]:
            terr.owner = 0
        self.state.last_stand_bonus_players = set()
        self.state.last_stand_bonus_territory = {}
        self.state.current_player = self.joueur
        self.state.phase = "playing"
        # La cible : un territoire du joueur 0, hors capitale PF et hors dore.
        self.cible = next(
            t for t in self.state.territories
            if t.owner == 0 and t.id not in self.state.golden_territory_ids
            and not regles.is_last_stand_bonus_territory(self.state, t.id)
        )
        self.cible.regiments = 3
        self.cout_plein = regles.calculate_corruption_cost(self.state, self.cible)[0]

    def passer_en_pf(self):
        actions.advance_turn(
            self.state, 1200.0 / self.state.cols, 620.0 / self.state.rows,
            random.Random(3), begin_next_turn=False,
        )
        self.state.current_player = self.joueur
        self.assertIn(self.joueur, self.state.last_stand_bonus_players)

    def test_prix_plein_hors_pf(self):
        self.assertFalse(regles.has_tax_haven_corruption_discount(self.state, self.joueur))
        self.assertGreater(self.cout_plein, 0)

    def test_moitie_prix_en_pf(self):
        self.passer_en_pf()
        cout, base, surcout = regles.calculate_corruption_cost(self.state, self.cible)
        self.assertEqual(base + surcout, self.cout_plein)
        self.assertEqual(cout, self.cout_plein // 2)

    def test_achat_debite_moitie_prix(self):
        self.passer_en_pf()
        self.state.player_money[self.joueur] = 100000
        resultat = achats.corrompre_territoire(self.state, self.cible)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(100000 - self.state.player_money[self.joueur], self.cout_plein // 2)
        self.assertEqual(self.cible.owner, self.joueur)

    def test_apercu_annonce_le_prix_reduit(self):
        self.passer_en_pf()
        apercu = achats.apercu_corruption(self.state, self.cible)
        self.assertTrue(apercu["possible"])
        self.assertTrue(apercu["reduction_pf"])
        self.assertEqual(apercu["cout"], self.cout_plein // 2)

    def test_apercu_ne_modifie_rien(self):
        argent = self.state.player_money.get(self.joueur, 0)
        achats.apercu_corruption(self.state, self.cible)
        self.assertEqual(self.cible.owner, 0)
        self.assertEqual(self.state.player_money.get(self.joueur, 0), argent)

    def test_apercu_refuse_son_propre_territoire(self):
        mien = next(t for t in self.state.territories if t.owner == self.joueur)
        self.assertFalse(achats.apercu_corruption(self.state, mien)["possible"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
