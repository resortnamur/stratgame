"""Regles d'aout 2026 : les quatre merveilles tardives.

Elles n'exigent ni science ni culture, mais ne se batissent qu'a partir du
tour 42, et coutent 500 ecus a un humain contre 300 a une IA.

- Oracle de Solmyre : fonde Solmyre, seconde religion conquerante. Elle
  recouvre toutes les religions nationales, mais jamais Elyrion — et
  Elyrion ne la recouvre pas davantage.
- Jardins de Kaleth : 50 points de culture et 50 ecus par tour.
- Dome de Selene : tous les territoires de son controleur sont a l'abri
  des missiles.
- Serment d'Orvane : le prochain joueur ne en cours de partie devient
  l'allie definitif de son controleur ; leurs reussites s'additionnent
  pour toutes les conditions de victoire, et ils ne s'attaquent plus.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_merveilles_tardives -v
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

RACINE = Path(__file__).resolve().parents[1]
CARTES_DIR = RACINE / "cartes_sauvegardees"
LARGEUR_LOGIQUE = 1200.0
HAUTEUR_LOGIQUE = 620.0


def partie_neuve():
    for chemin in sorted(CARTES_DIR.glob("*.json")):
        try:
            with open(chemin, "r", encoding="utf-8") as handle:
                carte = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(carte, dict) and carte.get("territories"):
            return mise_en_place.nouvelle_partie(
                carte, num_players=4, ai_player_count=0, rng=random.Random(11),
            )
    raise unittest.SkipTest("Aucune carte exploitable dans cartes_sauvegardees/.")


class BaseMerveille(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 0
        self.state.current_player = self.joueur
        self.state.turn = regles.LATE_WONDER_FIRST_TURN
        regles.ensure_player_economy(self.state, self.joueur)
        self.state.player_money[self.joueur] = 10_000

    def mien(self, index=0):
        possedes = [t for t in self.state.territories if t.owner == self.joueur]
        return possedes[index]

    def batir(self, wonder_type, terr=None):
        terr = terr if terr is not None else self.mien()
        self.state.wonder_construction_turns = {}
        return achats.construire_merveille(self.state, terr, wonder_type)

    def poser(self, wonder_type, terr=None):
        """Installe la merveille sans passer par la boutique."""
        terr = terr if terr is not None else self.mien()
        self.assertTrue(regles.build_wonder(self.state, terr.id, wonder_type, record_event=False))
        return terr


class TestDisponibiliteEtPrix(BaseMerveille):
    """Tour 42 au plus tot, 500 ecus pour un humain, 300 pour une IA."""

    def test_les_quatre_merveilles_sont_tardives(self):
        for wonder_type in ("solmyre_oracle", "kaleth_gardens", "selene_dome", "orvane_oath"):
            self.assertTrue(regles.is_late_wonder_type(wonder_type), wonder_type)
            self.assertFalse(regles.is_cultural_wonder_type(wonder_type), wonder_type)

    def test_rien_avant_le_tour_quarante_deux(self):
        self.state.turn = regles.LATE_WONDER_FIRST_TURN - 1
        resultat = self.batir("selene_dome")
        self.assertFalse(resultat.ok)
        self.assertIn(str(regles.LATE_WONDER_FIRST_TURN), resultat.message)
        self.assertEqual(self.state.player_money[self.joueur], 10_000)
        self.assertNotIn("selene_dome", self.state.wonder_territories)

    def test_aucun_seuil_de_science_ni_de_culture(self):
        self.state.player_science[self.joueur] = 0
        resultat = self.batir("selene_dome")
        self.assertTrue(resultat.ok, resultat.message)

    def test_cinq_cents_ecus_pour_un_humain(self):
        self.batir("selene_dome")
        self.assertEqual(
            self.state.player_money[self.joueur], 10_000 - regles.LATE_WONDER_COST,
        )

    def test_trois_cents_ecus_pour_une_ia(self):
        self.state.base_ai_players.add(self.joueur)
        self.state.human_controlled_players.discard(self.joueur)
        self.assertEqual(
            regles.get_wonder_cost(self.state, self.joueur, "selene_dome"),
            regles.AI_LATE_WONDER_COST,
        )
        self.batir("selene_dome")
        self.assertEqual(
            self.state.player_money[self.joueur], 10_000 - regles.AI_LATE_WONDER_COST,
        )

    def test_les_anciennes_merveilles_gardent_leur_prix(self):
        for wonder_type in ("elyrion_sanctuary", "ivory_rampart"):
            self.assertEqual(
                regles.get_wonder_cost(self.state, self.joueur, wonder_type),
                regles.WONDER_COST,
            )

    def test_apparaissent_dans_les_constructibles_au_bon_tour(self):
        self.state.player_science[self.joueur] = 0
        self.state.turn = regles.LATE_WONDER_FIRST_TURN - 1
        constructibles = regles.get_buildable_wonder_types(self.state, self.joueur)
        self.assertNotIn("orvane_oath", constructibles)
        self.state.turn = regles.LATE_WONDER_FIRST_TURN
        self.assertIn("orvane_oath", regles.get_buildable_wonder_types(self.state, self.joueur))


class TestOracleDeSolmyre(BaseMerveille):
    """Deux religions conquerantes, chacune rempart contre l'autre."""

    def test_la_merveille_fonde_solmyre(self):
        terr = self.poser("solmyre_oracle")
        religion = regles.SECOND_WONDER_RELIGION_ID
        self.assertEqual(self.state.religion_holy_sites.get(religion), terr.id)
        self.assertEqual(self.state.religious_influence.get(terr.id), religion)
        self.assertEqual(regles.get_religion_founder(self.state, religion), self.joueur)
        self.assertEqual(regles.get_religion_name(self.state, religion), "Solmyre")

    def test_solmyre_recouvre_une_religion_nationale(self):
        cible = self.mien(1)
        self.state.religious_influence[cible.id] = 0  # Auralis
        self.assertTrue(
            regles.can_religion_replace(self.state, regles.SECOND_WONDER_RELIGION_ID, cible.id)
        )

    def test_solmyre_ne_recouvre_pas_elyrion(self):
        cible = self.mien(1)
        self.state.religious_influence[cible.id] = regles.WONDER_RELIGION_ID
        self.assertFalse(
            regles.can_religion_replace(self.state, regles.SECOND_WONDER_RELIGION_ID, cible.id)
        )

    def test_elyrion_ne_recouvre_pas_solmyre(self):
        cible = self.mien(1)
        self.state.religious_influence[cible.id] = regles.SECOND_WONDER_RELIGION_ID
        self.assertFalse(
            regles.can_religion_replace(self.state, regles.WONDER_RELIGION_ID, cible.id)
        )

    def test_une_religion_nationale_ne_recouvre_jamais_rien(self):
        cible = self.mien(1)
        self.state.religious_influence[cible.id] = 1
        self.assertFalse(regles.can_religion_replace(self.state, 0, cible.id))

    def test_un_lieu_sacre_de_plus_a_rassembler(self):
        base = regles.get_required_holy_site_count_for_victory(self.state)
        self.assertEqual(base, 5)
        self.poser("elyrion_sanctuary")
        self.assertEqual(regles.get_required_holy_site_count_for_victory(self.state), 6)
        self.poser("solmyre_oracle", self.mien(1))
        self.assertEqual(regles.get_required_holy_site_count_for_victory(self.state), 7)

    def test_solmyre_n_est_pas_une_religion_nationale(self):
        self.poser("solmyre_oracle")
        self.assertIsNone(
            regles.get_player_national_religion_id(self.state, self.joueur)
        )
        self.assertTrue(regles.is_wonder_religion(regles.SECOND_WONDER_RELIGION_ID))

    def test_solmyre_compte_pour_les_bonus_de_son_controleur(self):
        terr = self.poser("solmyre_oracle")
        self.assertGreaterEqual(
            regles.get_national_religion_influenced_territory_count(self.state, self.joueur), 1,
        )
        self.assertEqual(
            self.state.religious_influence.get(terr.id), regles.SECOND_WONDER_RELIGION_ID,
        )

    def test_solmyre_survit_a_la_sauvegarde(self):
        terr = self.poser("solmyre_oracle")
        recharge = GameState.from_payload(json.loads(json.dumps(self.state.to_payload())))
        regles.sanitize_after_load(recharge)
        self.assertEqual(
            recharge.religious_influence.get(terr.id), regles.SECOND_WONDER_RELIGION_ID,
        )


