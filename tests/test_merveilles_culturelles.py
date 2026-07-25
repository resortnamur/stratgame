"""Nouvelles regles de juillet 2026 : expansion culturelle limitee a un
territoire au hasard par palier, et merveilles culturelles (Rempart d'Ivoire,
Fontaine de Cresus, Capitole d'Aurelia, Forge de Dedale).

Ces tests chargent une sauvegarde reelle puis manipulent l'etat directement.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import achats
from moteur import regles

RACINE = Path(__file__).resolve().parents[1]
SAVES_DIR = RACINE / "parties_en_cours"


def iter_etats():
    fichiers = sorted(SAVES_DIR.glob("*.json"))
    if not fichiers:
        raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
    for fichier in fichiers:
        with open(fichier, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        state = GameState.from_payload(payload)
        regles.sanitize_after_load(state)
        yield state


def charger_premier_etat():
    return next(iter_etats())


def joueurs_actifs(state):
    return [
        joueur for joueur in regles.get_active_players(state)
        if not regles.is_onu_player(state, joueur)
    ]


def territoire_du_joueur(state, joueur):
    for terr in state.territories:
        if terr.owner == joueur:
            return terr
    return None


class TestExpansionCulturelle(unittest.TestCase):
    """Un palier culturel n'annexe plus qu'UN territoire voisin au hasard."""

    def test_un_seul_territoire_annexe_par_palier(self):
        state = charger_premier_etat()
        rng = random.Random(20260725)
        joueur = next(
            (
                j for j in joueurs_actifs(state)
                if len(regles.get_culture_expansion_target_ids(state, j)) >= 2
            ),
            None,
        )
        if joueur is None:
            self.skipTest("Aucun joueur avec au moins deux cibles d'expansion.")

        # Consomme les paliers deja franchis, puis pousse la culture juste
        # au-dessus du palier suivant (centres d'age 1 : petits increments).
        culture = regles.calculate_player_culture(state, joueur)
        state.culture_expansion_milestones[joueur] = culture // 50 * 50
        palier_avant = state.culture_expansion_milestones[joueur]
        terr = territoire_du_joueur(state, joueur)
        for _ in range(1000):
            if regles.calculate_player_culture(state, joueur) >= palier_avant + 50:
                break
            state.cultural_center_ages.setdefault(terr.id, []).append(1)

        possessions_avant = {t.id for t in state.territories if t.owner == joueur}
        cibles_avant = regles.get_culture_expansion_target_ids(state, joueur)
        self.assertGreaterEqual(len(cibles_avant), 2)

        notes, _ = regles.trigger_culture_expansions_if_due(state, joueur, rng)
        self.assertTrue(notes, "Le palier aurait du declencher une expansion.")

        possessions_apres = {t.id for t in state.territories if t.owner == joueur}
        annexes = possessions_apres - possessions_avant
        paliers_consommes = (
            state.culture_expansion_milestones[joueur] - palier_avant
        ) // 50
        # Ancienne regle : toutes les cibles (>= 2) annexees d'un coup.
        # Nouvelle regle : exactement un territoire par palier consomme.
        self.assertEqual(len(annexes), paliers_consommes)
        self.assertGreaterEqual(len(annexes), 1)
        self.assertIn(next(iter(annexes)) if len(annexes) == 1 else min(annexes),
                      possessions_apres)

    def test_annexion_aleatoire_parmi_les_cibles(self):
        state = charger_premier_etat()
        joueur = next(
            (
                j for j in joueurs_actifs(state)
                if len(regles.get_culture_expansion_target_ids(state, j)) >= 2
            ),
            None,
        )
        if joueur is None:
            self.skipTest("Aucun joueur avec au moins deux cibles d'expansion.")
        cibles = sorted(regles.get_culture_expansion_target_ids(state, joueur))
        choix = {random.Random(graine).choice(cibles) for graine in range(24)}
        self.assertGreater(len(choix), 1, "Le tirage doit varier selon le hasard.")


class TestRempartIvoire(unittest.TestCase):
    """Le territoire du Rempart d'Ivoire est intouchable pour les IA."""

    def trouver_attaque_valide(self, state, attaquant_ia):
        for src in state.territories:
            if src.owner < 0 or src.regiments < 2:
                continue
            if regles.is_ai_player(state, src.owner) != attaquant_ia:
                continue
            if regles.is_onu_player(state, src.owner):
                continue
            state.current_player = src.owner
            for voisin in src.neighbors:
                dst = state.territories[voisin]
                if regles.can_attack_specific_target(state, src, dst):
                    return src, dst
        return None, None

    def test_attaque_ia_bloquee(self):
        state = charger_premier_etat()
        src, dst = self.trouver_attaque_valide(state, attaquant_ia=True)
        if src is None:
            self.skipTest("Aucune attaque IA valide dans cette sauvegarde.")
        state.wonder_territories["ivory_rampart"] = dst.id
        self.assertFalse(regles.can_attack_specific_target(state, src, dst))
        resultat = regles.resolve_attack_once(state, src, dst)
        self.assertFalse(resultat.conquered)
        self.assertEqual(resultat.att_text, "attaque interdite")
        del state.wonder_territories["ivory_rampart"]
        self.assertTrue(regles.can_attack_specific_target(state, src, dst))

    def test_attaque_humaine_autorisee(self):
        state = charger_premier_etat()
        src, dst = self.trouver_attaque_valide(state, attaquant_ia=False)
        if src is None:
            self.skipTest("Aucune attaque humaine valide dans cette sauvegarde.")
        state.wonder_territories["ivory_rampart"] = dst.id
        self.assertTrue(regles.can_attack_specific_target(state, src, dst))


