"""Regles d'aout 2026 : franchir un palier coupe les empires en deux.

Le premier palier franchi lancait son auteur vers tous les suivants :
l'avance qui l'avait porte la ne faisait que grandir, et la partie se jouait
d'un seul elan. Desormais chaque palier se paie, et il se paie sur toute la
carte : chaque empire laisse partir sa moitie la plus eloignee de sa
capitale vers un nouveau joueur IA, qui emporte la moitie du tresor et le
meme niveau de science. Autant de nouveaux joueurs que d'empires coupes. Le
point de victoire, lui, reste acquis. Seul le palier qui acheve la partie ne
scinde rien : il n'y aurait plus personne pour en profiter.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_scission_palier -v
"""

import json
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import mise_en_place
from moteur import regles

RACINE = Path(__file__).resolve().parents[1]
CARTES_DIR = RACINE / "cartes_sauvegardees"


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


class BaseScission(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.total = len(self.state.territories)
        self.seuil = math.ceil(self.total * 0.75)
        for joueur in regles.get_active_players(self.state):
            self.state.player_science[joueur] = 0

    def franchir_le_palier_territorial(self, joueur=0, rival=1):
        """Donne les 3/4 de la carte au joueur, puis enregistre les paliers."""
        for index, terr in enumerate(self.state.territories):
            terr.owner = joueur if index < self.seuil else rival
        return regles.register_victory_milestones(self.state, random.Random(7))

    def territoires_de(self, joueur):
        return [terr for terr in self.state.territories if terr.owner == joueur]

    def fermer(self, condition, joueur, tour=1):
        self.state.victory_milestones.append({
            "condition": condition, "joueur": joueur, "tour": tour, "raison": "pour le test",
        })


class TestScissionApresPalier(BaseScission):
    """Un palier franchi fait naitre un joueur sur la moitie de l'empire."""

    def test_le_palier_fait_naitre_un_nouveau_joueur(self):
        joueurs_avant = self.state.num_players
        nouveaux = self.franchir_le_palier_territorial()
        self.assertTrue(nouveaux)
        self.assertGreater(self.state.num_players, joueurs_avant)
        self.assertTrue(self.territoires_de(joueurs_avant))

    def test_la_scission_partage_l_empire_en_deux(self):
        avant = self.seuil
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        restants = len(self.territoires_de(0))
        partis = len(self.territoires_de(secessionniste))
        self.assertEqual(restants + partis, avant)
        self.assertEqual(partis, avant // 2)
        # Sur un nombre impair, l'ecu et le territoire de trop restent au
        # joueur d'origine.
        self.assertGreaterEqual(restants, partis)

    def test_le_nouveau_joueur_est_une_ia(self):
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        self.assertTrue(regles.is_ai_player(self.state, secessionniste))
        self.assertNotIn(secessionniste, self.state.human_controlled_players)
        self.assertIn(secessionniste, self.state.ai_personalities)

    def test_le_point_de_victoire_reste_a_son_auteur(self):
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        self.assertGreaterEqual(regles.get_victory_points(self.state, 0), 1)
        self.assertEqual(regles.get_victory_points(self.state, secessionniste), 0)

    def test_la_scission_est_annoncee_dans_les_evenements_majeurs(self):
        self.franchir_le_palier_territorial()
        self.assertTrue(
            any("SCISSION DE L'EMPIRE" in evenement
                for evenement in self.state.recent_major_events)
        )

    def test_le_detail_de_la_scission_est_attache_au_palier(self):
        secessionniste = self.state.num_players
        nouveaux = self.franchir_le_palier_territorial()
        palier = next(p for p in nouveaux if p["condition"] == "territoires")
        scission = palier["scission"]
        self.assertEqual(scission["joueur"], 0)
        self.assertEqual(scission["nouveau_joueur"], secessionniste)
        self.assertEqual(scission["territoires"], len(self.territoires_de(secessionniste)))

    def test_la_scission_survit_a_la_sauvegarde(self):
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        attendu = len(self.territoires_de(secessionniste))
        recharge = GameState.from_payload(json.loads(json.dumps(self.state.to_payload())))
        self.assertEqual(recharge.num_players, self.state.num_players)
        self.assertEqual(
            sum(1 for terr in recharge.territories if terr.owner == secessionniste),
            attendu,
        )


class TestScissionGenerale(BaseScission):
    """Un palier coupe en deux tous les empires, pas seulement son auteur."""

    def repartir(self, parts):
        """Distribue la carte : ``parts`` associe un joueur a son nombre de terres."""
        index = 0
        for joueur, combien in parts:
            for _ in range(combien):
                self.state.territories[index].owner = joueur
                index += 1
        for terr in self.state.territories[index:]:
            terr.owner = parts[0][0]

    def test_le_rival_se_coupe_aussi_en_deux(self):
        premier_ne = self.state.num_players
        avant_rival = self.total - self.seuil
        self.franchir_le_palier_territorial(joueur=0, rival=1)
        self.assertEqual(len(self.territoires_de(1)), avant_rival - avant_rival // 2)
        # Deux empires coupes, donc deux nouveaux joueurs.
        self.assertEqual(self.state.num_players, premier_ne + 2)
        self.assertTrue(self.territoires_de(premier_ne + 1))

    def test_chaque_empire_donne_naissance_a_un_joueur(self):
        self.repartir([(0, self.seuil), (1, 8), (2, 6), (3, 5)])
        premier_ne = self.state.num_players
        nouveaux = regles.register_victory_milestones(self.state, random.Random(7))
        self.assertTrue(nouveaux)
        self.assertEqual(self.state.num_players, premier_ne + 4)
        for rang, ancien in enumerate((0, 1, 2, 3)):
            with self.subTest(joueur=ancien):
                self.assertTrue(self.territoires_de(premier_ne + rang))

    def test_l_auteur_du_palier_est_coupe_le_premier(self):
        self.repartir([(0, self.seuil), (1, 10), (2, 9)])
        premier_ne = self.state.num_players
        nouveaux = regles.register_victory_milestones(self.state, random.Random(7))
        palier = next(p for p in nouveaux if p["condition"] == "territoires")
        self.assertEqual(palier["scission"]["joueur"], 0)
        self.assertEqual(palier["scission"]["nouveau_joueur"], premier_ne)
        self.assertEqual(
            [detail["joueur"] for detail in palier["scissions"]], [0, 1, 2],
        )

    def test_un_empire_d_un_seul_territoire_est_epargne(self):
        self.repartir([(0, self.seuil), (1, self.total - self.seuil - 1), (2, 1)])
        nouveaux = regles.register_victory_milestones(self.state, random.Random(7))
        palier = next(p for p in nouveaux if p["condition"] == "territoires")
        self.assertNotIn(2, [detail["joueur"] for detail in palier["scissions"]])
        self.assertEqual(len(self.territoires_de(2)), 1)

    def test_un_empire_de_deux_territoires_est_epargne(self):
        self.repartir([(0, self.seuil), (1, self.total - self.seuil - 2), (2, 2)])
        nouveaux = regles.register_victory_milestones(self.state, random.Random(7))
        palier = next(p for p in nouveaux if p["condition"] == "territoires")
        self.assertNotIn(2, [detail["joueur"] for detail in palier["scissions"]])
        self.assertEqual(len(self.territoires_de(2)), 2)

    def test_une_ia_de_deux_territoires_est_epargnee_aussi(self):
        self.state.human_controlled_players.discard(2)
        self.state.base_ai_players.add(2)
        self.repartir([(0, self.seuil), (1, self.total - self.seuil - 2), (2, 2)])
        regles.register_victory_milestones(self.state, random.Random(7))
        self.assertEqual(len(self.territoires_de(2)), 2)

    def test_un_empire_de_trois_territoires_se_coupe(self):
        self.repartir([(0, self.seuil), (1, self.total - self.seuil - 3), (2, 3)])
        nouveaux = regles.register_victory_milestones(self.state, random.Random(7))
        palier = next(p for p in nouveaux if p["condition"] == "territoires")
        self.assertIn(2, [detail["joueur"] for detail in palier["scissions"]])
        self.assertEqual(len(self.territoires_de(2)), 2)

    def test_les_nouveaux_joueurs_ne_se_scindent_pas_a_leur_tour(self):
        self.repartir([(0, self.seuil), (1, 10), (2, 9)])
        premier_ne = self.state.num_players
        regles.register_victory_milestones(self.state, random.Random(7))
        # Trois empires coupes, trois joueurs nes : pas un de plus.
        self.assertEqual(self.state.num_players, premier_ne + 3)

    def test_la_scission_generale_est_annoncee(self):
        self.franchir_le_palier_territorial()
        self.assertTrue(
            any("SCISSION GENERALE" in evenement
                for evenement in self.state.recent_major_events)
        )

    def test_la_cite_commercante_se_coupe_comme_les_autres(self):
        cites = sorted(self.state.commercial_city_players)
        if not cites:
            self.skipTest("Aucune Cite commercante sur cette partie.")
        cite = cites[0]
        self.repartir([(0, self.seuil), (1, 10), (cite, 9)])
        nouveaux = regles.register_victory_milestones(self.state, random.Random(7))
        palier = next(p for p in nouveaux if p["condition"] == "territoires")
        self.assertIn(cite, [detail["joueur"] for detail in palier["scissions"]])

    def test_le_dernier_palier_ne_coupe_toujours_rien(self):
        for condition in regles.REQUIRED_VICTORY_CONDITIONS:
            if condition != "territoires":
                self.fermer(condition, 1)
        self.repartir([(0, self.seuil), (1, 10), (2, 9)])
        joueurs_avant = self.state.num_players
        regles.register_victory_milestones(self.state, random.Random(7))
        self.assertEqual(self.state.num_players, joueurs_avant)
        self.assertEqual(len(self.territoires_de(1)), 10)


class TestDecoupeDepuisLaCapitale(BaseScission):
    """Ce sont les provinces les plus lointaines qui font secession."""

    def test_le_joueur_garde_sa_capitale(self):
        capitale = regles.get_active_regular_capital_id_for_player(self.state, 0)
        if capitale is None:
            self.skipTest("Le joueur 0 n'a pas de capitale active sur cette carte.")
        for index, terr in enumerate(self.state.territories):
            terr.owner = 0 if index < self.seuil else 1
        self.state.territories[capitale].owner = 0
        regles.register_victory_milestones(self.state, random.Random(7))
        self.assertEqual(self.state.territories[capitale].owner, 0)

    def test_les_partants_sont_plus_loin_que_les_restants(self):
        for index, terr in enumerate(self.state.territories):
            terr.owner = 0 if index < self.seuil else 1
        origine = regles.get_split_origin_territory_id(self.state, 0)
        self.assertIsNotNone(origine)
        possedes = {terr.id for terr in self.territoires_de(0)}
        distances = self._distances(origine, possedes)
        secessionniste = self.state.num_players
        regles.register_victory_milestones(self.state, random.Random(7))

        # La coupe se fait a une distance donnee : le plus proche des
        # partants n'est jamais plus pres du siege que le plus lointain des
        # restants. Seuls les ex aequo se retrouvent des deux cotes.
        partis = [distances[terr.id] for terr in self.territoires_de(secessionniste)]
        gardes = [distances[terr.id] for terr in self.territoires_de(0)]
        self.assertGreaterEqual(min(partis), max(gardes))

    def test_une_province_coupee_du_coeur_part_la_premiere(self):
        capitale = regles.get_active_regular_capital_id_for_player(self.state, 0)
        if capitale is None:
            self.skipTest("Le joueur 0 n'a pas de capitale active sur cette carte.")
        # Un empire compact autour de la capitale, plus des enclaves isolees
        # — assez pour atteindre le minimum de trois territoires scindables.
        compact = self._bloc_autour(capitale, 6)
        nb_enclaves = max(1, regles.MILESTONE_SPLIT_MIN_TERRITORIES - len(compact))
        enclaves = [
            terr.id for terr in self.state.territories
            if terr.id not in compact
            and not (set(terr.neighbors) & compact)
        ][:nb_enclaves]
        if len(enclaves) < nb_enclaves:
            self.skipTest("Cette carte n'offre pas assez d'enclaves isolees.")
        for terr in self.state.territories:
            terr.owner = 1
        for tid in compact:
            self.state.territories[tid].owner = 0
        for tid in enclaves:
            self.state.territories[tid].owner = 0

        secessionniste = self.state.num_players
        regles.split_empire_after_milestone(self.state, 0, random.Random(7))
        self.assertEqual(self.state.territories[enclaves[0]].owner, secessionniste)
        self.assertEqual(self.state.territories[capitale].owner, 0)

    def _distances(self, origine, possedes):
        distances = {origine: 0}
        frontier = [origine]
        while frontier:
            suivants = []
            for tid in frontier:
                for voisin in self.state.territories[tid].neighbors:
                    if voisin in possedes and voisin not in distances:
                        distances[voisin] = distances[tid] + 1
                        suivants.append(voisin)
            frontier = suivants
        injoignable = len(possedes) + 1
        return {tid: distances.get(tid, injoignable) for tid in possedes}

    def _bloc_autour(self, depart, taille):
        bloc = {depart}
        frontier = [depart]
        while frontier and len(bloc) < taille:
            tid = frontier.pop(0)
            for voisin in self.state.territories[tid].neighbors:
                if voisin not in bloc and len(bloc) < taille:
                    bloc.add(voisin)
                    frontier.append(voisin)
        return bloc


class TestPartageDuTresorEtDeLaScience(BaseScission):
    """L'argent se coupe en deux, la science se recopie, la culture suit les terres."""

    def test_l_argent_est_partage_en_deux(self):
        self.state.player_money[0] = 250
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        self.assertEqual(self.state.player_money[secessionniste], 125)
        self.assertEqual(self.state.player_money[0], 125)

    def test_l_ecu_impair_reste_au_joueur_d_origine(self):
        self.state.player_money[0] = 101
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        self.assertEqual(self.state.player_money[secessionniste], 50)
        self.assertEqual(self.state.player_money[0], 51)

    def test_la_science_se_recopie_sans_se_diviser(self):
        self.state.player_science[0] = 42
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        self.assertEqual(self.state.player_science[0], 42)
        self.assertEqual(self.state.player_science[secessionniste], 42)

    def test_la_culture_se_recompte_depuis_les_amenagements(self):
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        for joueur in (0, secessionniste):
            attendu = sum(
                regles.calculate_territory_culture(self.state, terr)
                for terr in self.territoires_de(joueur)
            )
            self.assertEqual(
                regles.calculate_player_culture(self.state, joueur), attendu,
            )


class TestQuandLaScissionNAPasLieu(BaseScission):
    """Le dernier palier, la carte entiere et les empires minuscules."""

    def test_le_dernier_palier_necessaire_ne_scinde_rien(self):
        for condition in regles.REQUIRED_VICTORY_CONDITIONS:
            if condition != "territoires":
                self.fermer(condition, 1)
        joueurs_avant = self.state.num_players
        nouveaux = self.franchir_le_palier_territorial()
        self.assertTrue(any(p["condition"] == "territoires" for p in nouveaux))
        self.assertEqual(self.state.num_players, joueurs_avant)
        self.assertEqual(len(self.territoires_de(0)), self.seuil)

    def test_tenir_toute_la_carte_ne_scinde_rien(self):
        for terr in self.state.territories:
            terr.owner = 0
        joueurs_avant = self.state.num_players
        regles.register_victory_milestones(self.state, random.Random(7))
        self.assertEqual(self.state.num_players, joueurs_avant)
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertEqual(gagnant, 0)

    def test_un_empire_d_un_seul_territoire_ne_se_coupe_pas(self):
        for index, terr in enumerate(self.state.territories):
            terr.owner = 1 if index else 0
        joueurs_avant = self.state.num_players
        self.assertIsNone(
            regles.split_empire_after_milestone(self.state, 0, random.Random(7))
        )
        self.assertEqual(self.state.num_players, joueurs_avant)
        self.assertEqual(len(self.territoires_de(0)), 1)

    def test_un_palier_deja_ferme_ne_scinde_pas_une_seconde_fois(self):
        self.franchir_le_palier_territorial()
        joueurs_avant = self.state.num_players
        self.assertEqual(
            regles.register_victory_milestones(self.state, random.Random(7)), [],
        )
        self.assertEqual(self.state.num_players, joueurs_avant)


class TestLaPartieContinueApresLaScission(BaseScission):
    """La scission rend la carte au jeu au lieu de la fermer."""

    def test_la_partie_ne_s_acheve_pas_sur_le_palier_scindeur(self):
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertIsNone(gagnant)
        for index, terr in enumerate(self.state.territories):
            terr.owner = 0 if index < self.seuil else 1
        gagnant, _raison = regles.evaluate_winner(self.state)
        self.assertIsNone(gagnant)
        self.assertGreaterEqual(regles.get_victory_points(self.state, 0), 1)

    def test_le_palier_territorial_n_est_plus_a_portee_apres_la_scission(self):
        self.franchir_le_palier_territorial()
        # Il ne tient plus les 3/4 : le palier suivant se merite a nouveau.
        self.assertLess(len(self.territoires_de(0)), self.seuil)

    def test_le_secessionniste_joue_pour_son_propre_compte(self):
        secessionniste = self.state.num_players
        self.franchir_le_palier_territorial()
        self.assertIn(secessionniste, regles.get_active_players(self.state))
        self.assertNotIn(secessionniste, regles.get_victory_bloc(self.state, 0))


if __name__ == "__main__":
    unittest.main()
