"""Encart des evenements importants du client web (juillet 2026).

Le moteur file deja les evenements majeurs par joueur humain et les
transforme en "modales" au debut de son tour (major_event_modal +
major_event_modal_queue). Le client web les affiche desormais dans un
encart superpose a la carte ; le message WebSocket ``modale_lue`` les
consomme une par une, uniquement pour le joueur au trait.

Lancement : ``python -m unittest tests.test_encart_evenements -v`` depuis
"Jeux Strat".
"""

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import regles
from serveur.app import creer_app

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_serveur import sauvegarde_avec_humain_au_trait

RANDOM_SEED = 20260722


class TestEncartEvenements(unittest.TestCase):
    def setUp(self):
        chemin = sauvegarde_avec_humain_au_trait()
        self._temp = tempfile.TemporaryDirectory()
        dossier = Path(self._temp.name)
        (dossier / chemin.name).write_text(
            chemin.read_text(encoding="utf-8"), encoding="utf-8",
        )
        self.app = creer_app(
            dossier, fichier_joueurs=dossier / "joueurs.json",
            delai_tour_ia=0.0, delai_pas_ia=0.0, sauvegarde_auto=False,
        )
        self.client = TestClient(self.app)
        resume = self.client.post(
            "/api/parties", json={"sauvegarde": chemin.name, "seed": RANDOM_SEED},
        ).json()
        self.partie_id = resume["id"]
        self.joueur = resume["joueur_courant"]
        self.session = self.app.state.gestionnaire.parties[self.partie_id]

    def tearDown(self):
        self._temp.cleanup()

    def test_consommation_en_session(self):
        session = self.session
        regles.queue_major_event_modal(session.state, "Premier", ["a", "b"])
        regles.queue_major_event_modal(session.state, "Second", ["c"])
        self.assertEqual(session.state.major_event_modal["title"], "Premier")

        # Seul le joueur au trait consomme.
        ok, code = session.consommer_modale_evenements(self.joueur + 1)
        self.assertEqual((ok, code), (False, "pas_votre_tour"))
        ok, code = session.consommer_modale_evenements(None)
        self.assertEqual((ok, code), (False, "pas_votre_tour"))

        ok, _ = session.consommer_modale_evenements(self.joueur)
        self.assertTrue(ok)
        self.assertEqual(session.state.major_event_modal["title"], "Second")
        ok, _ = session.consommer_modale_evenements(self.joueur)
        self.assertTrue(ok)
        self.assertIsNone(session.state.major_event_modal)
        ok, code = session.consommer_modale_evenements(self.joueur)
        self.assertEqual((ok, code), (False, "aucune_modale"))

    def test_modale_lue_via_websocket(self):
        regles.queue_major_event_modal(self.session.state, "Premier", ["a"])
        regles.queue_major_event_modal(self.session.state, "Second", ["b"])
        alice = self.client.post("/api/joueurs", json={"nom": "Alice"}).json()

        with self.client.websocket_connect(f"/ws/parties/{self.partie_id}") as ws:
            ws.send_json({
                "type": "rejoindre", "jeton": alice["jeton"], "joueur": self.joueur,
            })
            bienvenue = ws.receive_json()
            self.assertEqual(bienvenue["type"], "bienvenue")
            # L'encart est deja dans l'etat diffuse a la connexion.
            self.assertEqual(bienvenue["etat"]["major_event_modal"]["title"], "Premier")
            ws.receive_json()  # presence

            ws.send_json({"type": "modale_lue"})
            suite = ws.receive_json()
            self.assertEqual(suite["type"], "modale_suivante")
            self.assertEqual(suite["etat"]["major_event_modal"]["title"], "Second")

            ws.send_json({"type": "modale_lue"})
            suite = ws.receive_json()
            self.assertEqual(suite["type"], "modale_suivante")
            self.assertIsNone(suite["etat"]["major_event_modal"])

            ws.send_json({"type": "modale_lue"})
            refus = ws.receive_json()
            self.assertEqual((refus["type"], refus["code"]), ("refus", "aucune_modale"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