class TestFontaineCresus(unittest.TestCase):
    """La Fontaine de Cresus quintuple l'argent du territoire."""

    def test_revenu_multiplie_par_cinq(self):
        state = charger_premier_etat()
        terr = next(
            (
                t for t in state.territories
                if t.owner >= 0 and not regles.is_onu_player(state, t.owner)
            ),
            None,
        )
        self.assertIsNotNone(terr)
        avant = regles.calculate_territory_income(state, terr)
        state.wonder_territories["croesus_fountain"] = terr.id
        apres = regles.calculate_territory_income(state, terr)
        self.assertEqual(apres, avant * 5)


class TestCapitoleAurelia(unittest.TestCase):
    """La capitale posee sur le Capitole d'Aurelia ouvre le statut de nation."""

    def test_voie_culturelle_vers_la_nation(self):
        state = joueur = None
        for etat in iter_etats():
            candidat = next(
                (
                    j for j in joueurs_actifs(etat)
                    if regles.get_active_regular_capital_id_for_player(etat, j) is not None
                ),
                None,
            )
            if candidat is not None:
                state, joueur = etat, candidat
                break
        if joueur is None:
            self.skipTest("Aucun joueur avec capitale reguliere active.")
        capitale = regles.get_active_regular_capital_id_for_player(state, joueur)

        state.wonder_territories["aurelia_capitol"] = capitale
        self.assertTrue(regles.player_qualifies_for_nation_via_capitol(state, joueur))
        composant = regles.find_player_nation_component(state, joueur)
        self.assertIsNotNone(composant)
        self.assertIn(capitale, composant)

        # La merveille ailleurs que sur la capitale n'ouvre rien.
        autre = next(
            t.id for t in state.territories
            if t.owner == joueur and t.id != capitale
        )
        state.wonder_territories["aurelia_capitol"] = autre
        self.assertFalse(regles.player_qualifies_for_nation_via_capitol(state, joueur))


