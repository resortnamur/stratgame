"""Sessions de partie cote serveur (logique pure, sans FastAPI).

Une :class:`SessionPartie` enveloppe un ``GameState`` du moteur et arbitre ce
que la couche web n'a pas a connaitre : qui a le droit de jouer, quand les
tours IA s'enchainent, comment l'etat est diffuse (allege de l'historique
replay) et sauvegarde. La couche FastAPI (``app.py``) ne fait que transporter
les JSON entre les clients et cette classe.

Concurrence : toutes les methodes qui touchent l'etat prennent ``self.lock``
(threading.Lock) — la couche web serialise deja les actions par partie, le
verrou protege contre les acces croises (sauvegarde pendant un tour IA...).
"""

from __future__ import annotations

import dataclasses
import json
import random
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from moteur import actions, mise_en_place, regles
from moteur.etat import GameState

from .joueurs import RegistreJoueurs

# Dimensions logiques d'une cellule, heritees de la zone de carte de x45
# (1200 x 620 pixels) : la geometrie des ponts est exprimee en pixels dans
# les sauvegardes, on garde donc le meme repere que x45 et les tests.
LOGICAL_MAP_WIDTH = 1200.0
LOGICAL_MAP_HEIGHT = 620.0

# Garde-fou pour l'enchainement des tours IA (une partie 100 % IA joue
# jusqu'a la victoire : on plafonne large, bien au-dela d'une partie reelle).
MAX_CONSECUTIVE_AI_TURNS = 2000


def to_jsonable(value: Any) -> Any:
    """Convertit recursivement un rapport du moteur en structures JSON."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    return value


@dataclasses.dataclass
class ResultatAction:
    """Resultat d'une action arbitree par la session, pret a diffuser."""

    ok: bool
    code: str = "ok"
    outcome: Optional[Dict[str, Any]] = None
    rapports_ia: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    joueur_ia: Optional[int] = None  # le joueur IA du tour, pour la diffusion
    winner: Optional[int] = None
    winner_reason: str = ""


