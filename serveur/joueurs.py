"""Identites persistantes des joueurs (nom public + jeton secret).

Le registre associe un jeton (secret genere par le serveur, jamais diffuse
aux autres clients) a un nom public unique. Le client conserve son jeton
(localStorage) et le presente en rejoignant une partie : c'est lui qui permet
de retrouver son siege apres une coupure ou un changement d'appareil.

Persistance : un document JSON ``{jeton: nom}`` dans un stockage (module
``stockage``) — un fichier ``joueurs.json`` en local, une ligne en base sur
le serveur heberge. Relu au demarrage, reecrit a chaque inscription :
suffisant pour un serveur a une seule instance.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional

from .stockage import StockageFichiers

# Nom public : 1 a 24 caracteres une fois les espaces normalises.
LONGUEUR_NOM_MAX = 24


class RegistreJoueurs:
    """Le carnet des identites connues du serveur, adosse a un stockage."""

    def __init__(self, fichier: Optional[Path] = None, *, stockage=None,
                 nom_document: str = "joueurs.json") -> None:
        if stockage is None:
            if fichier is None:
                raise ValueError("RegistreJoueurs : fichier ou stockage requis.")
            fichier = Path(fichier)
            stockage = StockageFichiers(fichier.parent)
            nom_document = fichier.name
        self.stockage = stockage
        self.nom_document = nom_document
        self._lock = threading.Lock()
        self._noms_par_jeton: Dict[str, str] = {}
        contenu = stockage.lire(nom_document)
        if contenu is not None:
            try:
                payload = json.loads(contenu)
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                self._noms_par_jeton = {
                    str(jeton): str(nom) for jeton, nom in payload.items()
                }

    @staticmethod
    def normaliser_nom(nom) -> str:
        """Nettoie un nom public ; ``ValueError("nom_invalide")`` sinon."""
        if not isinstance(nom, str):
            raise ValueError("nom_invalide")
        nom = " ".join(nom.split())
        if not nom or len(nom) > LONGUEUR_NOM_MAX:
            raise ValueError("nom_invalide")
        return nom

    def inscrire(self, nom) -> Dict[str, str]:
        """Cree une identite ; ``ValueError("nom_pris")`` si le nom existe.

        L'unicite est verifiee sans tenir compte de la casse, pour eviter
        deux joueurs "Alice" et "alice" indistinguables a l'ecran.
        """
        nom = self.normaliser_nom(nom)
        with self._lock:
            if any(
                existant.casefold() == nom.casefold()
                for existant in self._noms_par_jeton.values()
            ):
                raise ValueError("nom_pris")
            jeton = uuid.uuid4().hex
            self._noms_par_jeton[jeton] = nom
            self._ecrire()
        return {"jeton": jeton, "nom": nom}

    def nom_par_jeton(self, jeton) -> Optional[str]:
        if not isinstance(jeton, str):
            return None
        return self._noms_par_jeton.get(jeton)

    def _ecrire(self) -> None:
        self.stockage.ecrire(
            self.nom_document,
            json.dumps(self._noms_par_jeton, ensure_ascii=False),
        )
