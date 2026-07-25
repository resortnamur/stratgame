"""Sauvegardes automatiques de securite (juillet 2026).

Le serveur ecrit une sauvegarde ``auto_<horodatage>_<id>.json`` apres chaque
action humaine et chaque tour IA, avec rotation (les plus anciennes sont
supprimees, les sauvegardes nommees par les joueurs ne sont jamais touchees).

Lancement : ``python -m unittest tests.test_sauvegarde_auto -v`` depuis
"Jeux Strat".
"""

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serveur.app import creer_app
from serveur.partie import (
    GestionnaireParties, MAX_SAUVEGARDES_AUTO, PREFIXE_SAUVEGARDE_AUTO,
)
from serveur.stockage import StockageFichiers, StockageMixte, StockageSql

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_serveur import premiere_sauvegarde, sauvegarde_avec_humain_au_trait

RANDOM_SEED = 20260722


def stockage_sqlite(dossier: Path) -> StockageSql:
    # StockageSql ouvre une connexion neuve par operation : il faut une base
    # qui survit entre deux connexions, donc un fichier (pas ":memory:").
    base = Path(dossier) / "documents.sqlite"
    return StockageSql(lambda: sqlite3.connect(base), "sauvegardes", marque="?")


class TestSupprimerStockage(unittest.TestCase):
    def test_fichiers(self):
        with tempfile.TemporaryDirectory() as dossier:
            stockage = StockageFichiers(Path(dossier))
            stockage.ecrire("a.json", "{}")
            stockage.supprimer("a.json")
            self.assertEqual(stockage.lister(), [])
            stockage.supprimer("absent.json")  # silencieux
            stockage.supprimer("../evasion.json")  # nom invalide : ignore

    def test_sql(self):
        with tempfile.TemporaryDirectory() as dossier:
            stockage = stockage_sqlite(Path(dossier))
            stockage.ecrire("a.json", "{}")
            stockage.supprimer("a.json")
            self.assertEqual(stockage.lister(), [])
            stockage.supprimer("absent.json")

    def test_mixte_ne_touche_que_la_surcouche(self):
        with tempfile.TemporaryDirectory() as dossier:
            base = StockageFichiers(Path(dossier) / "depot")
            base.ecrire("depot.json", "{}")
            mixte = StockageMixte(base, stockage_sqlite(Path(dossier)))
            mixte.ecrire("joueur.json", "{}")
            mixte.supprimer("joueur.json")
            mixte.supprimer("depot.json")
            # Le document du depot survit, celui du joueur est parti.
            self.assertEqual(mixte.lister(), ["depot.json"])


class TestSessionSauvegardeAuto(unittest.TestCase):
    def _gestionnaire(self, dossier: Path, actif: bool = True) -> GestionnaireParties:
        source = premiere_sauvegarde()
        (dossier / source.name).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8",
        )
        return GestionnaireParties(
            dossier, fichier_joueurs=dossier / "joueurs.json",
            sauvegarde_auto=actif,
        )

    def test_nom_et_ecriture(self):
        with tempfile.TemporaryDirectory() as temp:
            dossier = Path(temp)
            gestionnaire = self._gestionnaire(dossier)
            fichier = gestionnaire.lister_sauvegardes()[0]["fichier"]
            session = gestionnaire.ouvrir(fichier, seed=RANDOM_SEED)
            self.assertIsNotNone(session.nom_auto)
            self.assertTrue(session.nom_auto.startswith(PREFIXE_SAUVEGARDE_AUTO))

            nom = session.sauvegarder_auto()
            self.assertEqual(nom, session.nom_auto)
            payload = json.loads((dossier / nom).read_text(encoding="utf-8"))
            self.assertEqual(payload["kind"], "game")
            # La cible de la sauvegarde manuelle n'a pas bouge.
            self.assertEqual(session.source, fichier)
            # La sauvegarde auto apparait dans le catalogue du lobby.
            noms = {s["fichier"] for s in gestionnaire.lister_sauvegardes()}
            self.assertIn(nom, noms)

    def test_rotation_et_sauvegardes_manuelles_intactes(self):
        with tempfile.TemporaryDirectory() as temp:
            dossier = Path(temp)
            gestionnaire = self._gestionnaire(dossier)
            fichier = gestionnaire.lister_sauvegardes()[0]["fichier"]
            session = gestionnaire.ouvrir(fichier, seed=RANDOM_SEED)
            # Des sauvegardes auto anciennes + une sauvegarde nommee.
            for index in range(MAX_SAUVEGARDES_AUTO + 5):
                (dossier / f"auto_20200101-0000{index:02d}_vieux.json").write_text(
                    '{"kind": "game"}', encoding="utf-8",
                )
            (dossier / "ma_partie_preferee.json").write_text(
                '{"kind": "game"}', encoding="utf-8",
            )

            session.sauvegarder_auto()
            autos = sorted(
                chemin.name for chemin in dossier.glob("auto_*.json")
            )
            self.assertEqual(len(autos), MAX_SAUVEGARDES_AUTO)
            self.assertIn(session.nom_auto, autos)
            # Les plus anciennes sont parties, les plus recentes restent.
            self.assertNotIn("auto_20200101-000000_vieux.json", autos)
            # La sauvegarde nommee n'est jamais candidate a la rotation.
            self.assertTrue((dossier / "ma_partie_preferee.json").exists())
            self.assertTrue((dossier / fichier).exists())

    def test_desactivee(self):
        with tempfile.TemporaryDirectory() as temp:
            dossier = Path(temp)
            gestionnaire = self._gestionnaire(dossier, actif=False)
            fichier = gestionnaire.lister_sauvegardes()[0]["fichier"]
            session = gestionnaire.ouvrir(fichier, seed=RANDOM_SEED)
            self.assertIsNone(session.nom_auto)
            self.assertIsNone(session.sauvegarder_auto())
            self.assertEqual(list(dossier.glob("auto_*.json")), [])


