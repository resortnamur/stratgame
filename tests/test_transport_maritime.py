"""Transports maritimes : envoyer des troupes par la mer en phase de deplacement.

Procedure (identique en ligne et dans x45) : choisir le territoire de depart,
puis la destination — un territoire a soi que n'atteint aucune chaine de
territoires allies — et confirmer l'encart « Entreprendre un voyage a travers
les oceans ? », qui demande la taille du convoi (preremplie au maximum). Le convoi subit le meme
de a 64 faces qu'une expedition d'attaque ; les rescapes debarquent, les
autres disparaissent en mer.

Regles verifiees ici :
- deux territoires a soi, separes par une meme etendue d'eau continue ;
- refus si la terre les relie deja (le deplacement ordinaire suffit) ;
- plafond du convoi : la garnison moins un, et le quota de deplacements
  restant — chaque regiment embarque coute un deplacement, meme s'il coule ;
- pertes calculees comme pour une expedition (arrondi au plus proche,
  1 regiment minimum des qu'il y a sinistre) ;
- disponible en version complete comme en version simplifiee.

La carte de test est celle des expeditions : Alpha (cols 0-4) et Bravo
(cols 10-14) bordent la mer Ouest, Charlie (cols 25-29) ne borde que la mer
Est, et Bravo coupe la carte de haut en bas — les deux mers ne communiquent
donc pas.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import actions, regles

CELL_W = 10.0
CELL_H = 10.0


class DeTruque:
    """Un de a 64 faces qui tombe toujours sur la meme face."""

    def __init__(self, face: int) -> None:
        self.face = face
        self.appels = 0

    def randint(self, minimum: int, maximum: int) -> int:
        self.appels += 1
        return max(minimum, min(self.face, maximum))


def build_map_payload():
    """Trois territoires et deux mers qui ne communiquent pas."""
    rows, cols = 12, 30
    grid = [[-1] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(0, 5):
            grid[r][c] = 0        # Alpha
        for c in range(10, 15):
            grid[r][c] = 1        # Bravo (mur vertical complet)
        for c in range(25, 30):
            grid[r][c] = 2        # Charlie
    return {
        "kind": "map",
        "map_mode": "standard",
        "rows": rows,
        "cols": cols,
        "grid_territory": grid,
        "territories": [
            {"id": 0, "name": "Alpha", "reinforcement_bonus": 1},
            {"id": 1, "name": "Bravo", "reinforcement_bonus": 1},
            {"id": 2, "name": "Charlie", "reinforcement_bonus": 1},
        ],
    }


def build_state(regiments=(11, 3, 3), owners=(0, 0, 1), simple_mode=False):
    """Par defaut : Alpha et Bravo sont a moi, Charlie a l'adversaire."""
    state = GameState.from_map_payload(build_map_payload())
    state.num_players = 2
    state.initial_num_players = 2
    state.current_player = 0
    state.turn = 1
    state.phase = "playing"
    state.turn_phase = "move"
    state.turn_move_count = 0
    state.simple_mode = simple_mode
    state.player_money = {0: 0, 1: 0}
    for terr, owner, count in zip(state.territories, owners, regiments):
        terr.owner = owner
        terr.regiments = count
    return state


def territoires(state):
    return state.territories[0], state.territories[1], state.territories[2]


