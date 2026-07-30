"""Regle de juillet 2026 : un joueur ne peut construire un pont que depuis
un territoire qu'il controle — au moins une des deux extremites doit lui
appartenir (pas forcement les deux).

La regle vit dans ``moteur.achats.construire_pont``, seul point d'entree des
constructions de ponts par un joueur (x45 comme la version en ligne passent
par lui). Les ponts aleatoires (evenement naturel) ne sont pas concernes.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_ponts -v
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


def partie_neuve():
    fichiers = sorted(CARTES_DIR.glob("*.json"))
    if not fichiers:
        raise unittest.SkipTest("Aucune carte dans cartes_sauvegardees/.")
    with open(fichiers[0], "r", encoding="utf-8") as handle:
        carte = json.load(handle)
    return mise_en_place.nouvelle_partie(
        carte, num_players=4, ai_player_count=0, rng=random.Random(7),
    )


class TestPontDepuisSonTerritoire(unittest.TestCase):
    """Construire un pont exige de controler au moins une extremite."""

    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 0
        self.state.current_player = self.joueur
        self.cell_width = 1200.0 / self.state.cols
        self.cell_height = 620.0 / self.state.rows
        # Science et argent au max : seule la regle de possession joue.
        regles.ensure_player_economy(self.state, self.joueur)
        self.state.player_science[self.joueur] = 10_000
        self.state.player_money[self.joueur] = 10_000
        self.candidats = regles.get_valid_bridge_candidates(
            self.state, self.cell_width, self.cell_height,
        )

    def _candidat(self, condition):
        for (terr_a, terr_b), _points in self.candidats:
            if condition(terr_a, terr_b):
                return terr_a, terr_b
        return None

    def test_refus_sans_extremite_controlee(self):
        candidat = self._candidat(
            lambda a, b: self.state.territories[a].owner != self.joueur
            and self.state.territories[b].owner != self.joueur
        )
        if candidat is None:
            self.skipTest("Aucun pont candidat entierement hors du joueur 0.")
        argent_avant = self.state.player_money[self.joueur]
        resultat = achats.construire_pont(
            self.state, candidat[0], candidat[1], self.cell_width, self.cell_height,
        )
        self.assertFalse(resultat.ok)
        self.assertIn("controler au moins un", resultat.message)
        self.assertEqual(self.state.player_money[self.joueur], argent_avant)
        self.assertNotIn(tuple(sorted(candidat)), self.state.bridge_links)

    def test_succes_avec_une_extremite_controlee(self):
        candidat = self._candidat(
            lambda a, b: (self.state.territories[a].owner == self.joueur)
            != (self.state.territories[b].owner == self.joueur)
        )
        if candidat is None:
            self.skipTest("Aucun pont candidat avec exactement une extremite au joueur 0.")
        resultat = achats.construire_pont(
            self.state, candidat[0], candidat[1], self.cell_width, self.cell_height,
        )
        self.assertTrue(resultat.ok, resultat.message)
        self.assertIn(tuple(sorted(candidat)), self.state.bridge_links)

    def test_succes_avec_les_deux_extremites_controlees(self):
        candidat = self._candidat(
            lambda a, b: self.state.territories[a].owner == self.joueur
            and self.state.territories[b].owner == self.joueur
        )
        if candidat is None:
            self.skipTest("Aucun pont candidat entierement chez le joueur 0.")
        resultat = achats.construire_pont(
            self.state, candidat[0], candidat[1], self.cell_width, self.cell_height,
        )
        self.assertTrue(resultat.ok, resultat.message)
        self.assertIn(tuple(sorted(candidat)), self.state.bridge_links)


if __name__ == "__main__":
    unittest.main()
