"""Identites persistantes des joueurs (nom public + jeton secret).

Le registre associe un jeton (secret genere par le serveur, jamais diffuse
aux autres clients) a un nom public unique. Le client conserve son jeton
(localStorage) et le presente en rejoignant une partie : c'est lui qui permet
de retrouver son siege apres une coupure ou un changement d'appareil.

Persistance : un simple fichier JSON ``{jeton: nom}``, relu au demarrage et
reecrit a chaque inscription. Suffisant pour un serveur a une seule
instance ; l'etat en base viendra avec le deploiement (etape 4).
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional

# Nom public : 1 a 24 caracteres une fois les espaces normalises.
LONGUEUR_NOM_MAX = 24


class RegistreJoueurs:
    """Le carnet des identites connues du serveur, adosse a un fichier."""

    def __init__(self, fichier: Path) -> None:
        self.fichier = Path(fichier)
        self._lock = threading.Lock()
        self._noms_par_jeton: Dict[str, str] = {}
        if self.fichier.is_file():
            try:
                payload = json.loads(self.fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
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
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        self.fichier.write_text(
            json.dumps(self._noms_par_jeton, ensure_ascii=False),
            encoding="utf-8",
        )