class TestAutorisation(unittest.TestCase):
    def test_deux_territoires_a_moi_separes_par_la_mer(self):
        state = build_state()
        alpha, bravo, _ = territoires(state)
        self.assertTrue(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))
        # Et dans les deux sens.
        self.assertTrue(regles.can_transport_by_sea(state, bravo, alpha, CELL_W, CELL_H))

    def test_refus_vers_un_territoire_ennemi(self):
        state = build_state(owners=(0, 1, 1))
        alpha, bravo, _ = territoires(state)
        self.assertFalse(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))

    def test_refus_sans_etendue_d_eau_commune(self):
        state = build_state(owners=(0, 0, 0))
        alpha, _, charlie = territoires(state)
        self.assertFalse(regles.can_transport_by_sea(state, alpha, charlie, CELL_W, CELL_H))

    def test_refus_si_la_terre_relie_deja_les_deux(self):
        """Un pont entre Alpha et Bravo : le deplacement ordinaire suffit."""
        state = build_state()
        alpha, bravo, _ = territoires(state)
        self.assertTrue(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))
        regles.add_bridge(state, (0, 1), ((0, 4), (0, 10)), fragile=False)
        self.assertTrue(regles.can_move_between(state, alpha, bravo))
        self.assertFalse(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))

    def test_refus_avec_une_garnison_d_un_seul_regiment(self):
        state = build_state(regiments=(1, 3, 3))
        alpha, bravo, _ = territoires(state)
        self.assertFalse(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))

    def test_refus_quand_le_quota_de_deplacements_est_epuise(self):
        state = build_state()
        alpha, bravo, _ = territoires(state)
        state.turn_move_count = regles.get_end_turn_move_limit(state)
        self.assertEqual(regles.get_sea_transport_max_regiments(state, alpha), 0)
        self.assertFalse(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))

    def test_refus_depuis_un_territoire_qui_n_est_pas_le_mien(self):
        state = build_state(owners=(1, 0, 1))
        alpha, bravo, _ = territoires(state)
        self.assertFalse(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))

    def test_disponible_en_version_simplifiee(self):
        state = build_state(simple_mode=True)
        alpha, bravo, _ = territoires(state)
        self.assertTrue(regles.can_transport_by_sea(state, alpha, bravo, CELL_W, CELL_H))

    def test_une_destination_existe(self):
        state = build_state()
        alpha, _, _ = territoires(state)
        self.assertTrue(
            regles.has_any_sea_transport_target(state, alpha, CELL_W, CELL_H),
        )
        # Depuis Charlie (a l'adversaire), rien.
        self.assertFalse(
            regles.has_any_sea_transport_target(
                state, state.territories[2], CELL_W, CELL_H,
            ),
        )


class TestPlafondDuConvoi(unittest.TestCase):
    def test_plafond_par_la_garnison(self):
        state = build_state(regiments=(3, 3, 3))
        alpha, _, _ = territoires(state)
        # 3 regiments : 2 embarquables, sous le quota de 5 deplacements.
        self.assertEqual(regles.get_end_turn_move_limit(state), 5)
        self.assertEqual(regles.get_sea_transport_max_regiments(state, alpha), 2)

    def test_plafond_par_le_quota_de_deplacements(self):
        state = build_state(regiments=(11, 3, 3))
        alpha, _, _ = territoires(state)
        self.assertEqual(regles.get_sea_transport_max_regiments(state, alpha), 5)
        state.turn_move_count = 3
        self.assertEqual(regles.get_sea_transport_max_regiments(state, alpha), 2)

    def test_l_apercu_ramene_la_quantite_dans_les_bornes(self):
        state = build_state()
        alpha, bravo, _ = territoires(state)
        apercu = regles.get_sea_transport_preview(state, alpha, bravo, 999, CELL_W, CELL_H)
        self.assertEqual(apercu["regiments"], 5)
        self.assertEqual(apercu["maximum"], 5)
        apercu = regles.get_sea_transport_preview(state, alpha, bravo, 0, CELL_W, CELL_H)
        self.assertEqual(apercu["regiments"], 1)
        # Les chances sont celles d'une expedition : 64 faces au total.
        self.assertEqual(
            apercu["faces_indemne"] + sum(apercu["faces_pertes"].values()),
            regles.EXPEDITION_DIE_FACES,
        )

    def test_apercu_impossible_rend_none(self):
        state = build_state(owners=(0, 0, 0))
        alpha, _, charlie = territoires(state)
        self.assertIsNone(
            regles.get_sea_transport_preview(state, alpha, charlie, 2, CELL_W, CELL_H),
        )


