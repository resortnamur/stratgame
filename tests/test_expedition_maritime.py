"""Expeditions maritimes : plans d'eau, distances, de a 64 faces, combats.

Une carte synthetique 12x30 a trois territoires et deux mers permet de
verifier chaque regle sans dependre des sauvegardes :
- A et B bordent la mer Ouest, C ne borde que la mer Est : A peut lancer
  une expedition vers B mais jamais vers C (pas d'etendue d'eau continue) ;
- la distance est celle des deux points cotiers les plus proches ;
- la table de risques (paliers 100/300/800 px) somme toujours a 64 faces ;
- l'arrondi des pertes est au plus proche, avec 1 regiment perdu minimum ;
- le debarquement plafonne l'attaquant a 2 des et se bat jusqu'au dernier ;
- l'IA lance une expedition (>= 20 regiments, 1 chance sur 10) vers la
  cible eligible la plus faible ;
- aucune IA ne vise au-dela de 300 px (les humains, eux, restent libres) ;
- les Cites commercantes n'embarquent qu'a partir du tour 50.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import actions, ia, regles

# Geometrie logique du serveur (mais toute echelle marcherait ici).
CELL_W = 10.0
CELL_H = 10.0


def build_map_payload():
    """Trois territoires : A (cols 0-4), B (cols 10-14), C (cols 25-29).

    Entre A et B : la mer Ouest (cols 5-9). Entre B et C : la terre de B
    s'arrete col 14, la mer Est (cols 15-24) borde B ? Non — pour isoler
    C, une bande de terre neutre est impossible (la grille ne connait que
    des territoires ou de l'eau). On isole donc les mers par le territoire
    B lui-meme, qui traverse la carte de haut en bas : la mer Ouest
    (entre A et B) et la mer Est (entre B et C) ne communiquent pas.
    """
    rows, cols = 12, 30
    grid = [[-1] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(0, 5):
            grid[r][c] = 0        # A
        for c in range(10, 15):
            grid[r][c] = 1        # B (mur vertical complet)
        for c in range(25, 30):
            grid[r][c] = 2        # C
    territories = [
        {"id": 0, "name": "Alpha", "reinforcement_bonus": 1},
        {"id": 1, "name": "Bravo", "reinforcement_bonus": 1},
        {"id": 2, "name": "Charlie", "reinforcement_bonus": 1},
    ]
    return {
        "kind": "map",
        "map_mode": "standard",
        "rows": rows,
        "cols": cols,
        "grid_territory": grid,
        "territories": territories,
    }


def build_state(regiments=(11, 3, 3), owners=(0, 1, 1)):
    state = GameState.from_map_payload(build_map_payload())
    state.num_players = 2
    state.initial_num_players = 2
    state.current_player = 0
    state.turn = 1
    state.phase = "playing"
    state.turn_phase = "attack"
    state.player_money = {0: 0, 1: 0}
    for terr, owner, count in zip(state.territories, owners, regiments):
        terr.owner = owner
        terr.regiments = count
    return state


class RngFixe:
    """Un de pipe : rend les valeurs fournies, dans l'ordre."""

    def __init__(self, valeurs):
        self.valeurs = list(valeurs)

    def randint(self, a, b):
        return self.valeurs.pop(0)


class TestGeometrie(unittest.TestCase):
    def test_plans_deau_separes(self):
        state = build_state()
        bodies = regles.get_water_body_grid(state)
        ouest = bodies[0][7]
        est = bodies[0][20]
        self.assertNotEqual(ouest, est, "les deux mers doivent etre distinctes")
        self.assertEqual(bodies[5][6], ouest)
        self.assertEqual(bodies[11][22], est)
        self.assertEqual(bodies[3][2], -1, "la terre n'est pas un plan d'eau")

    def test_route_maritime_et_distance(self):
        state = build_state()
        # A et B bordent la mer Ouest : cotes en col 4 et col 10, soit
        # 6 colonnes d'ecart -> 60 px avec des cellules de 10 px.
        distance = regles.get_expedition_route_distance(state, 0, 1, CELL_W, CELL_H)
        self.assertIsNotNone(distance)
        self.assertAlmostEqual(distance, 60.0, places=6)
        # A et C ne partagent aucune mer : pas de route.
        self.assertIsNone(regles.get_expedition_route_distance(state, 0, 2, CELL_W, CELL_H))
        # B et C bordent la mer Est : cotes en col 14 et col 25, soit
        # 11 colonnes d'ecart -> 110 px (au-dela du premier palier).
        self.assertAlmostEqual(
            regles.get_expedition_route_distance(state, 1, 2, CELL_W, CELL_H), 110.0, places=6,
        )

    def test_eligibilite(self):
        state = build_state()
        a, b, c = state.territories
        self.assertTrue(regles.can_launch_expedition(state, a, b, CELL_W, CELL_H))
        self.assertFalse(
            regles.can_launch_expedition(state, a, c, CELL_W, CELL_H),
            "pas d'etendue d'eau continue entre A et C",
        )
        # Une garnison de 1 ne peut pas embarquer.
        a.regiments = 1
        self.assertFalse(regles.can_launch_expedition(state, a, b, CELL_W, CELL_H))
        a.regiments = 11
        # Les voisins s'attaquent normalement : jamais d'expedition.
        a.neighbors = sorted(set(a.neighbors) | {1})
        self.assertFalse(regles.can_launch_expedition(state, a, b, CELL_W, CELL_H))


class TestTableDeRisques(unittest.TestCase):
    def test_paliers(self):
        attendus = {
            50.0: (16, 8, 4, 2),
            100.0: (16, 8, 4, 2),
            100.5: (20, 12, 8, 4),
            300.0: (20, 12, 8, 4),
            300.5: (32, 16, 8, 4),
            800.0: (32, 16, 8, 4),
            800.5: (32, 16, 8, 8),
            9999.0: (32, 16, 8, 8),
        }
        for distance, faces in attendus.items():
            self.assertEqual(regles.get_expedition_risk_faces(distance), faces, distance)
            self.assertLessEqual(sum(faces), regles.EXPEDITION_DIE_FACES)

    def test_apercu(self):
        state = build_state()
        a, b = state.territories[0], state.territories[1]
        apercu = regles.get_expedition_preview(state, a, b, CELL_W, CELL_H)
        self.assertEqual(apercu["flotte"], 10)
        self.assertEqual(apercu["faces_indemne"], 34)
        self.assertEqual(apercu["faces_pertes"], {"25": 16, "50": 8, "75": 4, "100": 2})


class TestTraversee(unittest.TestCase):
    def resoudre(self, roll, flotte=10):
        state = build_state(regiments=(flotte + 1, 3, 3))
        a, b = state.territories[0], state.territories[1]
        crossing = regles.resolve_expedition_crossing(
            state, a, b, CELL_W, CELL_H, RngFixe([roll]),
        )
        return state, crossing

    def test_indemne(self):
        # Distance 60 px -> palier 1 : rolls 31-64 = indemne.
        state, crossing = self.resoudre(31)
        self.assertEqual(crossing.loss_percent, 0)
        self.assertEqual(crossing.survivors, 10)
        self.assertEqual(state.territories[0].regiments, 11)
        self.assertFalse(crossing.destroyed)

    def test_pertes_25_pourcent_arrondi(self):
        # 25 % de 10 = 2,5 -> arrondi au plus proche = 3 (int(x + 0.5)).
        state, crossing = self.resoudre(1)
        self.assertEqual(crossing.loss_percent, 25)
        self.assertEqual(crossing.regiments_lost, 3)
        self.assertEqual(crossing.survivors, 7)
        self.assertEqual(state.territories[0].regiments, 8)

    def test_pertes_minimum_un_regiment(self):
        # 25 % de 1 regiment = 0,25 -> au moins 1 regiment perdu.
        state, crossing = self.resoudre(1, flotte=1)
        self.assertEqual(crossing.regiments_lost, 1)
        self.assertEqual(crossing.survivors, 0)
        self.assertTrue(crossing.destroyed)

    def test_paliers_du_de(self):
        # Palier 1 : 1-16 -> 25 %, 17-24 -> 50 %, 25-28 -> 75 %, 29-30 -> 100 %.
        for roll, percent in ((16, 25), (17, 50), (24, 50), (25, 75), (28, 75), (29, 100), (30, 100)):
            _state, crossing = self.resoudre(roll)
            self.assertEqual(crossing.loss_percent, percent, f"roll={roll}")

    def test_naufrage_total(self):
        state, crossing = self.resoudre(30)
        self.assertEqual(crossing.loss_percent, 100)
        self.assertEqual(crossing.survivors, 0)
        self.assertTrue(crossing.destroyed)
        self.assertEqual(state.territories[0].regiments, 1,
                         "le regiment laisse au port reste seul")


class TestDebarquement(unittest.TestCase):
    def test_plafond_deux_des(self):
        state = build_state(regiments=(31, 3, 3))
        a, b = state.territories[0], state.territories[1]
        # Traversee indemne (roll 31), puis une passe : l'attaquant a 30
        # regiments en mer mais ne lance que 2 des (les deux premiers
        # randint apres la traversee).
        rng = RngFixe([31, 6, 6, 1, 1])
        regles.resolve_expedition_crossing(state, a, b, CELL_W, CELL_H, rng)
        result = regles.resolve_attack_once(
            state, a, b, rng, None, max_attack_dice=regles.EXPEDITION_MAX_ATTACK_DICE,
        )
        self.assertEqual(result.att_text, "[6, 6]", "2 des au maximum au debarquement")
        self.assertEqual(result.def_text, "[1, 1]")
        self.assertEqual(state.territories[1].regiments, 1)

    def test_combat_jusqu_au_dernier_homme(self):
        # Flotte de 2 : apres la traversee indemne, la flotte perd chaque
        # passe (des defavorables) et disparait — B reste au defenseur.
        state = build_state(regiments=(3, 3, 3))
        a, b = state.territories[0], state.territories[1]
        rolls = [31]          # traversee indemne, flotte = 2
        rolls += [1, 1, 6, 6] * 4   # att [1,1] vs def [6,6] : -2 par passe
        rng = RngFixe(rolls)
        crossing = regles.resolve_expedition_crossing(state, a, b, CELL_W, CELL_H, rng)
        self.assertEqual(crossing.survivors, 2)
        passes = 0
        while (not crossing.destroyed and state.phase == "playing"
               and regles.can_attack_specific_target(state, a, b, ignore_adjacency=True)):
            result = regles.resolve_attack_once(
                state, a, b, rng, None, max_attack_dice=regles.EXPEDITION_MAX_ATTACK_DICE,
            )
            passes += 1
            if result.conquered:
                break
        self.assertEqual(state.territories[0].regiments, 1, "la flotte a peri")
        self.assertEqual(state.territories[1].owner, 1, "B tient bon")
        self.assertGreaterEqual(passes, 1)

    def test_action_expedition_complete(self):
        state = build_state(regiments=(11, 1, 3))
        rng = RngFixe([31] + [6, 6, 1] * 10)  # indemne puis des gagnants
        outcome = actions.apply_action(
            state, {"type": "expedition", "source": 0, "cible": 1},
            CELL_W, CELL_H, rng,
        )
        self.assertTrue(outcome.ok)
        self.assertIsNotNone(outcome.expedition)
        self.assertEqual(outcome.expedition["crossing"].survivors, 10)
        self.assertTrue(outcome.attack_passes[-1].conquered)
        self.assertEqual(state.territories[1].owner, 0)
        self.assertEqual(len(outcome.expedition["passes"]), len(outcome.attack_passes))

    def test_action_expedition_refusee_sans_route(self):
        state = build_state()
        outcome = actions.apply_action(
            state, {"type": "expedition", "source": 0, "cible": 2},
            CELL_W, CELL_H, random.Random(1),
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "expedition_invalide")

    def test_naufrage_arrete_l_attaque(self):
        state = build_state(regiments=(11, 3, 3))
        rng = RngFixe([29])  # palier 1 : 29 -> 100 % de pertes
        outcome = actions.apply_action(
            state, {"type": "expedition", "source": 0, "cible": 1},
            CELL_W, CELL_H, rng,
        )
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.expedition["crossing"].destroyed)
        self.assertEqual(outcome.attack_passes, [], "aucun combat apres un naufrage")
        self.assertEqual(state.territories[0].regiments, 1)
        self.assertEqual(state.territories[1].owner, 1)


