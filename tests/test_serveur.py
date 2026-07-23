"""Tests du serveur (etape 2a) : sessions de partie et couche FastAPI.

Deux niveaux, comme le code :
- ``SessionPartie`` / ``GestionnaireParties`` en direct (sans HTTP) :
  arbitrage des droits, enchainement des tours IA, sauvegarde aller-retour ;
- l'application FastAPI via son TestClient : REST du lobby et protocole
  WebSocket (rejoindre, agir, refus, diffusion, presence).

Lancement : ``python -m unittest tests.test_serveur -v`` depuis ``Jeux Strat``.
"""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from moteur import regles
from serveur.app import creer_app
from serveur.partie import GestionnaireParties, SessionPartie

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PARTIES = RACINE / "parties_en_cours"
DOSSIER_CARTES = RACINE / "cartes_sauvegardees"
RANDOM_SEED = 20260722


def premiere_sauvegarde() -> Path:
    fichiers = sorted(DOSSIER_PARTIES.glob("*.json"))
    if not fichiers:
        raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours.")
    return fichiers[0]


def sauvegarde_avec_humain_au_trait() -> Path:
    """Une sauvegarde ou c'est a un joueur humain de jouer, phase d'attaque."""
    for chemin in sorted(DOSSIER_PARTIES.glob("*.json")):
        session = SessionPartie.depuis_fichier("sonde", chemin, seed=RANDOM_SEED)
        state = session.state
        if (
            state.phase == "playing"
            and state.turn_phase == "attack"
            and not regles.is_ai_player(state, state.current_player)
        ):
            return chemin
    raise unittest.SkipTest("Aucune sauvegarde avec un humain au trait.")


