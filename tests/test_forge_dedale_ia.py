"""La Forge de Dedale se pose la ou elle sert : le territoire d'ou l'IA
pourra batir le plus de ponts.

La merveille ne rend gratuits que les ponts dont une extremite est son
propre territoire (cf. ``achats.pont_offert_par_la_forge``). La poser sur
la province la plus riche, comme pour les autres merveilles, gaspillait
l'effet : le choix est desormais fait au nombre de ponts encore
constructibles depuis chaque territoire.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_forge_dedale_ia -v
"""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
        carte, num_players=4, ai_player_count=4, rng=random.Random(7),
    )


class TestPlacementForgeDedale(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.cell_width = 1200.0 / self.state.cols
        self.cell_height = 620.0 / self.state.rows
        self.joueur = next(
            joueur for joueur in regles.get_active_players(self.state)
            if regles.is_ai_player(self.state, joueur)
            and not regles.is_commercial_city_player(self.state, joueur)
        )
        self.ponts = {
            terr.id: regles.count_buildable_bridges_from_territory(
                self.state, terr.id, self.cell_width, self.cell_height,
            )
            for terr in self.state.territories
        }
        self._forge_seule()

    def _forge_seule(self):
        """Ne laisse que la Forge de Dedale a batir, sans toucher aux seuils."""
        self._buildable_origine = regles.get_buildable_wonder_types
        regles.get_buildable_wonder_types = lambda state, player: ["daedalus_forge"]
        self.addCleanup(
            setattr, regles, "get_buildable_wonder_types", self._buildable_origine,
        )

    def _cible_choisie(self):
        action = regles.find_ai_wonder_purchase(
            self.state, self.joueur, random.Random(1), self.cell_width, self.cell_height,
        )
        self.assertIsNotNone(action, "l'IA devrait pouvoir batir la Forge de Dedale")
        _cout, callback = action
        self.assertTrue(callback(), "la construction de la merveille devrait aboutir")
        return self.state.wonder_territories["daedalus_forge"]

    def test_la_forge_va_au_meilleur_point_de_passage(self):
        """Parmi ses territoires, l'IA choisit celui qui ouvre le plus de ponts."""
        possedes = [
            terr for terr in self.state.territories if terr.owner == self.joueur
        ]
        if not possedes:
            self.skipTest("L'IA tiree ne controle aucun territoire.")
        meilleur = max(self.ponts[terr.id] for terr in possedes)
        cible = self._cible_choisie()
        self.assertEqual(self.state.territories[cible].owner, self.joueur)
        self.assertEqual(
            self.ponts[cible], meilleur,
            "la Forge doit se poser sur un territoire au maximum de ponts constructibles",
        )

    def test_le_territoire_le_plus_riche_ne_l_emporte_plus(self):
        """Une province riche mais enclavee perd face au carrefour maritime."""
        carrefour = max(self.ponts, key=lambda tid: (self.ponts[tid], -tid))
        if self.ponts[carrefour] == 0:
            self.skipTest("Carte sans aucun pont constructible.")
        enclave = min(self.ponts, key=lambda tid: (self.ponts[tid], tid))
        self.assertEqual(self.ponts[enclave], 0, "il faut un territoire sans pont possible")

        # L'IA ne tient que ces deux territoires ; l'enclave est la plus riche.
        for terr in self.state.territories:
            if terr.owner == self.joueur:
                terr.owner = (self.joueur + 1) % self.state.num_players
        self.state.territories[carrefour].owner = self.joueur
        self.state.territories[enclave].owner = self.joueur
        self.state.factory_territory_ids.add(enclave)
        self.state.airport_territory_ids.add(enclave)
        self.state.port_territory_ids.add(enclave)
        self.state.sanctuary_territory_ids.discard(carrefour)
        self.state.sanctuary_territory_ids.discard(enclave)

        revenu_enclave = regles.calculate_territory_income(
            self.state, self.state.territories[enclave],
        )
        revenu_carrefour = regles.calculate_territory_income(
            self.state, self.state.territories[carrefour],
        )
        self.assertGreater(
            revenu_enclave, revenu_carrefour,
            "le scenario exige que l'ancien critere (le revenu) designe l'enclave",
        )

        self.assertEqual(self._cible_choisie(), carrefour)

    def test_les_autres_merveilles_gardent_le_critere_du_revenu(self):
        """Seule la Forge change de critere : le reste suit toujours l'argent."""
        regles.get_buildable_wonder_types = lambda state, player: ["croesus_fountain"]
        possedes = [
            terr for terr in self.state.territories if terr.owner == self.joueur
        ]
        if not possedes:
            self.skipTest("L'IA tiree ne controle aucun territoire.")
        attendu = max(
            (terr for terr in possedes if not regles.is_sanctuary_territory(self.state, terr.id)),
            key=lambda terr: (
                regles.calculate_territory_income(self.state, terr),
                len(terr.neighbors),
                terr.regiments,
                -terr.id,
            ),
        )
        action = regles.find_ai_wonder_purchase(
            self.state, self.joueur, random.Random(1), self.cell_width, self.cell_height,
        )
        self.assertIsNotNone(action)
        _cout, callback = action
        callback()
        self.assertEqual(self.state.wonder_territories["croesus_fountain"], attendu.id)


if __name__ == "__main__":
    unittest.main()