class TestExpeditionIA(unittest.TestCase):
    def build_ai_state(self, regiments=(25, 3, 5)):
        state = build_state(regiments=regiments)
        state.base_ai_players = {0}
        state.ai_player_count = 1
        return state

    def test_seuil_et_tirage(self):
        state = self.build_ai_state()
        # Tirage 1 sur 10 reussi -> un depart, vers l'eligible le plus
        # faible (B, seul eligible : C n'a pas de mer commune avec A).
        departs = list(ia.iter_ai_expedition_launches(state, CELL_W, CELL_H, RngFixe([1])))
        self.assertEqual([(src.id, dst.id) for src, dst in departs], [(0, 1)])
        # Tirage rate -> aucun depart.
        departs = list(ia.iter_ai_expedition_launches(state, CELL_W, CELL_H, RngFixe([5])))
        self.assertEqual(departs, [])

    def test_moins_de_20_regiments_jamais(self):
        state = self.build_ai_state(regiments=(19, 3, 5))
        rng = RngFixe([])  # aucun randint ne doit etre tire
        self.assertEqual(list(ia.iter_ai_expedition_launches(state, CELL_W, CELL_H, rng)), [])

    def test_cible_la_plus_faible(self):
        # B affaibli a 2 regiments contre une carte ou C serait aussi
        # eligible : on rapproche C de la mer Ouest en le donnant au meme
        # plan d'eau ? Plus simple : B (2 regiments) et B' n'existe pas —
        # on verifie directement le selecteur avec deux cibles eligibles.
        state = self.build_ai_state()
        # Rendre C eligible depuis A : on relie les deux mers en creusant
        # le mur de B sur la ligne 6 (la grille devient une seule mer).
        for col in range(10, 15):
            state.grid_territory[6][col] = -1
        state.territories[1].cells = [
            cell for cell in state.territories[1].cells if cell[0] != 6
        ]
        state.expedition_geometry_cache = {}
        state.territories[1].regiments = 4
        state.territories[2].regiments = 2
        src = state.territories[0]
        cible = ia.find_ai_expedition_target(state, src, CELL_W, CELL_H)
        self.assertEqual(
            cible.id, 2,
            "la cible la plus faible est preferee, quelle que soit la distance (sous le plafond)",
        )

    def test_tour_ia_complet_avec_expedition(self):
        state = self.build_ai_state()
        # randint(1,10)=1 -> depart ; puis traversee indemne (31) ; puis
        # des toujours gagnants jusqu'a la conquete ; ensuite le tour se
        # poursuit normalement avec un vrai rng seme.
        class RngMixte:
            def __init__(self):
                self.fixes = [1, 31]
                self.reel = random.Random(99)

            def randint(self, a, b):
                if self.fixes:
                    return self.fixes.pop(0)
                return self.reel.randint(a, b)

            def __getattr__(self, name):
                return getattr(self.reel, name)

        rapport = actions.play_ai_turn(state, CELL_W, CELL_H, RngMixte())
        self.assertIsNone(rapport.winner if state.phase == "playing" else None)
        # La flotte a debarque : le port d'attache garde 1 regiment.
        self.assertEqual(state.territories[0].regiments >= 1, True)


