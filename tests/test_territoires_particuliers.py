"""Regles d'octobre 2026 : les trois territoires aux proprietes particulieres.

Tires au hasard a la mise en place, sur trois territoires distincts, jamais
sur un +3 ni sur un territoire dore (une capitale ou un sanctuaire ONU, oui) :

- Trone des Ralliements : tous les 10 tours de possession (compteur remis a
  zero a chaque changement de proprietaire), un territoire tire au hasard se
  rallie a son proprietaire avec sa garnison ; jamais une capitale, un
  territoire dore ou un territoire de l'ONU.
- Veine inepuisable : 50 ecus par tour, 100 au-dela de 10 tours de
  possession ; ni multipliee par la capitale, ni touchee par le Sceau.
- Sol inviolable : ses amenagements ne sont jamais detruits (missile,
  captures repetees, demolition, y compris par le proprietaire).

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_territoires_particuliers -v
"""

import json
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import achats
from moteur import ia
from moteur import mise_en_place
from moteur import regles

RACINE = Path(__file__).resolve().parents[1]
CARTES_DIR = RACINE / "cartes_sauvegardees"


def charger_carte():
    for chemin in sorted(CARTES_DIR.glob("*.json")):
        try:
            with open(chemin, "r", encoding="utf-8") as handle:
                carte = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(carte, dict) and carte.get("territories"):
            return carte
    raise unittest.SkipTest("Aucune carte exploitable dans cartes_sauvegardees/.")


def partie_neuve(graine=11, **options):
    return mise_en_place.nouvelle_partie(
        charger_carte(), num_players=4, ai_player_count=0,
        rng=random.Random(graine), **options,
    )