class TestResolution(unittest.TestCase):
    def faces(self, state):
        distance = regles.get_expedition_route_distance(state, 0, 1, CELL_W, CELL_H)
        return distance, regles.get_expedition_risk_faces(distance)

    def test_traversee_indemne(self):
        state = build_state()
        alpha, bravo, _ = territoires(state)
        distance, faces = self.faces(state)
        # La derniere face du de est toujours dans la plage « indemne ».
        de = DeTruque(regles.EXPEDITION_DIE_FACES)
        resultat = regles.resolve_sea_transport(
            state, alpha, bravo, 4, CELL_W, CELL_H, de,
        )
        self.assertEqual(resultat.loss_percent, 0)
        self.assertEqual(resultat.regiments_lost, 0)
        self.assertEqual(resultat.survivors, 4)
        self.assertEqual(resultat.embarked, 4)
        self.assertEqual(alpha.regiments, 7)   # 11 - 4
        self.assertEqual(bravo.regiments, 7)   # 3 + 4
        self.assertEqual(state.turn_move_count, 4)
        self.assertEqual(resultat.moves_spent, 4)
        self.assertIn("traversee indemne", resultat.message)
        self.assertEqual(de.appels, 1)

    def test_sinistre_en_mer(self):
        state = build_state()
        alpha, bravo, _ = territoires(state)
        _distance, faces = self.faces(state)
        # La premiere face perdante est celle du palier le plus faible.
        premiere_perdante = 1
        de = DeTruque(premiere_perdante)
        attendu_percent = regles.EXPEDITION_LOSS_PERCENTS[0]
        resultat = regles.resolve_sea_transport(
            state, alpha, bravo, 4, CELL_W, CELL_H, de,
        )
        if faces[0] == 0:
            self.skipTest("Ce palier de distance n'a pas de face a 25 % de pertes.")
        self.assertEqual(resultat.loss_percent, attendu_percent)
        attendu_perdus = max(1, int(4 * attendu_percent / 100 + 0.5))
        self.assertEqual(resultat.regiments_lost, attendu_perdus)
        self.assertEqual(resultat.survivors, 4 - attendu_perdus)
        self.assertEqual(alpha.regiments, 7)
        self.assertEqual(bravo.regiments, 3 + 4 - attendu_perdus)
        # Le quota est debite du convoi entier, pertes comprises.
        self.assertEqual(state.turn_move_count, 4)
        self.assertIn("sinistre en mer", resultat.message)

    def test_naufrage_total(self):
        """100 % de pertes : le convoi disparait, la destination ne recoit rien."""
        state = build_state()
        alpha, bravo, _ = territoires(state)
        _distance, faces = self.faces(state)
        if faces[-1] == 0:
            self.skipTest("Ce palier de distance n'a pas de face de naufrage total.")
        # Les faces de naufrage total sont les dernieres du cumul des pertes.
        face_naufrage = sum(faces)
        de = DeTruque(face_naufrage)
        resultat = regles.resolve_sea_transport(
            state, alpha, bravo, 3, CELL_W, CELL_H, de,
        )
        self.assertEqual(resultat.loss_percent, 100)
        self.assertTrue(resultat.destroyed)
        self.assertEqual(resultat.survivors, 0)
        self.assertEqual(alpha.regiments, 8)   # 11 - 3
        self.assertEqual(bravo.regiments, 3)   # inchange
        self.assertEqual(state.turn_move_count, 3)
        self.assertIn("naufrage", resultat.message)
        # Un naufrage est un evenement majeur.
        self.assertTrue(
            any("naufrage" in evenement for evenement in state.recent_major_events),
            state.recent_major_events,
        )

    def test_quantite_ramenee_au_maximum(self):
        state = build_state(regiments=(4, 3, 3))
        alpha, bravo, _ = territoires(state)
        resultat = regles.resolve_sea_transport(
            state, alpha, bravo, 99, CELL_W, CELL_H, DeTruque(regles.EXPEDITION_DIE_FACES),
        )
        self.assertEqual(resultat.embarked, 3)   # garnison 4 - 1
        self.assertEqual(alpha.regiments, 1)
        self.assertEqual(state.turn_move_count, 3)

    def test_quantite_nulle_ou_negative_refusee(self):
        state = build_state()
        alpha, bravo, _ = territoires(state)
        for quantite in (0, -2):
            self.assertIsNone(regles.resolve_sea_transport(
                state, alpha, bravo, quantite, CELL_W, CELL_H, random.Random(1),
            ))
        self.assertEqual(state.turn_move_count, 0)

    def test_transport_impossible_rend_none(self):
        state = build_state(owners=(0, 1, 1))
        alpha, bravo, _ = territoires(state)
        self.assertIsNone(regles.resolve_sea_transport(
            state, alpha, bravo, 2, CELL_W, CELL_H, random.Random(1),
        ))
        self.assertEqual(alpha.regiments, 11)
        self.assertEqual(bravo.regiments, 3)

    def test_un_instantane_de_replay_est_enregistre(self):
        state = build_state()
        alpha, bravo, _ = territoires(state)
        avant = len(state.replay_history)
        regles.resolve_sea_transport(
            state, alpha, bravo, 2, CELL_W, CELL_H, DeTruque(regles.EXPEDITION_DIE_FACES),
        )
        self.assertGreater(len(state.replay_history), avant)


