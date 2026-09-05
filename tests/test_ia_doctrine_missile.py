"""Doctrine missile, score de menace et epargne dirigee des IA.

Trois initiatives ajoutees aux joueurs IA :

* le missile, tire avec parcimonie et **uniquement contre des humains** ;
* un score de menace par joueur, qui fait converger les attaques et les
  concentrations de fin de tour sur celui qui est en train de gagner ;
* une epargne dirigee : l'IA garde de quoi tirer au lieu de tout convertir
  en mercenaires — mais seulement si elle peut s'en servir.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import achats
from moteur import actions
from moteur import ia
from moteur import regles


NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
LARGEUR_CELLULE = 20.0
HAUTEUR_CELLULE = 20.0


class TirageForce:
    """Un rng dont ``randint`` retourne toujours 1 : le tirage passe."""

    def randint(self, borne_basse, borne_haute):
        return borne_basse

    def random(self):
        return 0.5

    def choice(self, sequence):
        return sequence[0]

    def shuffle(self, sequence):
        pass


class TirageBloque(TirageForce):
    """Le meme, mais ``randint`` rate toujours : le tirage echoue."""

    def randint(self, borne_basse, borne_haute):
        return borne_haute if borne_haute != borne_basse else borne_basse


def build_map_payload(count):
    """``count`` territoires alignes, chacun voisin du suivant, sans mer."""
    rows, cols = 6, 3 * count
    grid = [[0] * cols for _ in range(rows)]
    for r in range(rows):
        for index in range(count):
            for c in range(3 * index, 3 * index + 3):
                grid[r][c] = index
    return {
        "kind": "map",
        "map_mode": "standard",
        "rows": rows,
        "cols": cols,
        "grid_territory": grid,
        "territories": [
            {
                "id": index,
                "name": NAMES[index] if index < len(NAMES) else f"Terr{index}",
                "reinforcement_bonus": 1,
            }
            for index in range(count)
        ],
    }


def build_state(owners, regiments, ia_players=(0,), money=0, turn=30):
    """Partie minimale : ``ia_players`` sont des IA, les autres des humains."""
    state = GameState.from_map_payload(build_map_payload(len(owners)))
    state.num_players = max(owners) + 1
    state.initial_num_players = state.num_players
    state.current_player = 0
    state.turn = turn
    state.phase = "playing"
    state.turn_phase = "attack"
    state.base_ai_players = set(ia_players)
    state.player_money = {joueur: money for joueur in range(state.num_players)}
    state.player_science = {joueur: 0 for joueur in range(state.num_players)}
    for terr, owner, count in zip(state.territories, owners, regiments):
        terr.owner = owner
        terr.regiments = count
    return state


class TestDoctrineMissile(unittest.TestCase):
    """Le missile IA : rare, et jamais contre une autre IA."""

    def build(self, **kwargs):
        # J0 (IA, science 50) fait face a J1 (humain) et J2 (autre IA).
        state = build_state(
            owners=(0, 1, 2), regiments=(5, 20, 30),
            ia_players=(0, 2), money=regles.MISSILE_COST, **kwargs,
        )
        state.player_science[0] = regles.SCIENCE_MISSILE_THRESHOLD
        return state

    def cible(self, state, rng=None):
        return ia.find_ai_missile_target(
            state, LARGEUR_CELLULE, HAUTEUR_CELLULE, rng or TirageForce(),
        )

    def test_le_missile_vise_l_humain(self):
        state = self.build()
        cible = self.cible(state)
        self.assertIsNotNone(cible)
        self.assertEqual(cible.id, 1)

    def test_jamais_contre_une_autre_ia(self):
        """Seul le voisin IA reste : l'IA range son missile."""
        state = self.build()
        state.territories[1].owner = 2  # plus aucun humain sur la carte
        self.assertIsNone(self.cible(state))

    def test_rien_sans_la_science(self):
        state = self.build()
        state.player_science[0] = regles.AI_SCIENCE_MISSILE_THRESHOLD - 1
        self.assertIsNone(self.cible(state))

    def test_l_ia_s_arme_avant_la_boutique_humaine(self):
        """Le palier 1 s'ouvre a une IA la ou un humain attend encore."""
        state = self.build()
        state.player_science[0] = regles.AI_SCIENCE_MISSILE_THRESHOLD
        self.assertLess(
            regles.AI_SCIENCE_MISSILE_THRESHOLD, regles.SCIENCE_MISSILE_THRESHOLD,
        )
        self.assertEqual(regles.get_player_missile_tier(state, 0), 1)
        self.assertIsNotNone(self.cible(state))
        # Le meme siege repris en main par un humain rentre dans le rang.
        state.human_controlled_players.add(0)
        self.assertEqual(regles.get_player_missile_tier(state, 0), 0)

    def test_rien_sans_l_argent(self):
        state = self.build()
        state.player_money[0] = regles.MISSILE_COST - 1
        self.assertIsNone(self.cible(state))

    def test_rien_avant_le_tour_d_ouverture(self):
        state = self.build(turn=regles.AI_MISSILE_FIRST_TURN - 1)
        self.assertIsNone(self.cible(state))

    def test_le_missile_se_recharge(self):
        state = self.build()
        state.ai_last_missile_turns[0] = state.turn - 1
        self.assertIsNone(self.cible(state))
        state.ai_last_missile_turns[0] = state.turn - regles.AI_MISSILE_COOLDOWN_TURNS
        self.assertIsNotNone(self.cible(state))

    def test_le_tirage_peut_faire_renoncer(self):
        """Toutes conditions reunies, il reste la part de hasard."""
        state = self.build()
        self.assertIsNone(self.cible(state, TirageBloque()))

    def test_une_garnison_symbolique_ne_vaut_pas_le_tir(self):
        state = self.build()
        state.territories[1].regiments = regles.AI_MISSILE_MIN_TARGET_REGIMENTS - 1
        self.assertIsNone(self.cible(state))

    def test_un_allie_n_est_pas_bombarde(self):
        state = self.build()
        state.active_alliances[(1, 0)] = state.turn + regles.ALLIANCE_DURATION_TURNS
        self.assertIsNone(self.cible(state))

    def test_le_dome_de_selene_intercepte(self):
        state = self.build()
        state.wonder_territories["selene_dome"] = 1
        self.assertIsNone(self.cible(state))

    def test_la_portee_borne_le_choix(self):
        """Palier 1 : seul un voisin immediat de l'IA est atteignable."""
        # J0 ne touche que Bravo ; Delta (humain, gros) est deux crans plus loin.
        state = build_state(
            owners=(0, 1, 1, 1), regiments=(5, 10, 40, 40),
            ia_players=(0,), money=regles.MISSILE_COST,
        )
        state.player_science[0] = regles.SCIENCE_MISSILE_THRESHOLD
        cible = self.cible(state)
        self.assertIsNotNone(cible)
        self.assertEqual(cible.id, 1)

    def test_le_palier_trois_frappe_partout_et_choisit_le_plus_gros(self):
        state = build_state(
            owners=(0, 1, 1, 1), regiments=(5, 10, 40, 25),
            ia_players=(0,), money=regles.MISSILE_COST,
        )
        state.player_science[0] = regles.SCIENCE_MISSILE_TOTAL_THRESHOLD
        cible = self.cible(state)
        self.assertIsNotNone(cible)
        self.assertEqual(cible.id, 2)