class TestJardinsDeKaleth(BaseMerveille):
    """Cinquante points de culture et cinquante ecus, a plat."""

    def test_cinquante_ecus_de_plus_par_tour(self):
        avant = regles.calculate_player_income(self.state, self.joueur)
        self.poser("kaleth_gardens")
        apres = regles.calculate_player_income(self.state, self.joueur)
        self.assertEqual(apres - avant, regles.TOURISM_WONDER_INCOME)

    def test_cinquante_points_de_culture_de_plus(self):
        avant = regles.calculate_player_culture(self.state, self.joueur)
        self.poser("kaleth_gardens")
        apres = regles.calculate_player_culture(self.state, self.joueur)
        self.assertEqual(apres - avant, regles.TOURISM_WONDER_CULTURE)

    def test_les_doubleurs_ne_multiplient_pas_l_apport(self):
        self.poser("kaleth_gardens")
        avec_jardins = regles.calculate_player_culture(self.state, self.joueur)
        self.poser("thousand_voices_theatre", self.mien(1))
        avec_theatre = regles.calculate_player_culture(self.state, self.joueur)
        base = avec_jardins - regles.TOURISM_WONDER_CULTURE
        self.assertEqual(avec_theatre, base * 2 + regles.TOURISM_WONDER_CULTURE)

    def test_rien_pour_qui_ne_la_controle_pas(self):
        self.poser("kaleth_gardens")
        autre = next(
            joueur for joueur in regles.get_active_players(self.state)
            if joueur != self.joueur and not regles.is_onu_player(self.state, joueur)
        )
        avant = regles.calculate_player_income(self.state, autre)
        self.assertEqual(regles.calculate_player_income(self.state, autre), avant)