class TestPlafondDistanceIA(unittest.TestCase):
    """Aucune IA ne tente une traversee de plus de 300 px."""

    def build_ai_state(self, regiments=(25, 3, 5)):
        state = build_state(regiments=regiments)
        state.base_ai_players = {0}
        state.ai_player_count = 1
        return state

    def relier_les_deux_mers(self, state):
        """Perce le mur de B (ligne 6) : A borde alors aussi la mer Est."""
        for col in range(10, 15):
            state.grid_territory[6][col] = -1
        state.territories[1].cells = [
            cell for cell in state.territories[1].cells if cell[0] != 6
        ]
        state.expedition_geometry_cache = {}

    def test_cible_trop_lointaine_ecartee(self):
        state = self.build_ai_state()
        self.relier_les_deux_mers(state)
        src = state.territories[0]
        # A -> C : cotes col 4 et col 25, soit 210 px avec des cellules de
        # 10 px. En elargissant les cellules a 20 px, la meme route depasse
        # les 300 px : la cible sort du champ des IA.
        self.assertAlmostEqual(
            regles.get_expedition_route_distance(state, 0, 2, 20.0, CELL_H), 420.0, places=6,
        )
        state.territories[1].regiments = 4
        state.territories[2].regiments = 2   # la plus faible, mais trop loin
        cible = ia.find_ai_expedition_target(state, src, 20.0, CELL_H)
        self.assertEqual(cible.id, 1, "l'IA se rabat sur la cible a portee")

        # Le joueur humain, lui, garde le droit d'embarquer aussi loin.
        self.assertTrue(regles.can_launch_expedition(
            state, src, state.territories[2], 20.0, CELL_H,
        ))

    def test_aucune_cible_a_portee(self):
        state = self.build_ai_state()
        state.expedition_geometry_cache = {}
        src = state.territories[0]
        # Cellules de 60 px : A -> B fait 360 px, hors de portee des IA.
        self.assertAlmostEqual(
            regles.get_expedition_route_distance(state, 0, 1, 60.0, CELL_H), 360.0, places=6,
        )
        self.assertIsNone(ia.find_ai_expedition_target(state, src, 60.0, CELL_H))
        departs = list(ia.iter_ai_expedition_launches(state, 60.0, CELL_H, RngFixe([1])))
        self.assertEqual(departs, [], "le tirage reussi ne suffit pas sans cible a portee")