class TestTirPendantLeTourIa(unittest.TestCase):
    """Le tir ouvre le tour et se diffuse comme une passe a part entiere."""

    def test_le_tour_ia_commence_par_la_frappe(self):
        state = build_state(
            owners=(0, 1), regiments=(5, 20),
            ia_players=(0,), money=regles.MISSILE_COST,
        )
        state.player_science[0] = regles.SCIENCE_MISSILE_THRESHOLD
        pas = list(actions.play_ai_turn_steps(
            state, LARGEUR_CELLULE, HAUTEUR_CELLULE, TirageForce(),
        ))
        self.assertTrue(pas)
        premier = pas[0]
        self.assertIsInstance(premier, actions.AiMissileStep)
        self.assertEqual(premier.dst_id, 1)
        self.assertEqual(premier.src_id, 0)
        # La garnison a fondu de moitie et le missile est paye.
        self.assertEqual(state.territories[1].regiments, 10)
        self.assertEqual(state.player_money[0], 0)
        # Le rechargement demarre : pas de second tir le tour suivant.
        self.assertEqual(state.ai_last_missile_turns[0], state.turn)

    def test_un_tour_sans_missile_ne_produit_aucune_frappe(self):
        state = build_state(owners=(0, 1), regiments=(5, 20), ia_players=(0,))
        pas = list(actions.play_ai_turn_steps(
            state, LARGEUR_CELLULE, HAUTEUR_CELLULE, TirageForce(),
        ))
        self.assertFalse(any(isinstance(p, actions.AiMissileStep) for p in pas))