class TestDomeDeSelene(BaseMerveille):
    """Le bouclier antimissile couvre tout l'empire de son controleur."""

    def setUp(self):
        super().setUp()
        self.state.player_science[self.joueur] = achats.SCIENCE_MISSILE_TOTAL_THRESHOLD
        self.largeur = LARGEUR_LOGIQUE / self.state.cols
        self.hauteur = HAUTEUR_LOGIQUE / self.state.rows
        self.cible = next(
            terr for terr in self.state.territories
            if terr.owner >= 0
            and terr.owner != self.joueur
            and not regles.is_onu_player(self.state, terr.owner)
            and regles.is_territory_adjacent_to_player(self.state, terr.id, self.joueur)
        )
        self.cible.regiments = 10

    def _tirer(self):
        return achats.tirer_missile(self.state, self.cible, self.largeur, self.hauteur)

    def test_sans_dome_le_missile_passe(self):
        self.assertTrue(self._tirer().ok)

    def test_le_dome_intercepte(self):
        victime = self.cible.owner
        protege = next(t for t in self.state.territories if t.owner == victime)
        regles.build_wonder(self.state, protege.id, "selene_dome", record_event=False)
        resultat = self._tirer()
        self.assertFalse(resultat.ok)
        self.assertIn("intercepte", resultat.message)
        self.assertEqual(self.cible.regiments, 10)
        self.assertEqual(self.state.player_money[self.joueur], 10_000)

    def test_le_dome_protege_tout_l_empire_pas_seulement_son_territoire(self):
        victime = self.cible.owner
        possedes = [t for t in self.state.territories if t.owner == victime]
        if len(possedes) < 2:
            self.skipTest("Adversaire reduit a un seul territoire.")
        ailleurs = next(t for t in possedes if t.id != self.cible.id)
        regles.build_wonder(self.state, ailleurs.id, "selene_dome", record_event=False)
        self.assertFalse(self._tirer().ok)


