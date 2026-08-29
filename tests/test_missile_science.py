"""Regles d'aout 2026 sur la science : le missile et la victoire scientifique.

Le missile coute 200 ecus et se debloque a 50 points de science. Sa portee
et sa puissance montent avec elle :

- 50 points  : un territoire adverse voisin d'un des siens, la moitie des
               regiments (arrondie au superieur) est aneantie ;
- 100 points : jusqu'a MISSILE_RANGE_PX de ses propres terres ;
- 200 points : n'importe ou sur la carte, et le territoire est rase — il ne
               reste qu'un regiment et plus aucun amenagement.

Dans tous les cas il reste au moins un regiment : un missile ne conquiert
jamais. La victoire scientifique suit exactement la regle de la victoire
culturelle : 20 fois la science du meilleur rival (10 fois pour une IA), et
au moins 100 points.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_missile_science -v
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


def conditions_remplies(state):
    """Les conditions de victoire remplies a cet instant : (condition, joueur).

    Depuis les paliers de victoire, remplir une condition ne met plus fin a
    la partie : elle ferme un palier et rapporte un point a son auteur.
    """
    return {
        (condition, joueur)
        for condition, joueur, _raison in regles.find_satisfied_victory_conditions(state)
    }


class BaseMissile(unittest.TestCase):
    def setUp(self):
        self.state = partie_neuve()
        self.joueur = 0
        self.state.current_player = self.joueur
        regles.ensure_player_economy(self.state, self.joueur)
        self.state.player_money[self.joueur] = 10_000
        self.largeur = LARGEUR_LOGIQUE / self.state.cols
        self.hauteur = HAUTEUR_LOGIQUE / self.state.rows

    def science(self, points):
        self.state.player_science[self.joueur] = points

    def tirer(self, terr):
        return achats.tirer_missile(self.state, terr, self.largeur, self.hauteur)

    def voisin_adverse(self):
        for terr in self.state.territories:
            if terr.owner in (self.joueur, -1):
                continue
            if regles.is_territory_adjacent_to_player(self.state, terr.id, self.joueur):
                return terr
        self.skipTest("Aucun territoire adverse voisin.")

    def reduire_a_un_seul_territoire(self):
        """Acule le joueur sur un seul territoire.

        A la mise en place, chacun possede des territoires disperses sur toute
        la carte : plus rien n'est alors a plus de 190 pixels de chez soi. La
        portee intermediaire ne se mesure vraiment qu'une fois un empire
        resserre, ce que ce raccourci reproduit.
        """
        garde = next(t.id for t in self.state.territories if t.owner == self.joueur)
        repreneur = next(
            t.owner for t in self.state.territories
            if t.owner not in (self.joueur, -1)
        )
        for terr in self.state.territories:
            if terr.owner == self.joueur and terr.id != garde:
                terr.owner = repreneur
        return garde

    def lointain_adverse(self, distance_min):
        """Un territoire adverse a plus de ``distance_min`` pixels de chez soi."""
        for terr in self.state.territories:
            if terr.owner in (self.joueur, -1):
                continue
            distance = regles.get_distance_to_nearest_owned_territory(
                self.state, terr.id, self.joueur, self.largeur, self.hauteur,
            )
            if distance is not None and distance > distance_min:
                return terr
        return None


class TestPortee(BaseMissile):
    """La science commande la portee."""

    def test_verrouille_sous_cinquante_points(self):
        self.science(achats.SCIENCE_MISSILE_THRESHOLD - 1)
        terr = self.voisin_adverse()
        resultat = self.tirer(terr)
        self.assertFalse(resultat.ok)
        self.assertIn("science", resultat.message)
        self.assertEqual(self.state.player_money[self.joueur], 10_000)

    def test_paliers(self):
        for points, palier in (
            (0, 0),
            (achats.SCIENCE_MISSILE_THRESHOLD, 1),
            (achats.SCIENCE_MISSILE_RANGE_THRESHOLD, 2),
            (achats.SCIENCE_MISSILE_TOTAL_THRESHOLD, 3),
            (500, 3),
        ):
            self.science(points)
            self.assertEqual(
                achats.get_missile_tier(self.state, self.joueur), palier,
                f"{points} points de science",
            )

    def test_a_cinquante_points_seul_le_voisin_est_atteignable(self):
        self.science(achats.SCIENCE_MISSILE_THRESHOLD)
        self.reduire_a_un_seul_territoire()
        loin = self.lointain_adverse(achats.MISSILE_RANGE_PX)
        if loin is None:
            self.skipTest("Carte trop petite pour un territoire vraiment lointain.")
        resultat = self.tirer(loin)
        self.assertFalse(resultat.ok)
        self.assertIn("hors de portee", resultat.message)
        self.assertEqual(self.state.player_money[self.joueur], 10_000)

    def test_a_cent_points_la_portee_s_etend_mais_reste_bornee(self):
        self.science(achats.SCIENCE_MISSILE_RANGE_THRESHOLD)
        self.reduire_a_un_seul_territoire()
        # Ce qui est en deca de la portee passe...
        proche = self.lointain_adverse(0.0)
        if proche is not None and regles.get_distance_to_nearest_owned_territory(
            self.state, proche.id, self.joueur, self.largeur, self.hauteur,
        ) <= achats.MISSILE_RANGE_PX:
            proche.regiments = 10
            self.assertTrue(self.tirer(proche).ok)
        # ... mais pas au-dela.
        loin = self.lointain_adverse(achats.MISSILE_RANGE_PX)
        if loin is None:
            self.skipTest("Carte trop petite pour un territoire vraiment lointain.")
        resultat = self.tirer(loin)
        self.assertFalse(resultat.ok)
        self.assertIn("hors de portee", resultat.message)

    def test_a_deux_cents_points_toute_la_carte_est_a_portee(self):
        self.science(achats.SCIENCE_MISSILE_TOTAL_THRESHOLD)
        self.reduire_a_un_seul_territoire()
        loin = self.lointain_adverse(achats.MISSILE_RANGE_PX)
        if loin is None:
            self.skipTest("Carte trop petite pour un territoire vraiment lointain.")
        loin.regiments = 8
        resultat = self.tirer(loin)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(loin.regiments, 1)

    def test_on_ne_se_bombarde_pas_soi_meme(self):
        self.science(achats.SCIENCE_MISSILE_TOTAL_THRESHOLD)
        mien = next(t for t in self.state.territories if t.owner == self.joueur)
        resultat = self.tirer(mien)
        self.assertFalse(resultat.ok)
        self.assertEqual(self.state.player_money[self.joueur], 10_000)

    def test_refuse_faute_d_ecus(self):
        self.science(achats.SCIENCE_MISSILE_THRESHOLD)
        self.state.player_money[self.joueur] = achats.MISSILE_COST - 1
        terr = self.voisin_adverse()
        avant = terr.regiments
        resultat = self.tirer(terr)
        self.assertFalse(resultat.ok)
        self.assertEqual(terr.regiments, avant)


class TestDegats(BaseMissile):
    """La moitie des troupes, puis la table rase."""

    def test_moitie_arrondie_au_superieur(self):
        self.assertEqual(achats.calculate_missile_regiment_losses(10, 1), 5)
        self.assertEqual(achats.calculate_missile_regiment_losses(5, 1), 3)
        self.assertEqual(achats.calculate_missile_regiment_losses(2, 1), 1)

    def test_il_reste_toujours_un_regiment(self):
        for regiments in range(0, 12):
            for palier in (1, 2, 3):
                pertes = achats.calculate_missile_regiment_losses(regiments, palier)
                self.assertGreaterEqual(regiments - pertes, min(1, regiments))

    def test_un_regiment_seul_survit_au_missile(self):
        self.science(achats.SCIENCE_MISSILE_THRESHOLD)
        terr = self.voisin_adverse()
        terr.regiments = 1
        proprietaire = terr.owner
        resultat = self.tirer(terr)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(terr.regiments, 1)
        self.assertEqual(terr.owner, proprietaire)

    def test_le_missile_ne_conquiert_pas(self):
        self.science(achats.SCIENCE_MISSILE_TOTAL_THRESHOLD)
        terr = self.voisin_adverse()
        terr.regiments = 20
        proprietaire = terr.owner
        self.tirer(terr)
        self.assertEqual(terr.owner, proprietaire)
        self.assertEqual(terr.regiments, 1)

    def test_cout_preleve_une_fois(self):
        self.science(achats.SCIENCE_MISSILE_THRESHOLD)
        terr = self.voisin_adverse()
        terr.regiments = 10
        self.tirer(terr)
        self.assertEqual(self.state.player_money[self.joueur], 10_000 - achats.MISSILE_COST)

    def test_a_deux_cents_points_tous_les_amenagements_tombent(self):
        self.science(achats.SCIENCE_MISSILE_TOTAL_THRESHOLD)
        terr = self.voisin_adverse()
        terr.regiments = 12
        tid = terr.id
        self.state.fortress_territory_ids.add(tid)
        regles.add_industrial_structure(self.state, tid, "factory")
        self.state.temple_territory_ids.add(tid)
        self.state.cultural_center_ages.pop(tid, None)
        self.state.ruin_territory_ids.discard(tid)
        regles.add_cultural_center(self.state, tid)
        regles.add_university(self.state, tid)

        resultat = self.tirer(terr)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertNotIn(tid, self.state.fortress_territory_ids)
        self.assertEqual(regles.get_industrial_structure_count(self.state, tid), 0)
        self.assertNotIn(tid, self.state.temple_territory_ids)
        self.assertEqual(regles.get_cultural_center_count(self.state, tid), 0)
        self.assertNotIn(tid, self.state.university_territory_ids)
        # Le centre culturel rase laisse une ruine, comme toute destruction.
        self.assertTrue(regles.has_ruin(self.state, tid))

    def test_la_merveille_resiste_au_missile(self):
        self.science(achats.SCIENCE_MISSILE_TOTAL_THRESHOLD)
        terr = self.voisin_adverse()
        terr.regiments = 6
        self.state.wonder_territories["ivory_rampart"] = terr.id
        self.tirer(terr)
        self.assertEqual(self.state.wonder_territories.get("ivory_rampart"), terr.id)

    def test_sous_deux_cents_points_les_amenagements_tiennent(self):
        self.science(achats.SCIENCE_MISSILE_THRESHOLD)
        terr = self.voisin_adverse()
        terr.regiments = 10
        self.state.fortress_territory_ids.add(terr.id)
        self.tirer(terr)
        self.assertIn(terr.id, self.state.fortress_territory_ids)
        self.assertEqual(terr.regiments, 5)


class TestDistance(BaseMissile):
    """La mesure de distance qui borne la portee intermediaire."""

    def test_un_voisin_est_a_distance_nulle(self):
        terr = self.voisin_adverse()
        self.assertEqual(
            regles.get_distance_to_nearest_owned_territory(
                self.state, terr.id, self.joueur, self.largeur, self.hauteur,
            ),
            0.0,
        )

    def test_distance_symetrique_et_positive(self):
        a = next(t for t in self.state.territories if t.owner == self.joueur)
        b = next(
            t for t in self.state.territories
            if t.owner != self.joueur and t.id not in a.neighbors and t.id != a.id
        )
        aller = regles.get_territory_pixel_distance(
            self.state, a.id, b.id, self.largeur, self.hauteur,
        )
        retour = regles.get_territory_pixel_distance(
            self.state, b.id, a.id, self.largeur, self.hauteur,
        )
        self.assertIsNotNone(aller)
        self.assertAlmostEqual(aller, retour)
        self.assertGreater(aller, 0.0)


class TestVictoireScientifique(unittest.TestCase):
    """Vingt fois la science du meilleur rival, dix fois pour une IA."""

    def setUp(self):
        self.state = partie_neuve()
        self.joueurs = [
            joueur for joueur in regles.get_active_players(self.state)
            if not regles.is_onu_player(self.state, joueur)
        ]
        if len(self.joueurs) < 2:
            self.skipTest("Il faut au moins deux joueurs actifs.")
        for joueur in self.joueurs:
            self.state.player_science[joueur] = 0

    def test_le_plancher_est_necessaire(self):
        meneur = self.joueurs[0]
        self.state.player_science[meneur] = regles.SCIENCE_VICTORY_MIN_POINTS - 1
        self.assertNotIn(("science", meneur), conditions_remplies(self.state))

    def test_le_plancher_suffit_face_a_des_rivaux_a_zero(self):
        meneur = self.joueurs[0]
        self.state.player_science[meneur] = regles.SCIENCE_VICTORY_MIN_POINTS
        self.assertIn(("science", meneur), conditions_remplies(self.state))

    def test_vingt_fois_le_meilleur_rival_pour_un_humain(self):
        meneur, rival = self.joueurs[0], self.joueurs[1]
        self.state.player_science[rival] = 30
        self.state.player_science[meneur] = 599
        self.assertNotIn(("science", meneur), conditions_remplies(self.state))
        self.state.player_science[meneur] = 600
        self.assertIn(("science", meneur), conditions_remplies(self.state))

    def test_dix_fois_suffisent_a_une_ia(self):
        meneur, rival = self.joueurs[0], self.joueurs[1]
        self.state.base_ai_players.add(meneur)
        self.state.human_controlled_players.discard(meneur)
        self.state.player_science[rival] = 30
        self.state.player_science[meneur] = 300
        self.assertIn(("science", meneur), conditions_remplies(self.state))
        raison = next(
            r for condition, _j, r in regles.find_satisfied_victory_conditions(self.state)
            if condition == "science"
        )
        self.assertIn("10 fois", raison)


class TestMissileParLActionEnLigne(unittest.TestCase):
    """La version en ligne passe par ``moteur.actions``."""

    def test_achat_missile_declare_et_aiguille(self):
        from moteur import actions

        self.assertIn("missile", actions.ACHATS)
        state = partie_neuve()
        state.phase = "shopping"
        state.current_player = 0
        regles.ensure_player_economy(state, 0)
        state.player_money[0] = 10_000
        state.player_science[0] = achats.SCIENCE_MISSILE_THRESHOLD
        cible = next(
            terr for terr in state.territories
            if terr.owner not in (0, -1)
            and regles.is_territory_adjacent_to_player(state, terr.id, 0)
        )
        cible.regiments = 9
        outcome = actions.apply_action(
            state,
            {"type": "acheter", "achat": "missile", "territoire": cible.id},
            LARGEUR_LOGIQUE / state.cols, HAUTEUR_LOGIQUE / state.rows,
            random.Random(2),
        )
        self.assertTrue(outcome.ok, outcome.message)
        self.assertEqual(cible.regiments, 4)


if __name__ == "__main__":
    unittest.main()