class TestDiffusionDuTir(unittest.TestCase):
    """Le serveur transmet la frappe telle que le client l'attend."""

    def test_le_pas_diffuse_porte_le_detail_du_tir(self):
        from serveur.partie import SessionPartie

        state = build_state(
            owners=(0, 1), regiments=(5, 20),
            ia_players=(0,), money=regles.MISSILE_COST,
        )
        state.player_science[0] = regles.SCIENCE_MISSILE_THRESHOLD
        session = SessionPartie("p-test", state)
        session.rng = TirageForce()
        self.assertEqual(session.demarrer_tour_ia(), 0)
        pas, resultat = session.pas_tour_ia()
        self.assertIsNone(resultat)
        self.assertIsNotNone(pas)
        # C'est sur cette cle que le client branche son animation.
        frappe = pas.get("missile")
        self.assertIsNotNone(frappe)
        for cle in ("src_id", "dst_id", "tier", "losses", "message"):
            self.assertIn(cle, frappe)
        self.assertEqual(frappe["dst_id"], 1)
        self.assertGreater(frappe["losses"], 0)
        # Et les territoires touches accompagnent le pas, comme pour une attaque.
        self.assertTrue(pas.get("territoires"))

    def test_les_sieges_annoncent_la_doctrine_des_ia(self):
        """Le joueur doit pouvoir lire a quel genre d'IA il a affaire."""
        from serveur.partie import SessionPartie

        state = build_state(owners=(0, 1), regiments=(5, 5), ia_players=(0,))
        sieges = SessionPartie("p-sieges", state).sieges()
        par_joueur = {siege["joueur"]: siege for siege in sieges}
        self.assertEqual(par_joueur[0]["doctrine"], regles.get_ai_doctrine(state, 0))
        # Un siege humain n'a pas de doctrine.
        self.assertIsNone(par_joueur[1]["doctrine"])


class TestScoreDeMenace(unittest.TestCase):
    """Les IA convergent sur celui qui est en train de gagner."""

    def build(self):
        # J0 (IA) touche J1 (petit) et J2 (qui tient le reste de la carte).
        owners = (0, 1) + (2,) * 6
        state = build_state(
            owners=owners, regiments=(30, 5) + (5,) * 6, ia_players=(0,),
        )
        return state

    def test_le_meneur_a_le_score_le_plus_eleve(self):
        state = self.build()
        self.assertGreater(
            regles.get_player_menace_score(state, 2),
            regles.get_player_menace_score(state, 1),
        )

    def test_le_meneur_devient_la_cible_prioritaire(self):
        state = self.build()
        self.assertEqual(regles.get_ai_priority_target(state, 0), 2)

    def test_personne_ne_se_detache_personne_n_est_designe(self):
        """Deux rivaux a egalite : l'IA garde sa logique d'opportunite.

        La carte doit etre assez grande pour que personne ne soit a portee
        d'une victoire territoriale — sinon c'est l'etat d'urgence qui
        tranche, et il ignore justement la marge.
        """
        owners = (0,) * 8 + (1,) * 6 + (2,) * 6
        state = build_state(owners=owners, regiments=(5,) * 20, ia_players=(0,))
        self.assertFalse(regles.get_imminent_victory_threats(state))
        self.assertIsNone(regles.get_ai_priority_target(state, 0))

    def test_un_allie_n_est_jamais_designe(self):
        state = self.build()
        state.active_alliances[(2, 0)] = state.turn + regles.ALLIANCE_DURATION_TURNS
        self.assertNotEqual(regles.get_ai_priority_target(state, 0), 2)

    def test_l_attaque_prefere_la_cible_prioritaire(self):
        """A attaques egales, celle qui vise le meneur passe devant."""
        state = self.build()
        source = state.territories[0]
        faible = state.territories[1]   # J1, garnison identique
        meneur = state.territories[2]   # J2, garnison identique
        meneur.regiments = faible.regiments
        sans, _ = ia.ai_attack_score(state, source, faible, "standard", TirageForce())
        avec, _ = ia.ai_attack_score(state, source, meneur, "standard", TirageForce(), 2)
        self.assertGreater(avec, sans)