class SessionPartie:
    """Une partie ouverte sur le serveur, jouable par plusieurs clients."""

    def __init__(self, partie_id: str, state: GameState, source: Optional[Path] = None,
                 seed: Optional[int] = None) -> None:
        self.id = partie_id
        self.state = state
        self.source = source
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.cell_width = LOGICAL_MAP_WIDTH / state.cols
        self.cell_height = LOGICAL_MAP_HEIGHT / state.rows
        # Sieges reserves par identite : joueur -> {"jeton", "nom"}. La
        # reservation survit a la deconnexion (le jeton permet de revenir).
        self.reservations: Dict[int, Dict[str, str]] = {}
        # Deroule passe par passe du tour IA courant (voir demarrer_tour_ia).
        self._joueur_ia: Optional[int] = None
        self._pas_ia = None

    # ------------------------------------------------------------------
    # Chargement / sauvegarde
    # ------------------------------------------------------------------

    @classmethod
    def depuis_fichier(cls, partie_id: str, chemin: Path, seed: Optional[int] = None) -> "SessionPartie":
        """Charge une sauvegarde x45/moteur et applique les sanitisations."""
        payload = json.loads(Path(chemin).read_text(encoding="utf-8"))
        state = GameState.from_payload(payload)
        session = cls(partie_id, state, source=Path(chemin), seed=seed)
        regles.sanitize_after_load(state, session.rng, phase_before_load="start_menu")
        return session

    @classmethod
    def nouvelle(
        cls,
        partie_id: str,
        carte_payload: dict,
        num_players: int,
        ai_player_count: int,
        difficulty_level: str = "normal",
        tribes_mode: bool = False,
        seed: Optional[int] = None,
    ) -> "SessionPartie":
        """Cree une partie neuve depuis une carte (miroir de start_game_session).

        Le premier tour est demarre (``begin_player_turn``), comme dans x45 ;
        si le joueur 0 est une IA, l'appelant declenche ensuite
        ``jouer_tours_ia_en_attente``.
        """
        rng = random.Random(seed)
        state = mise_en_place.nouvelle_partie(
            carte_payload, num_players, ai_player_count,
            difficulty_level=difficulty_level, tribes_mode=tribes_mode, rng=rng,
        )
        session = cls(partie_id, state, source=None, seed=None)
        session.rng = rng
        actions.begin_player_turn(state, state.current_player, rng)
        return session

    def sauvegarder(self, chemin: Optional[Path] = None) -> Path:
        """Ecrit la partie au format canonique (schema v13, comme x45)."""
        cible = Path(chemin) if chemin is not None else self.source
        if cible is None:
            raise ValueError("Aucun fichier cible pour la sauvegarde.")
        with self.lock:
            payload = self.state.to_payload()
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.source = cible
        return cible

    # ------------------------------------------------------------------
    # Sieges et etat diffuse
    # ------------------------------------------------------------------

    def sieges(self) -> List[Dict[str, Any]]:
        """Un descriptif par joueur : humain/IA, actif, nom du reservataire."""
        actifs = set(regles.get_active_players(self.state))
        return [
            {
                "joueur": player,
                "ia": regles.is_ai_player(self.state, player),
                "actif": player in actifs,
                "nom": self.reservations.get(player, {}).get("nom"),
            }
            for player in range(self.state.num_players)
        ]

    def sieges_humains_libres(self) -> List[int]:
        return [
            s["joueur"] for s in self.sieges()
            if not s["ia"] and s["actif"] and s["joueur"] not in self.reservations
        ]

    def siege_de(self, jeton: Optional[str]) -> Optional[int]:
        """Le siege deja reserve par cette identite, s'il y en a un."""
        for joueur, reservation in self.reservations.items():
            if reservation["jeton"] == jeton:
                return joueur
        return None

    def reserver_siege(self, joueur: Any, jeton: str, nom: str) -> tuple:
        """Reserve un siege humain pour une identite ; retourne (ok, code).

        Re-reserver son propre siege reussit (c'est la reconnexion) ; les
        codes de refus : ``deja_un_siege`` (l'identite occupe un autre siege)
        et ``siege_indisponible`` (siege inconnu, IA, elimine ou pris).
        """
        with self.lock:
            deja = self.siege_de(jeton)
            if deja is not None:
                return (deja == joueur, "ok" if deja == joueur else "deja_un_siege")
            if not isinstance(joueur, int) or not 0 <= joueur < self.state.num_players:
                return (False, "siege_indisponible")
            if (
                regles.is_ai_player(self.state, joueur)
                or joueur not in regles.get_active_players(self.state)
                or joueur in self.reservations
            ):
                return (False, "siege_indisponible")
            self.reservations[joueur] = {"jeton": jeton, "nom": nom}
            return (True, "ok")

    def liberer_siege(self, jeton: Optional[str]) -> Optional[int]:
        """Libere le siege reserve par cette identite ; retourne le siege."""
        with self.lock:
            joueur = self.siege_de(jeton)
            if joueur is not None:
                del self.reservations[joueur]
            return joueur

    def etat_reseau(self) -> Dict[str, Any]:
        """L'etat complet a diffuser aux clients, sans l'historique replay.

        L'historique (jusqu'a plusieurs centaines de Ko) ne sert qu'au mode
        replay local : il reste dans les sauvegardes mais pas sur le reseau.
        Deux cles s'ajoutent au format canonique : ``phase`` (le format ne
        la stocke pas — x45 ne sauvegarde qu'en phase de jeu) et
        ``apercus`` — revenu, culture et gain de science par joueur actif,
        calcules par le moteur (l'equivalent de l'en-tete de la boutique et
        du panneau geopolitique de x45).
        """
        with self.lock:
            payload = self.state.to_payload()
            payload["phase"] = self.state.phase
            payload["apercus"] = {
                str(joueur): {
                    "revenu": regles.calculate_player_income(self.state, joueur),
                    "culture": regles.calculate_player_culture(self.state, joueur),
                    "science_gain": regles.calculate_player_science_income(self.state, joueur),
                }
                for joueur in regles.get_active_players(self.state)
            }
        payload["replay_history"] = []
        return payload

    def replay(self) -> List[dict]:
        """L'historique replay complet (charge a la demande, hors diffusion).

        Trop lourd pour accompagner chaque etat diffuse (jusqu'a ~1 Mo), il
        n'est envoye qu'au client qui demande un replay.
        """
        with self.lock:
            return list(self.state.replay_history)

    def resume(self) -> Dict[str, Any]:
        """Resume pour le lobby (liste des parties ouvertes)."""
        with self.lock:
            return {
                "id": self.id,
                "tour": self.state.turn,
                "joueur_courant": self.state.current_player,
                "phase": self.state.phase,
                "phase_tour": self.state.turn_phase,
                "num_players": self.state.num_players,
                "sieges": self.sieges(),
                "source": self.source.name if self.source else None,
            }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def appliquer_action(
        self,
        joueur: int,
        action: Dict[str, Any],
        submit_decider: Optional[Callable] = None,
    ) -> ResultatAction:
        """Applique une action d'un client apres arbitrage des droits.

        L'arbitrage serveur (avant les validations du moteur) :
        - la partie doit etre en cours (phases "playing"/"shopping") ;
        - c'est au tour de ``joueur`` ;
        - le siege de ``joueur`` est bien humain.
        Les tours IA qui suivent ne sont PAS joues ici : la couche web les
        enchaine un par un (``jouer_un_tour_ia``), avec une cadence, pour
        que les clients voient chaque tour se derouler.
        """
        with self.lock:
            if self.state.phase not in ("playing", "shopping"):
                return ResultatAction(ok=False, code="partie_terminee")
            if joueur != self.state.current_player:
                return ResultatAction(ok=False, code="pas_votre_tour")
            if regles.is_ai_player(self.state, joueur):
                return ResultatAction(ok=False, code="siege_ia")
            outcome = actions.apply_action(
                self.state, action, self.cell_width, self.cell_height,
                self.rng, submit_decider,
            )
            resultat = ResultatAction(
                ok=outcome.ok,
                code=outcome.code,
                outcome=to_jsonable(outcome),
                winner=outcome.winner,
                winner_reason=outcome.winner_reason,
            )
            if outcome.winner is not None:
                self.state.phase = "victory"
            return resultat

    def tour_ia_en_attente(self) -> bool:
        """Vrai si c'est a un joueur automatique (IA, cite...) de jouer."""
        with self.lock:
            return (
                self.state.phase == "playing"
                and regles.is_ai_player(self.state, self.state.current_player)
            )

    def demarrer_tour_ia(self) -> Optional[int]:
        """Prepare le deroule passe par passe du tour IA courant.

        Retourne le numero du joueur IA, ou None si ce n'est pas a une IA.
        Le tour se consomme ensuite avec ``pas_tour_ia`` ; abandonner un
        deroule en cours est sans danger (l'etat reste coherent entre deux
        passes, un nouveau demarrage reprend ou on en etait).
        """
        with self.lock:
            if self.state.phase != "playing" or not regles.is_ai_player(
                self.state, self.state.current_player
            ):
                return None
            self._joueur_ia = self.state.current_player
            self._pas_ia = actions.play_ai_turn_steps(
                self.state, self.cell_width, self.cell_height, self.rng,
            )
            return self._joueur_ia

    def pas_tour_ia(self):
        """Avance le tour IA d'une passe d'attaque.

        Retourne ``(pas, None)`` pour chaque passe (dict pret a diffuser),
        puis ``(None, resultat)`` quand le tour est fini (deplacements et
        fin de tour joues, rapport complet du tour).
        """
        with self.lock:
            try:
                pas = next(self._pas_ia)
            except StopIteration as fin:
                rapport = fin.value
                resultat = ResultatAction(
                    ok=True,
                    joueur_ia=self._joueur_ia,
                    rapports_ia=[to_jsonable(rapport)],
                    winner=rapport.winner,
                    winner_reason=rapport.winner_reason,
                )
                if rapport.winner is not None:
                    self.state.phase = "victory"
                return None, resultat
            return to_jsonable(pas), None

    def jouer_un_tour_ia(self) -> ResultatAction:
        """Joue UN tour IA (celui du joueur courant) et retourne son rapport.

        ``ok=False``/``rien_a_jouer`` si ce n'est pas a une IA. La couche web
        appelle cette methode en boucle, en diffusant l'etat entre chaque
        tour, pour que les joueurs voient la partie avancer IA par IA.
        """
        with self.lock:
            if self.state.phase != "playing" or not regles.is_ai_player(
                self.state, self.state.current_player
            ):
                return ResultatAction(ok=False, code="rien_a_jouer")
            joueur_ia = self.state.current_player
            rapport = actions.play_ai_turn(
                self.state, self.cell_width, self.cell_height, self.rng,
            )
            resultat = ResultatAction(
                ok=True,
                joueur_ia=joueur_ia,
                rapports_ia=[to_jsonable(rapport)],
                winner=rapport.winner,
                winner_reason=rapport.winner_reason,
            )
            if rapport.winner is not None:
                self.state.phase = "victory"
            return resultat


