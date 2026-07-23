"""Tests du serveur (etapes 2a-2c) : sessions, lobby et couche FastAPI.

Trois niveaux, comme le code :
- ``RegistreJoueurs`` : identites persistantes (nom + jeton, fichier) ;
- ``SessionPartie`` / ``GestionnaireParties`` en direct (sans HTTP) :
  arbitrage des droits, reservation des sieges, tours IA, sauvegarde ;
- l'application FastAPI via son TestClient : REST du lobby et protocole
  WebSocket (rejoindre, reconnexion, chat, refus, diffusion, presence).

Lancement : ``python -m unittest tests.test_serveur -v`` depuis ``Jeux Strat``.
"""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from moteur import regles
from serveur.app import creer_app
from serveur.joueurs import RegistreJoueurs
from serveur.partie import GestionnaireParties, SessionPartie

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PARTIES = RACINE / "parties_en_cours"
DOSSIER_CARTES = RACINE / "cartes_sauvegardees"
RANDOM_SEED = 20260722


def sauvegardes_de_partie() -> list:
    """Les vraies sauvegardes du dossier (ignore tout autre .json)."""
    fichiers = []
    for chemin in sorted(DOSSIER_PARTIES.glob("*.json")):
        try:
            payload = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("kind") == "game":
            fichiers.append(chemin)
    return fichiers


def premiere_sauvegarde() -> Path:
    fichiers = sauvegardes_de_partie()
    if not fichiers:
        raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours.")
    return fichiers[0]


def sauvegarde_avec_humain_au_trait() -> Path:
    """Une sauvegarde ou c'est a un joueur humain de jouer, phase d'attaque."""
    for chemin in sauvegardes_de_partie():
        session = SessionPartie.depuis_fichier("sonde", chemin, seed=RANDOM_SEED)
        state = session.state
        if (
            state.phase == "playing"
            and state.turn_phase == "attack"
            and not regles.is_ai_player(state, state.current_player)
        ):
            return chemin
    raise unittest.SkipTest("Aucune sauvegarde avec un humain au trait.")


class TestRegistreJoueurs(unittest.TestCase):
    def test_inscription_et_persistance(self):
        with tempfile.TemporaryDirectory() as dossier:
            fichier = Path(dossier) / "joueurs.json"
            registre = RegistreJoueurs(fichier)
            alice = registre.inscrire("  Alice   Dupont ")
            self.assertEqual(alice["nom"], "Alice Dupont")
            self.assertEqual(registre.nom_par_jeton(alice["jeton"]), "Alice Dupont")
            # Unicite (insensible a la casse) et noms irrecevables.
            with self.assertRaises(ValueError):
                registre.inscrire("alice dupont")
            with self.assertRaises(ValueError):
                registre.inscrire("   ")
            with self.assertRaises(ValueError):
                registre.inscrire("x" * 40)
            with self.assertRaises(ValueError):
                registre.inscrire(None)
            # Persistance : un registre neuf relit le fichier.
            recharge = RegistreJoueurs(fichier)
            self.assertEqual(recharge.nom_par_jeton(alice["jeton"]), "Alice Dupont")
            with self.assertRaises(ValueError):
                recharge.inscrire("Alice Dupont")
            self.assertIsNone(recharge.nom_par_jeton("inexistant"))