class TestAlerteDeVictoire(unittest.TestCase):
    """Quand quelqu'un touche au but, les IA lachent tout le reste."""

    def build(self):
        """J2 est a un territoire de la victoire territoriale ; J0 est l'IA."""
        # 20 territoires, seuil 15 : J2 en tient 14, la marge d'alerte est 3.
        owners = (0,) * 5 + (1,) + (2,) * 14
        state = build_state(owners=owners, regiments=(5,) * 20, ia_players=(0,))
        return state

    def test_l_alerte_se_declenche(self):
        state = self.build()
        menaces = [m["joueur"] for m in regles.get_imminent_victory_threats(state)]
        self.assertIn(2, menaces)

    def test_le_joueur_qui_touche_au_but_devient_la_cible(self):
        state = self.build()
        self.assertEqual(regles.get_ai_priority_target(state, 0), 2)
        self.assertTrue(regles.is_ai_facing_victory_alert(state, 0))

    def test_l_ia_passe_en_urgence(self):
        """Meme une IA « defensive » attaque a fond face a une victoire."""
        state = self.build()
        regles.assign_ai_personality_to_player(state, 0, "defensive")
        self.assertEqual(ia.get_ai_behavior(state, 0), "very_aggressive")

    def test_un_allie_menacant_ne_declenche_rien(self):
        """On ne peut pas l'attaquer : inutile de sonner l'alarme."""
        state = self.build()
        state.active_alliances[(2, 0)] = state.turn + regles.ALLIANCE_DURATION_TURNS
        self.assertIsNone(regles.get_ai_priority_target(state, 0))
        self.assertFalse(regles.is_ai_facing_victory_alert(state, 0))

    def test_sans_alerte_le_profil_reprend_la_main(self):
        state = build_state(
            owners=(0,) * 8 + (1,) * 6 + (2,) * 6, regiments=(5,) * 20, ia_players=(0,),
        )
        regles.assign_ai_personality_to_player(state, 0, "defensive")
        self.assertEqual(ia.get_ai_behavior(state, 0), "defensive")


