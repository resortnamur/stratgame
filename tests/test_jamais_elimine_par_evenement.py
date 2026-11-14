"""Regle dictee le 14/11/2026 : aucun evenement ne raye un joueur de la carte.

Sedition, revolte, trahison, revolution generale, chaos mondial, palier
culturel, fondation de Cite commercante, apparition d'un territoire ONU :
tous laissent au joueur son dernier territoire. Seule la guerre elimine.

Le cas qui motive la regle : un joueur reduit a trois territoires, sans
capitale active, les a tous perdus dans la meme sedition de fin de tour.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest tests.test_jamais_elimine_par_evenement -v
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


def partie_neuve(num_players=6):
    for chemin in sorted(CARTES_DIR.glob("*.json")):
        try:
            carte = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(carte, dict) and carte.get("territories"):
            return mise_en_place.nouvelle_partie(
                carte, num_players=num_players, ai_player_count=num_players - 1,
                rng=random.Random(17),
            )
    raise unittest.SkipTest("Aucune carte exploitable dans cartes_sauvegardees/.")


def reduire_a(state, player, nombre):
    """Ne laisse que `nombre` territoires au joueur, sans capitale active."""
    possedes = [terr for terr in state.territories if terr.owner == player]
    assert len(possedes) >= nombre
    repreneur = next(
        terr.owner for terr in state.territories
        if terr.owner not in (player, state.onu_player_id) and terr.owner >= 0
    )
    for terr in possedes[nombre:]:
        terr.owner = repreneur
    # Plus de capitale : c'est la situation qui a elimine le joueur.
    state.player_capital_ids.pop(player, None)
    gardes = [terr for terr in state.territories if terr.owner == player]
    for terr in gardes:
        terr.regiments = 1
    return gardes


class DeToujoursOui(random.Random):
    """Un de qui dit oui a chaque tirage de probabilite."""

    def randint(self, a, b):
        return a


class SeditionNEliminePas(unittest.TestCase):
    def test_trois_territoires_ne_tombent_pas_a_zero(self):
        state = partie_neuve()
        joueur = 0
        gardes = reduire_a(state, joueur, 3)
        self.assertEqual(len(gardes), 3)
        regles.maybe_trigger_sedition_at_end_of_turn(state, rng=DeToujoursOui(5))
        restants = [terr for terr in state.territories if terr.owner == joueur]
        self.assertGreaterEqual(
            len(restants), 1,
            "la sedition a raye le joueur de la carte",
        )

    def test_un_seul_territoire_ne_fait_jamais_sedition(self):
        """Son unique territoire reste a lui (il peut en recevoir d'autres)."""
        state = partie_neuve()
        joueur = 0
        gardes = reduire_a(state, joueur, 1)
        dernier = gardes[0].id
        regles.maybe_trigger_sedition_at_end_of_turn(state, rng=DeToujoursOui(5))
        self.assertEqual(state.territories[dernier].owner, joueur)

    def test_la_sedition_fonctionne_encore_sur_un_grand_empire(self):
        """Le garde-fou ne doit pas eteindre la mecanique."""
        state = partie_neuve()
        joueur = 0
        avant = sum(1 for terr in state.territories if terr.owner == joueur)
        if avant < 5:
            self.skipTest("Empire de depart trop petit sur cette carte.")
        state.player_capital_ids.pop(joueur, None)
        for terr in state.territories:
            if terr.owner == joueur:
                terr.regiments = 3
        regles.maybe_trigger_sedition_at_end_of_turn(state, rng=DeToujoursOui(5))
        apres = sum(1 for terr in state.territories if terr.owner == joueur)
        self.assertLess(apres, avant, "la sedition ne fait plus rien")
        self.assertGreaterEqual(apres, 1)


class EvenementsDEmpireNEliminentPas(unittest.TestCase):
    def test_le_bloc_transfere_laisse_toujours_un_territoire(self):
        state = partie_neuve()
        joueur = 0
        reduire_a(state, joueur, 3)
        bloc = regles.choose_owned_contiguous_block(
            state, joueur, 5, random.Random(2),
        )
        self.assertLessEqual(len(bloc), 2)

    def test_un_joueur_a_un_territoire_ne_perd_rien(self):
        state = partie_neuve()
        joueur = 0
        reduire_a(state, joueur, 1)
        bloc = regles.choose_owned_contiguous_block(
            state, joueur, 5, random.Random(2),
        )
        self.assertEqual(bloc, [])

    def test_chaos_mondial_n_elimine_personne(self):
        state = partie_neuve()
        joueur = 0
        reduire_a(state, joueur, 3)
        regles.build_global_chaos_event_message(state, rng=random.Random(4))
        restants = sum(1 for terr in state.territories if terr.owner == joueur)
        self.assertGreaterEqual(restants, 1)


class CultureNEliminePas(unittest.TestCase):
    def test_le_dernier_territoire_n_est_pas_une_cible_culturelle(self):
        state = partie_neuve()
        joueur = 0
        gardes = reduire_a(state, joueur, 1)
        dernier = gardes[0]
        voisin = next(
            (nid for nid in dernier.neighbors
             if 0 <= nid < len(state.territories)
             and state.territories[nid].owner not in (joueur, state.onu_player_id)
             and state.territories[nid].owner >= 0),
            None,
        )
        if voisin is None:
            self.skipTest("Pas de voisin ennemi sur cette carte.")
        annexeur = state.territories[voisin].owner
        self.assertNotIn(
            dernier.id, regles.get_culture_expansion_target_ids(state, annexeur),
        )
        self.assertIsNone(
            regles.annex_territory_by_culture(state, dernier.id, annexeur)
        )
        self.assertEqual(state.territories[dernier.id].owner, joueur)

    def test_paliers_culturels_en_rafale_laissent_un_territoire(self):
        state = partie_neuve()
        joueur = 0
        gardes = reduire_a(state, joueur, 3)
        voisins = [
            nid for terr in gardes for nid in terr.neighbors
            if 0 <= nid < len(state.territories)
            and state.territories[nid].owner not in (joueur, state.onu_player_id)
            and state.territories[nid].owner >= 0
        ]
        if not voisins:
            self.skipTest("Pas de voisin ennemi sur cette carte.")
        annexeur = state.territories[voisins[0]].owner
        for _ in range(30):
            state.culture_expansion_milestones[annexeur] = 0
            regles.trigger_culture_expansions_if_due(
                state, annexeur, rng=random.Random(5),
            )
        restants = sum(1 for terr in state.territories if terr.owner == joueur)
        self.assertGreaterEqual(
            restants, 1, "les paliers culturels ont elimine le joueur",
        )


class OnuEtCitesCommercantesNEliminentPas(unittest.TestCase):
    def test_l_onu_ne_prend_pas_le_dernier_territoire(self):
        state = partie_neuve()
        joueur = 0
        gardes = reduire_a(state, joueur, 1)
        self.assertFalse(
            regles.convert_territory_to_sanctuary(state, gardes[0].id)
        )
        self.assertEqual(state.territories[gardes[0].id].owner, joueur)

    def test_une_cite_commercante_ne_nait_pas_sur_le_dernier_territoire(self):
        state = partie_neuve()
        joueur = 0
        gardes = reduire_a(state, joueur, 1)
        dernier = gardes[0].id
        state.pending_commercial_city_spawns = 3
        regles.spawn_pending_commercial_cities(state, rng=random.Random(6))
        self.assertEqual(state.territories[dernier].owner, joueur)


if __name__ == "__main__":
    unittest.main()
