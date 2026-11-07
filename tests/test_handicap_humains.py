"""Regle du 07/11/2026 : les joueurs humains commencent avec un tiers de
regiments en moins.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_handicap_humains -v
"""

import json
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import mise_en_place, regles

CARTES_DIR = Path(__file__).resolve().parents[1] / "cartes_sauvegardees"


def charger_carte():
    for chemin in sorted(CARTES_DIR.glob("*.json")):
        try:
            carte = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(carte, dict) and carte.get("territories"):
            return carte
    raise unittest.SkipTest("Aucune carte exploitable dans cartes_sauvegardees/.")


def regiments_par_joueur(state):
    totaux = {}
    for terr in state.territories:
        if terr.owner >= 0:
            totaux[terr.owner] = totaux.get(terr.owner, 0) + terr.regiments
    return totaux


class TestHandicapHumains(unittest.TestCase):
    def partie(self, handicap=None, graine=5):
        carte = charger_carte()
        patch = (
            mock.patch.object(mise_en_place, "HUMAN_STARTING_REGIMENT_HANDICAP", handicap)
            if handicap is not None else mock.patch.object(mise_en_place, "random", random)
        )
        with patch:
            return mise_en_place.nouvelle_partie(
                json.loads(json.dumps(carte)), num_players=4, ai_player_count=2,
                rng=random.Random(graine),
            )

    def test_les_humains_perdent_un_tiers_les_ia_rien(self):
        sans = self.partie(handicap=0)
        avec = self.partie()
        avant, apres = regiments_par_joueur(sans), regiments_par_joueur(avec)
        humains = [p for p in range(avec.num_players)
                   if regles.is_human_player_id(avec, p)
                   and p not in avec.commercial_city_players]
        self.assertEqual(humains, [2, 3])
        for joueur in avant:
            if joueur in humains:
                self.assertEqual(apres[joueur], avant[joueur] - avant[joueur] // 3, joueur)
            else:
                self.assertEqual(apres[joueur], avant[joueur], joueur)
        # Memes territoires de part et d'autre : seule la garnison change.
        self.assertEqual(
            [t.owner for t in sans.territories], [t.owner for t in avec.territories])

    def test_jamais_moins_d_un_regiment_par_territoire(self):
        state = self.partie()
        for terr in state.territories:
            if terr.owner >= 0:
                self.assertGreaterEqual(terr.regiments, 1)

    def test_le_plancher_d_un_regiment_borne_la_perte(self):
        state = self.partie(handicap=0)
        for terr in state.territories:
            if terr.owner == 3:
                terr.regiments = 1
        mise_en_place.apply_human_regiment_handicap(state, random.Random(1))
        self.assertTrue(all(t.regiments == 1 for t in state.territories if t.owner == 3))


if __name__ == "__main__":
    unittest.main()