class BaseParticulier(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 0
        self.state.current_player = self.joueur

    def siege(self, sorte):
        return self.state.territories[self.state.special_territories[sorte]]

    def donner(self, sorte, joueur, depuis_tour):
        """Donne le territoire a ``joueur``, tenu depuis ``depuis_tour``."""
        terr = self.siege(sorte)
        self.state.sanctuary_territory_ids.discard(terr.id)
        terr.owner = joueur
        self.state.special_territory_holders[sorte] = [joueur, depuis_tour]
        return terr


class TestPlacement(unittest.TestCase):
    def test_trois_territoires_distincts_hors_bonus_et_dores(self):
        for graine in range(20):
            state = partie_neuve(graine)
            poses = state.special_territories
            self.assertEqual(set(poses), set(regles.SPECIAL_TERRITORY_KINDS))
            self.assertEqual(len(set(poses.values())), 3)
            for tid in poses.values():
                self.assertNotIn(tid, state.ultra_super_territory_ids)
                self.assertNotIn(tid, state.golden_territory_ids)

    def test_capitale_ou_onu_admis(self):
        vus = set()
        for graine in range(200):
            state = partie_neuve(graine)
            for tid in state.special_territories.values():
                if regles.is_any_capital_territory(state, tid):
                    vus.add("capitale")
                if regles.is_sanctuary_territory(state, tid):
                    vus.add("onu")
            if vus == {"capitale", "onu"}:
                break
        self.assertEqual(vus, {"capitale", "onu"})

    def test_compteurs_cales_au_premier_tour(self):
        state = partie_neuve()
        for sorte, tid in state.special_territories.items():
            self.assertEqual(
                state.special_territory_holders[sorte],
                [state.territories[tid].owner, 1],
            )

    def test_absents_en_version_simplifiee_et_sur_demande(self):
        self.assertEqual(partie_neuve(simple_mode=True).special_territories, {})
        self.assertEqual(partie_neuve(special_territories=False).special_territories, {})

    def test_sauvegarde_aller_retour(self):
        state = partie_neuve()
        recharge = GameState.from_payload(json.loads(json.dumps(state.to_payload())))
        self.assertEqual(recharge.special_territories, state.special_territories)
        self.assertEqual(recharge.special_territory_holders, state.special_territory_holders)


class TestVeine(BaseParticulier):
    def gain_de_la_veine(self):
        avec = regles.calculate_player_income(self.state, self.joueur)
        sorte = self.state.special_territories.pop(regles.ENDLESS_VEIN)
        sans = regles.calculate_player_income(self.state, self.joueur)
        self.state.special_territories[regles.ENDLESS_VEIN] = sorte
        return avec - sans

    def test_50_puis_100_au_dela_de_dix_tours(self):
        self.state.turn = 30
        self.donner(regles.ENDLESS_VEIN, self.joueur, 20)
        self.assertEqual(self.gain_de_la_veine(), 50)
        self.state.turn = 31
        self.assertEqual(self.gain_de_la_veine(), 100)

    def test_compteur_remis_a_zero_au_changement_de_mains(self):
        self.state.turn = 40
        terr = self.donner(regles.ENDLESS_VEIN, self.joueur, 20)
        terr.owner = 1
        regles.sync_special_territory_holders(self.state)
        terr.owner = self.joueur
        regles.sync_special_territory_holders(self.state)
        self.assertEqual(self.gain_de_la_veine(), 50)

    def test_ni_capitale_ni_sceau(self):
        self.state.turn = 40
        terr = self.donner(regles.ENDLESS_VEIN, self.joueur, 20)
        self.state.player_capital_ids[self.joueur] = terr.id
        with mock.patch.object(regles, "is_apocalypse_active", return_value=True):
            self.assertEqual(self.gain_de_la_veine(), 100)


class TestTrone(BaseParticulier):
    def test_ralliement_tous_les_dix_tours(self):
        self.state.turn = 31
        self.donner(regles.RALLY_THRONE, self.joueur, 21)
        avant = {t.id: (t.owner, t.regiments) for t in self.state.territories}
        message = regles.maybe_trigger_rally_throne(self.state, random.Random(3))
        self.assertIsNotNone(message)
        rallies = [
            t for t in self.state.territories if t.owner != avant[t.id][0]
        ]
        self.assertEqual(len(rallies), 1)
        rallie = rallies[0]
        self.assertEqual(rallie.owner, self.joueur)
        self.assertEqual(rallie.regiments, avant[rallie.id][1])

    def test_rien_hors_echeance(self):
        self.state.turn = 30
        self.donner(regles.RALLY_THRONE, self.joueur, 21)
        rng = mock.Mock(wraps=random.Random(3))
        self.assertIsNone(regles.maybe_trigger_rally_throne(self.state, rng))
        rng.choice.assert_not_called()

    def test_cibles_exclues(self):
        self.donner(regles.RALLY_THRONE, self.joueur, 1)
        cibles = regles.get_rally_throne_target_ids(self.state, self.joueur)
        self.assertTrue(cibles)
        for tid in cibles:
            terr = self.state.territories[tid]
            self.assertNotEqual(terr.owner, self.joueur)
            self.assertFalse(regles.is_any_capital_territory(self.state, tid))
            self.assertNotIn(tid, self.state.golden_territory_ids)
            self.assertNotIn(tid, self.state.sanctuary_territory_ids)
            self.assertFalse(regles.is_onu_player(self.state, terr.owner))

    def test_inactif_aux_mains_de_l_onu(self):
        self.state.turn = 31
        self.donner(regles.RALLY_THRONE, self.state.onu_player_id, 21)
        self.assertIsNone(regles.maybe_trigger_rally_throne(self.state, random.Random(3)))


class TestSolInviolable(BaseParticulier):
    def setUp(self):
        super().setUp()
        self.terr = self.donner(regles.INVIOLABLE_GROUND, self.joueur, 1)
        self.state.fortress_territory_ids.add(self.terr.id)
        regles.add_university(self.state, self.terr.id)
        regles.ensure_player_economy(self.state, self.joueur)
        self.state.player_money[self.joueur] = 10_000

    def test_missile(self):
        self.assertEqual(regles.destroy_all_amenities(self.state, self.terr.id), [])
        self.assertIn(self.terr.id, self.state.fortress_territory_ids)
        self.assertTrue(regles.has_university(self.state, self.terr.id))

    def test_captures_repetees(self):
        for _ in range(regles.SPECIAL_CAPTURE_LIMIT + 1):
            regles.register_special_capture(self.state, self.terr.id)
        self.assertIn(self.terr.id, self.state.fortress_territory_ids)
        self.assertTrue(regles.has_university(self.state, self.terr.id))

    def test_demolition_refusee_meme_au_proprietaire(self):
        self.assertFalse(achats.detruire_forteresse(self.state, self.terr).ok)
        self.assertFalse(achats.detruire_universite(self.state, self.terr).ok)
        self.assertIn(self.terr.id, self.state.fortress_territory_ids)
        self.assertEqual(self.state.player_money[self.joueur], 10_000)


class TestIa(BaseParticulier):
    def test_l_ia_prefere_un_territoire_particulier(self):
        tid = self.state.special_territories[regles.ENDLESS_VEIN]
        dst = self.state.territories[tid]
        src = self.state.territories[dst.neighbors[0]]
        src.regiments, dst.regiments = 20, 2
        avec, _ = ia.ai_attack_score(self.state, src, dst, "standard", random.Random(1))
        del self.state.special_territories[regles.ENDLESS_VEIN]
        sans, _ = ia.ai_attack_score(self.state, src, dst, "standard", random.Random(1))
        self.assertGreater(avec, sans)


if __name__ == "__main__":
    unittest.main()
