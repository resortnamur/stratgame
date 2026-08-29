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
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from moteur import actions, mise_en_place, regles
from moteur.etat import GameState

from .joueurs import RegistreJoueurs
from .stockage import (
    StockageFichiers, StockageMixte, assainir_nom, nom_est_valide,
    stockage_postgres,
)

# Dimensions logiques d'une cellule, heritees de la zone de carte de x45
# (1200 x 620 pixels) : la geometrie des ponts est exprimee en pixels dans
# les sauvegardes, on garde donc le meme repere que x45 et les tests.
LOGICAL_MAP_WIDTH = 1200.0
LOGICAL_MAP_HEIGHT = 620.0

# Garde-fou pour l'enchainement des tours IA (une partie 100 % IA joue
# jusqu'a la victoire : on plafonne large, bien au-dela d'une partie reelle).
MAX_CONSECUTIVE_AI_TURNS = 2000

# Sauvegardes automatiques de securite : prefixe reserve et nombre maximal
# conserve (les plus anciennes sont supprimees au fur et a mesure — les
# sauvegardes nommees par les joueurs ne sont jamais touchees).
PREFIXE_SAUVEGARDE_AUTO = "auto_"
MAX_SAUVEGARDES_AUTO = 10


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

    def __init__(self, partie_id: str, state: GameState, source: Optional[str] = None,
                 seed: Optional[int] = None, stockage=None) -> None:
        self.id = partie_id
        self.state = state
        # ``source`` est le nom du document d'origine dans ``stockage``
        # (module ``stockage``) : la sauvegarde par defaut y retourne.
        self.source = source
        self.stockage = stockage
        # Nom de la sauvegarde automatique de securite de cette session
        # (attribue par le gestionnaire ; None = pas de sauvegarde auto).
        self.nom_auto: Optional[str] = None
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
        """Charge une sauvegarde depuis un fichier (usage local et tests)."""
        chemin = Path(chemin)
        return cls.depuis_stockage(
            partie_id, StockageFichiers(chemin.parent), chemin.name, seed=seed,
        )

    @classmethod
    def depuis_stockage(cls, partie_id: str, stockage, nom: str,
                        seed: Optional[int] = None) -> "SessionPartie":
        """Charge une sauvegarde x45/moteur et applique les sanitisations."""
        contenu = stockage.lire(nom)
        if contenu is None:
            raise FileNotFoundError(nom)
        payload = json.loads(contenu)
        state = GameState.from_payload(payload)
        session = cls(partie_id, state, source=nom, seed=seed, stockage=stockage)
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
        simple_mode: bool = False,
        seed: Optional[int] = None,
    ) -> "SessionPartie":
        """Cree une partie neuve depuis une carte (miroir de start_game_session).

        Le premier tour est demarre (``begin_player_turn``), comme dans x45 ;
        si le joueur 0 est une IA, l'appelant declenche ensuite
        ``jouer_tours_ia_en_attente``.

        ``simple_mode`` : version simplifiee, uniquement basee sur le combat
        (ni boutique, ni economie, ni capitales — voir
        ``mise_en_place.nouvelle_partie``).
        """
        rng = random.Random(seed)
        state = mise_en_place.nouvelle_partie(
            carte_payload, num_players, ai_player_count,
            difficulty_level=difficulty_level, tribes_mode=tribes_mode,
            simple_mode=simple_mode, rng=rng,
        )
        session = cls(partie_id, state, source=None, seed=None)
        session.rng = rng
        actions.begin_player_turn(state, state.current_player, rng)
        return session

    def sauvegarder(self, cible=None) -> str:
        """Ecrit la partie au format canonique (schema v13, comme x45).

        ``cible`` : un nom de document dans le stockage de la session (par
        defaut : le document d'origine), ou un ``Path`` explicite (usage
        local et tests — la session bascule alors sur ce dossier).
        Retourne le nom du document ecrit.
        """
        if isinstance(cible, Path):
            self.stockage = StockageFichiers(cible.parent)
            nom = cible.name
        elif cible is not None:
            nom = assainir_nom(cible)
        else:
            nom = self.source
        if nom is None or self.stockage is None:
            raise ValueError("Aucun fichier cible pour la sauvegarde.")
        with self.lock:
            payload = self.state.to_payload()
        self.stockage.ecrire(nom, json.dumps(payload, ensure_ascii=False))
        self.source = nom
        return nom

    def preparer_sauvegarde_auto(self) -> None:
        """Attribue le nom de la sauvegarde automatique de cette session.

        Un nom neuf a chaque ouverture (horodate, donc trie du plus ancien
        au plus recent) : la rotation elimine naturellement les copies des
        sessions passees.
        """
        horodatage = time.strftime("%Y%m%d-%H%M%S")
        self.nom_auto = f"{PREFIXE_SAUVEGARDE_AUTO}{horodatage}_{self.id}.json"

    def sauvegarder_auto(self) -> Optional[str]:
        """Ecrit la sauvegarde de securite et fait tourner les anciennes.

        Contrairement a ``sauvegarder``, ne touche pas ``source`` : la
        sauvegarde manuelle garde sa cible. Retourne le nom ecrit, ou None
        si la session n'a pas de sauvegarde automatique.
        """
        if self.stockage is None or self.nom_auto is None:
            return None
        with self.lock:
            payload = self.state.to_payload()
        self.stockage.ecrire(self.nom_auto, json.dumps(payload, ensure_ascii=False))
        # Rotation : seuls les documents ``auto_*`` sont candidats — jamais
        # les sauvegardes nommees par les joueurs ni celles du depot.
        automatiques = sorted(
            nom for nom in self.stockage.lister()
            if nom.startswith(PREFIXE_SAUVEGARDE_AUTO) and nom != self.nom_auto
        )
        excedent = len(automatiques) - (MAX_SAUVEGARDES_AUTO - 1)
        for nom in automatiques[:max(0, excedent)]:
            self.stockage.supprimer(nom)
        return self.nom_auto

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

    def definir_mode_auto(self, joueur: Any, actif: bool) -> tuple:
        """Confie le siege ``joueur`` a l'IA (``actif``) ou lui rend la main.

        Retourne ``(ok, code)``. Seuls les sieges humains d'origine se
        basculent : les IA de base et l'ONU restent au moteur
        (``siege_indisponible``). Redemander le mode courant reussit
        (idempotent). Si le joueur confie son propre tour de boutique a
        l'IA, la partie revient en phase de jeu : l'IA ne fait pas
        d'achats en cours de tour (elle achete en fin de tour), la
        boucle des tours IA peut alors prendre le relais.
        """
        with self.lock:
            state = self.state
            if state.phase not in ("playing", "shopping"):
                return (False, "partie_terminee")
            if (
                not isinstance(joueur, int) or isinstance(joueur, bool)
                or not 0 <= joueur < state.num_players
                or joueur in state.base_ai_players
                or regles.is_onu_player(state, joueur)
            ):
                return (False, "siege_indisponible")
            actif = bool(actif)
            if actif == regles.is_ai_player(state, joueur):
                return (True, "ok")
            regles.set_auto_mode_for_player(state, joueur, actif, self.rng)
            if actif and joueur == state.current_player and state.phase == "shopping":
                state.phase = "playing"
            return (True, "ok")

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
            # Le nom du document d'origine, pour preremplir la sauvegarde
            # manuelle cote client.
            payload["source"] = self.source
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

    def bilans(self) -> Dict[str, Any]:
        """L'état des lieux de chaque joueur actif (panneau empire de x45).

        Tout est calculé par les règles du moteur : aménagements possédés,
        bonus, conditions d'accès au statut de nation (bloc d'un seul
        tenant, structures requises, capitale, délai de conservation) et
        progression vers la victoire.
        """
        with self.lock:
            state = self.state
            total = len(state.territories)
            seuil = (total * 3 + 3) // 4  # 3/4 arrondi supérieur, comme x45
            bilans = {}
            for joueur in regles.get_active_players(state):
                possessions = {t.id for t in state.territories if t.owner == joueur}
                regiments = sum(t.regiments for t in state.territories if t.owner == joueur)
                amenagements = {
                    "forteresses": len(state.fortress_territory_ids & possessions),
                    "usines": len(state.factory_territory_ids & possessions),
                    "aeroports": len(state.airport_territory_ids & possessions),
                    "ports": len(state.port_territory_ids & possessions),
                    "temples": len(state.temple_territory_ids & possessions),
                    "centres_culturels": sum(
                        1 for tid in possessions
                        if regles.get_cultural_center_count(state, tid) > 0
                    ),
                    "universites": len(state.university_territory_ids & possessions),
                }
                amenagements["total"] = sum(amenagements.values())
                # Une ruine n'est pas un amenagement bati : elle reste hors du
                # total, comme dans le panneau empire de x45.
                amenagements["ruines"] = len(state.ruin_territory_ids & possessions)
                bonus = {}
                for territoire in state.territories:
                    if territoire.owner == joueur and territoire.reinforcement_bonus > 1:
                        cle = f"+{territoire.reinforcement_bonus}"
                        bonus[cle] = bonus.get(cle, 0) + 1
                bilans[str(joueur)] = {
                    "territoires": len(possessions),
                    "regiments": regiments,
                    "amenagements": amenagements,
                    "bonus": bonus,
                    "mines": len(set(state.precious_mineral_mine_ids) & possessions),
                    "dores": len(set(state.golden_territory_ids) & possessions),
                    "nation": self._bilan_nation(joueur, possessions),
                    "religion": self._bilan_religion(joueur),
                    "points_victoire": regles.get_victory_points(state, joueur),
                    "culture": self._bilan_domination(
                        joueur, regles.calculate_player_culture,
                        regles.CULTURE_VICTORY_RATIO, regles.AI_CULTURE_VICTORY_RATIO,
                        regles.CULTURE_VICTORY_MIN_POINTS,
                    ),
                    "science": self._bilan_domination(
                        joueur, regles.get_player_science,
                        regles.SCIENCE_VICTORY_RATIO, regles.AI_SCIENCE_VICTORY_RATIO,
                        regles.SCIENCE_VICTORY_MIN_POINTS,
                    ),
                }
            return {
                "bilans": bilans,
                "total_territoires": total,
                "seuil_trois_quarts": seuil,
                "nb_dores": len(state.golden_territory_ids),
                # Qui approche d'une victoire, par quelque moyen que ce soit.
                "menaces": regles.get_victory_threats(state),
                # Les paliers deja franchis : chacun ferme une condition.
                "paliers": [dict(palier) for palier in state.victory_milestones],
                "nb_conditions": len(regles.VICTORY_CONDITIONS),
            }

    def _bilan_domination(
        self, joueur: int, mesure, facteur_humain: int, facteur_ia: int, plancher: int,
    ) -> Dict[str, Any]:
        """La progression vers une victoire de domination (verrou deja pris).

        Culture et science suivent la meme regle : ecraser le meilleur rival
        d'un facteur 20 (10 pour une IA) et depasser un plancher, sans quoi
        un rival a zero donnerait la victoire des le premier tour.
        """
        state = self.state
        points = mesure(state, joueur)
        rivaux = [
            autre for autre in regles.get_active_players(state)
            if autre != joueur and not regles.is_onu_player(state, autre)
        ]
        meilleur_rival = max((mesure(state, autre) for autre in rivaux), default=0)
        facteur = facteur_ia if regles.is_ai_player(state, joueur) else facteur_humain
        return {
            "points": points,
            "facteur": facteur,
            "meilleur_rival": meilleur_rival,
            "requis": max(plancher, facteur * meilleur_rival),
        }

    def _bilan_religion(self, joueur: int) -> Optional[Dict[str, Any]]:
        """La progression vers la victoire religieuse (verrou deja pris).

        ``None`` tant que le joueur n'a pas fonde de religion nationale : la
        religion de la merveille ne compte pas.
        """
        state = self.state
        religion_id = regles.get_player_national_religion_id(state, joueur)
        if religion_id is None:
            return None
        return {
            "nom": regles.get_religion_name(state, religion_id),
            "influence": regles.get_religion_influence_count(state, religion_id),
            "requis": regles.get_required_influence_count_for_religion_victory(
                state, joueur,
            ),
        }

    def _bilan_nation(self, joueur: int, possessions: set) -> Dict[str, Any]:
        """Les conditions de nation pour un joueur (verrou déjà pris)."""
        state = self.state
        composantes = regles.get_owned_components(state, joueur)
        candidates = [
            c for c in composantes if len(c) >= regles.NATION_MIN_TERRITORIES
        ]
        sortes_par_composante = {
            id(c): self._sortes_structures(c) for c in composantes
        }
        # Le bloc le plus prometteur : parmi les assez grands, celui qui a le
        # plus de sortes de structures ; sinon le plus grand tout court.
        cible = max(
            candidates or composantes,
            key=lambda c: (sum(sortes_par_composante[id(c)].values()), len(c)),
            default=[],
        )
        sortes = self._sortes_structures(cible)
        manquantes = [nom for nom, present in sortes.items() if not present]
        est_nation = joueur in state.nation_players
        depart = state.nation_qualification_start_turns.get(joueur)
        if est_nation:
            tours_restants = 0
        elif depart is not None:
            tours_restants = max(
                0, regles.NATION_QUALIFICATION_DELAY_TURNS - (state.turn - depart),
            )
        else:
            tours_restants = regles.NATION_QUALIFICATION_DELAY_TURNS
        conditions_extra = []
        via_capitole = False
        if "aurelia_capitol" in state.wonder_territories:
            via_capitole = regles.player_qualifies_for_nation_via_capitol(state, joueur)
            conditions_extra.append({
                "libelle": "Voie culturelle : capitale sur le Capitole d'Aurelia",
                "ok": via_capitole,
                "detail": (
                    "remplace toutes les autres conditions, sans délai"
                    if via_capitole else "y poser sa capitale suffit"
                ),
            })
        return {
            "est_nation": est_nation,
            "taille_bloc": len(cible),
            "conditions": conditions_extra + [
                {
                    "libelle": f"Un bloc d'au moins {regles.NATION_MIN_TERRITORIES} territoires d'un seul tenant",
                    "ok": len(cible) >= regles.NATION_MIN_TERRITORIES,
                    "detail": f"{len(cible)}/{regles.NATION_MIN_TERRITORIES}",
                },
                {
                    "libelle": "Toutes les structures dans ce bloc",
                    "ok": not manquantes,
                    "detail": "complètes" if not manquantes else "manque : " + ", ".join(manquantes),
                },
                {
                    "libelle": "Capitale active dans ce bloc",
                    "ok": bool(cible) and regles.component_has_active_regular_capital(
                        state, joueur, cible,
                    ),
                    "detail": "",
                },
                {
                    "libelle": f"Conserver le tout {regles.NATION_QUALIFICATION_DELAY_TURNS} tours",
                    "ok": est_nation or via_capitole,
                    "detail": (
                        "acquis" if est_nation
                        else "sans objet : le Capitole dispense du délai" if via_capitole
                        else f"{tours_restants} tour(s) restant(s)"
                    ),
                },
            ],
        }

    def _sortes_structures(self, composante: List[int]) -> Dict[str, bool]:
        """Les 7 sortes de structures requises présentes dans un bloc."""
        state = self.state
        bloc = set(composante)
        return {
            "forteresse": bool(state.fortress_territory_ids & bloc),
            "usine": bool(state.factory_territory_ids & bloc),
            "port": bool(state.port_territory_ids & bloc),
            "aéroport": bool(state.airport_territory_ids & bloc),
            "temple": bool(state.temple_territory_ids & bloc),
            "centre culturel": any(
                regles.get_cultural_center_count(state, tid) > 0 for tid in bloc
            ),
            "université": bool(state.university_territory_ids & bloc),
        }

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
                "simple_mode": bool(self.state.simple_mode),
                "sieges": self.sieges(),
                "source": self.source,
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

    def apercu_expedition(self, source: Any, cible: Any) -> Dict[str, Any]:
        """L'apercu d'une expedition maritime (encart de confirmation).

        Lecture seule : distance de la route maritime et chances du de a
        64 faces. ``possible=False`` avec un code si l'expedition est
        impossible (territoires invalides, pas d'etendue d'eau commune,
        cible voisine ou alliee...).
        """
        with self.lock:
            state = self.state
            try:
                source = int(source)
                cible = int(cible)
            except (TypeError, ValueError):
                return {"possible": False, "code": "territoire_invalide"}
            if not (0 <= source < len(state.territories) and 0 <= cible < len(state.territories)):
                return {"possible": False, "code": "territoire_invalide"}
            apercu = regles.get_expedition_preview(
                state, state.territories[source], state.territories[cible],
                self.cell_width, self.cell_height,
            )
            if apercu is None:
                return {"possible": False, "code": "expedition_invalide"}
            return {"possible": True, **apercu}

    def apercu_transport(self, source: Any, cible: Any, regiments: Any = 1) -> Dict[str, Any]:
        """L'apercu d'un transport maritime de fin de tour.

        Lecture seule : distance, nombre de regiments retenu, maximum
        embarquable et chances du de a 64 faces, pour l'encart
        « Entreprendre un voyage a travers les oceans ? ». ``possible=False``
        avec un code si le transport est impossible (territoires invalides,
        destination qui n'est pas a moi, deja reliee par la terre, aucune
        etendue d'eau commune, quota de deplacements epuise...).
        """
        with self.lock:
            state = self.state
            try:
                source = int(source)
                cible = int(cible)
            except (TypeError, ValueError):
                return {"possible": False, "code": "territoire_invalide"}
            if not (0 <= source < len(state.territories) and 0 <= cible < len(state.territories)):
                return {"possible": False, "code": "territoire_invalide"}
            apercu = regles.get_sea_transport_preview(
                state, state.territories[source], state.territories[cible], regiments,
                self.cell_width, self.cell_height,
            )
            if apercu is None:
                return {"possible": False, "code": "transport_invalide"}
            return {"possible": True, **apercu}

    def consommer_modale_evenements(self, joueur: Optional[int]) -> Tuple[bool, str]:
        """Retire l'encart d'evenements courant (bouton « Compris » du client).

        Seul le joueur au trait peut le consommer : l'encart lui est destine
        (il est cree au debut de son tour ou pendant celui-ci). S'il reste
        des encarts en file, le suivant prend la place.
        """
        with self.lock:
            if joueur is None or joueur != self.state.current_player:
                return (False, "pas_votre_tour")
            if self.state.major_event_modal is None:
                return (False, "aucune_modale")
            if self.state.major_event_modal_queue:
                self.state.major_event_modal = self.state.major_event_modal_queue.pop(0)
            else:
                self.state.major_event_modal = None
            return (True, "ok")

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
        fin de tour joues, rapport complet du tour). Si le joueur du tour
        a repris la main entre deux passes (mode auto desactive), le
        deroule est abandonne : ``(None, resultat)`` avec le code
        ``tour_repris``, l'etat restant coherent (c'est a lui de jouer).
        """
        with self.lock:
            if (
                self._joueur_ia is not None
                and self.state.current_player == self._joueur_ia
                and not regles.is_ai_player(self.state, self._joueur_ia)
            ):
                self._pas_ia = None
                return None, ResultatAction(
                    ok=True, code="tour_repris", joueur_ia=self._joueur_ia,
                )
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
    """Les parties ouvertes du serveur + les catalogues (sauvegardes, cartes).

    Les catalogues vivent dans des stockages (module ``stockage``) : des
    dossiers de fichiers en local ; avec ``database_url``, les fichiers du
    depot restent lisibles et tout ce que les joueurs ecrivent (sauvegardes,
    cartes importees, registre) va en base — le disque des hebergeurs
    gratuits ne survit pas aux redemarrages.
    """

    # Taille maximale d'une carte importee (les plus grosses cartes du depot
    # font ~400 Ko : 5 Mo laissent de la marge sans ouvrir la porte a tout).
    TAILLE_CARTE_MAX = 5_000_000

    def __init__(self, dossier_sauvegardes: Path, dossier_cartes: Optional[Path] = None,
                 fichier_joueurs: Optional[Path] = None,
                 database_url: Optional[str] = None,
                 sauvegarde_auto: bool = True) -> None:
        # ``sauvegarde_auto=False`` (tests) : les parties ouvertes n'ecrivent
        # aucune sauvegarde de securite.
        self.sauvegarde_auto = bool(sauvegarde_auto)
        base_sauvegardes = StockageFichiers(Path(dossier_sauvegardes))
        base_cartes = (
            StockageFichiers(Path(dossier_cartes)) if dossier_cartes is not None else None
        )
        if database_url:
            self.stockage_sauvegardes = StockageMixte(
                base_sauvegardes, stockage_postgres(database_url, "sauvegardes"),
            )
            self.stockage_cartes = StockageMixte(
                base_cartes, stockage_postgres(database_url, "cartes"),
            )
            self.registre = RegistreJoueurs(
                stockage=stockage_postgres(database_url, "config"),
            )
        else:
            self.stockage_sauvegardes = base_sauvegardes
            self.stockage_cartes = base_cartes
            # Le registre vit a cote du dossier des sauvegardes, pas dedans :
            # x45 et les tests sondent tous les .json de parties_en_cours.
            self.registre = RegistreJoueurs(
                fichier_joueurs if fichier_joueurs is not None
                else Path(dossier_sauvegardes).parent / "joueurs.json"
            )
        self.parties: Dict[str, SessionPartie] = {}
        self._compteur = 0
        self._lock = threading.Lock()
        # Metadonnees de catalogue par nom, gardees tant que la version du
        # document ne change pas : le lobby ne relit pas des Mo de JSON (ni
        # la base) a chaque affichage.
        self._meta_sauvegardes: Dict[str, tuple] = {}
        self._meta_cartes: Dict[str, tuple] = {}

    @staticmethod
    def _meta_sauvegarde(nom: str, payload: dict) -> Optional[Dict[str, Any]]:
        if payload.get("kind") != "game":
            return None
        return {
            "fichier": nom,
            "num_players": payload.get("num_players"),
            "tour": payload.get("turn"),
            "ai_player_count": payload.get("ai_player_count"),
        }

    @staticmethod
    def _meta_carte(nom: str, payload: dict) -> Optional[Dict[str, Any]]:
        # Les cartes anciennes n'ont pas de cle "kind" ; on ecarte juste
        # les sauvegardes de partie et les fichiers sans carte.
        if payload.get("kind") == "game" or not isinstance(payload.get("territories"), list):
            return None
        return {
            "fichier": nom,
            "map_mode": payload.get("map_mode", "standard"),
            "territoires": len(payload["territories"]),
        }

    def _lister_catalogue(self, stockage, cache: Dict[str, tuple],
                          extraire) -> List[Dict[str, Any]]:
        if stockage is None:
            return []
        versions = stockage.versions()
        for nom in list(cache):
            if nom not in versions:
                del cache[nom]
        resultats = []
        for nom in sorted(versions):
            entree = cache.get(nom)
            if entree is None or entree[0] != versions[nom]:
                meta = None
                contenu = stockage.lire(nom)
                if contenu is not None:
                    try:
                        payload = json.loads(contenu)
                    except ValueError:
                        payload = None
                    if isinstance(payload, dict):
                        meta = extraire(nom, payload)
                cache[nom] = (versions[nom], meta)
            meta = cache[nom][1]
            if meta is not None:
                resultats.append(dict(meta))
        return resultats

    def lister_sauvegardes(self) -> List[Dict[str, Any]]:
        return self._lister_catalogue(
            self.stockage_sauvegardes, self._meta_sauvegardes, self._meta_sauvegarde,
        )

    def lister_cartes(self) -> List[Dict[str, Any]]:
        return self._lister_catalogue(
            self.stockage_cartes, self._meta_cartes, self._meta_carte,
        )

    def _nouvel_id(self) -> str:
        with self._lock:
            self._compteur += 1
            return f"p{self._compteur}"

    def ouvrir(self, fichier: str, seed: Optional[int] = None) -> SessionPartie:
        if not nom_est_valide(fichier):
            raise FileNotFoundError(fichier)
        session = SessionPartie.depuis_stockage(
            self._nouvel_id(), self.stockage_sauvegardes, fichier, seed=seed,
        )
        if self.sauvegarde_auto:
            session.preparer_sauvegarde_auto()
        self.parties[session.id] = session
        return session

    def creer(
        self,
        fichier_carte: str,
        num_players: int,
        ai_player_count: int,
        difficulty_level: str = "normal",
        tribes_mode: bool = False,
        simple_mode: bool = False,
        seed: Optional[int] = None,
    ) -> SessionPartie:
        contenu = (
            self.stockage_cartes.lire(fichier_carte)
            if self.stockage_cartes is not None else None
        )
        if contenu is None:
            raise FileNotFoundError(fichier_carte)
        carte_payload = json.loads(contenu)
        session = SessionPartie.nouvelle(
            self._nouvel_id(), carte_payload, num_players, ai_player_count,
            difficulty_level=difficulty_level, tribes_mode=tribes_mode,
            simple_mode=simple_mode, seed=seed,
        )
        # Les sauvegardes futures de cette partie neuve iront au catalogue.
        session.stockage = self.stockage_sauvegardes
        if self.sauvegarde_auto:
            session.preparer_sauvegarde_auto()
        self.parties[session.id] = session
        return session

    def creer_depuis_payload(
        self,
        carte_payload: Any,
        num_players: int,
        ai_player_count: int,
        difficulty_level: str = "normal",
        tribes_mode: bool = False,
        simple_mode: bool = False,
        seed: Optional[int] = None,
    ) -> SessionPartie:
        """Cree une partie depuis une carte fournie en ligne (non cataloguee).

        C'est le chemin des cartes aleatoires generees par le lobby : la
        carte accompagne la creation de la partie sans passer par le
        catalogue ``cartes_sauvegardees``. Memes garde-fous que
        ``importer_carte`` : taille bornee et carte que le moteur sait
        vraiment charger (``ValueError('carte_invalide')`` sinon).
        """
        if not isinstance(carte_payload, dict):
            raise ValueError("carte_invalide")
        if len(json.dumps(carte_payload, ensure_ascii=False)) > self.TAILLE_CARTE_MAX:
            raise ValueError("carte_trop_grosse")
        try:
            GameState.from_map_payload(carte_payload)
        except Exception:
            raise ValueError("carte_invalide")
        session = SessionPartie.nouvelle(
            self._nouvel_id(), carte_payload, num_players, ai_player_count,
            difficulty_level=difficulty_level, tribes_mode=tribes_mode,
            simple_mode=simple_mode, seed=seed,
        )
        session.stockage = self.stockage_sauvegardes
        if self.sauvegarde_auto:
            session.preparer_sauvegarde_auto()
        self.parties[session.id] = session
        return session

    def importer_carte(self, nom: Any, payload: Any, remplacer: bool = False) -> Dict[str, Any]:
        """Valide et range une carte fournie par un client (lobby).

        Refus par ``ValueError`` : ``nom_fichier_invalide``,
        ``carte_invalide`` (le moteur ne sait pas la charger),
        ``carte_trop_grosse``, ``carte_existante`` (sans ``remplacer``).
        Retourne la fiche catalogue de la carte rangee.
        """
        nom = assainir_nom(nom)
        meta = (
            self._meta_carte(nom, payload) if isinstance(payload, dict) else None
        )
        if meta is None or not meta["territoires"] or self.stockage_cartes is None:
            raise ValueError("carte_invalide")
        contenu = json.dumps(payload, ensure_ascii=False)
        if len(contenu) > self.TAILLE_CARTE_MAX:
            raise ValueError("carte_trop_grosse")
        try:
            # La carte doit vraiment se charger : geometrie, voisins, liens.
            GameState.from_map_payload(payload)
        except Exception:
            raise ValueError("carte_invalide")
        if not remplacer and self.stockage_cartes.lire(nom) is not None:
            raise ValueError("carte_existante")
        self.stockage_cartes.ecrire(nom, contenu)
        return meta

    def fermer(self, partie_id: str) -> bool:
        return self.parties.pop(partie_id, None) is not None