class GestionnaireParties:
    """Les parties ouvertes du serveur + les catalogues (sauvegardes, cartes)."""

    def __init__(self, dossier_sauvegardes: Path, dossier_cartes: Optional[Path] = None,
                 fichier_joueurs: Optional[Path] = None) -> None:
        self.dossier_sauvegardes = Path(dossier_sauvegardes)
        self.dossier_cartes = Path(dossier_cartes) if dossier_cartes is not None else None
        # Le registre vit a cote du dossier des sauvegardes, pas dedans :
        # x45 et les tests sondent tous les .json de parties_en_cours.
        self.registre = RegistreJoueurs(
            fichier_joueurs if fichier_joueurs is not None
            else self.dossier_sauvegardes.parent / "joueurs.json"
        )
        self.parties: Dict[str, SessionPartie] = {}
        self._compteur = 0
        self._lock = threading.Lock()

    def lister_sauvegardes(self) -> List[Dict[str, Any]]:
        resultats = []
        for chemin in sorted(self.dossier_sauvegardes.glob("*.json")):
            try:
                payload = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("kind") != "game":
                continue
            resultats.append({
                "fichier": chemin.name,
                "num_players": payload.get("num_players"),
                "tour": payload.get("turn"),
                "ai_player_count": payload.get("ai_player_count"),
            })
        return resultats

    def lister_cartes(self) -> List[Dict[str, Any]]:
        if self.dossier_cartes is None:
            return []
        resultats = []
        for chemin in sorted(self.dossier_cartes.glob("*.json")):
            try:
                payload = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            # Les cartes anciennes n'ont pas de cle "kind" ; on ecarte juste
            # les sauvegardes de partie et les fichiers sans carte.
            if payload.get("kind") == "game" or not isinstance(payload.get("territories"), list):
                continue
            resultats.append({
                "fichier": chemin.name,
                "map_mode": payload.get("map_mode", "standard"),
                "territoires": len(payload["territories"]),
            })
        return resultats

    def _nouvel_id(self) -> str:
        with self._lock:
            self._compteur += 1
            return f"p{self._compteur}"

    @staticmethod
    def _chemin_sous(dossier: Optional[Path], fichier: str) -> Path:
        if dossier is None:
            raise FileNotFoundError(fichier)
        chemin = (dossier / fichier).resolve()
        if chemin.parent != dossier.resolve() or not chemin.is_file():
            raise FileNotFoundError(fichier)
        return chemin

    def ouvrir(self, fichier: str, seed: Optional[int] = None) -> SessionPartie:
        chemin = self._chemin_sous(self.dossier_sauvegardes, fichier)
        session = SessionPartie.depuis_fichier(self._nouvel_id(), chemin, seed=seed)
        self.parties[session.id] = session
        return session

    def creer(
        self,
        fichier_carte: str,
        num_players: int,
        ai_player_count: int,
        difficulty_level: str = "normal",
        tribes_mode: bool = False,
        seed: Optional[int] = None,
    ) -> SessionPartie:
        chemin = self._chemin_sous(self.dossier_cartes, fichier_carte)
        carte_payload = json.loads(chemin.read_text(encoding="utf-8"))
        session = SessionPartie.nouvelle(
            self._nouvel_id(), carte_payload, num_players, ai_player_count,
            difficulty_level=difficulty_level, tribes_mode=tribes_mode, seed=seed,
        )
        self.parties[session.id] = session
        return session

    def fermer(self, partie_id: str) -> bool:
        return self.parties.pop(partie_id, None) is not None