class TestSessionPartie(unittest.TestCase):
    def test_chargement_et_resume(self):
        session = SessionPartie.depuis_fichier("p1", premiere_sauvegarde(), seed=RANDOM_SEED)
        resume = session.resume()
        self.assertEqual(resume["id"], "p1")
        self.assertEqual(len(resume["sieges"]), session.state.num_players)
        self.assertEqual(resume["phase"], "playing")

    def test_etat_reseau_sans_replay(self):
        session = SessionPartie.depuis_fichier("p1", premiere_sauvegarde(), seed=RANDOM_SEED)
        etat = session.etat_reseau()
        self.assertEqual(etat["replay_history"], [])
        self.assertEqual(etat["kind"], "game")
        # L'etat diffuse reste chargeable par le moteur (sans le replay).
        from moteur.etat import GameState
        GameState.from_payload(etat)

    def test_arbitrage_des_droits(self):
        chemin = sauvegarde_avec_humain_au_trait()
        session = SessionPartie.depuis_fichier("p1", chemin, seed=RANDOM_SEED)
        courant = session.state.current_player
        autre = next(
            joueur for joueur in range(session.state.num_players) if joueur != courant
        )
        refus = session.appliquer_action(autre, {"type": "terminer_attaque"})
        self.assertFalse(refus.ok)
        self.assertEqual(refus.code, "pas_votre_tour")

        joueur_ia = next(
            (j for j in range(session.state.num_players)
             if regles.is_ai_player(session.state, j)), None,
        )
        if joueur_ia is not None:
            session.state.current_player = joueur_ia
            refus = session.appliquer_action(joueur_ia, {"type": "terminer_attaque"})
            self.assertFalse(refus.ok)
            self.assertEqual(refus.code, "siege_ia")
            session.state.current_player = courant

        refus = session.appliquer_action(courant, {"type": "fin_de_tour"})
        self.assertFalse(refus.ok)
        self.assertEqual(refus.code, "phase_invalide")

    def test_tour_complet_et_tours_ia(self):
        chemin = sauvegarde_avec_humain_au_trait()
        session = SessionPartie.depuis_fichier("p1", chemin, seed=RANDOM_SEED)
        joueur = session.state.current_player

        resultat = session.appliquer_action(joueur, {"type": "terminer_attaque"})
        self.assertTrue(resultat.ok)
        self.assertEqual(resultat.outcome["next_phase"], "shopping")

        resultat = session.appliquer_action(joueur, {"type": "terminer_achats"})
        self.assertTrue(resultat.ok)

        resultat = session.appliquer_action(joueur, {"type": "fin_de_tour"})
        self.assertTrue(resultat.ok)
        # Les tours IA qui suivaient ont ete joues dans la foulee : soit la
        # partie est finie, soit c'est de nouveau a un humain de jouer.
        if resultat.winner is None:
            self.assertFalse(
                regles.is_ai_player(session.state, session.state.current_player)
            )
        for rapport in resultat.rapports_ia:
            self.assertFalse(rapport["skipped"])
        # Le resultat complet est serialisable tel quel pour le WebSocket.
        json.dumps(resultat.outcome)
        json.dumps(resultat.rapports_ia)

    def test_sauvegarde_aller_retour(self):
        session = SessionPartie.depuis_fichier("p1", premiere_sauvegarde(), seed=RANDOM_SEED)
        with tempfile.TemporaryDirectory() as dossier:
            cible = Path(dossier) / "partie_test.json"
            session.sauvegarder(cible)
            recharge = SessionPartie.depuis_fichier("p2", cible, seed=RANDOM_SEED)
            self.assertEqual(
                recharge.state.to_payload()["territories_state"],
                session.state.to_payload()["territories_state"],
            )

    def test_gestionnaire(self):
        gestionnaire = GestionnaireParties(DOSSIER_PARTIES, DOSSIER_CARTES)
        sauvegardes = gestionnaire.lister_sauvegardes()
        self.assertTrue(sauvegardes)
        self.assertIn("fichier", sauvegardes[0])
        session = gestionnaire.ouvrir(sauvegardes[0]["fichier"], seed=RANDOM_SEED)
        self.assertIn(session.id, gestionnaire.parties)
        with self.assertRaises(FileNotFoundError):
            gestionnaire.ouvrir("../x45.py")
        self.assertTrue(gestionnaire.fermer(session.id))

    def test_partie_neuve_depuis_une_carte(self):
        gestionnaire = GestionnaireParties(DOSSIER_PARTIES, DOSSIER_CARTES)
        cartes = gestionnaire.lister_cartes()
        self.assertTrue(cartes)
        self.assertNotIn("partie_001.json", {carte["fichier"] for carte in cartes})

        session = gestionnaire.creer(
            cartes[0]["fichier"], num_players=4, ai_player_count=2, seed=RANDOM_SEED,
        )
        state = session.state
        self.assertEqual(state.phase, "playing")
        self.assertEqual((state.current_player, state.turn), (0, 1))
        # 4 joueurs choisis + 1 cite commercante, tous actifs sur la carte.
        self.assertEqual(state.num_players, 5)
        self.assertEqual(len(regles.get_active_players(state)), 5)
        self.assertEqual(len(state.golden_territory_ids), 4)
        self.assertEqual(len(state.sanctuary_territory_ids), 3)
        # Chaque joueur ordinaire a sa capitale.
        self.assertEqual(sorted(state.player_capital_ids), [0, 1, 2, 3])
        # L'etat est serialisable et rechargeable.
        recharge = SessionPartie("p2", type(state).from_payload(state.to_payload()))
        self.assertEqual(recharge.state.num_players, 5)

        with self.assertRaises(ValueError):
            gestionnaire.creer(cartes[0]["fichier"], num_players=1, ai_player_count=0)


