"""Tests de la couche de stockage (etape 4a) : fichiers, SQL, mixte.

Le backend SQL est exerce sur sqlite3 (livre avec Python) : les requetes
sont exactement celles de la production (Postgres via psycopg), seul le
marqueur de parametre change — c'est le contrat de ``StockageSql``.

Lancement : ``python -m unittest tests.test_stockage -v`` depuis ``Jeux Strat``.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from serveur.joueurs import RegistreJoueurs
from serveur.partie import GestionnaireParties
from serveur.stockage import (
    StockageFichiers, StockageMixte, StockageSql, assainir_nom, nom_est_valide,
)

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PARTIES = RACINE / "parties_en_cours"
DOSSIER_CARTES = RACINE / "cartes_sauvegardees"
RANDOM_SEED = 20260724


def stockage_sqlite(dossier: str, collection: str) -> StockageSql:
    """Le backend SQL de production, branche sur une base sqlite locale."""
    chemin = str(Path(dossier) / "base.sqlite3")
    return StockageSql(lambda: sqlite3.connect(chemin), collection, marque="?")


class TestNoms(unittest.TestCase):
    def test_noms_acceptes_et_refuses(self):
        self.assertEqual(assainir_nom("  Ma Carte étoilée.json "), "Ma Carte étoilée.json")
        for nom in (
            None, 42, "", ".json", "sans-extension", "trop" + "x" * 90 + ".json",
            "../evasion.json", "dossier/carte.json", "dossier\\carte.json",
            ".cachee.json", "deux..points.json", "etoile*.json", "nul\x00.json",
        ):
            self.assertFalse(nom_est_valide(nom), repr(nom))
            with self.assertRaises(ValueError):
                assainir_nom(nom)


class ContratStockage:
    """Les tests communs a tous les backends (duck typing du contrat)."""

    def construire(self, dossier: str):
        raise NotImplementedError

    def test_contrat(self):
        with tempfile.TemporaryDirectory() as dossier:
            stockage = self.construire(dossier)
            self.assertEqual(stockage.lister(), [])
            self.assertEqual(stockage.versions(), {})
            self.assertIsNone(stockage.lire("absent.json"))

            stockage.ecrire("b.json", '{"n": 1}')
            stockage.ecrire("a.json", '{"n": 2}')
            self.assertEqual(stockage.lister(), ["a.json", "b.json"])
            self.assertEqual(stockage.lire("a.json"), '{"n": 2}')

            # La version change quand (et seulement quand) le contenu change.
            versions = stockage.versions()
            self.assertEqual(set(versions), {"a.json", "b.json"})
            self.assertEqual(stockage.versions(), versions)
            stockage.ecrire("a.json", '{"n": 3}')
            self.assertNotEqual(stockage.versions()["a.json"], versions["a.json"])
            self.assertEqual(stockage.lire("a.json"), '{"n": 3}')

            # Les noms dangereux sont refuses en ecriture, muets en lecture.
            with self.assertRaises(ValueError):
                stockage.ecrire("../evasion.json", "{}")
            self.assertIsNone(stockage.lire("../evasion.json"))


class TestStockageFichiers(ContratStockage, unittest.TestCase):
    def construire(self, dossier):
        return StockageFichiers(Path(dossier) / "docs")

    def test_dossier_absent(self):
        stockage = StockageFichiers(Path("dossier-qui-n-existe-pas-du-tout"))
        self.assertEqual(stockage.lister(), [])
        self.assertIsNone(stockage.lire("x.json"))


class TestStockageSql(ContratStockage, unittest.TestCase):
    def construire(self, dossier):
        return stockage_sqlite(dossier, "sauvegardes")

    def test_collections_isolees(self):
        with tempfile.TemporaryDirectory() as dossier:
            cartes = stockage_sqlite(dossier, "cartes")
            sauvegardes = stockage_sqlite(dossier, "sauvegardes")
            cartes.ecrire("x.json", "carte")
            sauvegardes.ecrire("x.json", "partie")
            self.assertEqual(cartes.lire("x.json"), "carte")
            self.assertEqual(sauvegardes.lire("x.json"), "partie")
            self.assertEqual(cartes.lister(), ["x.json"])


class TestStockageMixte(ContratStockage, unittest.TestCase):
    def construire(self, dossier):
        # Une base de depot vide + la surcouche SQL : le contrat complet
        # doit tenir sur la surcouche seule.
        return StockageMixte(
            StockageFichiers(Path(dossier) / "depot"),
            stockage_sqlite(dossier, "sauvegardes"),
        )

    def test_lecture_fusionnee_et_ecriture_en_surcouche(self):
        with tempfile.TemporaryDirectory() as dossier:
            depot = StockageFichiers(Path(dossier) / "depot")
            depot.ecrire("livree.json", '{"origine": "depot"}')
            depot.ecrire("commune.json", '{"origine": "depot"}')
            mixte = StockageMixte(depot, stockage_sqlite(dossier, "sauvegardes"))

            self.assertEqual(mixte.lister(), ["commune.json", "livree.json"])
            self.assertEqual(mixte.lire("livree.json"), '{"origine": "depot"}')

            # Ecrire ne touche jamais le depot ; la surcouche prime ensuite.
            mixte.ecrire("commune.json", '{"origine": "base"}')
            mixte.ecrire("neuve.json", '{"origine": "base"}')
            self.assertEqual(mixte.lire("commune.json"), '{"origine": "base"}')
            self.assertEqual(depot.lire("commune.json"), '{"origine": "depot"}')
            self.assertEqual(
                mixte.lister(), ["commune.json", "livree.json", "neuve.json"],
            )
            # La version signale aussi le passage depot -> surcouche.
            self.assertEqual(mixte.versions()["commune.json"][0], "sur")
            self.assertEqual(mixte.versions()["livree.json"][0], "base")

    def test_sans_base(self):
        with tempfile.TemporaryDirectory() as dossier:
            mixte = StockageMixte(None, stockage_sqlite(dossier, "cartes"))
            self.assertEqual(mixte.lister(), [])
            mixte.ecrire("x.json", "{}")
            self.assertEqual(mixte.lire("x.json"), "{}")


class TestRegistreSurStockage(unittest.TestCase):
    def test_registre_en_base(self):
        with tempfile.TemporaryDirectory() as dossier:
            stockage = stockage_sqlite(dossier, "config")
            registre = RegistreJoueurs(stockage=stockage)
            alice = registre.inscrire("Alice")
            # Un registre neuf sur le meme stockage relit les identites.
            recharge = RegistreJoueurs(stockage=stockage)
            self.assertEqual(recharge.nom_par_jeton(alice["jeton"]), "Alice")
            with self.assertRaises(ValueError):
                recharge.inscrire("alice")


class TestGestionnaireSurStockage(unittest.TestCase):
    """Le parcours serveur heberge : depot en lecture, 'base' en ecriture."""

    def gestionnaire_mixte(self, dossier: str) -> GestionnaireParties:
        gestionnaire = GestionnaireParties(DOSSIER_PARTIES, DOSSIER_CARTES)
        gestionnaire.stockage_sauvegardes = StockageMixte(
            gestionnaire.stockage_sauvegardes, stockage_sqlite(dossier, "sauvegardes"),
        )
        gestionnaire.stockage_cartes = StockageMixte(
            gestionnaire.stockage_cartes, stockage_sqlite(dossier, "cartes"),
        )
        return gestionnaire

    def test_sauvegarde_en_surcouche_et_rechargement(self):
        with tempfile.TemporaryDirectory() as dossier:
            gestionnaire = self.gestionnaire_mixte(dossier)
            sauvegardes = gestionnaire.lister_sauvegardes()
            if not sauvegardes:
                raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours.")
            avant = {s["fichier"] for s in sauvegardes}

            session = gestionnaire.ouvrir(sauvegardes[0]["fichier"], seed=RANDOM_SEED)
            self.assertEqual(session.sauvegarder("partie_hebergee.json"), "partie_hebergee.json")
            # Rien sur le disque du depot : tout est dans la surcouche.
            self.assertFalse((DOSSIER_PARTIES / "partie_hebergee.json").exists())
            apres = {s["fichier"] for s in gestionnaire.lister_sauvegardes()}
            self.assertEqual(apres - avant, {"partie_hebergee.json"})

            recharge = gestionnaire.ouvrir("partie_hebergee.json", seed=RANDOM_SEED)
            self.assertEqual(
                recharge.state.to_payload()["territories_state"],
                session.state.to_payload()["territories_state"],
            )

    def test_import_de_carte(self):
        with tempfile.TemporaryDirectory() as dossier:
            gestionnaire = self.gestionnaire_mixte(dossier)
            cartes = gestionnaire.lister_cartes()
            self.assertTrue(cartes)
            contenu = gestionnaire.stockage_cartes.lire(cartes[0]["fichier"])
            payload = json.loads(contenu)

            fiche = gestionnaire.importer_carte("Ma carte.json", payload)
            self.assertEqual(fiche["fichier"], "Ma carte.json")
            self.assertEqual(fiche["territoires"], cartes[0]["territoires"])
            self.assertIn(
                "Ma carte.json",
                {c["fichier"] for c in gestionnaire.lister_cartes()},
            )
            self.assertFalse((DOSSIER_CARTES / "Ma carte.json").exists())

            # Doublon sans remplacer : refuse ; avec remplacer : accepte.
            with self.assertRaises(ValueError) as refus:
                gestionnaire.importer_carte("Ma carte.json", payload)
            self.assertEqual(str(refus.exception), "carte_existante")
            gestionnaire.importer_carte("Ma carte.json", payload, remplacer=True)

            # Une partie neuve se cree depuis la carte importee.
            session = gestionnaire.creer(
                "Ma carte.json", num_players=3, ai_player_count=1, seed=RANDOM_SEED,
            )
            self.assertEqual(session.state.phase, "playing")

            # Les refus types : nom impossible, carte illisible, sauvegarde.
            with self.assertRaises(ValueError):
                gestionnaire.importer_carte("../evasion.json", payload)
            with self.assertRaises(ValueError) as refus:
                gestionnaire.importer_carte("vide.json", {"territories": []})
            self.assertEqual(str(refus.exception), "carte_invalide")
            with self.assertRaises(ValueError):
                gestionnaire.importer_carte("triche.json", {**payload, "kind": "game"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
