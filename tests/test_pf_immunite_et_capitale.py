"""Deux regles dictees le 14/11/2026, sur le mode paradis fiscal.

1. Un joueur en paradis fiscal ne perd jamais d'argent : ni dans une crise
   boursiere, ni dans un krach.
2. Un palier culturel annexe un territoire adjacent au hasard, mais jamais
   une capitale -- y compris la ville d'origine d'un joueur passe en
   paradis fiscal, qui ne figure plus dans player_capital_ids.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_pf_immunite_et_capitale -v
"""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def reduire_a_un_territoire(state, player):
    """Ne laisse qu'un territoire au joueur, et le passe en paradis fiscal."""
    possedes = [terr for terr in state.territories if terr.owner == player]
    assert possedes, "le joueur ne possede rien"
    garde = possedes[0]
    repreneur = next(
        terr.owner for terr in state.territories
        if terr.owner not in (player, state.onu_player_id)
    )
    for terr in possedes[1:]:
        terr.owner = repreneur
    regles.activate_last_stand_bonus_if_needed(state, player)
    return garde


class ImmuniteBoursiere(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.pf = 0
        self.bastion = reduire_a_un_territoire(self.state, self.pf)

    def test_le_joueur_est_bien_en_paradis_fiscal(self):
        self.assertTrue(regles.is_tax_haven_player(self.state, self.pf))
        self.assertIn(self.bastion.id, regles.get_player_tax_haven_capital_ids(self.state, self.pf))

    def _declencher(self, event_type):
        """Force une crise ou un krach, sans dependre du tirage."""
        class DeTruque:
            def __init__(self, crash):
                self.crash = crash

            def randint(self, a, b):
                # randint(1, 50) == 1 -> krach ; randint(1, 10) == 1 -> crise
                if b == 50:
                    return 1 if self.crash else 2
                return 1

            def random(self):
                return 0.0

        for player in self.state.player_money:
            self.state.player_money[player] = 900
        message = regles.maybe_trigger_market_event(
            self.state, rng=DeTruque(event_type == "crash"),
        )
        self.assertIsNotNone(message)
        self.assertIn(event_type, message)
        return message

    def test_crise_boursiere_sans_perte_pour_le_paradis_fiscal(self):
        message = self._declencher("crise")
        self.assertEqual(self.state.player_money[self.pf], 900)
        self.assertEqual(self.state.player_money[1], 600)
        self.assertIn("paradis fiscal", message)

    def test_krach_sans_perte_pour_le_paradis_fiscal(self):
        self._declencher("crash")
        self.assertEqual(self.state.player_money[self.pf], 900)
        self.assertEqual(self.state.player_money[1], 300)


class CapitaleJamaisAnnexeeParLaCulture(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.pf = 0
        self.bastion = reduire_a_un_territoire(self.state, self.pf)

    def test_la_ville_d_origine_pf_n_est_pas_une_cible_culturelle(self):
        voisin = next(
            (nid for nid in self.bastion.neighbors
             if 0 <= nid < len(self.state.territories)
             and self.state.territories[nid].owner not in (self.pf, self.state.onu_player_id)),
            None,
        )
        if voisin is None:
            self.skipTest("Le bastion n'a pas de voisin ennemi sur cette carte.")
        annexeur = self.state.territories[voisin].owner
        cibles = regles.get_culture_expansion_target_ids(self.state, annexeur)
        self.assertNotIn(self.bastion.id, cibles)

    def test_l_annexion_directe_du_bastion_pf_est_refusee(self):
        voisin = next(
            (nid for nid in self.bastion.neighbors
             if 0 <= nid < len(self.state.territories)
             and self.state.territories[nid].owner not in (self.pf, self.state.onu_player_id)),
            None,
        )
        if voisin is None:
            self.skipTest("Le bastion n'a pas de voisin ennemi sur cette carte.")
        annexeur = self.state.territories[voisin].owner
        self.assertIsNone(
            regles.annex_territory_by_culture(self.state, self.bastion.id, annexeur)
        )
        self.assertEqual(self.state.territories[self.bastion.id].owner, self.pf)

    def test_le_palier_culturel_epargne_le_bastion_pf(self):
        """Le joueur PF a repris des villes : son bastion reste intouchable."""
        voisins_ennemis = [
            nid for nid in self.bastion.neighbors
            if 0 <= nid < len(self.state.territories)
            and self.state.territories[nid].owner not in (self.pf, self.state.onu_player_id)
        ]
        if not voisins_ennemis:
            self.skipTest("Le bastion n'a pas de voisin ennemi sur cette carte.")
        annexeur = self.state.territories[voisins_ennemis[0]].owner
        # Le joueur PF recupere un territoire (sedition) : il en a deux,
        # mais son bastion reste sa capitale paradis fiscal.
        self.state.culture_expansion_milestones[annexeur] = 0
        for _ in range(40):
            regles.trigger_culture_expansions_if_due(
                self.state, annexeur, rng=random.Random(3),
            )
            self.state.culture_expansion_milestones[annexeur] = 0
            self.assertEqual(
                self.state.territories[self.bastion.id].owner, self.pf,
                "le bastion paradis fiscal a ete annexe par un palier culturel",
            )


if __name__ == "__main__":
    unittest.main()