class TestDoctrinesDesIa(unittest.TestCase):
    """Le profil dit comment l'IA se bat, la doctrine ou passe son argent."""

    def test_la_doctrine_se_lit_sur_le_numero_et_ne_bouge_pas(self):
        state = build_state(owners=(0, 1), regiments=(5, 5), ia_players=(0,))
        premiere = regles.get_ai_doctrine(state, 0)
        state.turn += 10
        state.territories[0].regiments = 99
        self.assertEqual(regles.get_ai_doctrine(state, 0), premiere)

    def test_les_quatre_doctrines_sont_representees(self):
        vues = {regles.get_ai_doctrine(None, joueur) for joueur in range(10)}
        self.assertEqual(vues, set(regles.AI_DOCTRINE_SETTINGS))

    def test_le_cycle_des_doctrines_decale_celui_des_profils(self):
        """Cinq doctrines pour quatre profils : les paires ne se figent pas."""
        self.assertNotEqual(
            len(regles.AI_DOCTRINES_ORDER) % len(regles.AI_PROFILES), 0,
        )

    def test_le_batisseur_mure_et_instruit_plus_que_le_conquerant(self):
        batisseur = regles.AI_DOCTRINE_SETTINGS["batisseur"]
        conquerant = regles.AI_DOCTRINE_SETTINGS["conquerant"]
        self.assertGreater(
            regles.get_ai_fortress_quota(24, batisseur["territories_per_fortress"]),
            regles.get_ai_fortress_quota(24, conquerant["territories_per_fortress"]),
        )
        self.assertGreater(
            regles.get_ai_knowledge_quota(24, batisseur["territories_per_knowledge_building"]),
            regles.get_ai_knowledge_quota(24, conquerant["territories_per_knowledge_building"]),
        )

    def test_les_quatre_doctrines_arment_avec_une_parcimonie_graduee(self):
        """Toutes tirent, mais pas au meme rythme : l'ordre fait le caractere."""
        ordre = ("artificier", "equilibre", "batisseur", "conquerant")
        for doctrine in ordre:
            with self.subTest(doctrine=doctrine):
                self.assertTrue(regles.AI_DOCTRINE_SETTINGS[doctrine]["fires_missiles"])
                self.assertGreaterEqual(
                    regles.AI_DOCTRINE_SETTINGS[doctrine]["war_chest"],
                    regles.MISSILE_COST,
                )
        for plus_prompt, plus_avare in zip(ordre, ordre[1:]):
            with self.subTest(paire=(plus_prompt, plus_avare)):
                prompt = regles.AI_DOCTRINE_SETTINGS[plus_prompt]
                avare = regles.AI_DOCTRINE_SETTINGS[plus_avare]
                self.assertLessEqual(
                    prompt["missile_denominator"], avare["missile_denominator"],
                )
                self.assertLessEqual(
                    prompt["missile_cooldown_turns"], avare["missile_cooldown_turns"],
                )
                self.assertLessEqual(
                    prompt["missile_min_target_regiments"],
                    avare["missile_min_target_regiments"],
                )

    def test_l_artificier_tire_plus_souvent_que_l_equilibre(self):
        artificier = regles.AI_DOCTRINE_SETTINGS["artificier"]
        equilibre = regles.AI_DOCTRINE_SETTINGS["equilibre"]
        self.assertLess(artificier["missile_denominator"], equilibre["missile_denominator"])
        self.assertLess(artificier["missile_cooldown_turns"], equilibre["missile_cooldown_turns"])
        self.assertLess(
            artificier["missile_min_target_regiments"],
            equilibre["missile_min_target_regiments"],
        )
        self.assertGreater(artificier["war_chest"], equilibre["war_chest"])

    def test_le_batisseur_garde_lui_aussi_de_quoi_tirer(self):
        # J2 est batisseur (cf. AI_DOCTRINES_ORDER) : le plus savant, donc le
        # premier arme — il met de cote le prix d'un tir, pas davantage.
        self.assertEqual(regles.get_ai_doctrine(None, 2), "batisseur")
        state = build_state(
            owners=(2, 1), regiments=(5, 5), ia_players=(2,),
            money=10 * regles.MERCENARY_COST,
        )
        state.player_science[2] = regles.SCIENCE_MISSILE_TOTAL_THRESHOLD
        self.assertEqual(regles.get_ai_war_chest_target(state, 2), regles.MISSILE_COST)

    def test_le_batisseur_tire_desormais(self):
        state = build_state(
            owners=(2, 1), regiments=(5, 20), ia_players=(2,),
            money=10 * regles.MISSILE_COST,
        )
        state.current_player = 2
        state.player_science[2] = regles.SCIENCE_MISSILE_TOTAL_THRESHOLD
        cible = ia.find_ai_missile_target(
            state, LARGEUR_CELLULE, HAUTEUR_CELLULE, TirageForce(),
        )
        self.assertIsNotNone(cible)
        self.assertEqual(cible.id, 1)

    def test_le_conquerant_laisse_passer_une_garnison_modeste(self):
        """Garnison de 6 : le batisseur tire, le conquerant garde ses ecus."""
        self.assertEqual(regles.get_ai_doctrine(None, 3), "conquerant")
        for tireur, attendu in ((2, True), (3, False)):
            with self.subTest(tireur=tireur):
                state = build_state(
                    owners=(tireur, 1), regiments=(5, 6), ia_players=(tireur,),
                    money=10 * regles.MISSILE_COST,
                )
                state.current_player = tireur
                state.player_science[tireur] = regles.SCIENCE_MISSILE_TOTAL_THRESHOLD
                cible = ia.find_ai_missile_target(
                    state, LARGEUR_CELLULE, HAUTEUR_CELLULE, TirageForce(),
                )
                self.assertEqual(cible is not None, attendu)

    def test_deux_doctrines_ne_depensent_pas_le_meme_argent(self):
        """Meme empire, meme caisse : le batisseur batit, le conquerant arme."""
        self.assertEqual(regles.get_ai_doctrine(None, 2), "batisseur")
        self.assertEqual(regles.get_ai_doctrine(None, 3), "conquerant")
        owners = (2,) * 12 + (3,) * 12
        state = build_state(
            owners=owners, regiments=(1,) * 24, ia_players=(2, 3), money=3000,
        )
        for joueur in (2, 3):
            regles.execute_ai_economic_actions(state, joueur, random.Random(4))

        def bilan(joueur):
            possede = [t for t in state.territories if t.owner == joueur]
            batiments = sum(
                1 for t in possede if t.id in state.fortress_territory_ids
            ) + sum(
                1 for t in possede if t.id in state.university_territory_ids
            ) + sum(
                regles.get_cultural_center_count(state, t.id) for t in possede
            )
            return batiments, sum(t.regiments for t in possede)

        batiments_batisseur, regiments_batisseur = bilan(2)
        batiments_conquerant, regiments_conquerant = bilan(3)
        self.assertGreater(batiments_batisseur, batiments_conquerant)
        self.assertGreater(regiments_conquerant, regiments_batisseur)

    def test_l_artificier_tire_la_ou_l_equilibre_renonce(self):
        """Garnison de 4 : sous le seuil de l'equilibre, au-dessus du sien."""
        # J1 est artificier, J0 equilibre (cf. AI_DOCTRINES_ORDER).
        self.assertEqual(regles.get_ai_doctrine(None, 1), "artificier")
        self.assertEqual(regles.get_ai_doctrine(None, 0), "equilibre")
        for tireur, attendu in ((1, True), (0, False)):
            with self.subTest(tireur=tireur):
                owners = (tireur, 3)
                state = build_state(
                    owners=owners, regiments=(5, 4),
                    ia_players=(tireur,), money=regles.MISSILE_COST,
                )
                state.current_player = tireur
                state.player_science[tireur] = regles.SCIENCE_MISSILE_THRESHOLD
                cible = ia.find_ai_missile_target(
                    state, LARGEUR_CELLULE, HAUTEUR_CELLULE, TirageForce(),
                )
                self.assertEqual(cible is not None, attendu)