class TestApiSauvegardeAuto(unittest.TestCase):
    def test_prefixe_auto_refuse_en_manuel(self):
        with tempfile.TemporaryDirectory() as temp:
            dossier = Path(temp)
            source = premiere_sauvegarde()
            (dossier / source.name).write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8",
            )
            app = creer_app(
                dossier, fichier_joueurs=dossier / "joueurs.json",
                sauvegarde_auto=False,
            )
            client = TestClient(app)
            resume = client.post(
                "/api/parties", json={"sauvegarde": source.name, "seed": RANDOM_SEED},
            ).json()
            reponse = client.post(
                f"/api/parties/{resume['id']}/sauvegarder",
                json={"fichier": "auto_ma_partie.json"},
            )
            self.assertEqual(reponse.status_code, 422)
            self.assertIn("auto_", reponse.json()["detail"])

    def test_action_declenche_la_sauvegarde_auto(self):
        chemin = sauvegarde_avec_humain_au_trait()
        with tempfile.TemporaryDirectory() as temp:
            dossier = Path(temp)
            (dossier / chemin.name).write_text(
                chemin.read_text(encoding="utf-8"), encoding="utf-8",
            )
            app = creer_app(
                dossier, fichier_joueurs=dossier / "joueurs.json",
                delai_tour_ia=0.0, delai_pas_ia=0.0,
            )
            client = TestClient(app)
            resume = client.post(
                "/api/parties", json={"sauvegarde": chemin.name, "seed": RANDOM_SEED},
            ).json()
            joueur = resume["joueur_courant"]
            alice = client.post("/api/joueurs", json={"nom": "Alice"}).json()

            with client.websocket_connect(f"/ws/parties/{resume['id']}") as ws:
                ws.send_json({
                    "type": "rejoindre", "jeton": alice["jeton"], "joueur": joueur,
                })
                self.assertEqual(ws.receive_json()["type"], "bienvenue")
                ws.receive_json()  # presence
                ws.send_json({"type": "action", "action": {"type": "terminer_attaque"}})
                resultat = ws.receive_json()
                self.assertEqual(resultat["type"], "resultat")
                self.assertTrue(resultat["resultat"]["ok"])

                # L'ecriture suit la diffusion : on lui laisse un instant.
                for _ in range(100):
                    autos = list(dossier.glob("auto_*.json"))
                    if autos:
                        break
                    time.sleep(0.05)
                self.assertTrue(autos, "Aucune sauvegarde automatique ecrite.")
                payload = json.loads(autos[0].read_text(encoding="utf-8"))
                self.assertEqual(payload["kind"], "game")


if __name__ == "__main__":
    unittest.main(verbosity=2)
