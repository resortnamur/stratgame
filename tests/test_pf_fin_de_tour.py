"""Regle de novembre 2026 : le passage en paradis fiscal se juge des la fin
du tour du joueur, et non plus seulement au debut de son tour suivant.

Le cas qui motive la regle : un joueur finit son tour avec un seul
territoire, puis en recoit un second avant de rejouer (vente d'un autre
joueur, par exemple). Il doit etre devenu paradis fiscal quand meme.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_pf_fin_de_tour -v
"""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import actions
from moteur import mise_en_place
from moteur import regles

CARTES_DIR = Path(__file__).resolve().parents[1] / "cartes_sauvegardees"


def partie_neuve():
    for chemin in sorted(CARTES_DIR.glob("*.json")):
        try:
            carte = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(carte, dict) and carte.get("territories"):
            return mise_en_place.nouvelle_partie(
                carte, num_players=4, ai_player_count=0, rng=random.Random(11),
            )
    raise unittest.SkipTest("Aucune carte exploitable dans cartes_sauvegardees/.")


class PassagePfEnFinDeTour(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.cw = 1200.0 / self.state.cols
        self.ch = 620.0 / self.state.rows
        self.joueur = 1
        # Le joueur 1 est ramene a un seul territoire ; le reste passe au 0.
        siens = [t for t in self.state.territories if t.owner == self.joueur]
        self.bastion = siens[0]
        for terr in siens[1:]:
            terr.owner = 0
        self.state.last_stand_bonus_players = set()
        self.state.last_stand_bonus_territory = {}
        self.state.current_player = self.joueur
        self.state.phase = "playing"

    def finir_le_tour(self):
        return actions.advance_turn(
            self.state, self.cw, self.ch, random.Random(3), begin_next_turn=False,
        )

    def test_pf_des_la_fin_du_tour(self):
        rapport = self.finir_le_tour()
        self.assertIn(self.joueur, self.state.last_stand_bonus_players)
        self.assertIn(self.bastion.id, regles.get_player_tax_haven_capital_ids(self.state, self.joueur))
        self.assertIn(self.bastion.id, self.state.fortress_territory_ids)
        self.assertTrue(rapport.last_stand_message)

    def test_territoire_recu_entre_temps_ne_fait_pas_manquer_le_statut(self):
        self.finir_le_tour()
        # Avant que le joueur 1 ne rejoue, un autre joueur lui cede un territoire.
        cede = next(t for t in self.state.territories if t.owner == 0)
        cede.owner = self.joueur
        self.state.current_player = self.joueur
        actions.begin_player_turn(self.state, self.joueur, random.Random(4))
        self.assertIn(self.joueur, self.state.last_stand_bonus_players)

    def test_le_debut_de_tour_rattrape_toujours_le_joueur_conquis(self):
        # Ramene a un territoire pendant le tour des autres : le debut de son
        # tour le fait toujours passer en paradis fiscal.
        self.state.current_player = self.joueur
        actions.begin_player_turn(self.state, self.joueur, random.Random(4))
        self.assertIn(self.joueur, self.state.last_stand_bonus_players)

    def test_pas_de_pf_avec_deux_territoires_en_fin_de_tour(self):
        cede = next(t for t in self.state.territories if t.owner == 0)
        cede.owner = self.joueur
        self.finir_le_tour()
        self.assertNotIn(self.joueur, self.state.last_stand_bonus_players)


if __name__ == "__main__":
    unittest.main()