class TestSessionPartie(unittest.TestCase):
    def test_reservation_de_sieges(self):
        session = SessionPartie.depuis_fichier("p1", premiere_sauvegarde(), seed=RANDOM_SEED)
        libres = session.sieges_humains_libres()
        self.assertTrue(libres)
        siege = libres[0]

        self.assertEqual(session.reserver_siege(siege, "jeton-a", "Alice"), (True, "ok"))
        # Re-reserver son siege est la reconnexion : accepte.
        self.assertEqual(session.reserver_siege(siege, "jeton-a", "Alice"), (True, "ok"))
        # Un siege pris, un siege inconnu, un deuxieme siege : refuses.
        self.assertEqual(
            session.reserver_siege(siege, "jeton-b", "Bob"), (False, "siege_indisponible"),
        )
        self.assertEqual(
            session.reserver_siege(999, "jeton-b", "Bob"), (False, "siege_indisponible"),
        )
        if len(libres) > 1:
            self.assertEqual(
                session.reserver_siege(libres[1], "jeton-a", "Alice"),
                (False, "deja_un_siege"),
            )

        self.assertEqual(session.siege_de("jeton-a"), siege)
        self.assertNotIn(siege, session.sieges_humains_libres())
        descriptif = next(s for s in session.sieges() if s["joueur"] == siege)
        self.assertEqual(descriptif["nom"], "Alice")

        self.assertEqual(session.liberer_siege("jeton-a"), siege)
        self.assertIsNone(session.liberer_siege("jeton-a"))
        self.assertIn(siege, session.sieges_humains_libres())

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
        # Les tours IA se jouent maintenant un par un (la couche web les
        # diffuse avec une cadence) : on les enchaine jusqu'au prochain
        # humain ou a la victoire.
        vainqueur = resultat.winner
        rapports = []
        while vainqueur is None and session.tour_ia_en_attente():
            suite = session.jouer_un_tour_ia()
            self.assertTrue(suite.ok)
            self.assertIsNotNone(suite.joueur_ia)
            rapports.extend(suite.rapports_ia)
            vainqueur = suite.winner
        if vainqueur is None:
            self.assertFalse(
                regles.is_ai_player(session.state, session.state.current_player)
            )
        for rapport in rapports:
            self.assertFalse(rapport["skipped"])
        self.assertEqual(session.jouer_un_tour_ia().code, "rien_a_jouer")
        # Le resultat complet est serialisable tel quel pour le WebSocket.
        json.dumps(resultat.outcome)
        json.dumps(rapports)

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
        # Le registre des joueurs ecrit un fichier : il va dans un dossier
        # temporaire pour ne pas polluer parties_en_cours.
        self._dossier_temp = tempfile.TemporaryDirectory()
        self.app = creer_app(
            DOSSIER_PARTIES, DOSSIER_CARTES,
            fichier_joueurs=Path(self._dossier_temp.name) / "joueurs.json",
            delai_tour_ia=0.0,  # pas de cadence dans les tests
            delai_pas_ia=0.0,
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self._dossier_temp.cleanup()

    def ouvrir_partie(self, fichier: str) -> dict:
        reponse = self.client.post("/api/parties", json={"sauvegarde": fichier, "seed": RANDOM_SEED})
        self.assertEqual(reponse.status_code, 200)
        return reponse.json()

    def inscrire(self, nom: str) -> dict:
        reponse = self.client.post("/api/joueurs", json={"nom": nom})
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

    def test_rest_inscription(self):
        alice = self.inscrire("Alice")
        self.assertIn("jeton", alice)
        self.assertEqual(alice["nom"], "Alice")
        # Nom deja pris (insensible a la casse) et noms irrecevables.
        self.assertEqual(
            self.client.post("/api/joueurs", json={"nom": "alice"}).status_code, 409,
        )
        self.assertEqual(
            self.client.post("/api/joueurs", json={"nom": "   "}).status_code, 422,
        )
        self.assertEqual(self.client.post("/api/joueurs", json={}).status_code, 422)

    def test_websocket_rejoindre_et_jouer(self):
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]
        alice = self.inscrire("Alice")

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws:
            ws.send_json({"type": "rejoindre", "jeton": alice["jeton"], "joueur": joueur})
            bienvenue = ws.receive_json()
            self.assertEqual(bienvenue["type"], "bienvenue")
            self.assertEqual(bienvenue["joueur"], joueur)
            self.assertEqual(bienvenue["nom"], "Alice")
            self.assertEqual(bienvenue["etat"]["current_player"], joueur)

            presence = ws.receive_json()
            self.assertEqual(presence["type"], "presence")
            siege = next(s for s in presence["sieges"] if s["joueur"] == joueur)
            self.assertEqual(siege["nom"], "Alice")
            self.assertTrue(siege["connecte"])
            self.assertEqual(presence["spectateurs"], [])

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
        alice = self.inscrire("Alice")
        bob = self.inscrire("Bob")

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws1:
            ws1.send_json({"type": "rejoindre", "jeton": alice["jeton"], "joueur": joueur})
            ws1.receive_json()  # bienvenue
            ws1.receive_json()  # presence

            with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws2:
                # Un siege sans identite, un jeton inconnu : refuses.
                ws2.send_json({"type": "rejoindre", "joueur": joueur})
                self.assertEqual(ws2.receive_json()["code"], "identite_requise")
                ws2.send_json({"type": "rejoindre", "jeton": "faux", "joueur": joueur})
                self.assertEqual(ws2.receive_json()["code"], "jeton_inconnu")
                # Le siege est deja reserve par Alice.
                ws2.send_json({"type": "rejoindre", "jeton": bob["jeton"], "joueur": joueur})
                self.assertEqual(ws2.receive_json()["code"], "siege_indisponible")
                # Un siege IA est refuse aussi.
                siege_ia = next(
                    (s["joueur"] for s in resume["sieges"] if s["ia"]), None,
                )
                if siege_ia is not None:
                    ws2.send_json({"type": "rejoindre", "jeton": bob["jeton"],
                                   "joueur": siege_ia})
                    self.assertEqual(ws2.receive_json()["code"], "siege_indisponible")
                # En spectateur anonyme : bienvenue sans siege ni nom, pas
                # d'action ni de chat possibles.
                ws2.send_json({"type": "rejoindre"})
                bienvenue = ws2.receive_json()
                self.assertEqual(bienvenue["type"], "bienvenue")
                self.assertIsNone(bienvenue["joueur"])
                self.assertIsNone(bienvenue["nom"])
                ws1.receive_json()  # presence diffusee a ws1
                presence = ws2.receive_json()  # presence diffusee a ws2
                self.assertEqual(presence["spectateurs"], [None])
                ws2.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
                self.assertEqual(ws2.receive_json()["code"], "spectateur")
                ws2.send_json({"type": "chat", "texte": "coucou"})
                self.assertEqual(ws2.receive_json()["code"], "identite_requise")

                # Le spectateur voit les resultats du joueur actif.
                ws1.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
                self.assertEqual(ws1.receive_json()["type"], "resultat")
                self.assertEqual(ws2.receive_json()["type"], "resultat")

    def test_client_statique(self):
        reponse = self.client.get("/")
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("text/html", reponse.headers["content-type"])
        self.assertIn("Jeux Strat", reponse.text)
        self.assertEqual(self.client.get("/app.js").status_code, 200)
        self.assertEqual(self.client.get("/style.css").status_code, 200)
        # Les routes API passent avant le statique.
        self.assertEqual(self.client.get("/api/cartes").status_code, 200)

    def test_websocket_prendre_siege(self):
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]
        alice = self.inscrire("Alice")

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws:
            # Alice entre en spectatrice identifiee puis s'assoit.
            ws.send_json({"type": "rejoindre", "jeton": alice["jeton"]})
            self.assertIsNone(ws.receive_json()["joueur"])  # bienvenue
            ws.receive_json()  # presence
            ws.send_json({"type": "prendre_siege", "joueur": joueur})
            pris = ws.receive_json()
            self.assertEqual((pris["type"], pris["joueur"]), ("siege_pris", joueur))
            presence = ws.receive_json()
            siege = next(s for s in presence["sieges"] if s["joueur"] == joueur)
            self.assertEqual((siege["nom"], siege["connecte"]), ("Alice", True))
            # Un deuxieme siege est refuse (une identite, un siege).
            autre = next(
                (s["joueur"] for s in presence["sieges"]
                 if not s["ia"] and s["actif"] and s["joueur"] != joueur), None,
            )
            if autre is not None:
                ws.send_json({"type": "prendre_siege", "joueur": autre})
                self.assertEqual(ws.receive_json()["code"], "deja_un_siege")
            # Assise, elle peut agir.
            ws.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
            self.assertEqual(ws.receive_json()["type"], "resultat")

    def test_websocket_tours_ia_diffuses_un_par_un(self):
        """Les tours IA arrivent en messages separes (un etat par tour)."""
        cartes = self.client.get("/api/cartes").json()["cartes"]
        resume = self.client.post("/api/parties", json={
            "carte": cartes[0]["fichier"], "joueurs": 2, "ia": 1,
            "seed": RANDOM_SEED,
        }).json()
        alice = self.inscrire("Alice")
        siege_humain = next(
            s["joueur"] for s in resume["sieges"] if not s["ia"] and s["actif"]
        )
        courant_est_ia = next(
            s["ia"] for s in resume["sieges"] if s["joueur"] == resume["joueur_courant"]
        )

        with self.client.websocket_connect(f"/ws/parties/{resume['id']}") as ws:
            ws.send_json({"type": "rejoindre", "jeton": alice["jeton"]})
            ws.receive_json()  # bienvenue
            ws.receive_json()  # presence

            def prochain_resultat(passes_vues):
                """Consomme les pas_ia (en les comptant) jusqu'au resultat."""
                while True:
                    message = ws.receive_json()
                    if message["type"] == "pas_ia":
                        self.assertIn("result", message["pas"])
                        self.assertTrue(message["pas"]["territoires"])
                        passes_vues.append(message["pas"])
                        continue
                    self.assertEqual(message["type"], "resultat")
                    return message

            if courant_est_ia:
                # L'arrivee du premier client deroule les IA jusqu'a l'humain,
                # chaque passe d'attaque diffusee avant le rapport du tour.
                passes = []
                message = prochain_resultat(passes)
                self.assertIsNone(message["action"])
                rapport = message["resultat"]["rapports_ia"][0]
                self.assertEqual(len(passes), rapport["attack_passes"])
                self.assertEqual(message["etat"]["current_player"], siege_humain)

            ws.send_json({"type": "prendre_siege", "joueur": siege_humain})
            ws.receive_json()  # siege_pris
            ws.receive_json()  # presence
            for action in ("terminer_attaque", "terminer_achats", "fin_de_tour"):
                ws.send_json({"type": "action", "action": {"type": action}})
                self.assertEqual(ws.receive_json()["type"], "resultat")

            # Apres la fin de tour : l'IA et la cite commercante jouent,
            # chacune dans son propre message, jusqu'au retour a l'humain.
            joueurs_vus = []
            while True:
                passes = []
                message = prochain_resultat(passes)
                self.assertIsNone(message["action"])
                rapport = message["resultat"]["rapports_ia"][0]
                self.assertEqual(len(passes), rapport["attack_passes"])
                joueurs_vus.append(message["joueur"])
                if message["etat"]["current_player"] == siege_humain:
                    break
            self.assertEqual(len(joueurs_vus), 2)
            self.assertEqual(len(set(joueurs_vus)), 2)

    def test_websocket_erreur_moteur(self):
        """Une exception pendant une action devient un refus, pas un silence."""
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]
        alice = self.inscrire("Alice")

        session = self.app.state.gestionnaire.parties[partie_id]
        def explose(*args, **kwargs):
            raise RuntimeError("panne simulee")
        session.appliquer_action = explose

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws:
            ws.send_json({"type": "rejoindre", "jeton": alice["jeton"], "joueur": joueur})
            ws.receive_json()  # bienvenue
            ws.receive_json()  # presence
            ws.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
            self.assertEqual(ws.receive_json()["code"], "erreur_serveur")
            # La connexion reste utilisable apres l'erreur.
            ws.send_json({"type": "chat", "texte": "toujours la"})
            self.assertEqual(ws.receive_json()["type"], "chat")

    def test_websocket_reconnexion(self):
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]
        alice = self.inscrire("Alice")
        bob = self.inscrire("Bob")

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws:
            ws.send_json({"type": "rejoindre", "jeton": alice["jeton"], "joueur": joueur})
            ws.receive_json()  # bienvenue
            ws.receive_json()  # presence

        # Alice est deconnectee : son siege lui reste reserve.
        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws_bob:
            ws_bob.send_json({"type": "rejoindre", "jeton": bob["jeton"], "joueur": joueur})
            self.assertEqual(ws_bob.receive_json()["code"], "siege_indisponible")

        # Elle revient avec son seul jeton et retrouve son siege.
        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws:
            ws.send_json({"type": "rejoindre", "jeton": alice["jeton"]})
            bienvenue = ws.receive_json()
            self.assertEqual(bienvenue["type"], "bienvenue")
            self.assertEqual(bienvenue["joueur"], joueur)
            presence = ws.receive_json()
            siege = next(s for s in presence["sieges"] if s["joueur"] == joueur)
            self.assertEqual((siege["nom"], siege["connecte"]), ("Alice", True))

    def test_websocket_remplacement_de_connexion(self):
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]
        alice = self.inscrire("Alice")

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws1:
            ws1.send_json({"type": "rejoindre", "jeton": alice["jeton"], "joueur": joueur})
            ws1.receive_json()  # bienvenue
            ws1.receive_json()  # presence

            # La meme identite se connecte ailleurs : elle garde son siege,
            # l'ancienne connexion est fermee par le serveur.
            with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws2:
                ws2.send_json({"type": "rejoindre", "jeton": alice["jeton"]})
                bienvenue = ws2.receive_json()
                self.assertEqual(bienvenue["joueur"], joueur)
                with self.assertRaises(Exception):
                    ws1.receive_json()

    def test_websocket_chat_et_quitter_siege(self):
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.ouvrir_partie(chemin.name)
        partie_id = resume["id"]
        joueur = resume["joueur_courant"]
        alice = self.inscrire("Alice")
        bob = self.inscrire("Bob")

        with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws1:
            ws1.send_json({"type": "rejoindre", "jeton": alice["jeton"], "joueur": joueur})
            ws1.receive_json()  # bienvenue
            ws1.receive_json()  # presence

            with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws2:
                ws2.send_json({"type": "rejoindre", "jeton": bob["jeton"]})
                bienvenue = ws2.receive_json()
                self.assertIsNone(bienvenue["joueur"])
                self.assertEqual(bienvenue["nom"], "Bob")
                ws1.receive_json()  # presence
                presence = ws2.receive_json()
                self.assertEqual(presence["spectateurs"], ["Bob"])

                # Le chat est diffuse a tous, spectateur identifie compris.
                ws2.send_json({"type": "chat", "texte": "  Salut !  "})
                for ws in (ws1, ws2):
                    chat = ws.receive_json()
                    self.assertEqual(chat["type"], "chat")
                    self.assertEqual(chat["nom"], "Bob")
                    self.assertIsNone(chat["joueur"])
                    self.assertEqual(chat["texte"], "Salut !")
                ws1.send_json({"type": "chat", "texte": "Bienvenue"})
                for ws in (ws1, ws2):
                    chat = ws.receive_json()
                    self.assertEqual((chat["nom"], chat["joueur"]), ("Alice", joueur))

                # Alice libere son siege : Bob peut le prendre... apres
                # avoir quitte son role de spectateur (une seule connexion).
                ws1.send_json({"type": "quitter_siege"})
                self.assertEqual(ws1.receive_json()["type"], "siege_quitte")
                presence = ws1.receive_json()
                siege = next(s for s in presence["sieges"] if s["joueur"] == joueur)
                self.assertEqual((siege["nom"], siege["connecte"]), (None, False))
                ws2.receive_json()  # meme presence pour Bob
                ws1.send_json({"type": "quitter_siege"})
                self.assertEqual(ws1.receive_json()["code"], "aucun_siege")

            # Bob revient et reserve le siege libere.
            with self.client.websocket_connect(f"/ws/parties/{partie_id}") as ws3:
                ws3.send_json({"type": "rejoindre", "jeton": bob["jeton"], "joueur": joueur})
                bienvenue = ws3.receive_json()
                self.assertEqual((bienvenue["joueur"], bienvenue["nom"]), (joueur, "Bob"))

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
