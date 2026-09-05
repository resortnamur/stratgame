"""Chaque merveille doit avoir son icone, dans les deux versions.

Les quatre merveilles tardives d'aout 2026 sont arrivees sans entree dans
la table des couleurs : elles s'affichaient en pastilles grises et muettes,
des deux cotes. Ce test rend la recidive impossible — ajouter une merveille
sans lui donner sa couleur casse la suite.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_icones_merveilles -v
"""

import io
import os
import re
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from moteur import regles

CLIENT_JS = RACINE / "client" / "app.js"
GRIS_DE_SECOURS = ((70, 70, 70), (235, 235, 235))


class TestIconesDesMerveillesX45(unittest.TestCase):
    """La table des couleurs de x45 couvre toutes les merveilles."""

    @classmethod
    def setUpClass(cls):
        try:
            import x45
        except Exception as exc:  # pygame absent ou affichage impossible
            raise unittest.SkipTest(f"x45 non importable ici : {exc}")
        cls.x45 = x45

    def test_x45_connait_toutes_les_merveilles_du_moteur(self):
        """x45 ne doit pas garder sa propre table de merveilles.

        Il en gardait une copie : les merveilles ajoutees ensuite y
        manquaient, et sa boutique plantait sur un KeyError des que l'une
        d'elles devenait constructible — la liste des merveilles a batir
        vient du moteur, leur description venait de la copie.
        """
        table = self.x45.GraphicalGame.WONDER_DEFINITIONS
        self.assertEqual(dict(table), dict(regles.WONDER_DEFINITIONS))
        for wonder_type in regles.WONDER_DEFINITIONS:
            with self.subTest(merveille=wonder_type):
                # L'acces direct est celui que fait la boutique de x45.
                self.assertIn("name", table[wonder_type])

    def test_chaque_merveille_a_sa_couleur(self):
        couleurs = self.x45.GraphicalGame.WONDER_BADGE_COLORS
        for wonder_type in regles.WONDER_DEFINITIONS:
            self.assertIn(wonder_type, couleurs, wonder_type)

    def test_aucune_merveille_ne_tombe_sur_le_gris_de_secours(self):
        couleurs = self.x45.GraphicalGame.WONDER_BADGE_COLORS
        for wonder_type in regles.WONDER_DEFINITIONS:
            self.assertNotEqual(couleurs[wonder_type], GRIS_DE_SECOURS, wonder_type)

    def test_les_couleurs_de_fond_sont_toutes_distinctes(self):
        fonds = [
            fond for wonder_type, (fond, _symbole)
            in self.x45.GraphicalGame.WONDER_BADGE_COLORS.items()
            if wonder_type in regles.WONDER_DEFINITIONS
        ]
        self.assertEqual(len(fonds), len(set(fonds)))

    def test_chaque_merveille_a_son_dessin(self):
        """Le badge doit dessiner autre chose qu'un rectangle vide."""
        import pygame

        jeu = self.x45.GraphicalGame()
        surface = pygame.Surface((40, 40))
        ancien, jeu.screen = jeu.screen, surface
        try:
            for wonder_type in regles.WONDER_DEFINITIONS:
                surface.fill((0, 0, 0))
                jeu.draw_wonder_badge(20, 20, wonder_type)
                _fond, symbole = self.x45.GraphicalGame.WONDER_BADGE_COLORS[wonder_type]
                # Le symbole occupe l'interieur du badge : on le cherche la,
                # loin du contour qui porte la meme couleur.
                interieur = [
                    surface.get_at((x, y))[:3]
                    for x in range(14, 27) for y in range(14, 27)
                ]
                self.assertIn(symbole, interieur, wonder_type)
        finally:
            jeu.screen = ancien


class TestIconesDesMerveillesEnLigne(unittest.TestCase):
    """La table des couleurs du client web couvre toutes les merveilles."""

    def setUp(self):
        if not CLIENT_JS.is_file():
            self.skipTest("client/app.js introuvable.")
        self.source = io.open(CLIENT_JS, encoding="utf-8").read()

    def _table_des_couleurs(self):
        debut = self.source.index('elyrion_sanctuary: ["rgb(')
        fin = self.source.index("};", debut)
        return self.source[debut:fin]

    def test_chaque_merveille_a_sa_couleur(self):
        table = self._table_des_couleurs()
        for wonder_type in regles.WONDER_DEFINITIONS:
            self.assertIn(f"{wonder_type}:", table, wonder_type)

    def test_chaque_merveille_a_son_glyphe(self):
        table = self._table_des_couleurs()
        for wonder_type in regles.WONDER_DEFINITIONS:
            entree = re.search(
                rf'{wonder_type}: \["[^"]+", "[^"]+", "([^"]+)"\]', table,
            )
            self.assertIsNotNone(entree, wonder_type)
            self.assertNotEqual(entree.group(1), "?", wonder_type)

    def test_les_glyphes_sont_tous_distincts(self):
        table = self._table_des_couleurs()
        glyphes = re.findall(r': \["[^"]+", "[^"]+", "([^"]+)"\]', table)
        self.assertEqual(len(glyphes), len(regles.WONDER_DEFINITIONS))
        self.assertEqual(len(glyphes), len(set(glyphes)))


if __name__ == "__main__":
    unittest.main()
