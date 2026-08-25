"""La question "annexer ou soumettre ?" posee a une nation (bug telephone).

Symptome : sur telephone, une attaque menee par une nation figeait la partie
apres le clic sur « OK ». Deux causes, corrigees ensemble.

1. Le verrou de la partie est tenu pendant toute l'action, question comprise
   (jusqu'a ``DELAI_DECISION_S``). ``etat_reseau()`` le prend, et il etait
   appele a meme la boucle asyncio : la moindre arrivee pendant la question
   bloquait la boucle *entiere* — plus un message lu, donc plus de reponse
   possible ni de coupure detectee. La partie se figeait pour tout le monde
   jusqu'au delai de garde.
2. La question etait attachee a la connexion. La boite de dialogue native du
   navigateur met la page en veille sur telephone : le socket mourait pendant
   que le joueur lisait, sa reponse partait dans le vide, et rien ne lui
   reposait la question a la reconnexion.

Les deux tests tournent contre un **vrai serveur uvicorn** : le ``TestClient``
de Starlette monte une boucle asyncio par WebSocket, ce qui masque justement
le blocage de boucle qu'on veut prouver ici.

Lancement : ``python -m unittest tests.test_soumission_nation -v``.
"""

import asyncio
import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

import uvicorn
import websockets

from serveur.app import creer_app

from tests.test_serveur import (
    DOSSIER_CARTES, DOSSIER_PARTIES, RANDOM_SEED, sauvegarde_avec_humain_au_trait,
)

# Une reponse attendue plus longtemps que ca, c'est le gel : le delai de
# garde du serveur, lui, est a deux minutes.
DELAI_REPONSE_S = 20


def paire_attaquable(state, joueur):
    """(source a moi, cible ennemie voisine) : de quoi declencher une conquete."""
    for terr in state.territories:
        if terr.owner != joueur or terr.regiments < 2:
            continue
        for voisin in terr.neighbors:
            cible = state.territories[voisin]
            if cible.owner is not None and cible.owner != joueur:
                return terr.id, voisin
    return None


