"""Palais du Pacte d'Or et Cites commercantes (correctif juillet 2026).

Tant que le Palais est construit, la CC reste tres agressive et ignore la
limite des 10 territoires. Son controleur (s'il est valide) est son unique
allie protege ; sans controleur valide (territoire a l'ONU, fige ou aux
mains de la CC), la CC n'a plus d'allie et attaque tout le monde — elle ne
retombe plus dans la passivite totale observee auparavant.

Lancement : ``python -m unittest tests.test_palais_pacte_dor -v`` depuis
"Jeux Strat".
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import ia
from moteur import regles

RACINE = Path(__file__).resolve().parents[1]
SAVES_DIR = RACINE / "parties_en_cours"


def etat_avec_grande_cite_commercante():
    """Un etat contenant une CC d'au moins 10 territoires, avec un hote
    valide pour le Palais (IA classique), ou None si aucune sauvegarde ne
    convient."""
    for chemin in sorted(SAVES_DIR.glob("*.json")):
        try:
            payload = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict) or payload.get("kind") != "game":
            continue
        state = GameState.from_payload(payload)
        regles.sanitize_after_load(state)
        if "golden_pact_palace" in state.wonder_territories:
            continue
        for cc in sorted(state.commercial_city_players):
            if regles.count_player_territories(state, cc) < ia.COMMERCIAL_CITY_TERRITORY_LIMIT:
                continue
            hote = next(
                (
                    t for t in state.territories
                    if t.owner >= 0
                    and t.owner != cc
                    and regles.is_ai_player(state, t.owner)
                    and t.owner not in state.commercial_city_players
                    and not regles.is_onu_player(state, t.owner)
                    and regles.get_wonder_type_at_territory(state, t.id) is None
                    and not regles.is_sanctuary_territory(state, t.id)
                ),
                None,
            )
            if hote is not None:
                return state, cc, hote
    return None, None, None


class TestPalaisPacteDor(unittest.TestCase):
    def setUp(self):
        self.state, self.cc, self.hote = etat_avec_grande_cite_commercante()
        if self.state is None:
            self.skipTest("Aucune sauvegarde avec une grande CC et un hote valide.")
        self.state.current_player = self.cc

    def test_controleur_valide_est_le_seul_allie(self):
        state, cc, hote = self.state, self.cc, self.hote
        state.wonder_territories["golden_pact_palace"] = hote.id
        regles.enforce_commercial_city_wonder_exclusivity(state)
        self.assertEqual(regles.get_commercial_city_wonder_ally(state), hote.owner)
        # L'allie est protege, tous les autres sont attaquables.
        self.assertTrue(regles.is_attack_blocked_by_alliance(state, cc, hote.owner))
        autre_ia = next(
            j for j in regles.get_active_players(state)
            if j not in (cc, hote.owner)
            and regles.is_ai_player(state, j)
            and not regles.is_onu_player(state, j)
            and j not in state.commercial_city_players
        )
        self.assertFalse(regles.is_attack_blocked_by_alliance(state, cc, autre_ia))
        self.assertIsNotNone(ia.find_ai_attack(state))

    def test_palais_sans_controleur_la_cc_reste_offensive(self):
        state, cc, hote = self.state, self.cc, self.hote
        state.wonder_territories["golden_pact_palace"] = hote.id
        # Le territoire du Palais passe a l'ONU (soumission, figement...).
        hote.owner = state.onu_player_id
        self.assertIsNone(regles.get_commercial_city_wonder_ally(state))
        # Plus d'allie protege : la CC peut attaquer n'importe qui, et la
        # limite des 10 territoires ne la paralyse plus.
        autre_ia = next(
            j for j in regles.get_active_players(state)
            if j != cc
            and regles.is_ai_player(state, j)
            and not regles.is_onu_player(state, j)
            and j not in state.commercial_city_players
        )
        self.assertFalse(regles.is_attack_blocked_by_alliance(state, cc, autre_ia))
        self.assertGreaterEqual(
            regles.count_player_territories(state, cc),
            ia.COMMERCIAL_CITY_TERRITORY_LIMIT,
        )
        self.assertIsNotNone(ia.find_ai_attack(state))

    def test_palais_possede_par_la_cc_meme_effet(self):
        state, cc, hote = self.state, self.cc, self.hote
        state.wonder_territories["golden_pact_palace"] = hote.id
        hote.owner = cc
        self.assertIsNone(regles.get_commercial_city_wonder_ally(state))
        self.assertIsNotNone(ia.find_ai_attack(state))

    def test_sans_palais_la_limite_reste(self):
        state, cc = self.state, self.cc
        self.assertNotIn("golden_pact_palace", state.wonder_territories)
        self.assertGreaterEqual(
            regles.count_player_territories(state, cc),
            ia.COMMERCIAL_CITY_TERRITORY_LIMIT,
        )
        # Sans Palais, une grande CC reste une puissance paisible.
        self.assertIsNone(ia.find_ai_attack(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