class TestVocabulaireDActions(unittest.TestCase):
    def test_action_transport_maritime(self):
        state = build_state()
        resultat = actions.apply_action(
            state,
            {"type": "transport_maritime", "source": 0, "cible": 1, "quantite": 3},
            CELL_W, CELL_H, DeTruque(regles.EXPEDITION_DIE_FACES),
        )
        self.assertTrue(resultat.ok, resultat.code)
        self.assertIn("arrivent a bon port", resultat.message)
        self.assertEqual(state.territories[0].regiments, 8)
        self.assertEqual(state.territories[1].regiments, 6)
        self.assertEqual(state.turn_move_count, 3)
        # Le rapport porte les deux territoires touches, pour les clients.
        touches = {t["id"]: t for t in resultat.transport["territoires"]}
        self.assertEqual(touches[0]["regiments"], 8)
        self.assertEqual(touches[1]["regiments"], 6)
        self.assertEqual(resultat.transport["resultat"].roll, regles.EXPEDITION_DIE_FACES)

    def test_refus_hors_phase_de_deplacement(self):
        state = build_state()
        state.turn_phase = "attack"
        resultat = actions.apply_action(
            state,
            {"type": "transport_maritime", "source": 0, "cible": 1, "quantite": 2},
            CELL_W, CELL_H, random.Random(1),
        )
        self.assertFalse(resultat.ok)
        self.assertEqual(resultat.code, "phase_invalide")

    def test_refus_si_la_terre_relie_les_deux(self):
        state = build_state()
        regles.add_bridge(state, (0, 1), ((0, 4), (0, 10)), fragile=False)
        resultat = actions.apply_action(
            state,
            {"type": "transport_maritime", "source": 0, "cible": 1, "quantite": 2},
            CELL_W, CELL_H, random.Random(1),
        )
        self.assertFalse(resultat.ok)
        self.assertEqual(resultat.code, "transport_invalide")

    def test_refus_territoire_inconnu(self):
        state = build_state()
        resultat = actions.apply_action(
            state,
            {"type": "transport_maritime", "source": 0, "cible": 42, "quantite": 2},
            CELL_W, CELL_H, random.Random(1),
        )
        self.assertFalse(resultat.ok)
        self.assertEqual(resultat.code, "territoire_invalide")

    def test_le_deplacement_terrestre_reste_refuse_par_la_mer(self):
        """Temoin : sans transport, la mer bloque toujours un deplacement."""
        state = build_state()
        resultat = actions.apply_action(
            state, {"type": "deplacer", "source": 0, "cible": 1},
            CELL_W, CELL_H, random.Random(1),
        )
        self.assertFalse(resultat.ok)
        self.assertEqual(resultat.code, "continuite")


if __name__ == "__main__":
    unittest.main(verbosity=2)