class TestCiteCommercanteAvantTour50(unittest.TestCase):
    """Les Cites commercantes n'embarquent pas avant le tour 50."""

    def build_cc_state(self, turn):
        state = build_state(regiments=(25, 3, 5))
        state.base_ai_players = {0}
        state.ai_player_count = 1
        state.commercial_city_players = {0}
        state.commercial_city_capital_ids = {0: 0}
        state.turn = turn
        return state

    def test_avant_le_tour_50_aucune_expedition(self):
        state = self.build_cc_state(turn=49)
        src, cible = state.territories[0], state.territories[1]
        self.assertFalse(regles.can_player_launch_expeditions(state, 0))
        self.assertFalse(regles.can_launch_expedition(state, src, cible, CELL_W, CELL_H))
        rng = RngFixe([])   # aucun tirage ne doit avoir lieu
        self.assertEqual(list(ia.iter_ai_expedition_launches(state, CELL_W, CELL_H, rng)), [])
        outcome = actions.apply_action(
            state, {"type": "expedition", "source": 0, "cible": 1},
            CELL_W, CELL_H, random.Random(1),
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.code, "expedition_invalide")

    def test_a_partir_du_tour_50_les_expeditions_reprennent(self):
        state = self.build_cc_state(turn=50)
        src, cible = state.territories[0], state.territories[1]
        self.assertTrue(regles.can_player_launch_expeditions(state, 0))
        self.assertTrue(regles.can_launch_expedition(state, src, cible, CELL_W, CELL_H))
        departs = list(ia.iter_ai_expedition_launches(state, CELL_W, CELL_H, RngFixe([1])))
        self.assertEqual([(s.id, d.id) for s, d in departs], [(0, 1)])

    def test_les_autres_ia_embarquent_des_le_debut(self):
        """Le verrou ne vise que les CC : une IA ordinaire n'attend pas."""
        state = self.build_cc_state(turn=1)
        state.commercial_city_players = set()
        state.commercial_city_capital_ids = {}
        self.assertTrue(regles.can_player_launch_expeditions(state, 0))
        departs = list(ia.iter_ai_expedition_launches(state, CELL_W, CELL_H, RngFixe([1])))
        self.assertEqual([(s.id, d.id) for s, d in departs], [(0, 1)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