class TestApplicationWeb(unittest.TestCase):
    def setUp(self):
        self.app = creer_app(DOSSIER_PARTIES, DOSSIER_CARTES)
        self.client = TestClient(self.app)

    def ouvrir_partie(self, fichier: str) -> dict:
        reponse = self.client.post("/api/parties", json={"sauvegarde": fichier, "seed": RANDOM_SEED})
        self.assertEqual(reponse.status_code, 200)
        return reponse.json()

    def test_rest_lobby(self):
        reponse = self.client.get("/api/sauvegardes")
        self.assertEqual(reponse.status_code, 200)
        sauvegardes = reponse.json()["sauvegardes"]
        self.assertTrue(sauvegardes)

        resume = self.ouvrir_partie(sauvegardes[0]["fichier"])
        self.assertIn("id", resume)
        self.assertTrue(resume["sieges"])

        reponse = self.client.get("/api/parties")
        self.assertEqual(len(reponse.json()["parties"]), 1)

        reponse = self.client.get(f"/api/parties/{resume['id']}/etat")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["replay_history"], [])

        self.assertEqual(self.client.post(
            "/api/parties", json={"sauvegarde": "inexistante.json"},
        ).status_code, 404)
        self.assertEqual(self.client.get("/api/parties/absente/etat").status_code, 404)

    def test_rest_partie_neuve(self):
        reponse = self.client.get("/api/cartes")
        self.assertEqual(reponse.status_code, 200)
        cartes = reponse.json()["cartes"]
        self.assertTrue(cartes)

        reponse = self.client.post("/api/parties", json={
            "carte": cartes[0]["fichier"], "joueurs": 4, "ia": 2,
            "mode": "normal", "seed": RANDOM_SEED,
        })
        self.assertEqual(reponse.status_code, 200)
        resume = reponse.json()
        self.assertEqual(resume["tour"], 1)
        self.assertEqual(resume["num_players"], 5)
        self.assertEqual(resume["source"], None)

        # Parametres invalides et carte inconnue.
        self.assertEqual(self.client.post("/api/parties", json={
            "carte": cartes[0]["fichier"], "joueurs": 1,
        }).status_code, 422)
        self.assertEqual(self.client.post("/api/parties", json={
            "carte": "inconnue.json", "joueurs": 4,
        }).status_code, 404)

    def test_websocket_rejoindre_et_jouer(self):
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws:
            ws.send_json({"type": "rejoindre", "joueur": joueur})
            bienvenue = ws.receive_json()
            self.assertEqual(bienvenue["type"], "bienvenue")
            self.assertEqual(bienvenue["joueur"], joueur)
            self.assertEqual(bienvenue["etat"]["current_player"], joueur)

            presence = ws.receive_json()
            self.assertEqual(presence["type"], "presence")
            self.assertEqual(presence["sieges_occupes"], [joueur])

            ws.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
            resultat = ws.receive_json()
            self.assertEqual(resultat["type"], "resultat")
            self.assertEqual(resultat["joueur"], joueur)
            self.assertTrue(resultat["resultat"]["ok"])
            self.assertEqual(resultat["etat"]["phase"], "shopping")

            # Une action hors phase est refusee, pour l'emetteur seul.
            ws.send_json({"type": "action", "action": {"type": "fin_de_tour"}})
            refus = ws.receive_json()
            self.assertEqual(refus["type"], "refus")
            self.assertEqual(refus["code"], "phase_invalide")

    def test_websocket_spectateur_et_sieges(self):
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws1:
            ws1.send_json({"type": "rejoindre", "joueur": joueur})
            ws1.receive_json()  # bienvenue
            ws1.receive_json()  # presence

            with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws2:
                # Le siege est deja pris.
                ws2.send_json({"type": "rejoindre", "joueur": joueur})
                self.assertEqual(ws2.receive_json()["code"], "siege_indisponible")
                # Un siege IA est refuse aussi.
                siege_ia = next(
                    (s["joueur"] for s in resume["sieges"] if s["ia"]), None,
                )
                if siege_ia is not None:
                    ws2.send_json({"type": "rejoindre", "joueur": siege_ia})
                    self.assertEqual(ws2.receive_json()["code"], "siege_indisponible")
                # En spectateur : bienvenue sans siege, pas d'action possible.
                ws2.send_json({"type": "rejoindre"})
                bienvenue = ws2.receive_json()
                self.assertEqual(bienvenue["type"], "bienvenue")
                self.assertIsNone(bienvenue["joueur"])
                ws1.receive_json()  # presence diffusee a ws1
                ws2.receive_json()  # presence diffusee a ws2
                ws2.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
                self.assertEqual(ws2.receive_json()["code"], "spectateur")

                # Le spectateur voit les resultats du joueur actif.
                ws1.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
                self.assertEqual(ws1.receive_json()["type"], "resultat")
                self.assertEqual(ws2.receive_json()["type"], "resultat")

    def test_sauvegarde_via_api(self):
        with tempfile.TemporaryDirectory() as dossier:
            dossier_parties = Path(dossier)
            source = premiere_sauvegarde()
            copie = dossier_parties / source.name
            copie.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

            app = creer_app(dossier_parties)
            client = TestClient(app)
            resume = client.post(
                "/api/parties", json={"sauvegarde": source.name, "seed": RANDOM_SEED},
            ).json()
            reponse = client.post(
                f"/api/parties/{resume['id']}/sauvegarder",
                json={"fichier": "partie_serveur.json"},
            )
            self.assertEqual(reponse.status_code, 200)
            self.assertEqual(reponse.json()["fichier"], "partie_serveur.json")
            payload = json.loads((dossier_parties / "partie_serveur.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "game")
            # Un chemin qui sort du dossier est refuse.
            reponse = client.post(
                f"/api/parties/{resume['id']}/sauvegarder",
                json={"fichier": "../evasion.json"},
            )
            self.assertEqual(reponse.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