class TestEpargneDirigee(unittest.TestCase):
    """L'IA ne rase plus la caisse quand un missile est a sa portee."""

    def build(self, science, humains=True):
        owners = (0, 1) if humains else (0, 2)
        state = build_state(
            owners=owners, regiments=(5, 5),
            ia_players=(0,) if humains else (0, 2),
            money=10 * regles.MERCENARY_COST,
        )
        state.player_science[0] = science
        return state

    def test_sans_la_science_l_ia_arme_tout(self):
        state = self.build(science=0)
        self.assertEqual(regles.get_ai_war_chest_target(state, 0), 0)

    def test_avec_la_science_l_ia_garde_de_quoi_tirer(self):
        state = self.build(science=regles.SCIENCE_MISSILE_THRESHOLD)
        self.assertEqual(
            regles.get_ai_war_chest_target(state, 0),
            regles.AI_SPECIAL_OPERATIONS_RESERVE,
        )

    def test_sans_humain_le_magot_n_a_pas_de_raison_d_etre(self):
        state = self.build(science=regles.SCIENCE_MISSILE_THRESHOLD, humains=False)
        self.assertEqual(regles.get_ai_war_chest_target(state, 0), 0)

    def test_les_mercenaires_s_arretent_au_magot(self):
        state = self.build(science=regles.SCIENCE_MISSILE_THRESHOLD)
        owned = [terr for terr in state.territories if terr.owner == 0]
        action = regles.find_regular_ai_mercenary_purchase(state, 0, owned, random.Random(1))
        self.assertIsNotNone(action)
        attendu = (
            state.player_money[0] - regles.AI_SPECIAL_OPERATIONS_RESERVE
        ) // regles.MERCENARY_COST * regles.MERCENARY_COST
        self.assertEqual(action[0], attendu)

    def test_le_magot_couvre_bien_un_missile(self):
        """La reserve et le prix du tir ne doivent pas diverger."""
        self.assertGreaterEqual(regles.AI_SPECIAL_OPERATIONS_RESERVE, achats.MISSILE_COST)


if __name__ == "__main__":
    unittest.main()
