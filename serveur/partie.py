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

from moteur import actions, regles
from moteur.etat import GameState

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
        """Un descriptif par joueur : humain/IA, actif, eliminable au lobby."""
        actifs = set(regles.get_active_players(self.state))
        return [
            {
                "joueur": player,
                "ia": regles.is_ai_player(self.state, player),
                "actif": player in actifs,
            }
            for player in range(self.state.num_players)
        ]

    def sieges_humains_libres(self, occupes: set) -> List[int]:
        actifs = set(regles.get_active_players(self.state))
        return [
            s["joueur"] for s in self.sieges()
            if not s["ia"] and s["joueur"] in actifs and s["joueur"] not in occupes
        ]

    def etat_reseau(self) -> Dict[str, Any]:
        """L'etat complet a diffuser aux clients, sans l'historique replay.

        L'historique (jusqu'a plusieurs centaines de Ko) ne sert qu'au mode
        replay local : il reste dans les sauvegardes mais pas sur le reseau.
        La clé ``phase`` s'ajoute au format canonique (qui ne la stocke pas :
        x45 ne sauvegarde qu'en phase de jeu) — le client doit distinguer
        "playing", "shopping" et "victory".
        """
        with self.lock:
            payload = self.state.to_payload()
            payload["phase"] = self.state.phase
        payload["replay_history"] = []
        return payload

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
        Ensuite les tours IA qui suivent sont joues dans la foulee, et leurs
        rapports sont joints au resultat.
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
            if outcome.ok:
                self._jouer_tours_ia(resultat)
            return resultat

    def jouer_tours_ia_en_attente(self) -> ResultatAction:
        """Joue les tours IA si c'est a une IA de jouer (ex. : au chargement).

        Retourne un resultat sans ``outcome`` (aucune action humaine) mais
        avec les rapports IA a diffuser ; ``ok=False``/``rien_a_jouer`` si ce
        n'etait pas a une IA.
        """
        with self.lock:
            resultat = ResultatAction(ok=True)
            if self.state.phase != "playing" or not regles.is_ai_player(
                self.state, self.state.current_player
            ):
                return ResultatAction(ok=False, code="rien_a_jouer")
            self._jouer_tours_ia(resultat)
            return resultat

    def _jouer_tours_ia(self, resultat: ResultatAction) -> None:
        """Enchaine les tours IA jusqu'au prochain humain (verrou deja pris)."""
        for _ in range(MAX_CONSECUTIVE_AI_TURNS):
            if self.state.phase != "playing":
                break
            if not regles.is_ai_player(self.state, self.state.current_player):
                break
            rapport = actions.play_ai_turn(
                self.state, self.cell_width, self.cell_height, self.rng,
            )
            resultat.rapports_ia.append(to_jsonable(rapport))
            if rapport.winner is not None:
                resultat.winner = rapport.winner
                resultat.winner_reason = rapport.winner_reason
                self.state.phase = "victory"
                break


class GestionnaireParties:
    """Les parties ouvertes du serveur + le catalogue des sauvegardes."""

    def __init__(self, dossier_sauvegardes: Path) -> None:
        self.dossier_sauvegardes = Path(dossier_sauvegardes)
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

    def ouvrir(self, fichier: str, seed: Optional[int] = None) -> SessionPartie:
        chemin = (self.dossier_sauvegardes / fichier).resolve()
        if chemin.parent != self.dossier_sauvegardes.resolve() or not chemin.is_file():
            raise FileNotFoundError(fichier)
        with self._lock:
            self._compteur += 1
            partie_id = f"p{self._compteur}"
        session = SessionPartie.depuis_fichier(partie_id, chemin, seed=seed)
        self.parties[partie_id] = session
        return session

    def fermer(self, partie_id: str) -> bool:
        return self.parties.pop(partie_id, None) is not None
