"""Regles d'aout 2026 : les vues de la carte.

Le bouton fait desormais tourner quatre vues :

1. les forteresses seules ;
2. les forteresses avec les merveilles ;
3. tous les autres amenagements — usines, aeroports, ports, temples,
   centres culturels, ruines, universites — sans forteresse ni merveille ;
4. l'influence religieuse, inchangee.

Les statuts (mines, lieux saints, capitales, paradis fiscaux) restent
visibles dans toutes les vues : sans eux, on confondrait une capitale avec
un territoire ordinaire.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_vues_carte -v
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestVuesDeLaCarte(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import x45
        except Exception as exc:  # pygame absent ou affichage impossible
            raise unittest.SkipTest(f"x45 non importable ici : {exc}")
        cls.jeu = x45.GraphicalGame()

    def setUp(self):
        self.jeu.simple_mode = False
        self.jeu.map_icon_view = "fortress"

    def test_les_quatre_vues_dans_l_ordre(self):
        self.assertEqual(
            self.jeu.MAP_ICON_VIEWS, ("fortress", "wonders", "amenities", "religion"),
        )

    def test_le_bouton_fait_le_tour(self):
        vues = []
        for _ in range(len(self.jeu.MAP_ICON_VIEWS) + 1):
            self.jeu.toggle_all_map_icons()
            vues.append(self.jeu.get_map_icon_view())
        self.assertEqual(vues, ["wonders", "amenities", "religion", "fortress", "wonders"])

    def test_forteresses_seules(self):
        self.jeu.map_icon_view = "fortress"
        self.assertTrue(self.jeu.map_view_shows_fortresses())
        self.assertFalse(self.jeu.map_view_shows_wonders())
        self.assertFalse(self.jeu.map_view_shows_amenities())

    def test_forteresses_avec_merveilles(self):
        self.jeu.map_icon_view = "wonders"
        self.assertTrue(self.jeu.map_view_shows_fortresses())
        self.assertTrue(self.jeu.map_view_shows_wonders())
        self.assertFalse(self.jeu.map_view_shows_amenities())

    def test_les_autres_amenagements_sans_forteresse_ni_merveille(self):
        self.jeu.map_icon_view = "amenities"
        self.assertFalse(self.jeu.map_view_shows_fortresses())
        self.assertFalse(self.jeu.map_view_shows_wonders())
        self.assertTrue(self.jeu.map_view_shows_amenities())

    def test_la_vue_religion_garde_ses_forteresses(self):
        self.jeu.map_icon_view = "religion"
        self.assertTrue(self.jeu.is_religion_view_active())
        self.assertTrue(self.jeu.map_view_shows_fortresses())
        self.assertFalse(self.jeu.map_view_shows_wonders())
        self.assertFalse(self.jeu.map_view_shows_amenities())

    def test_la_version_simplifiee_saute_la_religion(self):
        self.jeu.simple_mode = True
        self.jeu.map_icon_view = "amenities"
        self.jeu.toggle_all_map_icons()
        self.assertEqual(self.jeu.get_map_icon_view(), "fortress")

    def test_une_vue_inconnue_retombe_sur_les_forteresses(self):
        self.jeu.map_icon_view = "all"  # l'ancienne vue « toutes les icones »
        self.assertEqual(self.jeu.get_map_icon_view(), "fortress")

    def test_chaque_vue_a_son_libelle_et_son_bouton(self):
        for vue in self.jeu.MAP_ICON_VIEWS:
            self.assertIn(vue, self.jeu.MAP_ICON_VIEW_LABELS)
            self.assertIn(vue, self.jeu.MAP_ICON_VIEW_BUTTONS)


if __name__ == "__main__":
    unittest.main()
