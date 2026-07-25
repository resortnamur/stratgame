"""Stockage des documents JSON du serveur (sauvegardes, cartes, registre).

Le serveur manipule trois familles de documents : les sauvegardes de partie,
les cartes et le registre des joueurs. En local, tout vit dans des fichiers
(``parties_en_cours/``, ``cartes_sauvegardees/``, ``joueurs.json``). Sur un
hebergeur gratuit, le disque est efface a chaque redemarrage : ce module
abstrait donc le rangement derriere un contrat commun, avec une variante en
base de donnees (etape 4 du plan de migration).

Contrat (duck typing, les contenus sont du texte — en pratique du JSON) :

- ``lister() -> [nom, ...]``
- ``versions() -> {nom: version}`` — un jeton opaque qui change quand le
  contenu change (mtime pour les fichiers, compteur pour la base) ; permet
  aux appelants de mettre en cache les metadonnees sans relire les contenus.
- ``lire(nom) -> contenu | None``
- ``ecrire(nom, contenu)``
- ``supprimer(nom)`` — silencieux si le document n'existe pas ; sur un
  stockage mixte, seule la surcouche est touchee (les fichiers du depot
  restent intacts).

Implementations :

- :class:`StockageFichiers` — un dossier de ``.json`` (comportement local
  historique) ;
- :class:`StockageSql` — une table ``documents`` dans une base SQL,
  agnostique du pilote (Postgres via psycopg en production, sqlite3 dans
  les tests : memes requetes, seul le marqueur de parametre change) ;
- :class:`StockageMixte` — une base en lecture seule (les sauvegardes et
  cartes livrees avec le depot) + une surcouche en ecriture (tout ce que
  les joueurs creent) ; en cas de doublon, la surcouche prime.

``stockage_postgres(DATABASE_URL, collection)`` construit la variante de
production (connexion neuve par operation : robuste face aux coupures des
Postgres serverless type Neon, et le trafic du jeu est faible).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Nom de document acceptable : un nom de fichier .json simple, sans chemin.
# (Les cartes existantes ont des espaces et des accents : on interdit juste
# ce qui permettrait de sortir du dossier ou casserait un systeme de fichiers.)
_CARACTERES_INTERDITS = re.compile(r'[\x00-\x1f/\\<>:"|?*]')
LONGUEUR_NOM_MAX = 80


def assainir_nom(nom: Any) -> str:
    """Valide un nom de document ; ``ValueError("nom_fichier_invalide")`` sinon."""
    if not isinstance(nom, str):
        raise ValueError("nom_fichier_invalide")
    nom = nom.strip()
    if (
        not nom.endswith(".json")
        or len(nom) <= len(".json")
        or len(nom) > LONGUEUR_NOM_MAX
        or nom.startswith(".")
        or ".." in nom
        or _CARACTERES_INTERDITS.search(nom)
    ):
        raise ValueError("nom_fichier_invalide")
    return nom


def nom_est_valide(nom: Any) -> bool:
    try:
        assainir_nom(nom)
    except ValueError:
        return False
    return True


class StockageFichiers:
    """Un dossier de fichiers ``.json`` (le rangement local historique)."""

    def __init__(self, dossier: Path) -> None:
        self.dossier = Path(dossier)

    def lister(self) -> List[str]:
        if not self.dossier.is_dir():
            return []
        return sorted(
            chemin.name for chemin in self.dossier.glob("*.json")
            if nom_est_valide(chemin.name)
        )

    def versions(self) -> Dict[str, Any]:
        resultats: Dict[str, Any] = {}
        for nom in self.lister():
            try:
                resultats[nom] = (self.dossier / nom).stat().st_mtime_ns
            except OSError:
                continue
        return resultats

    def lire(self, nom: str) -> Optional[str]:
        if not nom_est_valide(nom):
            return None
        chemin = self.dossier / nom
        try:
            return chemin.read_text(encoding="utf-8")
        except OSError:
            return None

    def ecrire(self, nom: str, contenu: str) -> None:
        nom = assainir_nom(nom)
        self.dossier.mkdir(parents=True, exist_ok=True)
        (self.dossier / nom).write_text(contenu, encoding="utf-8")

    def supprimer(self, nom: str) -> None:
        if not nom_est_valide(nom):
            return
        try:
            (self.dossier / nom).unlink()
        except OSError:
            pass


class StockageSql:
    """Une collection de documents dans une table SQL.

    ``connecter`` retourne une connexion DB-API neuve a chaque appel (elle
    est fermee apres chaque operation) ; ``marque`` est le marqueur de
    parametre du pilote (``%s`` pour psycopg, ``?`` pour sqlite3). La table
    est partagee entre les collections (une ligne = un document).
    """

    def __init__(self, connecter: Callable[[], Any], collection: str,
                 marque: str = "%s") -> None:
        self.connecter = connecter
        self.collection = collection
        self.marque = marque
        self._executer(
            "CREATE TABLE IF NOT EXISTS documents ("
            " collection TEXT NOT NULL,"
            " nom TEXT NOT NULL,"
            " contenu TEXT NOT NULL,"
            " version INTEGER NOT NULL DEFAULT 1,"
            " PRIMARY KEY (collection, nom))",
            (),
        )

    def _executer(self, requete: str, parametres: tuple, lecture: bool = False):
        requete = requete.replace("?", self.marque)
        connexion = self.connecter()
        try:
            curseur = connexion.cursor()
            curseur.execute(requete, parametres)
            lignes = curseur.fetchall() if lecture else None
            connexion.commit()
            return lignes
        finally:
            connexion.close()

    def lister(self) -> List[str]:
        lignes = self._executer(
            "SELECT nom FROM documents WHERE collection = ? ORDER BY nom",
            (self.collection,), lecture=True,
        )
        return [ligne[0] for ligne in lignes]

    def versions(self) -> Dict[str, Any]:
        lignes = self._executer(
            "SELECT nom, version FROM documents WHERE collection = ?",
            (self.collection,), lecture=True,
        )
        return {ligne[0]: ligne[1] for ligne in lignes}

    def lire(self, nom: str) -> Optional[str]:
        if not nom_est_valide(nom):
            return None
        lignes = self._executer(
            "SELECT contenu FROM documents WHERE collection = ? AND nom = ?",
            (self.collection, nom), lecture=True,
        )
        return lignes[0][0] if lignes else None

    def ecrire(self, nom: str, contenu: str) -> None:
        nom = assainir_nom(nom)
        self._executer(
            "INSERT INTO documents (collection, nom, contenu, version)"
            " VALUES (?, ?, ?, 1)"
            " ON CONFLICT (collection, nom) DO UPDATE SET"
            " contenu = excluded.contenu, version = documents.version + 1",
            (self.collection, nom, contenu),
        )

    def supprimer(self, nom: str) -> None:
        if not nom_est_valide(nom):
            return
        self._executer(
            "DELETE FROM documents WHERE collection = ? AND nom = ?",
            (self.collection, nom),
        )


class StockageMixte:
    """Une base en lecture seule + une surcouche en ecriture.

    Le cas du serveur heberge : les sauvegardes et cartes du depot restent
    disponibles (fichiers, en lecture), tout ce que les joueurs ecrivent va
    dans la surcouche (la base de donnees, qui survit aux redemarrages).
    Un nom present des deux cotes : la surcouche prime.
    """

    def __init__(self, base: Optional[Any], surcouche: Any) -> None:
        self.base = base
        self.surcouche = surcouche

    def lister(self) -> List[str]:
        noms = set(self.surcouche.lister())
        if self.base is not None:
            noms.update(self.base.lister())
        return sorted(noms)

    def versions(self) -> Dict[str, Any]:
        # Prefixes distincts : un document qui passe de la base a la
        # surcouche change forcement de version, meme a jetons egaux.
        resultats: Dict[str, Any] = {}
        if self.base is not None:
            resultats.update({
                nom: ("base", jeton) for nom, jeton in self.base.versions().items()
            })
        resultats.update({
            nom: ("sur", jeton) for nom, jeton in self.surcouche.versions().items()
        })
        return resultats

    def lire(self, nom: str) -> Optional[str]:
        contenu = self.surcouche.lire(nom)
        if contenu is None and self.base is not None:
            contenu = self.base.lire(nom)
        return contenu

    def ecrire(self, nom: str, contenu: str) -> None:
        self.surcouche.ecrire(nom, contenu)

    def supprimer(self, nom: str) -> None:
        # Les documents du depot (la base) ne sont jamais supprimes : seuls
        # les documents ecrits par les joueurs (la surcouche) le sont.
        self.surcouche.supprimer(nom)


def stockage_postgres(database_url: str, collection: str) -> StockageSql:
    """La variante de production : une collection dans un Postgres heberge."""
    import psycopg  # importe ici : requis sur le serveur heberge seulement

    def connecter():
        return psycopg.connect(database_url)

    return StockageSql(connecter, collection, marque="%s")