class TestSermentDOrvane(BaseMerveille):
    """Un allie definitif, un seul a la fois, et des reussites communes."""

    def _naissance(self):
        return regles.allocate_rebel_player(self.state, random.Random(3))[0]

    def test_sans_serment_personne_ne_prete_serment(self):
        nouveau = self._naissance()
        self.assertIsNone(regles.get_eternal_ally(self.state))
        self.assertNotEqual(nouveau, regles.get_eternal_ally(self.state))

    def test_le_prochain_joueur_ne_prete_serment(self):
        self.poser("orvane_oath")
        nouveau = self._naissance()
        self.assertEqual(regles.get_eternal_ally(self.state), nouveau)
        self.assertEqual(regles.get_eternal_ally_patron(self.state), self.joueur)

    def test_un_seul_allie_a_la_fois(self):
        self.poser("orvane_oath")
        premier = self._naissance()
        # On donne un territoire au premier allie pour qu'il reste en vie.
        self.state.territories[self.mien(1).id].owner = premier
        second = self._naissance()
        self.assertEqual(regles.get_eternal_ally(self.state), premier)
        self.assertNotEqual(regles.get_eternal_ally(self.state), second)

    def test_l_allie_elimine_laisse_la_place_au_suivant(self):
        self.poser("orvane_oath")
        premier = self._naissance()
        self.state.territories[self.mien(1).id].owner = premier
        self.assertEqual(regles.get_eternal_ally(self.state), premier)
        # Le premier est elimine : il ne lui reste plus rien.
        for terr in self.state.territories:
            if terr.owner == premier:
                terr.owner = self.joueur
        second = self._naissance()
        self.state.territories[self.mien(1).id].owner = second
        self.assertEqual(regles.get_eternal_ally(self.state), second)
        self.assertNotEqual(premier, second)

    def test_le_patron_et_son_allie_ne_s_attaquent_pas(self):
        self.poser("orvane_oath")
        allie = self._naissance()
        self.state.territories[self.mien(1).id].owner = allie
        self.assertTrue(regles.is_attack_blocked_by_alliance(self.state, self.joueur, allie))
        self.assertTrue(regles.is_attack_blocked_by_alliance(self.state, allie, self.joueur))

    def test_les_territoires_s_additionnent_pour_les_trois_quarts(self):
        self.poser("orvane_oath")
        allie = self._naissance()
        total = len(self.state.territories)
        seuil = -(-total * 3 // 4)
        # Le patron prend un peu plus de la moitie, l'allie le reste jusqu'au seuil.
        moitie = total // 2
        for index, terr in enumerate(self.state.territories):
            terr.owner = self.joueur if index < moitie else (
                allie if index < seuil else (self.joueur + 1) % 4 + 1
            )
        # Sans le serment, ni l'un ni l'autre n'atteint les 3/4.
        self.assertLess(sum(1 for t in self.state.territories if t.owner == self.joueur), seuil)
        self.assertLess(sum(1 for t in self.state.territories if t.owner == allie), seuil)
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, self.joueur)
        self.assertIn("allie definitif", raison)

    def test_la_culture_de_l_allie_compte_pour_le_patron(self):
        self.poser("orvane_oath")
        allie = self._naissance()
        self.state.territories[self.mien(1).id].owner = allie
        self.state.cultural_center_ages = {}
        self.state.ruin_territory_ids = set()
        for terr in self.state.territories:
            if terr.owner in (self.joueur, allie):
                regles.add_ruin(self.state, terr.id)
        bloc = regles.get_victory_bloc(self.state, self.joueur)
        self.assertEqual(set(bloc), {self.joueur, allie})
        total = sum(regles.calculate_player_culture(self.state, membre) for membre in bloc)
        self.assertGreater(total, regles.calculate_player_culture(self.state, self.joueur))

    def test_perdre_le_serment_c_est_perdre_son_allie(self):
        serment = self.poser("orvane_oath")
        allie = self._naissance()
        self.state.territories[self.mien(1).id].owner = allie
        self.assertEqual(regles.get_eternal_ally(self.state), allie)
        # Le Serment passe a un tiers, sans combat (revolte, corruption, don).
        tiers = next(
            joueur for joueur in regles.get_active_players(self.state)
            if joueur not in (self.joueur, allie)
            and not regles.is_onu_player(self.state, joueur)
        )
        serment.owner = tiers
        self.assertIsNone(regles.get_eternal_ally(self.state))
        self.assertEqual(regles.get_victory_bloc(self.state, tiers), (tiers,))
        self.assertEqual(regles.get_victory_bloc(self.state, self.joueur), (self.joueur,))

    def test_le_nouveau_porteur_du_serment_attend_une_naissance(self):
        serment = self.poser("orvane_oath")
        premier = self._naissance()
        self.state.territories[self.mien(1).id].owner = premier
        tiers = next(
            joueur for joueur in regles.get_active_players(self.state)
            if joueur not in (self.joueur, premier)
            and not regles.is_onu_player(self.state, joueur)
        )
        serment.owner = tiers
        second = self._naissance()
        self.assertEqual(regles.get_eternal_ally(self.state), second)
        self.assertEqual(regles.get_eternal_ally_patron(self.state), tiers)

    def test_le_serment_ne_revient_pas_a_son_ancien_porteur(self):
        serment = self.poser("orvane_oath")
        allie = self._naissance()
        self.state.territories[self.mien(1).id].owner = allie
        tiers = next(
            joueur for joueur in regles.get_active_players(self.state)
            if joueur not in (self.joueur, allie)
            and not regles.is_onu_player(self.state, joueur)
        )
        serment.owner = tiers
        # Une naissance rompt formellement l'ancien serment...
        self._naissance()
        serment.owner = self.joueur
        # ... et le reprendre ne ressuscite pas l'ancienne alliance.
        self.assertNotEqual(regles.get_eternal_ally(self.state), allie)

    def test_l_allie_ne_gagne_pas_pour_son_propre_compte(self):
        serment = self.poser("orvane_oath")
        allie = self._naissance()
        for terr in self.state.territories:
            terr.owner = allie
        # Le patron garde le Serment : sans lui, l'alliance se dissout.
        serment.owner = self.joueur
        # Tout le reste est a l'allie : c'est le patron qui remporte la partie.
        gagnant, raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, self.joueur)
        self.assertIn("allie definitif", raison)

    def test_le_serment_survit_a_la_sauvegarde(self):
        self.poser("orvane_oath")
        allie = self._naissance()
        self.state.territories[self.mien(1).id].owner = allie
        recharge = GameState.from_payload(json.loads(json.dumps(self.state.to_payload())))
        regles.sanitize_after_load(recharge)
        self.assertEqual(regles.get_eternal_ally(recharge), allie)


if __name__ == "__main__":
    unittest.main()