class TestQuestionSoumission(unittest.TestCase):
    """Un serveur uvicorn par test : une seule boucle, comme en production."""

    def setUp(self):
        self._dossier_temp = tempfile.TemporaryDirectory()
        self.app = creer_app(
            DOSSIER_PARTIES, DOSSIER_CARTES,
            fichier_joueurs=Path(self._dossier_temp.name) / "joueurs.json",
            delai_tour_ia=0.0, delai_pas_ia=0.0, sauvegarde_auto=False,
        )
        config = uvicorn.Config(self.app, host="127.0.0.1", port=0, log_level="error")
        self._serveur = uvicorn.Server(config)
        self._fil = threading.Thread(target=self._serveur.run, daemon=True)
        self._fil.start()
        limite = time.monotonic() + 15
        while not self._serveur.started and time.monotonic() < limite:
            time.sleep(0.02)
        if not self._serveur.started:
            raise unittest.SkipTest("Le serveur uvicorn n'a pas demarre.")
        self.port = self._serveur.servers[0].sockets[0].getsockname()[1]

    def tearDown(self):
        self._serveur.should_exit = True
        self._fil.join(timeout=10)
        self._dossier_temp.cleanup()

    # ------------------------------------------------------------------
    # Outillage
    # ------------------------------------------------------------------

    def poster(self, route, corps):
        requete = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{route}", data=json.dumps(corps).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(requete) as reponse:
            return json.load(reponse)

    def preparer_partie(self):
        """Ouvre une partie, fait du joueur au trait une nation, rend la paire."""
        chemin = sauvegarde_avec_humain_au_trait()
        resume = self.poster(
            "/api/parties", {"sauvegarde": chemin.name, "seed": RANDOM_SEED},
        )
        session = self.app.state.gestionnaire.parties[resume["id"]]
        joueur = session.state.current_player
        # Statut de nation : c'est lui qui declenche la question.
        session.state.nation_players.add(joueur)
        paire = paire_attaquable(session.state, joueur)
        if paire is None:
            raise unittest.SkipTest("Aucune attaque possible dans cette sauvegarde.")
        jeton = self.poster("/api/joueurs", {"nom": "Alice"})["jeton"]
        url = f"ws://127.0.0.1:{self.port}/ws/parties/{resume['id']}"
        return url, session, joueur, paire, jeton

    async def lire(self, ws, attendu):
        """Le prochain message du type attendu (presence et accueil au passage)."""
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), DELAI_REPONSE_S))
            if message["type"] == attendu:
                return message
            self.assertIn(message["type"], ("presence", "bienvenue"))

    async def attaquer_et_recevoir_la_question(self, ws, jeton, joueur, src, dst):
        await ws.send(json.dumps({
            "type": "rejoindre", "jeton": jeton, "joueur": joueur,
        }))
        await self.lire(ws, "bienvenue")
        await ws.send(json.dumps({"type": "action", "action": {
            "type": "assaut_total", "source": src, "cible": dst,
        }}))
        question = await self.lire(ws, "question_soumission")
        self.assertEqual(question["territoire"], dst)
        return question

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_une_arrivee_ne_fige_plus_la_partie(self):
        """Quelqu'un rejoint pendant la question : la reponse doit passer.

        ``rejoindre`` repond avec l'etat complet, et ``etat_reseau()`` attend
        le verrou tenu par l'attaque en cours. Lu a meme la boucle asyncio,
        il la bloquait entierement — la reponse du joueur n'arrivait jamais.
        """
        asyncio.run(asyncio.wait_for(self._scenario_arrivee(), 60))

    async def _scenario_arrivee(self):
        url, _, joueur, (src, dst), jeton = self.preparer_partie()
        bob = self.poster("/api/joueurs", {"nom": "Bob"})["jeton"]

        async with websockets.connect(url) as ws:
            await self.attaquer_et_recevoir_la_question(ws, jeton, joueur, src, dst)

            async with websockets.connect(url) as spectateur:
                # L'arrivant reclame l'etat : il patientera jusqu'a la fin de
                # l'action, mais sans empecher personne d'autre de parler.
                await spectateur.send(json.dumps({"type": "rejoindre", "jeton": bob}))

                await ws.send(json.dumps({
                    "type": "decision_soumission", "reponse": False,
                }))
                resultat = await self.lire(ws, "resultat")
                self.assertTrue(resultat["resultat"]["ok"])

                # Et l'arrivant est servi dans la foulee.
                bienvenue = await self.lire(spectateur, "bienvenue")
                self.assertIsNone(bienvenue["joueur"])

    def test_la_question_survit_a_une_coupure(self):
        """Telephone en veille : le socket meurt, la reponse ne part pas.

        A la reconnexion, le meme siege retrouve la question et y repond —
        au lieu d'attendre deux minutes que le serveur tranche tout seul.
        """
        asyncio.run(asyncio.wait_for(self._scenario_coupure(), 60))

    async def _scenario_coupure(self):
        url, session, joueur, (src, dst), jeton = self.preparer_partie()

        async with websockets.connect(url) as ws:
            await self.attaquer_et_recevoir_la_question(ws, jeton, joueur, src, dst)
            # Le telephone s'endort : la connexion tombe, sans reponse.

        async with websockets.connect(url) as ws2:
            await ws2.send(json.dumps({"type": "rejoindre", "jeton": jeton}))
            # La question est reposee d'elle-meme, avant meme l'etat complet
            # (que le verrou de l'attaque en cours retient encore).
            reposee = await self.lire(ws2, "question_soumission")
            self.assertEqual(reposee["territoire"], dst)

            # Et cette nouvelle connexion peut y repondre : soumission.
            await ws2.send(json.dumps({
                "type": "decision_soumission", "reponse": True,
            }))
            resultat = await self.lire(ws2, "resultat")
            self.assertTrue(resultat["resultat"]["ok"])

        self.assertIn(dst, session.state.submitted_territory_ids)
        self.assertEqual(session.state.submitted_territory_overlords[dst], joueur)


if __name__ == "__main__":
    unittest.main()
