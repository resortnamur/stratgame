"""Regle de novembre 2026 : un joueur ne peut BATIR que 5 merveilles.

C'est la construction qui est limitee, pas la possession :
- une merveille perdue ne rend pas de place ;
- une merveille conquise ne prend pas de place ;
- le compteur survit a la sauvegarde.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_limite_merveilles -v
"""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import achats
from moteur import mise_en_place
from moteur import regles

CARTES_DIR = Path(__file__).resolve().parents[1] / "cartes_sauvegardees"
# Tardives (sans seuil de science ni de culture) puis classiques.
LIMITE = regles.MAX_WONDERS_BUILT_PER_PLAYER


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


class LimiteMerveilles(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.state.current_player = 0
        self.state.turn = regles.LATE_WONDER_FIRST_TURN
        regles.ensure_player_economy(self.state, 0)
        regles.ensure_player_economy(self.state, 1)
        # Seuils de science et de culture leves pour toutes les familles.
        self.state.player_science[0] = 100_000
        self.state.player_science[1] = 100_000

    def libres(self, joueur):
        return [
            t for t in self.state.territories
            if t.owner == joueur
            and regles.get_wonder_type_at_territory(self.state, t.id) is None
            and not regles.is_sanctuary_territory(self.state, t.id)
        ]

    def batir(self, joueur=0):
        """Construit, via la boutique, la premiere merveille constructible."""
        self.state.current_player = joueur
        self.state.player_money[joueur] = 100_000
        self.state.wonder_construction_turns = {}  # un nouveau tour
        types = [
            w for w in regles.get_buildable_wonder_types(self.state, joueur)
            if not regles.is_apocalypse_wonder_type(w)
        ]
        type_ = types[0] if types else "solmyre_oracle"
        return achats.construire_merveille(self.state, self.libres(joueur)[0], type_), type_

    def test_cinq_merveilles_puis_refus(self):
        for _ in range(LIMITE):
            res, type_ = self.batir()
            self.assertTrue(res.ok, (type_, res.message))
        self.assertEqual(regles.get_player_wonders_built(self.state, 0), LIMITE)
        self.assertEqual(regles.get_buildable_wonder_types(self.state, 0), [])
        argent = self.state.player_money[0] = 100_000
        self.state.wonder_construction_turns = {}
        type_ = next(iter(regles.get_available_wonder_types(self.state)))
        res = achats.construire_merveille(self.state, self.libres(0)[0], type_)
        self.assertFalse(res.ok)
        self.assertIn("Limite atteinte", res.message)
        self.assertEqual(self.state.player_money[0], argent)

    def test_perdre_une_merveille_ne_rend_pas_de_place(self):
        for _ in range(LIMITE):
            self.assertTrue(self.batir()[0].ok)
        # Le joueur 1 prend une des merveilles du joueur 0.
        tid = next(iter(self.state.wonder_territories.values()))
        self.state.territories[tid].owner = 1
        self.assertEqual(regles.get_buildable_wonder_types(self.state, 0), [])
        # ... et ce butin ne compte pas dans le quota du joueur 1.
        self.assertEqual(regles.get_player_wonders_built(self.state, 1), 0)
        self.assertTrue(self.batir(joueur=1)[0].ok)

    def test_ia_respecte_la_limite(self):
        self.state.player_wonders_built[0] = LIMITE
        self.state.base_ai_players = {0}
        self.assertIsNone(regles.find_ai_wonder_purchase(self.state, 0))

    def test_compteur_sauvegarde(self):
        self.assertTrue(self.batir()[0].ok)
        self.assertTrue(self.batir()[0].ok)
        recharge = GameState.from_payload(self.state.to_payload())
        self.assertEqual(regles.get_player_wonders_built(recharge, 0), 2)

    def test_sceau_compte_pour_une_a_sa_fermeture(self):
        self.state.turn = regles.APOCALYPSE_FIRST_TURN
        terr = self.libres(0)[0]
        for _ in range(regles.APOCALYPSE_STAGES - 1):
            regles.advance_apocalypse_site(self.state, terr.id, 0)
        self.assertEqual(regles.get_player_wonders_built(self.state, 0), 0)
        regles.advance_apocalypse_site(self.state, terr.id, 0)
        self.assertEqual(regles.get_player_wonders_built(self.state, 0), 1)


if __name__ == "__main__":
    unittest.main()
