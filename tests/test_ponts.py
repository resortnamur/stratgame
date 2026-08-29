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


class TestPontsEtVoisinage(unittest.TestCase):
    """Regle d'aout 2026 : un pont donne un voisin de plus.

    Ce voisin compte partout ou le voisinage compte, a commencer par le
    revenu et la culture que le territoire produit. Les ponts dessines sur
    la carte comptent comme les autres : ils survivent au demarrage de la
    partie, alors qu'ils disparaissaient avec l'economie remise a zero.
    """

    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 0
        self.state.current_player = self.joueur
        self.cell_width = 1200.0 / self.state.cols
        self.cell_height = 620.0 / self.state.rows
        regles.ensure_player_economy(self.state, self.joueur)
        self.state.player_science[self.joueur] = 10_000
        self.state.player_money[self.joueur] = 100_000

    def _candidats_depuis(self, territory_id):
        return [
            (a, b) for (a, b), _points in regles.get_valid_bridge_candidates(
                self.state, self.cell_width, self.cell_height,
            )
            if territory_id in (a, b)
        ]

    def test_un_pont_ajoute_un_voisin_et_ce_qu_il_rapporte(self):
        candidats = regles.get_valid_bridge_candidates(
            self.state, self.cell_width, self.cell_height,
        )
        if not candidats:
            self.skipTest("Aucun pont possible sur cette carte.")
        (a, b), _points = candidats[0]
        terr = self.state.territories[a]
        # Un centre culturel pour que la culture du territoire soit visible.
        self.state.cultural_center_ages.pop(terr.id, None)
        self.state.ruin_territory_ids.discard(terr.id)
        regles.add_cultural_center(self.state, terr.id, age=0)

        voisins_avant = len(terr.neighbors)
        revenu_avant = regles.calculate_territory_income(self.state, terr)
        culture_avant = regles.calculate_territory_culture(self.state, terr)

        resultat = achats.construire_pont(
            self.state, a, b, self.cell_width, self.cell_height,
        )
        self.assertTrue(resultat.ok, resultat.message)

        self.assertEqual(len(terr.neighbors), voisins_avant + 1)
        self.assertIn(b, terr.neighbors)
        self.assertGreater(regles.calculate_territory_income(self.state, terr), revenu_avant)
        self.assertGreater(regles.calculate_territory_culture(self.state, terr), culture_avant)
        # Le voisinage vaut dans les deux sens.
        self.assertIn(a, self.state.territories[b].neighbors)

    def test_trois_ponts_font_trois_voisins_de_plus(self):
        depart = None
        for terr in self.state.territories:
            if len(self._candidats_depuis(terr.id)) >= 3:
                depart = terr
                break
        if depart is None:
            self.skipTest("Aucun territoire ne peut recevoir trois ponts.")
        voisins_avant = len(depart.neighbors)
        poses = 0
        for a, b in self._candidats_depuis(depart.id):
            autre = b if a == depart.id else a
            if autre in depart.neighbors:
                continue
            resultat = achats.construire_pont(
                self.state, a, b, self.cell_width, self.cell_height,
            )
            if resultat.ok:
                poses += 1
            if poses == 3:
                break
        if poses < 3:
            self.skipTest("Trois ponts n'ont pas pu etre construits.")
        self.assertEqual(len(depart.neighbors), voisins_avant + 3)

    def test_detruire_un_pont_reprend_le_voisin(self):
        candidats = regles.get_valid_bridge_candidates(
            self.state, self.cell_width, self.cell_height,
        )
        if not candidats:
            self.skipTest("Aucun pont possible sur cette carte.")
        (a, b), _points = candidats[0]
        terr = self.state.territories[a]
        voisins_avant = len(terr.neighbors)
        self.assertTrue(
            achats.construire_pont(self.state, a, b, self.cell_width, self.cell_height).ok
        )
        self.assertEqual(len(terr.neighbors), voisins_avant + 1)
        self.assertTrue(achats.detruire_pont(self.state, a, b).ok)
        self.assertEqual(len(terr.neighbors), voisins_avant)
        self.assertNotIn(b, terr.neighbors)


class TestPontsDeLaCarte(unittest.TestCase):
    """Les ponts dessines sur la carte survivent au demarrage de la partie."""

    def _carte_avec_pont(self):
        for chemin in sorted(CARTES_DIR.glob("*.json")):
            try:
                with open(chemin, "r", encoding="utf-8") as handle:
                    carte = json.load(handle)
            except (OSError, ValueError):
                continue
            if isinstance(carte, dict) and carte.get("bridge_links"):
                return carte
        return None

    def test_le_pont_de_la_carte_reste_et_compte_comme_voisin(self):
        carte = self._carte_avec_pont()
        if carte is None:
            self.skipTest("Aucune carte sauvegardee ne porte de pont.")
        attendus = {
            tuple(sorted((int(a), int(b)))) for a, b in carte["bridge_links"]
        }
        state = mise_en_place.nouvelle_partie(
            carte, num_players=4, ai_player_count=0, rng=random.Random(7),
        )
        self.assertEqual(set(state.bridge_links), attendus)
        for a, b in attendus:
            self.assertIn(b, state.territories[a].neighbors)
            self.assertIn(a, state.territories[b].neighbors)


if __name__ == "__main__":
    unittest.main()