class TestForgeDedale(unittest.TestCase):
    """La Forge de Dedale offre les ponts touchant son territoire."""

    def test_pont_offert_uniquement_depuis_la_forge(self):
        state = charger_premier_etat()
        joueur = joueurs_actifs(state)[0]
        state.current_player = joueur
        terr = territoire_du_joueur(state, joueur)
        state.wonder_territories["daedalus_forge"] = terr.id
        self.assertTrue(achats.pont_offert_par_la_forge(state, terr.id, terr.id + 1))
        self.assertTrue(achats.pont_offert_par_la_forge(state, 0, terr.id))
        hors_forge = [t.id for t in state.territories if t.id != terr.id][:2]
        self.assertFalse(
            achats.pont_offert_par_la_forge(state, hors_forge[0], hors_forge[1])
        )
        # Un autre joueur ne beneficie pas de la merveille d'autrui.
        autre_joueur = next(j for j in joueurs_actifs(state) if j != joueur)
        state.current_player = autre_joueur
        self.assertFalse(achats.pont_offert_par_la_forge(state, terr.id, 0))

    def test_pont_gratuit_et_sans_science(self):
        state = charger_premier_etat()
        cell_width = 1200.0 / state.cols
        cell_height = 620.0 / state.rows
        joueur = joueurs_actifs(state)[0]
        state.current_player = joueur
        state.player_science[joueur] = 0

        candidats = regles.get_valid_bridge_candidates(state, cell_width, cell_height)
        candidat = next(
            (
                (key, points) for key, points in candidats
                if state.territories[key[0]].owner == joueur
                or state.territories[key[1]].owner == joueur
            ),
            None,
        )
        if candidat is None:
            self.skipTest("Aucun pont geometriquement possible depuis ce joueur.")
        (terr_a, terr_b), _ = candidat
        extremite = (
            terr_a if state.territories[terr_a].owner == joueur else terr_b
        )

        # Sans la Forge : verrouille par la science.
        refus = achats.construire_pont(state, terr_a, terr_b, cell_width, cell_height)
        self.assertFalse(refus.ok)
        self.assertIn("verrouilles", refus.message)

        # Avec la Forge sur une extremite : gratuit, meme sans science.
        state.wonder_territories["daedalus_forge"] = extremite
        regles.ensure_player_economy(state, joueur)
        argent_avant = state.player_money[joueur]
        resultat = achats.construire_pont(state, terr_a, terr_b, cell_width, cell_height)
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(state.player_money[joueur], argent_avant)
        self.assertIn("gratuitement", resultat.message)

        # Destruction egalement offerte.
        argent_avant = state.player_money[joueur]
        destruction = achats.detruire_pont(state, terr_a, terr_b)
        self.assertTrue(destruction.ok, destruction.message)
        self.assertEqual(state.player_money[joueur], argent_avant)


class TestSeuilsMerveilles(unittest.TestCase):
    """Merveilles culturelles : 100 points de culture, exclusivite conservee."""

    def test_achat_refuse_sans_culture_puis_accepte(self):
        state = charger_premier_etat()
        joueur = joueurs_actifs(state)[0]
        state.current_player = joueur
        regles.ensure_player_economy(state, joueur)
        state.player_money[joueur] = 10_000
        terr = territoire_du_joueur(state, joueur)

        # Nettoie toute merveille deja posee sur ce territoire.
        state.wonder_territories = {
            kind: tid for kind, tid in state.wonder_territories.items()
            if tid != terr.id
        }
        state.cultural_center_ages[terr.id] = []

        if regles.calculate_player_culture(state, joueur) < regles.CULTURE_WONDER_THRESHOLD:
            refus = achats.construire_merveille(state, terr, "ivory_rampart")
            self.assertFalse(refus.ok)
            self.assertIn("Culture insuffisante", refus.message)

        for _ in range(1000):
            if (
                regles.calculate_player_culture(state, joueur)
                >= regles.CULTURE_WONDER_THRESHOLD
            ):
                break
            state.cultural_center_ages.setdefault(terr.id, []).append(1)

        resultat = achats.construire_merveille(state, terr, "ivory_rampart")
        self.assertTrue(resultat.ok, resultat.message)
        self.assertEqual(state.wonder_territories.get("ivory_rampart"), terr.id)

        # Exclusivite : pas de deuxieme merveille (culturelle ou non) ici.
        refus = achats.construire_merveille(state, terr, "croesus_fountain")
        self.assertFalse(refus.ok)
        self.assertIn("accueille deja une merveille", refus.message)

    def test_seuil_science_inchange_pour_les_classiques(self):
        state = charger_premier_etat()
        joueur = joueurs_actifs(state)[0]
        state.current_player = joueur
        regles.ensure_player_economy(state, joueur)
        state.player_money[joueur] = 10_000
        state.player_science[joueur] = 0
        terr = territoire_du_joueur(state, joueur)
        state.wonder_territories = {
            kind: tid for kind, tid in state.wonder_territories.items()
            if kind != "atlas_observatory" and tid != terr.id
        }
        refus = achats.construire_merveille(state, terr, "atlas_observatory")
        self.assertFalse(refus.ok)
        self.assertIn("Science insuffisante", refus.message)


if __name__ == "__main__":
    unittest.main()
