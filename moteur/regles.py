"""Regles pures du jeu, operant sur GameState (etape 1b de la migration).

Chaque fonction est le miroir fidele d'une methode de x45.py (GraphicalGame),
transposee en fonction de module prenant l'etat en premier argument. Cette
premiere tranche couvre les *sanitisations executees au chargement d'une
sauvegarde* (x45 : fin de ``apply_saved_game_state``), afin que la parite
moteur/x45 devienne totale.

Points de fidelite :
- ``sanitize_after_load`` reproduit exactement la sequence x45 (lignes
  1506-1518), y compris la mise en attente du statut paradis fiscal pendant
  ``sanitize_economy_state`` puis sa restauration avant
  ``refresh_last_stand_bonus_state``.
- ``get_commercial_city_capital_id`` reprend la version *avec* mise en cache
  de x45 (a la difference de la variante de lecture seule de etat.py), car les
  sanitisations dependent de cet effet de bord.
- Les mecaniques abandonnees (vassaux) restent des coquilles vides, comme
  dans x45.
- L'aleatoire est injectable via ``rng`` (module ``random`` par defaut) pour
  permettre des tests deterministes et, plus tard, un serveur reproductible.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .etat import GameState, MAX_REPLAY_SNAPSHOTS, Territory, sanitize_major_event_modal

# ----------------------------------------------------------------------
# Constantes de regles (miroir des attributs de classe de x45)
# ----------------------------------------------------------------------

MAX_CULTURAL_CENTERS_PER_TERRITORY = 1
# La ruine que laisse un centre culturel detruit : un rendement fixe, sans
# rapport avec les voisins du territoire ni avec l'anciennete du batiment.
RUIN_INCOME = 20
RUIN_CULTURE = 5
INITIAL_CAPITAL_REGIMENTS = 6

RELIGIONS = [
    {"name": "Auralis", "symbol": "A*", "color": (244, 208, 63)},
    {"name": "Noctyra", "symbol": "N)", "color": (165, 105, 189)},
    {"name": "Veridia", "symbol": "V^", "color": (88, 214, 141)},
    {"name": "Pyronis", "symbol": "P!", "color": (236, 112, 99)},
    {"name": "Mareon", "symbol": "M~", "color": (84, 153, 199)},
    {"name": "Elyrion", "symbol": "E+", "color": (174, 235, 255)},
    {"name": "Solmyre", "symbol": "S#", "color": (255, 170, 80)},
]
WONDER_RELIGION_ID = 5
SECOND_WONDER_RELIGION_ID = 6
# Les deux religions conquerantes recouvrent toutes les autres, mais
# jamais l'une l'autre : chacune est le seul rempart contre sa jumelle.
WONDER_RELIGION_IDS = (WONDER_RELIGION_ID, SECOND_WONDER_RELIGION_ID)
WONDER_RELIGION_SOURCES = {
    WONDER_RELIGION_ID: "elyrion_sanctuary",
    SECOND_WONDER_RELIGION_ID: "solmyre_oracle",
}
WONDER_DEFINITIONS = {
    "elyrion_sanctuary": {
        "name": "Sanctuaire d'Elyrion",
        "effect": "Fonde Elyrion, religion conquerante liee au territoire",
        "kind": "science",
    },
    "thousand_voices_theatre": {
        "name": "Theatre des Mille Voix",
        "effect": "Double la culture de son controleur",
        "kind": "science",
    },
    "atlas_observatory": {
        "name": "Observatoire d'Atlas",
        "effect": "Double la science effective de son controleur",
        "kind": "science",
    },
    "golden_pact_palace": {
        "name": "Palais du Pacte d'Or",
        "effect": "Fait de son controleur l'unique allie de la Cite commercante",
        "kind": "science",
    },
    # Merveilles culturelles : memes regles d'exclusivite (une seule
    # merveille par territoire, chaque merveille unique sur la carte),
    # mais debloquees par la culture plutot que par la science.
    "ivory_rampart": {
        "name": "Rempart d'Ivoire",
        "effect": "Protege ce territoire de toute attaque des joueurs IA",
        "kind": "culture",
    },
    "croesus_fountain": {
        "name": "Fontaine de Cresus",
        "effect": "Multiplie par 5 l'argent produit par ce territoire",
        "kind": "culture",
    },
    "aurelia_capitol": {
        "name": "Capitole d'Aurelia",
        "effect": "Donne aussitot le statut de nation si la capitale de son proprietaire s'y trouve, sans aucune autre condition",
        "kind": "culture",
    },
    "daedalus_forge": {
        "name": "Forge de Dedale",
        "effect": "Ponts construits ou detruits gratuitement depuis ce territoire",
        "kind": "culture",
    },
    # Merveilles tardives : ni science ni culture requises, mais elles
    # n'apparaissent qu'au tour LATE_WONDER_FIRST_TURN, et leur prix
    # depend de qui les batit (cf. get_wonder_cost).
    "solmyre_oracle": {
        "name": "Oracle de Solmyre",
        "effect": "Fonde Solmyre, seconde religion conquerante ; seule Elyrion lui resiste",
        "kind": "late",
    },
    "kaleth_gardens": {
        "name": "Jardins de Kaleth",
        "effect": "Rapporte chaque tour 50 points de culture et 50 ecus a son controleur",
        "kind": "late",
    },
    "selene_dome": {
        "name": "Dome de Selene",
        "effect": "Protege des missiles tous les territoires de son controleur",
        "kind": "late",
    },
    "orvane_oath": {
        "name": "Serment d'Orvane",
        "effect": "Le prochain joueur ne en cours de partie devient l'allie definitif de son controleur",
        "kind": "late",
    },
}

AI_PROFILES = ["standard", "aggressive", "defensive", "variable"]

CAPITAL_INCOME_MULTIPLIER = 10
NATION_INCOME_DIVISOR = 10
PRECIOUS_MINERAL_MINE_INCOME = 100
RELIGIOUS_INCOME_BONUS_PER_TERRITORY = 2
RELIGIOUS_REINFORCEMENT_TERRITORIES_PER_BONUS = 3
# Victoire culturelle : ecraser la culture de tous ses rivaux. Le rapport ne
# suffit pas — un adversaire a zero rendrait la victoire immediate — d'ou le
# plancher de culture a atteindre en plus.
CULTURE_VICTORY_RATIO = 20
AI_CULTURE_VICTORY_RATIO = 10
CULTURE_VICTORY_MIN_POINTS = 100
# Victoire scientifique : exactement la meme mecanique que la culture.
SCIENCE_VICTORY_RATIO = 20
AI_SCIENCE_VICTORY_RATIO = 10
SCIENCE_VICTORY_MIN_POINTS = 100
# Victoire religieuse : part de la carte que la religion nationale doit couvrir.
NATIONAL_RELIGION_VICTORY_RATIO = 0.9
AI_NATIONAL_RELIGION_VICTORY_RATIO = 0.75
MAX_REINFORCEMENTS_PER_TURN = 10
MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS = 120
MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS_WITH_BONUS_5 = 200
AI_REINFORCEMENT_BONUS_STAGES = (
    (33, 1),
    (41, 2),
    (49, 3),
    (57, 4),
    (65, 5),
)
MAX_END_TURN_MOVES = 5
EXPANDED_END_TURN_MOVES = 10
EXPANDED_END_TURN_MOVE_TERRITORY_THRESHOLD = 10
SCIENCE_ATTACK_4_DICE_THRESHOLD = 500
CULTURE_ADVANTAGE_THRESHOLD = 15
SPECIAL_CAPTURE_LIMIT = 3
TAX_HAVEN_LOSS_TERRITORY_THRESHOLD = 10
AI_NATION_SUBMISSION_DENOMINATOR = 100
NATION_MIN_TERRITORIES = 10
NATION_QUALIFICATION_DELAY_TURNS = 10
NATION_CAPITAL_LOSS_DELAY_TURNS = 10
# Une masse de terre de moins de dix territoires est une ile isolee : une IA
# qui y garde sa capitale ne pourra jamais former son bloc national, elle
# cherche donc a demenager sur un continent des qu'elle y possede un
# territoire (meme seuil que NATION_MIN_TERRITORIES : c'est la meme raison).
AI_MAINLAND_MIN_TERRITORIES = 10
ALLIANCE_DURATION_TURNS = 10
AI_NATION_ALLIANCE_DENOMINATOR = 20
AI_MOBILIZATION_DENOMINATOR = 100
SEDITION_DENOMINATOR = 50000
SUBMITTED_TERRITORY_INSTABILITY_DENOMINATOR = 40
SUBMITTED_TERRITORY_INTEGRATION_DELAY_TURNS = 20
# Ressources tardives : trois de chaque sorte, et pas une de plus. Chacune
# s'epuise au bout de LATE_RESOURCE_LIFETIME_TURNS tours et reapparait
# aussitot sur un autre territoire tire au hasard : le compte reste constant,
# mais aucune position n'est acquise pour toujours.
BONUS_5_SPAWN_TURNS = (35, 43, 51)
PRECIOUS_MINERAL_MINE_SPAWN_TURNS = (37, 45, 53)
LATE_RESOURCE_LIFETIME_TURNS = 20
# Plafond par sorte. Il vaut aussi pour les parties commencees sous
# l'ancienne regle (quatre gisements) : le surnombre n'est pas remplace
# quand il s'epuise, la partie retombe d'elle-meme a trois.
LATE_RESOURCE_TARGET_COUNT = 3
BRIDGE_SPAWN_DENOMINATOR = 20
BRIDGE_COLLAPSE_DENOMINATOR = 30
# Version simplifiee : les forteresses ne s'achetent plus, elles ne peuvent
# donc que disparaitre (detruites apres trois captures). Une chance sur
# SIMPLE_FORTRESS_SPAWN_DENOMINATOR par tour global en repose une, tant qu'il
# en reste moins de SIMPLE_FORTRESS_TARGET_COUNT sur la carte.
SIMPLE_FORTRESS_TARGET_COUNT = 5
SIMPLE_FORTRESS_SPAWN_DENOMINATOR = 6
BRIDGE_MAX_LENGTH_PX = 76.0
# Expeditions maritimes : de a 64 faces tire a la traversee. Chaque palier
# de distance (en pixels de la carte logique 1200x620) donne le nombre de
# faces qui coutent 25/50/75/100 % de la flotte ; le reste des 64 faces
# laisse la traversee indemne. None = au-dela du dernier seuil.
EXPEDITION_DIE_FACES = 64
EXPEDITION_LOSS_PERCENTS = (25, 50, 75, 100)
EXPEDITION_RISK_TIERS = (
    (100.0, (16, 8, 4, 2)),
    (300.0, (20, 12, 8, 4)),
    (800.0, (32, 16, 8, 4)),
    (None, (32, 16, 8, 8)),
)
EXPEDITION_MAX_ATTACK_DICE = 2
EXPEDITION_AI_MIN_REGIMENTS = 20
EXPEDITION_AI_LAUNCH_DENOMINATOR = 10
# Au-dela de 300 px (le deuxieme palier de risque), les debarquements des IA
# echouaient trop souvent : elles s'interdisent les traversees plus longues.
EXPEDITION_AI_MAX_DISTANCE_PX = 300.0
# Les Cites commercantes n'embarquent pas avant ce tour : leurs expeditions
# de debut de partie etaient trop punitives pour les joueurs humains.
COMMERCIAL_CITY_EXPEDITION_FIRST_TURN = 50
RELIGION_SPREAD_INTERVAL_BY_TEMPLE_COUNT = {
    1: 30,
    2: 25,
    3: 20,
    4: 15,
    5: 10,
    6: 5,
    7: 1,
}
SCIENCE_WONDER_THRESHOLD = 100
AI_SCIENCE_WONDER_THRESHOLD = 50
CULTURE_WONDER_THRESHOLD = 50
AI_CULTURE_WONDER_THRESHOLD = 25
# Merveilles tardives : ouvertes a tous, mais seulement a partir de ce
# tour, et payantes selon la nature du batisseur.
LATE_WONDER_FIRST_TURN = 42
LATE_WONDER_COST = 500
AI_LATE_WONDER_COST = 300
TOURISM_WONDER_CULTURE = 50
TOURISM_WONDER_INCOME = 50
MERCENARY_COST = 50
FORTRESS_COST = 100
FACTORY_COST = 100
AIRPORT_COST = 100
PORT_COST = 100
CULTURAL_CENTER_COST = 200
UNIVERSITY_COST = 200
TEMPLE_COST = 300
WONDER_COST = 300
CHANGE_CAPITAL_COST = 300
# Une mission convertit un territoire quelconque a la religion nationale.
MISSION_COST = 200
CORRUPTION_COST_PER_REGIMENT = 200
REDUCED_CORRUPTION_COST_PER_REGIMENT = 40
CORRUPTION_FORTRESS_SURCHARGE = 400
CORRUPTION_INDUSTRIAL_SURCHARGE = 400
CORRUPTION_CULTURAL_CENTER_SURCHARGE = 800
CORRUPTION_BONUS_TERRITORY_SURCHARGE = 400


# ----------------------------------------------------------------------
# Version simplifiee
# ----------------------------------------------------------------------

def is_simple_mode(state) -> bool:
    """La partie est-elle en version simplifiee (uniquement le combat) ?

    ``getattr`` plutot qu'un acces direct : les regles s'appliquent aussi par
    duck typing a ``GraphicalGame`` (x45) et a d'anciennes sauvegardes, qui
    peuvent ne pas porter l'attribut.
    """
    return bool(getattr(state, "simple_mode", False))


# ----------------------------------------------------------------------
# Requetes de base sur les joueurs
# ----------------------------------------------------------------------

def is_onu_player(state: GameState, player: int) -> bool:
    return player == state.onu_player_id


def is_ai_player(state: GameState, player: int) -> bool:
    if player < 0 or is_onu_player(state, player):
        return False
    return (
        (player in state.base_ai_players or player in state.auto_controlled_players)
        and player not in state.human_controlled_players
    )


def is_human_player_id(state: GameState, player: int) -> bool:
    return 0 <= player < state.num_players and not is_ai_player(state, player)


def get_active_players(state: GameState) -> List[int]:
    return sorted({terr.owner for terr in state.territories if terr.owner >= 0})


def count_player_territories(state: GameState, player: int) -> int:
    return sum(1 for terr in state.territories if terr.owner == player)


def ensure_player_economy(state: GameState, player: int) -> None:
    if player >= 0 and player not in state.player_money:
        state.player_money[player] = 0


def assign_ai_personality_to_player(
    state: GameState, player: int, profile: Optional[str] = None, rng=random,
) -> None:
    state.ai_personalities[player] = profile if profile in AI_PROFILES else rng.choice(AI_PROFILES)
    state.ai_current_behavior.pop(player, None)


def get_ai_personality(state: GameState, player: int, rng=random) -> str:
    if player not in state.ai_personalities:
        assign_ai_personality_to_player(
            state, player,
            "standard" if player in state.auto_controlled_players else None,
            rng,
        )
    return state.ai_personalities.get(player, "standard")


def prepare_ai_behavior_for_turn(state: GameState, player: int, rng=random) -> None:
    """Fixe le comportement du tour : les profils "variable" retirent au sort."""
    profile = get_ai_personality(state, player, rng)
    if profile == "variable":
        state.ai_current_behavior[player] = rng.choice(["standard", "aggressive", "defensive"])
    else:
        state.ai_current_behavior[player] = profile


def set_auto_mode_for_player(state: GameState, player: int, enabled: bool, rng=random) -> None:
    """Bascule un joueur en mode IA (``enabled``) ou humain (miroir de x45).

    En mode IA le joueur recoit la personnalite "standard" ; au retour en
    mode humain, si c'est son tour, la phase revient a l'attaque (comme
    x45 : l'humain reprend son tour depuis le debut).
    """
    if player < 0 or is_onu_player(state, player):
        return
    if enabled:
        state.human_controlled_players.discard(player)
        if player not in state.base_ai_players:
            state.auto_controlled_players.add(player)
        assign_ai_personality_to_player(state, player, "standard", rng)
    else:
        state.auto_controlled_players.discard(player)
        state.human_controlled_players.add(player)
        state.ai_personalities.pop(player, None)
        state.ai_current_behavior.pop(player, None)
        if player == state.current_player and state.phase == "playing":
            state.turn_phase = "attack"


# ----------------------------------------------------------------------
# Cites commercantes
# ----------------------------------------------------------------------

def is_potential_commercial_city_player(state: GameState, player: int) -> bool:
    return player in state.commercial_city_players


def get_commercial_city_capital_id(state: GameState, player: int) -> Optional[int]:
    capital_id = state.commercial_city_capital_ids.get(player)
    if capital_id is not None:
        if 0 <= capital_id < len(state.territories) and state.territories[capital_id].owner == player:
            return capital_id
        return None
    owned = sorted(terr.id for terr in state.territories if terr.owner == player)
    if not owned:
        return None
    # Compatibilite anciennes sauvegardes : on fige (avec cache, comme x45)
    # le plus ancien territoire encore possede.
    capital_id = owned[0]
    state.commercial_city_capital_ids[player] = capital_id
    return capital_id


def is_commercial_city_player(state: GameState, player: int) -> bool:
    if player not in state.commercial_city_players:
        return False
    return get_commercial_city_capital_id(state, player) is not None


def is_commercial_city_definitively_destroyed(state: GameState, player: int) -> bool:
    if player not in state.commercial_city_players:
        return False
    capital_id = state.commercial_city_capital_ids.get(player)
    if capital_id is None or not (0 <= capital_id < len(state.territories)):
        return True
    return state.territories[capital_id].owner != player


def schedule_commercial_city_replacement_if_destroyed(state: GameState, player: int) -> Optional[str]:
    if not is_commercial_city_definitively_destroyed(state, player):
        return None
    # Les vassaux sont une mecanique abandonnee : la branche correspondante
    # de x45 est morte (aucun vassal ne peut exister) et n'est pas reprise.
    state.commercial_city_players.discard(player)
    state.commercial_city_capital_ids.pop(player, None)
    state.last_stand_bonus_players.discard(player)
    state.last_stand_bonus_territory.pop(player, None)
    assign_ai_personality_to_player(state, player, "standard")
    state.pending_commercial_city_spawns = max(0, state.pending_commercial_city_spawns) + 1
    message = (
        f"J{player + 1} perd definitivement son statut de Cite commercante. "
        "Une nouvelle Cite commercante apparaitra au debut du prochain tour."
    )
    record_major_event(state, message)
    return message


def refresh_destroyed_commercial_cities(state: GameState) -> List[str]:
    messages: List[str] = []
    for player in sorted(list(state.commercial_city_players)):
        message = schedule_commercial_city_replacement_if_destroyed(state, player)
        if message:
            messages.append(message)
    return messages


# ----------------------------------------------------------------------
# Capitales
# ----------------------------------------------------------------------

def get_regular_capital_owner(state: GameState, territory_id: int) -> Optional[int]:
    for player, capital_id in state.player_capital_ids.items():
        if capital_id == territory_id:
            return player
    return None


def is_regular_capital_territory(state: GameState, territory_id: int) -> bool:
    return get_regular_capital_owner(state, territory_id) is not None


def is_any_capital_territory(state: GameState, territory_id: int) -> bool:
    return (
        is_regular_capital_territory(state, territory_id)
        or territory_id in set(state.commercial_city_capital_ids.values())
    )


def is_active_regular_capital(state: GameState, territory_id: int) -> bool:
    original_owner = get_regular_capital_owner(state, territory_id)
    return (
        original_owner is not None
        and 0 <= territory_id < len(state.territories)
        and state.territories[territory_id].owner == original_owner
        and not is_onu_player(state, original_owner)
        and not is_potential_commercial_city_player(state, original_owner)
    )


# ----------------------------------------------------------------------
# Paradis fiscaux (dernier bastion)
# ----------------------------------------------------------------------

def get_player_tax_haven_capital_ids(state: GameState, player: int) -> Set[int]:
    if is_potential_commercial_city_player(state, player):
        if not is_commercial_city_player(state, player):
            return set()
        capital_id = get_commercial_city_capital_id(state, player)
        return {capital_id} if capital_id is not None else set()
    raw_value = state.last_stand_bonus_territory.get(player, set())
    if isinstance(raw_value, set):
        return set(raw_value)
    if isinstance(raw_value, (list, tuple)):
        return {int(tid) for tid in raw_value}
    if raw_value is None:
        return set()
    return {int(raw_value)}


def get_all_tax_haven_capital_ids(state: GameState) -> Set[int]:
    capital_ids: Set[int] = set()
    for player in (
        set(state.last_stand_bonus_players)
        | set(state.last_stand_bonus_territory)
        | set(state.commercial_city_players)
    ):
        capital_ids.update(get_player_tax_haven_capital_ids(state, player))
    return capital_ids


def is_last_stand_bonus_territory(state: GameState, territory_id: int) -> bool:
    return territory_id in get_all_tax_haven_capital_ids(state)


def is_territory_tax_haven_immune_to_religion(state: GameState, territory_id: int) -> bool:
    return is_last_stand_bonus_territory(state, territory_id)


def refresh_last_stand_bonus_state(state: GameState) -> None:
    """Nettoie les avantages de paradis fiscal devenus incoherents."""
    valid_ids = set(range(len(state.territories)))
    normalized_players: Set[int] = set()
    normalized_territories: dict[int, Set[int]] = {}
    for player in (
        set(state.last_stand_bonus_players)
        | set(state.last_stand_bonus_territory)
        | set(state.commercial_city_players)
    ):
        if is_potential_commercial_city_player(state, player):
            if is_commercial_city_player(state, player):
                capital_id = get_commercial_city_capital_id(state, player)
                if capital_id is not None:
                    normalized_players.add(player)
                    normalized_territories[player] = {capital_id}
            continue
        valid_capitals = {
            tid for tid in get_player_tax_haven_capital_ids(state, player)
            if tid in valid_ids and state.territories[tid].owner == player
        }
        if not valid_capitals:
            continue
        normalized_players.add(player)
        normalized_territories[player] = valid_capitals
    state.last_stand_bonus_players = normalized_players
    state.last_stand_bonus_territory = normalized_territories


def snapshot_tax_haven_turn_start_territory_counts(state: GameState) -> None:
    """Memorise les possessions PF au tout debut du tour global."""
    state.tax_haven_turn_start_territory_counts = {
        player: count_player_territories(state, player)
        for player in state.last_stand_bonus_players
    }


# ----------------------------------------------------------------------
# Evenements majeurs
# ----------------------------------------------------------------------

def queue_major_event_modal(state: GameState, title: str, events: List[str]) -> None:
    modal = sanitize_major_event_modal({"title": title, "events": events})
    if modal is None:
        return
    if state.major_event_modal is None:
        state.major_event_modal = modal
    else:
        state.major_event_modal_queue.append(modal)


def record_major_event(state: GameState, message: str) -> None:
    if not message:
        return
    clean = " ".join(str(message).split())
    if not clean:
        return
    if state.recent_major_events and state.recent_major_events[-1] == clean:
        return
    state.recent_major_events.append(clean)
    state.recent_major_events = state.recent_major_events[-8:]

    if state.phase not in ("playing", "shopping"):
        return
    human_players = [
        player for player in get_active_players(state)
        if is_human_player_id(state, player)
    ]
    collecting = getattr(state, "collecting_between_turn_events", False)
    immediate_player = (
        state.current_player
        if not collecting and state.current_player in human_players
        else None
    )
    if immediate_player is not None:
        queue_major_event_modal(state, "Evenement important", [clean])
    for player in human_players:
        if player == immediate_player:
            continue
        pending = state.pending_major_events_for_humans.setdefault(player, [])
        if not pending or pending[-1] != clean:
            pending.append(clean)
            state.pending_major_events_for_humans[player] = pending[-20:]


# ----------------------------------------------------------------------
# Replay
# ----------------------------------------------------------------------

def build_replay_snapshot(state: GameState, label: str = "") -> dict:
    return {
        "turn": int(state.turn),
        "player": int(state.current_player),
        "label": str(label),
        "owners": [int(territory.owner) for territory in state.territories],
        "regiments": [int(territory.regiments) for territory in state.territories],
        "reinforcement_bonuses": [int(territory.reinforcement_bonus) for territory in state.territories],
        "precious_mines": sorted(int(tid) for tid in state.precious_mineral_mine_ids),
        "wonders": {str(kind): int(tid) for kind, tid in state.wonder_territories.items()},
        "fortresses": sorted(int(tid) for tid in state.fortress_territory_ids),
        "factories": sorted(int(tid) for tid in state.factory_territory_ids),
        "airports": sorted(int(tid) for tid in state.airport_territory_ids),
        "ports": sorted(int(tid) for tid in state.port_territory_ids),
        "cultural_centers": sorted(int(tid) for tid in state.cultural_center_ages),
        "ruins": sorted(int(tid) for tid in state.ruin_territory_ids),
        "universities": sorted(int(tid) for tid in state.university_territory_ids),
        "temples": sorted(int(tid) for tid in state.temple_territory_ids),
        "sanctuaries": sorted(int(tid) for tid in state.sanctuary_territory_ids),
        "submitted": sorted(int(tid) for tid in state.submitted_territory_ids),
        "capitals": {str(player): int(tid) for player, tid in state.player_capital_ids.items()},
        "commercial_capitals": {str(player): int(tid) for player, tid in state.commercial_city_capital_ids.items()},
        "commercial_players": sorted(int(player) for player in state.commercial_city_players),
        "nation_players": sorted(int(player) for player in state.nation_players),
        "religious_influence": {str(tid): int(religion_id) for tid, religion_id in state.religious_influence.items()},
        "religion_holy_sites": {str(religion_id): int(tid) for religion_id, tid in state.religion_holy_sites.items()},
        "religion_foundation_turns": {str(religion_id): int(turn) for religion_id, turn in state.religion_foundation_turns.items()},
        "religion_last_spread_turns": {str(religion_id): int(turn) for religion_id, turn in state.religion_last_spread_turns.items()},
        "money": {str(player): int(value) for player, value in state.player_money.items()},
        "science": {str(player): int(value) for player, value in state.player_science.items()},
        "bridges": [
            {
                "a": int(a),
                "b": int(b),
                "start": list(state.bridge_link_points[(a, b)][0]),
                "end": list(state.bridge_link_points[(a, b)][1]),
                "fragile": (a, b) in state.fragile_bridge_links,
            }
            for a, b in sorted(state.bridge_links)
            if (a, b) in state.bridge_link_points
        ],
    }


def replay_snapshot_signature(snapshot: dict) -> tuple:
    return (
        tuple(snapshot.get("owners", [])),
        tuple(snapshot.get("regiments", [])),
        tuple(snapshot.get("reinforcement_bonuses", [])),
        tuple(snapshot.get("precious_mines", [])),
        tuple(sorted(snapshot.get("wonders", {}).items())),
        tuple(snapshot.get("fortresses", [])),
        tuple(snapshot.get("factories", [])),
        tuple(snapshot.get("airports", [])),
        tuple(snapshot.get("ports", [])),
        tuple(snapshot.get("cultural_centers", [])),
        tuple(snapshot.get("ruins", [])),
        tuple(snapshot.get("universities", [])),
        tuple(snapshot.get("temples", [])),
        tuple(snapshot.get("sanctuaries", [])),
        tuple(sorted(snapshot.get("religious_influence", {}).items())),
        tuple(
            (
                item.get("a"), item.get("b"), tuple(item.get("start", [])),
                tuple(item.get("end", [])), bool(item.get("fragile", False))
            )
            for item in snapshot.get("bridges", [])
        ),
    )


def record_replay_snapshot(state: GameState, label: str = "", force: bool = False) -> None:
    if not state.territories:
        return
    snapshot = build_replay_snapshot(state, label)
    if state.replay_history and not force:
        previous = state.replay_history[-1]
        if replay_snapshot_signature(previous) == replay_snapshot_signature(snapshot):
            if label:
                previous["label"] = label
                previous["turn"] = int(state.turn)
                previous["player"] = int(state.current_player)
            return
    state.replay_history.append(snapshot)
    if len(state.replay_history) > MAX_REPLAY_SNAPSHOTS:
        first = state.replay_history[0]
        state.replay_history = [first] + state.replay_history[-(MAX_REPLAY_SNAPSHOTS - 1):]


# ----------------------------------------------------------------------
# Sanitisations
# ----------------------------------------------------------------------

def sanitize_player_capitals(state: GameState) -> None:
    valid_ids = set(range(len(state.territories)))
    state.player_capital_ids = {
        int(player): int(tid)
        for player, tid in state.player_capital_ids.items()
        if int(player) >= 0
        and int(player) < state.num_players
        and int(player) not in state.commercial_city_players
        and int(tid) in valid_ids
    }
    state.sanctuary_territory_ids.difference_update(set(state.player_capital_ids.values()))


def sanitize_vassal_territories(state: GameState) -> None:
    # Mecanique abandonnee : x45 vide les structures de vassalite ; GameState
    # ne les stocke plus du tout (emises vides a la serialisation).
    return


def sanitize_submitted_territories(state: GameState) -> None:
    valid_ids = set(range(len(state.territories)))
    state.submitted_territory_ids = {
        tid for tid in state.submitted_territory_ids
        if tid in valid_ids and state.territories[tid].owner == state.onu_player_id
    }
    state.submitted_territory_overlords = {
        tid: int(overlord)
        for tid, overlord in state.submitted_territory_overlords.items()
        if tid in state.submitted_territory_ids and 0 <= int(overlord) < state.num_players
    }
    state.submitted_territory_created_turns = {
        tid: max(1, int(state.submitted_territory_created_turns.get(tid, state.turn)))
        for tid in state.submitted_territory_ids
        if tid in state.submitted_territory_overlords
    }
    state.integrated_submitted_territories = {
        int(player): {
            int(tid) for tid in territory_ids
            if 0 <= int(tid) < len(state.territories) and state.territories[int(tid)].owner == int(player)
        }
        for player, territory_ids in state.integrated_submitted_territories.items()
        if 0 <= int(player) < state.num_players
    }
    state.sanctuary_territory_ids.update(state.submitted_territory_ids)


def sanitize_religion_state(state: GameState) -> None:
    valid_ids = set(range(len(state.territories)))
    valid_religions = set(range(len(RELIGIONS)))
    state.religion_founders = {
        int(player): int(religion_id)
        for player, religion_id in state.religion_founders.items()
        if 0 <= int(player) < state.num_players and int(religion_id) in valid_religions
    }
    used_religions = set(state.religion_founders.values())
    used_religions.update(get_founded_wonder_religion_ids(state))
    state.religion_foundation_turns = {
        int(religion_id): max(1, int(turn))
        for religion_id, turn in state.religion_foundation_turns.items()
        if int(religion_id) in used_religions
    }
    state.religion_last_spread_turns = {
        religion_id: max(
            state.religion_foundation_turns.get(religion_id, 1),
            int(state.religion_last_spread_turns.get(
                religion_id,
                state.religion_foundation_turns.get(religion_id, state.turn),
            )),
        )
        for religion_id in used_religions
    }
    state.religion_holy_sites = {
        int(religion_id): int(tid)
        for religion_id, tid in state.religion_holy_sites.items()
        if int(religion_id) in used_religions and int(tid) in valid_ids
    }
    state.religious_influence = {
        int(tid): int(religion_id)
        for tid, religion_id in state.religious_influence.items()
        if int(tid) in valid_ids
        and int(religion_id) in used_religions
        and not is_territory_tax_haven_immune_to_religion(state, int(tid))
    }


def enforce_commercial_city_wonder_exclusivity(state: GameState) -> None:
    if "golden_pact_palace" not in state.wonder_territories:
        return
    commercial_players = set(state.commercial_city_players)
    state.active_alliances = {
        key: expires_turn
        for key, expires_turn in state.active_alliances.items()
        if key[0] not in commercial_players and key[1] not in commercial_players
    }
    state.alliance_start_turns = {
        key: start_turn for key, start_turn in state.alliance_start_turns.items()
        if key in state.active_alliances
    }
    state.active_offensive_alliances = {
        key: data
        for key, data in state.active_offensive_alliances.items()
        if key[0] not in commercial_players and key[1] not in commercial_players and data[0] not in commercial_players
    }
    state.offensive_alliance_start_turns = {
        key: start_turn for key, start_turn in state.offensive_alliance_start_turns.items()
        if key in state.active_offensive_alliances
    }
    state.active_ai_alliances = {
        key: expires_turn
        for key, expires_turn in state.active_ai_alliances.items()
        if not (set(key) & commercial_players)
    }
    state.ai_alliance_start_turns = {
        key: start_turn for key, start_turn in state.ai_alliance_start_turns.items()
        if key in state.active_ai_alliances
    }


def enforce_golden_territory_onu_immunity(state: GameState, rng=random) -> None:
    if not state.golden_territory_ids:
        return
    golden_ids = {tid for tid in state.golden_territory_ids if 0 <= tid < len(state.territories)}
    if not golden_ids:
        return
    state.sanctuary_territory_ids.difference_update(golden_ids)
    active_players = [
        player for player in range(state.num_players)
        if player >= 0 and not is_onu_player(state, player)
    ]
    for territory_id in golden_ids:
        terr = state.territories[territory_id]
        if terr.owner == state.onu_player_id or terr.owner < 0:
            terr.owner = rng.choice(active_players) if active_players else 0
            terr.regiments = max(1, terr.regiments)


def sync_late_resource_lifetimes(state: GameState) -> None:
    """Recale les compteurs de duree de vie des ressources tardives.

    Une ressource presente sans tour d'apparition connu — sauvegarde
    anterieure a la regle des vingt tours, ou gisement pose par une autre
    mecanique — repart pour un cycle complet depuis le tour courant. Les
    compteurs orphelins (ressource disparue entre-temps, par exemple un
    territoire passe a l'ONU) sont oublies.

    Appele au changement de tour global, pas au chargement : la sauvegarde
    relue reste ainsi identique a l'octet pres.
    """
    bonus_5_ids = {
        terr.id for terr in state.territories if terr.reinforcement_bonus == 5
    }
    state.bonus_5_spawn_turns = {
        tid: int(turn) for tid, turn in state.bonus_5_spawn_turns.items()
        if tid in bonus_5_ids
    }
    for territory_id in sorted(bonus_5_ids - set(state.bonus_5_spawn_turns)):
        state.bonus_5_spawn_turns[territory_id] = state.turn

    state.precious_mineral_mine_spawn_turns = {
        tid: int(turn) for tid, turn in state.precious_mineral_mine_spawn_turns.items()
        if tid in state.precious_mineral_mine_ids
    }
    for territory_id in sorted(
        set(state.precious_mineral_mine_ids) - set(state.precious_mineral_mine_spawn_turns)
    ):
        state.precious_mineral_mine_spawn_turns[territory_id] = state.turn


def sanitize_economy_state(state: GameState) -> None:
    valid_ids = set(range(len(state.territories)))
    sanitize_player_capitals(state)
    sanitize_submitted_territories(state)
    sanitize_vassal_territories(state)
    state.fortress_territory_ids = {tid for tid in state.fortress_territory_ids if tid in valid_ids}
    state.precious_mineral_mine_ids = {
        tid for tid in state.precious_mineral_mine_ids if tid in valid_ids
    }
    sanitized_wonders: dict[str, int] = {}
    occupied_wonder_territories: Set[int] = set()
    for wonder_type, territory_id in state.wonder_territories.items():
        if wonder_type not in WONDER_DEFINITIONS:
            continue
        territory_id = int(territory_id)
        if territory_id not in valid_ids or territory_id in occupied_wonder_territories:
            continue
        sanitized_wonders[wonder_type] = territory_id
        occupied_wonder_territories.add(territory_id)
    state.wonder_territories = sanitized_wonders
    raw_factory_ids = {tid for tid in state.factory_territory_ids if tid in valid_ids}
    raw_airport_ids = {tid for tid in state.airport_territory_ids if tid in valid_ids}
    raw_port_ids = {tid for tid in state.port_territory_ids if tid in valid_ids}

    # Regle generale : un seul amenagement industriel par territoire.
    state.factory_territory_ids = set(raw_factory_ids)
    state.airport_territory_ids = {
        tid for tid in raw_airport_ids
        if tid not in state.factory_territory_ids
    }
    state.port_territory_ids = {
        tid for tid in raw_port_ids
        if tid not in state.factory_territory_ids and tid not in state.airport_territory_ids
    }
    # Les alias herites industry_* de x45 sont derives a la serialisation
    # (etat.to_payload) et ne sont pas stockes dans GameState.
    state.fortress_capture_counts = {
        tid: max(0, int(state.fortress_capture_counts.get(tid, 0)))
        for tid in state.fortress_territory_ids
    }
    state.industrial_capture_counts = {
        tid: max(0, int(state.industrial_capture_counts.get(tid, 0)))
        for tid in (state.factory_territory_ids | state.airport_territory_ids | state.port_territory_ids)
    }
    state.cultural_center_ages = {
        tid: [max(0, int(age)) for age in ages[:MAX_CULTURAL_CENTERS_PER_TERRITORY]]
        for tid, ages in state.cultural_center_ages.items()
        if tid in valid_ids and ages
    }
    state.cultural_capture_counts = {
        tid: max(0, int(state.cultural_capture_counts.get(tid, 0)))
        for tid in state.cultural_center_ages
    }
    state.ruin_territory_ids = {
        int(tid) for tid in state.ruin_territory_ids if int(tid) in valid_ids
    }
    state.university_territory_ids = {
        tid for tid in state.university_territory_ids
        if tid in valid_ids
    }
    state.university_capture_counts = {
        tid: max(0, int(state.university_capture_counts.get(tid, 0)))
        for tid in state.university_territory_ids
    }
    state.university_ages = {
        tid: max(0, int(state.university_ages.get(tid, 0)))
        for tid in state.university_territory_ids
    }
    state.temple_territory_ids = {
        tid for tid in state.temple_territory_ids
        if tid in valid_ids
    }
    state.temple_capture_counts = {
        tid: max(0, int(state.temple_capture_counts.get(tid, 0)))
        for tid in state.temple_territory_ids
    }
    sanitize_religion_state(state)
    state.player_science = {
        int(player): max(0, int(points))
        for player, points in state.player_science.items()
        if 0 <= int(player) < state.num_players
    }
    state.culture_expansion_milestones = {
        int(player): max(0, int(milestone) // 50 * 50)
        for player, milestone in state.culture_expansion_milestones.items()
        if 0 <= int(player) < state.num_players
    }
    state.commercial_city_capital_ids = {
        int(player): int(tid)
        for player, tid in state.commercial_city_capital_ids.items()
        if int(player) in state.commercial_city_players
        and int(tid) in valid_ids
    }
    refresh_destroyed_commercial_cities(state)
    ally = getattr(state, "eternal_ally_player", None)
    if ally is not None and not (0 <= ally < state.num_players):
        state.eternal_ally_player = None
        state.eternal_ally_patron = None
    refresh_last_stand_bonus_state(state)
    enforce_commercial_city_wonder_exclusivity(state)
    for player in range(state.num_players):
        ensure_player_economy(state, player)


def sanitize_after_load(state: GameState, rng=random, phase_before_load: str = "setup") -> None:
    """Applique les sanitisations de x45 apres un chargement de sauvegarde.

    Miroir exact de la fin de ``apply_saved_game_state`` (x45 : 1506-1518),
    a appeler juste apres ``GameState.from_payload``. Comme dans x45 :
    - le statut paradis fiscal charge est mis de cote pendant
      ``sanitize_economy_state`` (qui verrait sinon des incoherences), puis
      restaure et re-normalise ;
    - ``phase_before_load`` reproduit la phase de x45 pendant le chargement
      ("setup"/"start_menu" : les evenements majeurs ne creent pas de modale).
    """
    saved_last_stand_bonus_players = {int(player) for player in state.last_stand_bonus_players}
    saved_last_stand_bonus_territory = {
        int(player): {int(tid) for tid in capital_ids}
        for player, capital_ids in state.last_stand_bonus_territory.items()
    }
    state.last_stand_bonus_players = set()
    state.last_stand_bonus_territory = {}
    state.phase = phase_before_load

    sanitize_economy_state(state)
    sanitize_player_capitals(state)
    enforce_golden_territory_onu_immunity(state, rng)

    state.last_stand_bonus_players = saved_last_stand_bonus_players
    state.last_stand_bonus_territory = saved_last_stand_bonus_territory
    refresh_last_stand_bonus_state(state)
    sanitize_religion_state(state)
    if not state.tax_haven_turn_start_territory_counts:
        snapshot_tax_haven_turn_start_territory_counts(state)
    state.phase = "playing"
    if not state.replay_history:
        record_replay_snapshot(state, f"Reprise de la partie au tour {state.turn}", force=True)
    # Miroir du reset_ai_turn_state de fin de chargement : si le joueur
    # courant est une IA, son comportement du tour est fixe (les profils
    # "variable" retirent au sort).
    if is_ai_player(state, state.current_player):
        prepare_ai_behavior_for_turn(state, state.current_player, rng)


# ----------------------------------------------------------------------
# Structures industrielles, merveilles, religion (requetes)
# ----------------------------------------------------------------------

def get_industrial_structure_count(state: GameState, territory_id: int) -> int:
    return sum(
        1 for ids in (state.factory_territory_ids, state.airport_territory_ids, state.port_territory_ids)
        if territory_id in ids
    )


def player_has_complete_industrial_set(state: GameState, player: int) -> bool:
    if player < 0 or is_onu_player(state, player):
        return False
    owned_ids = {terr.id for terr in state.territories if terr.owner == player}
    return (
        bool(state.factory_territory_ids & owned_ids)
        and bool(state.airport_territory_ids & owned_ids)
        and bool(state.port_territory_ids & owned_ids)
    )


def get_wonder_controller(state: GameState, wonder_type: str) -> Optional[int]:
    territory_id = state.wonder_territories.get(wonder_type)
    if territory_id is None or not (0 <= territory_id < len(state.territories)):
        return None
    owner = state.territories[territory_id].owner
    if owner < 0 or is_onu_player(state, owner):
        return None
    return owner


def player_controls_wonder(state: GameState, player: int, wonder_type: str) -> bool:
    return get_wonder_controller(state, wonder_type) == player


def is_territory_protected_from_ai_attacks(state: GameState, territory_id: int) -> bool:
    """Le Rempart d'Ivoire protege son territoire des attaques des IA."""
    return state.wonder_territories.get("ivory_rampart") == territory_id


def get_player_temple_count(state: GameState, player: int) -> int:
    if player < 0 or is_onu_player(state, player):
        return 0
    return sum(
        1
        for territory_id in state.temple_territory_ids
        if 0 <= territory_id < len(state.territories)
        and state.territories[territory_id].owner == player
    )


def get_national_religion_influenced_territory_count(state: GameState, player: int) -> int:
    religion_ids: Set[int] = set()
    founded_religion_id = state.religion_founders.get(player)
    if founded_religion_id is not None:
        religion_ids.add(founded_religion_id)
    for religion_id, wonder_type in WONDER_RELIGION_SOURCES.items():
        if player_controls_wonder(state, player, wonder_type):
            religion_ids.add(religion_id)
    if not religion_ids:
        return 0
    return sum(
        1
        for territory in state.territories
        if territory.owner == player
        and state.religious_influence.get(territory.id) in religion_ids
    )


def get_player_national_religion_id(state: GameState, player: int) -> Optional[int]:
    """La religion nationale fondee par ce joueur, s'il en a une.

    La religion de la merveille (Elyrion) n'est jamais une religion nationale :
    elle n'ouvre ni l'immunite aux revoltes, ni les missions, ni la victoire
    religieuse.
    """
    if player < 0:
        return None
    religion_id = state.religion_founders.get(player)
    if religion_id is None or is_wonder_religion(religion_id):
        return None
    return religion_id


def get_religion_influence_count(state: GameState, religion_id: int) -> int:
    """Le nombre de territoires de la carte sous l'influence de cette religion.

    Peu importe qui les possede : c'est l'extension de la foi qui compte.
    """
    territory_count = len(state.territories)
    return sum(
        1 for tid, rid in state.religious_influence.items()
        if rid == religion_id and 0 <= tid < territory_count
    )


def get_religious_income_bonus(state: GameState, player: int) -> int:
    influenced_count = get_national_religion_influenced_territory_count(state, player)
    return influenced_count * RELIGIOUS_INCOME_BONUS_PER_TERRITORY


def get_religious_reinforcement_bonus(state: GameState, player: int) -> int:
    influenced_count = get_national_religion_influenced_territory_count(state, player)
    if influenced_count <= 0:
        return 0
    return math.ceil(influenced_count / RELIGIOUS_REINFORCEMENT_TERRITORIES_PER_BONUS)


def get_controlled_holy_site_count(state: GameState, player: int) -> int:
    return sum(
        1
        for tid in state.religion_holy_sites.values()
        if 0 <= tid < len(state.territories) and state.territories[tid].owner == player
    )


def get_required_holy_site_count_for_victory(state: GameState) -> int:
    """Les cinq lieux sacres nationaux, plus ceux des religions conquerantes."""
    return WONDER_RELIGION_ID + len(get_founded_wonder_religion_ids(state))


def get_required_influence_count_for_religion_victory(state: GameState, player: int) -> int:
    """Combien de territoires sous influence nationale pour gagner la partie.

    Neuf dixiemes de la carte pour un joueur humain, trois quarts pour une IA.
    """
    total = len(state.territories)
    if total <= 0:
        return 0
    ratio = (
        AI_NATIONAL_RELIGION_VICTORY_RATIO if is_ai_player(state, player)
        else NATIONAL_RELIGION_VICTORY_RATIO
    )
    return math.ceil(total * ratio)


def is_holy_site_victory_active(state: GameState) -> bool:
    required = get_required_holy_site_count_for_victory(state)
    return len(state.religion_holy_sites) >= required


# ----------------------------------------------------------------------
# Revenus
# ----------------------------------------------------------------------

def is_colonized_player(state: GameState, player: int) -> bool:
    # Mecanique abandonnee, comme dans x45.
    return False


def calculate_territory_income(state: GameState, territory: Territory) -> int:
    if territory.owner == state.onu_player_id:
        return 0
    base_income = max(1, len(territory.neighbors))
    industrial_count = get_industrial_structure_count(state, territory.id)
    income = base_income + (base_income * industrial_count)
    is_tax_haven_capital = territory.id in get_player_tax_haven_capital_ids(state, territory.owner)
    is_regular_capital = is_active_regular_capital(state, territory.id)
    if is_tax_haven_capital or is_regular_capital:
        income *= CAPITAL_INCOME_MULTIPLIER
    if state.wonder_territories.get("croesus_fountain") == territory.id:
        # Fontaine de Cresus : l'argent du territoire est quintuple, en
        # plus des autres multiplicateurs eventuels.
        income *= 5
    return income


def calculate_submitted_territory_income(state: GameState, territory: Territory) -> int:
    base_income = max(1, len(territory.neighbors))
    industrial_count = get_industrial_structure_count(state, territory.id)
    income = base_income + (base_income * industrial_count)
    if state.wonder_territories.get("croesus_fountain") == territory.id:
        income *= 5
    return income


def calculate_submitted_territory_tribute(state: GameState, player: int) -> int:
    if player < 0 or is_onu_player(state, player):
        return 0
    sanitize_submitted_territories(state)
    return sum(
        calculate_submitted_territory_income(state, state.territories[tid])
        for tid, overlord in state.submitted_territory_overlords.items()
        if overlord == player and 0 <= tid < len(state.territories)
    )


def is_tax_haven_income_bonus_active(state: GameState, player: int) -> bool:
    return (
        player in state.last_stand_bonus_players
        and bool(get_player_tax_haven_capital_ids(state, player))
        and player_has_complete_industrial_set(state, player)
    )


def calculate_player_income(state: GameState, player: int) -> int:
    if is_onu_player(state, player):
        return 0
    income = sum(
        calculate_territory_income(state, terr)
        for terr in state.territories if terr.owner == player
    )
    income += calculate_submitted_territory_tribute(state, player)
    if is_tax_haven_income_bonus_active(state, player):
        income = (income * 3) // 2
    if player in state.nation_players:
        income //= NATION_INCOME_DIVISOR
    income += get_religious_income_bonus(state, player)
    owned_mines = sum(
        1 for tid in state.precious_mineral_mine_ids
        if 0 <= tid < len(state.territories) and state.territories[tid].owner == player
    )
    income += owned_mines * PRECIOUS_MINERAL_MINE_INCOME
    # Les ruines rendent un montant fixe, comme les mines : ni multiplie par
    # la capitale, ni divise par le statut de nation.
    income += get_player_ruin_count(state, player) * RUIN_INCOME
    if player_controls_wonder(state, player, "kaleth_gardens"):
        income += TOURISM_WONDER_INCOME
    return income


def collect_income_for_player(state: GameState, player: int) -> int:
    if player < 0 or is_onu_player(state, player):
        return 0
    ensure_player_economy(state, player)
    income = calculate_player_income(state, player)
    state.player_money[player] += income
    return income


# ----------------------------------------------------------------------
# Renforts de fin de tour
# ----------------------------------------------------------------------

@dataclass
class ReinforcementReport:
    """Resultat de ``grant_reinforcements`` : etat + message a afficher.

    ``kind`` permet a l'appelant (x45 ou le futur serveur) de choisir la
    presentation : "colonisation" (aucun renfort), "plafond" (limite de
    regiments atteinte) ou "renforts" (renforts distribues).
    """

    kind: str
    message: str


def player_controls_bonus_5(state: GameState, player: int) -> bool:
    return any(
        terr.owner == player and terr.reinforcement_bonus == 5
        for terr in state.territories
    )


def get_reinforcement_regiment_limit(state: GameState, player: int) -> int:
    if player_controls_bonus_5(state, player):
        return MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS_WITH_BONUS_5
    return MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS


def get_ai_reinforcement_bonus(state: GameState, player: int) -> int:
    if not is_ai_player(state, player):
        return 0
    bonus = 0
    for start_turn, stage_bonus in AI_REINFORCEMENT_BONUS_STAGES:
        if state.turn < start_turn:
            break
        bonus = stage_bonus
    return bonus


def place_end_turn_reinforcement(state: GameState, terr: Territory, player: int) -> bool:
    """Place un renfort, ou le convertit en ecus si le territoire a une universite.

    Exception : un joueur reduit a son dernier territoire touche ses renforts
    en regiments meme sous une universite — elle ne doit pas le condamner en
    asphyxiant sa seule source de troupes.
    """
    if terr.id in state.university_territory_ids:
        owned_count = sum(1 for t in state.territories if t.owner == player)
        if owned_count > 1:
            ensure_player_economy(state, player)
            state.player_money[player] += 10
            return True
    terr.regiments += 1
    return False


def grant_reinforcements(state: GameState, player: int, rng=random) -> Optional[ReinforcementReport]:
    if is_onu_player(state, player):
        return None
    if is_colonized_player(state, player):
        return ReinforcementReport(
            "colonisation",
            f"Joueur {player + 1}: aucun renfort tant que la colonisation dure.",
        )
    owned = [t for t in state.territories if t.owner == player]
    if not owned:
        return None
    total_regiments = sum(max(0, terr.regiments) for terr in owned)
    regiment_limit = get_reinforcement_regiment_limit(state, player)
    if total_regiments >= regiment_limit:
        # Sans boutique, il n'y a plus de mercenaires a proposer en secours.
        recours = "" if is_simple_mode(state) else " Mercenaires toujours achetables."
        return ReinforcementReport(
            "plafond",
            f"Joueur {player + 1}: aucun renfort recu ({total_regiments} regiment(s), "
            f"plafond {regiment_limit}).{recours}",
        )
    controlled_territories = len(owned)
    ultra_owned = sum(1 for t in owned if t.reinforcement_bonus == 3)
    bonus_5_owned = sum(1 for t in owned if t.reinforcement_bonus == 5)
    base_reinforcements = min(MAX_REINFORCEMENTS_PER_TURN, math.ceil(controlled_territories / 3))
    bonus_reinforcements = ultra_owned * 3
    bonus_5_reinforcements = bonus_5_owned * 5
    religious_influenced_territories = get_national_religion_influenced_territory_count(state, player)
    religious_reinforcements = get_religious_reinforcement_bonus(state, player)
    ai_reinforcements = get_ai_reinforcement_bonus(state, player)
    reinforcements = (
        base_reinforcements + bonus_reinforcements + bonus_5_reinforcements
        + religious_reinforcements + ai_reinforcements
    )
    fortress_owned = [t for t in owned if t.id in state.fortress_territory_ids]
    fortress_reinforcements = 0
    university_conversions = 0

    if fortress_owned:
        priority_count = min(3, reinforcements)
        for _ in range(priority_count):
            terr = rng.choice(fortress_owned)
            if place_end_turn_reinforcement(state, terr, player):
                university_conversions += 1
            fortress_reinforcements += 1

        for _ in range(reinforcements - priority_count):
            terr = rng.choice(owned)
            if place_end_turn_reinforcement(state, terr, player):
                university_conversions += 1
    else:
        for _ in range(reinforcements):
            terr = rng.choice(owned)
            if place_end_turn_reinforcement(state, terr, player):
                university_conversions += 1

    bonus_text = f", bonus +3: {bonus_reinforcements}" if bonus_reinforcements else ""
    bonus_5_text = f", bonus +5: {bonus_5_reinforcements}" if bonus_5_reinforcements else ""
    ai_bonus_text = f", progression IA: {ai_reinforcements}" if ai_reinforcements else ""
    religion_text = (
        f", bonus religieux: {religious_reinforcements} pour "
        f"{religious_influenced_territories} territoire(s) sous influence nationale"
        if religious_reinforcements else ""
    )
    fortress_text = f", dont {fortress_reinforcements} prioritaire(s) en forteresse" if fortress_reinforcements else ""
    university_text = f", {university_conversions} converti(s) en {university_conversions * 10} ecu(s) par universite" if university_conversions else ""
    return ReinforcementReport(
        "renforts",
        f"Joueur {player + 1}: {reinforcements} renforts recus ({base_reinforcements} pour "
        f"{controlled_territories} territoire(s) controle(s), arrondi superieur, plafond de base "
        f"{MAX_REINFORCEMENTS_PER_TURN}{bonus_text}{bonus_5_text}{religion_text}{ai_bonus_text}; "
        f"{ultra_owned} territoire(s) +3, {bonus_5_owned} territoire(s) +5{fortress_text}{university_text}).",
    )


# ----------------------------------------------------------------------
# Deplacements de fin de tour
# ----------------------------------------------------------------------

def get_end_turn_move_limit(state: GameState, player: Optional[int] = None) -> int:
    player = state.current_player if player is None else player
    if count_player_territories(state, player) >= EXPANDED_END_TURN_MOVE_TERRITORY_THRESHOLD:
        return EXPANDED_END_TURN_MOVES
    return MAX_END_TURN_MOVES


def can_move_between(state: GameState, src: Territory, dst: Territory) -> bool:
    if src.id == dst.id:
        return False
    if src.owner != state.current_player or dst.owner != state.current_player:
        return False
    visited = set()
    stack = [src.id]
    while stack:
        territory_id = stack.pop()
        if territory_id == dst.id:
            return True
        if territory_id in visited:
            continue
        visited.add(territory_id)
        for neighbor_id in state.territories[territory_id].neighbors:
            neighbor = state.territories[neighbor_id]
            if neighbor.owner == state.current_player and neighbor_id not in visited:
                stack.append(neighbor_id)
    return False


def move_one_regiment(state: GameState, src: Territory, dst: Territory) -> Tuple[bool, str]:
    """Deplace un regiment de ``src`` vers ``dst`` si les regles le permettent.

    Retourne ``(True, "ok")`` en cas de succes, sinon ``(False, code)`` ou
    ``code`` identifie la regle violee : "limite", "proprietaire",
    "meme_territoire", "garnison", "continuite". L'appelant gere l'affichage
    et l'eventuelle fin de tour automatique (regle d'interface, pas de jeu).
    """
    move_limit = get_end_turn_move_limit(state)
    if state.turn_move_count >= move_limit:
        return False, "limite"
    if src.owner != state.current_player or dst.owner != state.current_player:
        return False, "proprietaire"
    if src.id == dst.id:
        return False, "meme_territoire"
    if src.regiments <= 1:
        return False, "garnison"
    if not can_move_between(state, src, dst):
        return False, "continuite"
    src.regiments -= 1
    dst.regiments += 1
    state.turn_move_count += 1
    return True, "ok"


# ----------------------------------------------------------------------
# Victoire
# ----------------------------------------------------------------------

def get_eternal_ally_patron(state: GameState) -> Optional[int]:
    """Qui tient le Serment d'Orvane, et donc l'allie definitif."""
    return get_wonder_controller(state, "orvane_oath")


def release_stale_eternal_ally(state: GameState) -> None:
    """Rompt le serment devenu caduc : la place se rouvre au prochain venu.

    Deux facons de le rompre : l'allie disparait, ou le Serment d'Orvane
    change de mains — qui perd la merveille perd son allie, et le nouveau
    controleur devra attendre une naissance.

    Appele au seul moment ou la question se pose, la naissance d'un joueur :
    un allie tout juste ne n'a pas encore recu ses territoires et ne doit pas
    passer pour mort.
    """
    ally = getattr(state, "eternal_ally_player", None)
    if ally is None:
        return
    patron = get_eternal_ally_patron(state)
    if (
        not (0 <= ally < state.num_players)
        or not any(terr.owner == ally for terr in state.territories)
        or patron is None
        or patron != getattr(state, "eternal_ally_patron", None)
    ):
        state.eternal_ally_player = None
        state.eternal_ally_patron = None


def get_eternal_ally(state: GameState) -> Optional[int]:
    """L'allie definitif en vigueur.

    Le serment lie un allie a un patron precis : des que le Serment d'Orvane
    quitte les mains de celui qui l'a recu, l'alliance tombe.
    """
    ally = getattr(state, "eternal_ally_player", None)
    if ally is None:
        return None
    patron = get_eternal_ally_patron(state)
    if patron is None or patron == ally:
        return None
    if patron != getattr(state, "eternal_ally_patron", None):
        return None
    return ally


def bind_eternal_ally_if_possible(state: GameState, new_player: int) -> Optional[str]:
    """Attache au Serment d'Orvane un joueur ne en cours de partie.

    Un seul allie a la fois : tant que le precedent vit, les nouveaux venus
    restent libres. Sans controleur du Serment, personne ne prete serment.
    """
    patron = get_eternal_ally_patron(state)
    if patron is None or patron == new_player:
        return None
    release_stale_eternal_ally(state)
    if getattr(state, "eternal_ally_player", None) is not None:
        return None
    state.eternal_ally_player = new_player
    state.eternal_ally_patron = patron
    message = (
        f"Tour {state.turn}: J{new_player + 1} prete le Serment d'Orvane a J{patron + 1} : "
        "allie definitif, leurs reussites ne comptent plus que pour un."
    )
    record_major_event(state, message)
    return message


def get_victory_bloc(state: GameState, player: int) -> Tuple[int, ...]:
    """Le joueur et, s'il tient le Serment d'Orvane, son allie definitif."""
    ally = get_eternal_ally(state)
    if ally is not None and player == get_eternal_ally_patron(state):
        return (player, ally)
    return (player,)


def is_eternal_ally(state: GameState, player: int) -> bool:
    return get_eternal_ally(state) == player


def get_union_members(state: GameState, player: int) -> Set[int]:
    # Les unions sont une mecanique abandonnee : chaque joueur est seul.
    return {player} if isinstance(player, int) and player >= 0 else set()


def get_human_union_champions(state: GameState, player: int) -> List[int]:
    if state.final_duel_active or not is_human_player_id(state, player):
        return []
    members = get_union_members(state, player)
    champions = sorted(member for member in members if is_human_player_id(state, member))
    return champions if len(champions) >= 2 else []


def maybe_start_final_duel(state: GameState, winner: int) -> bool:
    champions = get_human_union_champions(state, winner)
    if len(champions) < 2:
        return False
    # Inatteignable tant que get_union_members renvoie {player} (unions
    # abandonnees) : le corps de x45 n'est pas porte pour ne pas trainer du
    # code mort. Si les unions reviennent un jour, porter x45:11066.
    raise NotImplementedError("Duel final par union humaine : mecanique abandonnee dans x45.")


def find_domination_candidate(
    state: GameState,
    owners: Set[int],
    measure,
    ratio_human: int,
    ratio_ai: int,
    minimum: int,
) -> Optional[Tuple[int, int, int, int]]:
    """Le joueur qui ecrase tous ses rivaux sur une mesure (culture, science).

    Retourne ``(joueur, sa valeur, celle du meilleur rival, rapport exige)``,
    ou ``None``. Le rapport ne suffit pas : sans plancher, des rivaux a zero
    donneraient la victoire des le premier tour.
    """
    for owner in sorted(owners):
        value = measure(state, owner)
        if value < minimum:
            continue
        rivals = [
            rival for rival in owners
            if rival != owner and not is_onu_player(state, rival)
        ]
        if not rivals:
            continue
        ratio = ratio_ai if is_ai_player(state, owner) else ratio_human
        best_rival_value = max(measure(state, rival) for rival in rivals)
        if value >= ratio * best_rival_value:
            return owner, value, best_rival_value, ratio
    return None


def evaluate_winner(state: GameState) -> Tuple[Optional[int], str]:
    """Miroir de ``check_winner`` (x45:11144), qui retourne aussi la raison.

    x45 stocke la raison dans ``last_victory_reason`` ; ici elle est renvoyee
    pour que l'appelant en dispose sans etat annexe.
    """
    owners = {t.owner for t in state.territories if t.owner >= 0}
    if not owners:
        return None, ""
    if state.final_duel_active and state.final_duel_champions:
        champions = list(state.final_duel_champions or [])
        alive_champions = [
            champion for champion in champions
            if any(t.owner == champion for t in state.territories)
        ]
        eliminated_champions = [champion for champion in champions if champion not in alive_champions]
        if not eliminated_champions:
            return None, ""

        eliminated_label = ", ".join(f"J{champion + 1}" for champion in eliminated_champions)
        pending_winner = state.final_duel_pending_winner
        if pending_winner in alive_champions:
            return pending_winner, f"a provoque la disparition du champion {eliminated_label} dans la finale"

        if len(alive_champions) == 1:
            return alive_champions[0], f"reste seul champion apres la disparition de {eliminated_label}"

        def bloc_size(champion: int) -> int:
            return sum(
                1 for terr in state.territories
                if state.final_duel_alliances.get(
                    terr.owner, terr.owner if terr.owner in champions else None,
                ) == champion
            )

        winner = max(alive_champions, key=lambda champion: (bloc_size(champion), -champion))
        return winner, f"gagne la finale apres la disparition de {eliminated_label}"

    def accept_winner(owner: int, reason: str) -> Tuple[Optional[int], str]:
        if maybe_start_final_duel(state, owner):
            return None, reason
        return owner, reason

    # Le Serment d'Orvane fond un allie definitif dans son patron : toutes
    # les reussites de l'allie sont portees au credit du patron, et l'allie
    # ne concourt plus pour son propre compte.
    eternal_ally = get_eternal_ally(state)
    candidates = {owner for owner in owners if owner != eternal_ally}
    ally_note = (
        f" (avec son allie definitif J{eternal_ally + 1})"
        if eternal_ally is not None else ""
    )

    def bloc_owns(territory: Territory, bloc: Tuple[int, ...]) -> bool:
        return territory.owner in bloc

    def bloc_note(bloc: Tuple[int, ...]) -> str:
        return ally_note if len(bloc) > 1 else ""

    required_holy_sites = get_required_holy_site_count_for_victory(state)
    if is_holy_site_victory_active(state):
        for owner in sorted(candidates):
            bloc = get_victory_bloc(state, owner)
            holy_count = sum(get_controlled_holy_site_count(state, member) for member in bloc)
            if holy_count >= required_holy_sites:
                return accept_winner(
                    owner, f"controle les {required_holy_sites} lieux sacres" + bloc_note(bloc),
                )

    map_size = len(state.territories)
    for founder, religion_id in sorted(state.religion_founders.items()):
        if is_wonder_religion(religion_id) or founder not in owners:
            continue
        required_influence = get_required_influence_count_for_religion_victory(state, founder)
        if required_influence <= 0:
            continue
        influence_count = get_religion_influence_count(state, religion_id)
        if influence_count >= required_influence:
            part = "3/4" if is_ai_player(state, founder) else "9/10"
            # La foi d'un allie definitif fait gagner son patron.
            winner = get_eternal_ally_patron(state) if founder == eternal_ally else founder
            if winner is None:
                continue
            return accept_winner(
                winner,
                f"a etendu {get_religion_name(state, religion_id)} sur {part} des territoires "
                f"({influence_count}/{map_size})"
                + (ally_note if winner != founder else ""),
            )

    for label, measure, ratio_human, ratio_ai, minimum in (
        ("culture", calculate_player_culture,
         CULTURE_VICTORY_RATIO, AI_CULTURE_VICTORY_RATIO, CULTURE_VICTORY_MIN_POINTS),
        ("science", get_player_science,
         SCIENCE_VICTORY_RATIO, AI_SCIENCE_VICTORY_RATIO, SCIENCE_VICTORY_MIN_POINTS),
    ):
        def bloc_measure(st: GameState, owner: int, measure=measure) -> int:
            return sum(measure(st, member) for member in get_victory_bloc(st, owner))

        candidate = find_domination_candidate(
            state, candidates, bloc_measure, ratio_human, ratio_ai, minimum,
        )
        if candidate is None:
            continue
        owner, value, best_rival_value, ratio = candidate
        return accept_winner(
            owner,
            f"ecrase la {label} de tous ses rivaux : {value} points, "
            f"soit au moins {ratio} fois le meilleur adversaire ({best_rival_value})"
            + bloc_note(get_victory_bloc(state, owner)),
        )

    for owner in sorted(candidates):
        bloc = get_victory_bloc(state, owner)
        if all(bloc_owns(t, bloc) for t in state.territories):
            return accept_winner(
                owner,
                "a conquis tous les territoires, sanctuaires ONU compris" + bloc_note(bloc),
            )

    total_territories = len(state.territories)
    threshold = math.ceil(total_territories * 0.75)
    for owner in sorted(candidates):
        bloc = get_victory_bloc(state, owner)
        owned_count = sum(1 for t in state.territories if bloc_owns(t, bloc))
        if owned_count >= threshold:
            return accept_winner(
                owner,
                f"controle au moins les 3/4 des territoires ({owned_count}/{total_territories})"
                + bloc_note(bloc),
            )

    if len(state.golden_territory_ids) == 4:
        for owner in sorted(candidates):
            bloc = get_victory_bloc(state, owner)
            if all(
                0 <= tid < len(state.territories) and state.territories[tid].owner in bloc
                for tid in state.golden_territory_ids
            ):
                return accept_winner(
                    owner, "controle les 4 territoires dores" + bloc_note(bloc),
                )

    return None, ""


# ----------------------------------------------------------------------
# Science
# ----------------------------------------------------------------------

def get_player_science(state: GameState, player: Optional[int] = None) -> int:
    player = state.current_player if player is None else player
    if player < 0 or is_onu_player(state, player):
        return 0
    state.player_science.setdefault(player, 0)
    science = state.player_science.get(player, 0)
    if player_controls_wonder(state, player, "atlas_observatory"):
        science *= 2
    return science


def has_science_level(state: GameState, player: int, threshold: int) -> bool:
    return get_player_science(state, player) >= threshold


def can_player_attack_with_four_dice(state: GameState, player: int) -> bool:
    return has_science_level(state, player, SCIENCE_ATTACK_4_DICE_THRESHOLD)


# ----------------------------------------------------------------------
# Culture
# ----------------------------------------------------------------------

def get_cultural_center_count(state: GameState, territory_id: int) -> int:
    return len(state.cultural_center_ages.get(territory_id, []))


def has_ruin(state: GameState, territory_id: int) -> bool:
    return territory_id in state.ruin_territory_ids


def add_ruin(state: GameState, territory_id: int) -> bool:
    """Transforme un centre culturel detruit en ruine.

    Un territoire ne porte jamais plus d'une ruine, et une ruine ne
    disparait jamais : elle suit le territoire d'un proprietaire a l'autre.
    """
    if not (0 <= territory_id < len(state.territories)):
        return False
    if territory_id in state.ruin_territory_ids:
        return False
    state.ruin_territory_ids.add(territory_id)
    return True


def get_player_ruin_count(state: GameState, player: int) -> int:
    if player < 0 or is_onu_player(state, player):
        return 0
    return sum(
        1 for tid in state.ruin_territory_ids
        if 0 <= tid < len(state.territories) and state.territories[tid].owner == player
    )


def get_cultural_center_multiplier(age: int) -> int:
    if age >= 100:
        return 10
    if age >= 40:
        return 5
    if age >= 10:
        return 2
    return 1


def calculate_territory_culture(state: GameState, territory: Territory) -> int:
    if territory.owner == state.onu_player_id:
        return 0
    ages = state.cultural_center_ages.get(territory.id, [])
    base = max(1, len(territory.neighbors))
    culture = sum(base * get_cultural_center_multiplier(age) for age in ages)
    if has_ruin(state, territory.id):
        # La ruine rend ses points fixes : ni voisins, ni anciennete.
        culture += RUIN_CULTURE
    return culture


def calculate_player_culture(state: GameState, player: int) -> int:
    if player < 0 or is_onu_player(state, player):
        return 0
    culture = sum(
        calculate_territory_culture(state, terr)
        for terr in state.territories if terr.owner == player
    )
    if player in state.last_stand_bonus_players:
        culture *= 2
    if player_controls_wonder(state, player, "thousand_voices_theatre"):
        culture *= 2
    if player_controls_wonder(state, player, "kaleth_gardens"):
        # Apport fixe du tourisme : les doubleurs ne le multiplient pas.
        culture += TOURISM_WONDER_CULTURE
    return culture


def get_culture_protection_level(state: GameState, player: int) -> int:
    culture = calculate_player_culture(state, player)
    for level in (150, 125, 100, 75, 50, 25):
        if culture >= level:
            return level
    return 0


def calculate_cultural_revolt_or_betrayal_loss_count(
    state: GameState, player: int, default_loss_count: int,
) -> int:
    protection_level = get_culture_protection_level(state, player)
    capped_losses = {25: 4, 50: 3, 75: 2, 100: 1, 125: 0, 150: 0}
    if protection_level in capped_losses:
        return min(default_loss_count, capped_losses[protection_level])
    return default_loss_count


def get_culture_protection_label(state: GameState, player: int) -> str:
    culture = calculate_player_culture(state, player)
    level = get_culture_protection_level(state, player)
    if level >= 150:
        return f"culture {culture}, immunite totale"
    if level >= 125:
        return f"culture {culture}, pertes revolte/trahison annulees, revolution limitee a 1/10"
    if level >= 100:
        return f"culture {culture}, pertes revolte/trahison limitees a 1, revolution limitee a 1/7"
    if level >= 75:
        return f"culture {culture}, pertes revolte/trahison limitees a 2, revolution limitee a 1/6"
    if level >= 50:
        return f"culture {culture}, pertes revolte/trahison limitees a 3, revolution limitee a 1/5"
    if level >= 25:
        return f"culture {culture}, pertes revolte/trahison limitees a 4, revolution limitee a 1/4"
    return f"culture {culture}, aucune protection culturelle"


def get_culture_protection_suffix(state: GameState, player: int) -> str:
    """Le rappel de protection culturelle colle a un message d'evenement.

    Vide en version simplifiee : sans culture, « culture 0, aucune protection
    culturelle » n'aurait aucun sens a l'ecran.
    """
    if is_simple_mode(state):
        return ""
    return f" ({get_culture_protection_label(state, player)})"


def has_culture_advantage(
    state: GameState, player: int, target_player: int, threshold: Optional[int] = None,
) -> bool:
    threshold = CULTURE_ADVANTAGE_THRESHOLD if threshold is None else threshold
    player_culture = calculate_player_culture(state, player)
    target_culture = calculate_player_culture(state, target_player)
    return player_culture >= threshold and player_culture >= target_culture * 3


# ----------------------------------------------------------------------
# Destruction de structures et captures speciales
# ----------------------------------------------------------------------

def _sync_legacy_industry_aliases(state: GameState) -> None:
    # Compat x45 (duck typing) : GraphicalGame maintient encore les alias
    # industry_* herites ; GameState ne les stocke pas (derives a la
    # serialisation).
    if hasattr(state, "industry_territory_ids"):
        state.industry_territory_ids = set(state.factory_territory_ids)
        state.industry_capture_counts = {
            tid: state.industrial_capture_counts.get(tid, 0)
            for tid in state.factory_territory_ids
        }


def remove_all_industrial_structures(state: GameState, territory_id: int) -> int:
    removed = 0
    for ids in (state.factory_territory_ids, state.airport_territory_ids, state.port_territory_ids):
        if territory_id in ids:
            ids.discard(territory_id)
            removed += 1
    state.industrial_capture_counts.pop(territory_id, None)
    _sync_legacy_industry_aliases(state)
    return removed


def remove_university(state: GameState, territory_id: int) -> bool:
    if territory_id not in state.university_territory_ids:
        return False
    state.university_territory_ids.discard(territory_id)
    state.university_capture_counts.pop(territory_id, None)
    state.university_ages.pop(territory_id, None)
    return True


def remove_temple(state: GameState, territory_id: int) -> bool:
    if territory_id not in state.temple_territory_ids:
        return False
    state.temple_territory_ids.discard(territory_id)
    state.temple_capture_counts.pop(territory_id, None)
    return True


def remove_fortress(state: GameState, territory_id: int) -> bool:
    if territory_id not in state.fortress_territory_ids:
        return False
    state.fortress_territory_ids.discard(territory_id)
    state.fortress_capture_counts.pop(territory_id, None)
    return True


def remove_all_cultural_centers(state: GameState, territory_id: int) -> int:
    """Rase les centres culturels d'un territoire : il en reste une ruine."""
    removed = len(state.cultural_center_ages.get(territory_id, []))
    if not removed:
        return 0
    state.cultural_center_ages.pop(territory_id, None)
    state.cultural_capture_counts.pop(territory_id, None)
    add_ruin(state, territory_id)
    return removed


def destroy_all_amenities(state: GameState, territory_id: int) -> List[str]:
    """Rase tous les amenagements d'un territoire et dit ce qui est tombe.

    Les merveilles resistent : elles ne sont pas des amenagements. La ruine
    aussi, puisque rien ne la detruit jamais — et un centre culturel rase
    ici en laisse une, comme n'importe quelle destruction de centre.
    """
    destroyed: List[str] = []
    if remove_fortress(state, territory_id):
        destroyed.append("forteresse")
    industrial_count = remove_all_industrial_structures(state, territory_id)
    if industrial_count:
        label = "amenagement industriel" if industrial_count == 1 else "amenagements industriels"
        destroyed.append(f"{industrial_count} {label}")
    if remove_temple(state, territory_id):
        destroyed.append("temple")
    cultural_count = remove_all_cultural_centers(state, territory_id)
    if cultural_count:
        plural = "" if cultural_count == 1 else "s"
        destroyed.append(f"{cultural_count} centre{plural} culturel{plural} (reduit{plural} en ruine)")
    if remove_university(state, territory_id):
        destroyed.append("universite")
    return destroyed


def register_special_capture(state: GameState, territory_id: int) -> List[str]:
    messages: List[str] = []
    terr_name = state.territories[territory_id].name
    if territory_id in state.fortress_territory_ids:
        count = state.fortress_capture_counts.get(territory_id, 0) + 1
        if count >= SPECIAL_CAPTURE_LIMIT:
            state.fortress_territory_ids.discard(territory_id)
            state.fortress_capture_counts.pop(territory_id, None)
            messages.append(f"Forteresse de {terr_name} detruite apres 3 captures.")
        else:
            state.fortress_capture_counts[territory_id] = count
            messages.append(f"Forteresse de {terr_name}: capture {count}/3.")

    if get_industrial_structure_count(state, territory_id) > 0:
        count = state.industrial_capture_counts.get(territory_id, 0) + 1
        if count >= SPECIAL_CAPTURE_LIMIT:
            removed = remove_all_industrial_structures(state, territory_id)
            label = "amenagement industriel" if removed == 1 else "amenagements industriels"
            messages.append(f"{removed} {label} de {terr_name} detruit(s) apres 3 captures.")
        else:
            state.industrial_capture_counts[territory_id] = count
            messages.append(f"Amenagements industriels de {terr_name}: capture {count}/3.")

    if territory_id in state.cultural_center_ages:
        count = state.cultural_capture_counts.get(territory_id, 0) + 1
        if count >= SPECIAL_CAPTURE_LIMIT:
            removed = len(state.cultural_center_ages.get(territory_id, []))
            state.cultural_center_ages.pop(territory_id, None)
            state.cultural_capture_counts.pop(territory_id, None)
            # Le centre ne disparait pas : il devient une ruine, definitive.
            add_ruin(state, territory_id)
            messages.append(
                f"{removed} centre(s) culturel(s) de {terr_name} detruit(s) apres 3 captures : "
                f"il n'en reste qu'une ruine ({RUIN_INCOME} ecu(s) et {RUIN_CULTURE} points de culture par tour)."
            )
        else:
            state.cultural_capture_counts[territory_id] = count
            messages.append(f"Centres culturels de {terr_name}: capture {count}/3.")

    if territory_id in state.university_territory_ids:
        count = state.university_capture_counts.get(territory_id, 0) + 1
        if count >= SPECIAL_CAPTURE_LIMIT:
            remove_university(state, territory_id)
            messages.append(f"Universite de {terr_name} detruite apres 3 captures.")
        else:
            state.university_capture_counts[territory_id] = count
            messages.append(f"Universite de {terr_name}: capture {count}/3.")

    if territory_id in state.temple_territory_ids:
        count = state.temple_capture_counts.get(territory_id, 0) + 1
        if count >= SPECIAL_CAPTURE_LIMIT:
            remove_temple(state, territory_id)
            messages.append(f"Temple de {terr_name} detruit apres 3 captures.")
        else:
            state.temple_capture_counts[territory_id] = count
            messages.append(f"Temple de {terr_name}: capture {count}/3.")
    return messages


# ----------------------------------------------------------------------
# Paradis fiscaux : mutations
# ----------------------------------------------------------------------

def remove_religious_influence_from_tax_haven(state: GameState, territory_id: int) -> None:
    state.religious_influence.pop(territory_id, None)


def add_tax_haven_capital(state: GameState, player: int, territory_id: int) -> None:
    state.last_stand_bonus_players.add(player)
    capital_ids = get_player_tax_haven_capital_ids(state, player)
    capital_ids.add(territory_id)
    state.last_stand_bonus_territory[player] = capital_ids
    remove_religious_influence_from_tax_haven(state, territory_id)


def remove_tax_haven_player(state: GameState, player: int) -> bool:
    if is_commercial_city_player(state, player):
        return False
    if player not in state.last_stand_bonus_players and player not in state.last_stand_bonus_territory:
        return False
    state.last_stand_bonus_players.discard(player)
    state.last_stand_bonus_territory.pop(player, None)
    return True


def remove_tax_haven_capital(state: GameState, player: int, territory_id: int) -> None:
    capital_ids = get_player_tax_haven_capital_ids(state, player)
    capital_ids.discard(territory_id)
    if capital_ids:
        state.last_stand_bonus_players.add(player)
        state.last_stand_bonus_territory[player] = capital_ids
    else:
        remove_tax_haven_player(state, player)


def deactivate_last_stand_bonus_after_conquest(state: GameState, player: int) -> bool:
    """Retire le statut paradis fiscal apres une conquete militaire.

    N'est appelee que lors d'une capture par la force ; les autres
    acquisitions de territoire ne doivent pas la declencher.
    """
    if player < 0 or is_onu_player(state, player) or is_commercial_city_player(state, player):
        return False
    return remove_tax_haven_player(state, player)


def count_player_universities(state: GameState, player: int) -> int:
    return sum(
        1
        for territory_id in state.university_territory_ids
        if 0 <= territory_id < len(state.territories)
        and state.territories[territory_id].owner == player
    )


def get_tax_haven_territory_limit(state: GameState, player: int) -> Optional[int]:
    if is_human_player_id(state, player):
        return None
    return TAX_HAVEN_LOSS_TERRITORY_THRESHOLD


def enforce_last_stand_bonus_limits(state: GameState, begin_of_turn: bool = False) -> Optional[str]:
    """Retire le paradis fiscal uniquement au debut du tour du joueur concerne."""
    if not begin_of_turn:
        return None
    player = state.current_player
    if is_potential_commercial_city_player(state, player):
        refresh_last_stand_bonus_state(state)
        return None
    if player not in state.last_stand_bonus_players:
        return None
    territory_count = state.tax_haven_turn_start_territory_counts.get(
        player,
        count_player_territories(state, player),
    )
    territory_limit = get_tax_haven_territory_limit(state, player)
    if territory_limit is None or territory_count <= territory_limit:
        return None
    remove_tax_haven_player(state, player)
    university_count = count_player_universities(state, player)
    return (
        f"J{player + 1} controle {territory_count} territoires en debut de tour "
        f"avec {university_count} universite(s), au-dessus du plafond PF de {territory_limit} "
        f": paradis fiscal termine."
    )


# ----------------------------------------------------------------------
# Alliances
# ----------------------------------------------------------------------

def is_nation_alliance_active(state: GameState, player_a: int, player_b: int) -> bool:
    return player_a == player_b


def normalize_ai_alliance_key(ai_a: int, ai_b: int) -> Tuple[int, int]:
    return tuple(sorted((ai_a, ai_b)))


def get_commercial_city_wonder_ally(state: GameState) -> Optional[int]:
    ally = get_wonder_controller(state, "golden_pact_palace")
    if ally is None or is_commercial_city_player(state, ally):
        return None
    return ally


def cleanup_expired_alliances(state: GameState) -> None:
    # La branche guerre froide de x45 est morte (mecanique abandonnee).
    if state.active_alliances:
        state.active_alliances = {
            key: expires_turn
            for key, expires_turn in state.active_alliances.items()
            if state.turn < expires_turn
            and is_human_player_id(state, key[0])
            and is_ai_player(state, key[1])
            and any(terr.owner == key[0] for terr in state.territories)
            and any(terr.owner == key[1] for terr in state.territories)
        }
        state.alliance_start_turns = {
            key: start for key, start in state.alliance_start_turns.items()
            if key in state.active_alliances
        }
    if state.active_ai_alliances:
        state.active_ai_alliances = {
            key: expires_turn
            for key, expires_turn in state.active_ai_alliances.items()
            if state.turn < expires_turn
            and all(is_ai_player(state, player) for player in key)
            and all(not is_onu_player(state, player) for player in key)
            and all(any(terr.owner == player for terr in state.territories) for player in key)
        }
        state.ai_alliance_start_turns = {
            key: start_turn
            for key, start_turn in state.ai_alliance_start_turns.items()
            if key in state.active_ai_alliances
        }
    if state.active_offensive_alliances:
        state.active_offensive_alliances = {
            key: (target, expires_turn)
            for key, (target, expires_turn) in state.active_offensive_alliances.items()
            if state.turn < expires_turn
            and is_human_player_id(state, key[0])
            and is_ai_player(state, key[1])
            and any(terr.owner == key[0] for terr in state.territories)
            and any(terr.owner == key[1] for terr in state.territories)
            and any(terr.owner == target for terr in state.territories)
        }
        state.offensive_alliance_start_turns = {
            key: start for key, start in state.offensive_alliance_start_turns.items()
            if key in state.active_offensive_alliances
        }
    enforce_commercial_city_wonder_exclusivity(state)


def is_alliance_active(state: GameState, human_player: int, ai_player: int) -> bool:
    cleanup_expired_alliances(state)
    return state.turn < state.active_alliances.get((human_player, ai_player), -1)


def is_offensive_alliance_active(state: GameState, human_player: int, ai_player: int) -> bool:
    cleanup_expired_alliances(state)
    data = state.active_offensive_alliances.get((human_player, ai_player))
    return data is not None and state.turn < data[1]


def is_ai_alliance_active(state: GameState, ai_a: int, ai_b: int) -> bool:
    if ai_a == ai_b:
        return False
    cleanup_expired_alliances(state)
    key = normalize_ai_alliance_key(ai_a, ai_b)
    return state.turn < state.active_ai_alliances.get(key, -1)


def is_attack_blocked_by_alliance(state: GameState, attacker: int, defender: int) -> bool:
    if attacker != defender and "orvane_oath" in state.wonder_territories:
        # Un serment definitif se tient : le patron et son allie ne
        # s'attaquent pas, dans un sens comme dans l'autre.
        patron = get_eternal_ally_patron(state)
        if patron is not None:
            bloc = get_victory_bloc(state, patron)
            if len(bloc) > 1 and attacker in bloc and defender in bloc:
                return True
    if attacker != defender and "golden_pact_palace" in state.wonder_territories:
        attacker_is_commercial = is_commercial_city_player(state, attacker)
        defender_is_commercial = is_commercial_city_player(state, defender)
        if attacker_is_commercial or defender_is_commercial:
            # Le Palais remplace entierement la diplomatie initiale de la CC,
            # meme quand il n'a plus de controleur valide (territoire passe a
            # l'ONU, fige ou aux mains de la CC) : la CC n'a alors simplement
            # plus d'allie protege et attaque tout le monde.
            ally = get_commercial_city_wonder_ally(state)
            other_player = defender if attacker_is_commercial else attacker
            return ally is not None and other_player == ally
    if attacker != defender and state.final_duel_active:
        champions = set(state.final_duel_champions or ())
        attacker_bloc = state.final_duel_alliances.get(
            attacker, attacker if attacker in champions else None)
        defender_bloc = state.final_duel_alliances.get(
            defender, defender if defender in champions else None)
        if attacker_bloc is not None and attacker_bloc == defender_bloc:
            return True
    # Guerre froide et vassaux : mecaniques abandonnees, blocs morts dans x45.
    if attacker != defender and is_nation_alliance_active(state, attacker, defender):
        if is_human_player_id(state, attacker) and is_ai_player(state, defender):
            return False
        return True
    if attacker != defender and is_commercial_city_player(state, attacker):
        if is_commercial_city_player(state, defender) or is_human_player_id(state, defender):
            return False
    if attacker != defender and is_ai_player(state, attacker) and is_ai_player(state, defender):
        if is_ai_alliance_active(state, attacker, defender):
            return True
        attacker_cc = is_commercial_city_player(state, attacker)
        defender_cc = is_commercial_city_player(state, defender)
        if attacker_cc != defender_cc:
            return True
    if is_ai_player(state, attacker) and is_human_player_id(state, defender):
        return is_alliance_active(state, defender, attacker)
    return False


def break_alliance_due_to_human_attack(state: GameState, attacker: int, defender: int) -> Optional[str]:
    if not is_human_player_id(state, attacker) or not is_ai_player(state, defender):
        return None
    key = (attacker, defender)
    messages = []
    # Alliance nationale : is_nation_alliance_active exige attacker == defender,
    # impossible ici (humain vs IA) ; la branche de x45 est morte.
    if is_alliance_active(state, attacker, defender):
        state.active_alliances.pop(key, None)
        state.alliance_start_turns.pop(key, None)
        messages.append(f"alliance defensive rompue avec J{defender + 1}")
    if is_offensive_alliance_active(state, attacker, defender):
        state.active_offensive_alliances.pop(key, None)
        state.offensive_alliance_start_turns.pop(key, None)
        messages.append(f"alliance offensive rompue avec J{defender + 1}")
    if not messages:
        return None
    message = f"Alliance rompue : J{attacker + 1} attaque J{defender + 1} (" + ", ".join(messages) + ")."
    record_major_event(state, message)
    return message


# ----------------------------------------------------------------------
# Nations
# ----------------------------------------------------------------------

def get_owned_components(state: GameState, player: int) -> List[List[int]]:
    owned_ids = {terr.id for terr in state.territories if terr.owner == player}
    components: List[List[int]] = []
    seen: Set[int] = set()
    for territory_id in sorted(owned_ids):
        if territory_id in seen:
            continue
        stack = [territory_id]
        seen.add(territory_id)
        component: List[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor_id in state.territories[current].neighbors:
                if neighbor_id in owned_ids and neighbor_id not in seen:
                    seen.add(neighbor_id)
                    stack.append(neighbor_id)
        components.append(sorted(component))
    return components


def component_has_all_nation_structures(state: GameState, territory_ids: List[int]) -> bool:
    territory_set = set(territory_ids)
    return (
        bool(state.fortress_territory_ids & territory_set)
        and bool(state.factory_territory_ids & territory_set)
        and bool(state.port_territory_ids & territory_set)
        and bool(state.airport_territory_ids & territory_set)
        and bool(state.temple_territory_ids & territory_set)
        and any(get_cultural_center_count(state, tid) > 0 for tid in territory_set)
        and bool(state.university_territory_ids & territory_set)
    )


def get_active_regular_capital_id_for_player(state: GameState, player: int) -> Optional[int]:
    capital_id = state.player_capital_ids.get(player)
    if capital_id is None or not (0 <= capital_id < len(state.territories)):
        return None
    if state.territories[capital_id].owner != player:
        return None
    if is_onu_player(state, player) or is_potential_commercial_city_player(state, player):
        return None
    return capital_id


def component_has_active_regular_capital(state: GameState, player: int, territory_ids: List[int]) -> bool:
    territory_set = set(territory_ids)
    if is_commercial_city_player(state, player):
        capital_id = get_commercial_city_capital_id(state, player)
        return capital_id is not None and capital_id in territory_set
    capital_id = get_active_regular_capital_id_for_player(state, player)
    return capital_id is not None and capital_id in territory_set


def player_qualifies_for_nation_via_capitol(state: GameState, player: int) -> bool:
    """Capitole d'Aurelia : la capitale posee sur la merveille ouvre a elle
    seule le statut de nation, sans exigence de taille ni de structures.

    Le statut est acquis immediatement (cf.
    ``update_nation_qualification_progress``) : ni delai de conservation, ni
    bloc d'un seul tenant, ni amenagements. Que la capitale ait ete deplacee
    sur la merveille ou la merveille batie sur la capitale ne change rien.
    """
    capitol_id = state.wonder_territories.get("aurelia_capitol")
    if capitol_id is None or not (0 <= capitol_id < len(state.territories)):
        return False
    if state.territories[capitol_id].owner != player:
        return False
    return component_has_active_regular_capital(state, player, [capitol_id])


def find_player_nation_component(
    state: GameState, player: int, require_capital: bool = True,
) -> Optional[List[int]]:
    if player < 0 or is_onu_player(state, player):
        return None
    if player_qualifies_for_nation_via_capitol(state, player):
        capitol_id = state.wonder_territories["aurelia_capitol"]
        for component in get_owned_components(state, player):
            if capitol_id in component:
                return component
    for component in get_owned_components(state, player):
        if len(component) < NATION_MIN_TERRITORIES:
            continue
        if not component_has_all_nation_structures(state, component):
            continue
        if require_capital and not component_has_active_regular_capital(state, player, component):
            continue
        return component
    return None


def reset_nation_qualification_progress(state: GameState, player: int) -> None:
    state.nation_qualification_start_turns.pop(player, None)


def convert_commercial_city_to_nation(state: GameState, player: int) -> Optional[str]:
    if player not in state.commercial_city_players:
        return None
    former_capital_id = get_commercial_city_capital_id(state, player)
    state.commercial_city_players.discard(player)
    state.commercial_city_capital_ids.pop(player, None)
    state.last_stand_bonus_players.discard(player)
    state.last_stand_bonus_territory.pop(player, None)
    if (
        former_capital_id is not None
        and 0 <= former_capital_id < len(state.territories)
        and state.territories[former_capital_id].owner == player
    ):
        state.player_capital_ids[player] = former_capital_id
    assign_ai_personality_to_player(state, player, "standard")
    state.pending_commercial_city_spawns = max(0, state.pending_commercial_city_spawns) + 1
    sanitize_player_capitals(state)
    return (
        f"J{player + 1} perd definitivement son statut de Cite commercante et devient une nation IA standard. "
        "Une nouvelle Cite commercante apparaitra au debut du prochain cycle de tours."
    )


def form_nation_for_player(state: GameState, player: int) -> Optional[str]:
    if player in state.nation_players:
        return None
    component = find_player_nation_component(state, player)
    if component is None:
        return None
    cc_note = convert_commercial_city_to_nation(state, player)
    state.nation_players.add(player)
    reset_nation_qualification_progress(state, player)
    state.nation_capital_loss_start_turns.pop(player, None)
    message = (
        f"Tour {state.turn}: J{player + 1} devient une nation "
        f"({len(component)} territoires contigus avec tous les amenagements requis). "
        f"Ses revenus sont desormais divises par {NATION_INCOME_DIVISOR}."
    )
    if cc_note:
        message += " " + cc_note
    record_major_event(state, message)
    return message


def update_nation_qualification_progress(state: GameState, player: int) -> Optional[str]:
    if player in state.nation_players:
        reset_nation_qualification_progress(state, player)
        return None
    component = find_player_nation_component(state, player)
    if component is None:
        reset_nation_qualification_progress(state, player)
        return None
    if player_qualifies_for_nation_via_capitol(state, player):
        # Capitole d'Aurelia : le statut de nation est acquis des que la
        # capitale est posee sur la merveille (ou la merveille sur la
        # capitale), sans delai de conservation ni aucune autre condition.
        return form_nation_for_player(state, player)
    if player not in state.nation_qualification_start_turns:
        state.nation_qualification_start_turns[player] = state.turn
        return (
            f"Tour {state.turn}: J{player + 1} remplit les criteres nationaux. "
            f"Il devra les conserver pendant {NATION_QUALIFICATION_DELAY_TURNS} tours."
        )
    if state.turn - state.nation_qualification_start_turns[player] < NATION_QUALIFICATION_DELAY_TURNS:
        return None
    return form_nation_for_player(state, player)


def lose_nation_status_if_needed(state: GameState, player: int) -> Optional[str]:
    if player not in state.nation_players:
        state.nation_capital_loss_start_turns.pop(player, None)
        return None

    territory_count = count_player_territories(state, player)
    loss_reason: Optional[str] = None
    if territory_count <= 1:
        loss_reason = "il ne controle plus qu'un territoire"
    else:
        capital_id = get_active_regular_capital_id_for_player(state, player)
        if capital_id is not None:
            state.nation_capital_loss_start_turns.pop(player, None)
            return None
        if player not in state.nation_capital_loss_start_turns:
            state.nation_capital_loss_start_turns[player] = state.turn
            return (
                f"Tour {state.turn}: J{player + 1} n'a plus de capitale. "
                f"Le statut de nation sera perdu si la situation dure {NATION_CAPITAL_LOSS_DELAY_TURNS} tours."
            )
        if state.turn - state.nation_capital_loss_start_turns[player] < NATION_CAPITAL_LOSS_DELAY_TURNS:
            return None
        loss_reason = "il est reste dix tours sans capitale"

    state.nation_players.discard(player)
    reset_nation_qualification_progress(state, player)
    state.nation_capital_loss_start_turns.pop(player, None)
    territory = next((terr for terr in state.territories if terr.owner == player), None)
    if territory is not None and territory_count <= 1:
        add_tax_haven_capital(state, player, territory.id)
        if territory.id not in state.fortress_territory_ids:
            state.fortress_territory_ids.add(territory.id)
            state.fortress_capture_counts[territory.id] = 0
        message = f"Tour {state.turn}: J{player + 1} perd son statut de nation ({loss_reason}) et bascule en paradis fiscal sur {territory.name}."
    else:
        message = f"Tour {state.turn}: J{player + 1} perd son statut de nation ({loss_reason})."
    record_major_event(state, message)
    return message


def sanitize_nation_diplomacy(state: GameState) -> None:
    active_players = set(get_active_players(state))
    state.nation_players = {
        player for player in state.nation_players
        if player in active_players
    }
    state.nation_qualification_start_turns = {
        player: start_turn
        for player, start_turn in state.nation_qualification_start_turns.items()
        if player in active_players and player not in state.nation_players
    }
    state.nation_capital_loss_start_turns = {
        player: start_turn
        for player, start_turn in state.nation_capital_loss_start_turns.items()
        if player in state.nation_players
    }
    # nation_alliances / nation_wars / guerre froide : mecaniques abandonnees,
    # x45 les remet a vide ; GameState ne les stocke pas.


def refresh_nation_states(state: GameState, trigger_player: Optional[int] = None) -> List[str]:
    if state.final_duel_active:
        state.nation_players = set()
        state.nation_qualification_start_turns = {}
        state.nation_capital_loss_start_turns = {}
        return []
    messages: List[str] = []
    active_players = get_active_players(state)
    for player in list(state.nation_players):
        message = lose_nation_status_if_needed(state, player)
        if message:
            messages.append(message)
    for player in active_players:
        message = update_nation_qualification_progress(state, player)
        if message:
            messages.append(message)
    sanitize_nation_diplomacy(state)
    return messages


# ----------------------------------------------------------------------
# Territoires soumis (protectorats ONU)
# ----------------------------------------------------------------------

def is_sanctuary_territory(state: GameState, territory_id: int) -> bool:
    return territory_id in state.sanctuary_territory_ids


def is_submitted_territory(state: GameState, territory_id: int) -> bool:
    return territory_id in state.submitted_territory_ids


def should_force_submit_for_nation_limit(state: GameState, attacker: int) -> bool:
    return False


def get_nation_territory_limit(state: GameState, player: int) -> int:
    return 10 ** 9


def should_submit_conquered_territory(
    state: GameState,
    attacker: int,
    territory: Territory,
    defeated_regiments: int = 1,
    rng=random,
    submit_decider=None,
) -> bool:
    """Decide si un territoire conquis par une nation est soumis a l'ONU.

    Pour une IA, la regle est aleatoire (1 chance sur
    ``AI_NATION_SUBMISSION_DENOMINATOR``). Pour un humain, la decision est
    deleguee a ``submit_decider(attacker, territory, defeated_regiments)`` :
    boite de dialogue dans x45, question au client dans la version web.
    Sans decideur, l'annexion normale s'applique (comme x45 sans Tkinter).
    """
    if state.final_duel_active:
        return False
    if attacker not in state.nation_players:
        return False
    if is_sanctuary_territory(state, territory.id) or territory.owner == state.onu_player_id:
        return False
    if is_ai_player(state, attacker):
        return rng.randint(1, AI_NATION_SUBMISSION_DENOMINATOR) == 1
    if submit_decider is not None:
        return bool(submit_decider(attacker, territory, defeated_regiments))
    return False


def submit_conquered_territory(state: GameState, territory_id: int, overlord: int, regiments: int) -> bool:
    if state.final_duel_active:
        return False
    if overlord not in state.nation_players:
        return False
    if not (0 <= territory_id < len(state.territories)):
        return False
    terr = state.territories[territory_id]
    terr.owner = state.onu_player_id
    terr.regiments = max(1, int(regiments))
    terr.reinforcement_bonus = 1
    state.sanctuary_territory_ids.add(territory_id)
    state.submitted_territory_ids.add(territory_id)
    state.submitted_territory_overlords[territory_id] = overlord
    state.submitted_territory_created_turns[territory_id] = state.turn
    state.ultra_super_territory_ids.discard(territory_id)
    state.super_territory_ids.discard(territory_id)
    return True


# ----------------------------------------------------------------------
# Eliminations
# ----------------------------------------------------------------------

def mark_eliminated_player_if_human(state: GameState, player: int) -> None:
    if is_human_player_id(state, player):
        state.eliminated_human_players.add(player)


def refresh_eliminated_human_players(state: GameState) -> None:
    state.eliminated_human_players = {
        player for player in state.eliminated_human_players
        if 0 <= player < state.num_players
        and is_human_player_id(state, player)
        and not any(terr.owner == player for terr in state.territories)
    }


def transfer_eliminated_player_money(state: GameState, eliminated_player: int, winner: int) -> str:
    if eliminated_player < 0 or winner < 0 or eliminated_player == winner:
        return ""
    ensure_player_economy(state, eliminated_player)
    ensure_player_economy(state, winner)
    amount = state.player_money.get(eliminated_player, 0)
    if amount <= 0:
        return ""
    state.player_money[winner] += amount
    state.player_money[eliminated_player] = 0
    return f" J{winner + 1} recupere {amount} ecu(s) de J{eliminated_player + 1}."


# ----------------------------------------------------------------------
# Evenements punitifs (annexion de sanctuaire, chaos)
# ----------------------------------------------------------------------

def is_protected_from_revolt(state: GameState, territory_id: int) -> bool:
    """Ce territoire est-il a l'abri d'une revolte ou d'une trahison ?

    Version simplifiee uniquement : une forteresse ne change jamais de camp
    sans combat. Il faut venir la prendre.
    """
    return is_simple_mode(state) and territory_id in state.fortress_territory_ids


def is_protected_from_revolt_by_national_religion(state: GameState, territory_id: int) -> bool:
    """Ce territoire est-il tenu par la foi de son proprietaire ?

    Avantage des religions nationales : un territoire sous l'influence de la
    religion nationale fondee par celui qui le possede ne se revolte jamais.
    Ni revolte, ni revolution, ni trahison, ni sedition. La religion de la
    merveille (Elyrion) ne protege pas.
    """
    if not (0 <= territory_id < len(state.territories)):
        return False
    religion_id = get_player_national_religion_id(state, state.territories[territory_id].owner)
    if religion_id is None:
        return False
    return state.religious_influence.get(territory_id) == religion_id


def choose_owned_contiguous_block(
    state: GameState, player: int, count: int, rng=random,
    exclude_fortresses: bool = False,
    exclude_religion_protected: bool = False,
) -> List[Territory]:
    """Choisit si possible un bloc contigu de territoires appartenant au joueur.

    Les capitales ordinaires actives sont exclues du tirage.
    ``exclude_fortresses`` ecarte en plus les territoires fortifies : les
    appelants le passent pour les revoltes et les trahisons, ou la version
    simplifiee protege les forteresses (``is_protected_from_revolt``).
    ``exclude_religion_protected`` ecarte les territoires acquis a la religion
    nationale de leur proprietaire : revoltes, revolutions et trahisons le
    passent, le chaos mondial non.
    """
    owned_ids = [
        terr.id for terr in state.territories
        if terr.owner == player and not is_active_regular_capital(state, terr.id)
        and not (exclude_fortresses and is_protected_from_revolt(state, terr.id))
        and not (
            exclude_religion_protected
            and is_protected_from_revolt_by_national_religion(state, terr.id)
        )
    ]
    if count <= 0 or not owned_ids:
        return []
    target_count = min(count, len(owned_ids))
    owned_set = set(owned_ids)

    components: List[List[int]] = []
    seen: Set[int] = set()
    for tid in owned_ids:
        if tid in seen:
            continue
        stack = [tid]
        seen.add(tid)
        component: List[int] = []
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor_id in state.territories[current].neighbors:
                if neighbor_id in owned_set and neighbor_id not in seen:
                    seen.add(neighbor_id)
                    stack.append(neighbor_id)
        components.append(component)

    eligible_components = [component for component in components if len(component) >= target_count]
    if eligible_components:
        component = rng.choice(eligible_components)
        start_id = rng.choice(component)
        selected: List[int] = [start_id]
        selected_set = {start_id}
        frontier = [nid for nid in state.territories[start_id].neighbors if nid in component]
        rng.shuffle(frontier)
        while frontier and len(selected) < target_count:
            picked = frontier.pop(0)
            if picked in selected_set:
                continue
            selected.append(picked)
            selected_set.add(picked)
            next_neighbors = [
                nid for nid in state.territories[picked].neighbors
                if nid in component and nid not in selected_set and nid not in frontier
            ]
            rng.shuffle(next_neighbors)
            frontier.extend(next_neighbors)
        if len(selected) < target_count:
            remaining = [tid for tid in component if tid not in selected_set]
            rng.shuffle(remaining)
            selected.extend(remaining[: target_count - len(selected)])
        return [state.territories[tid] for tid in selected[:target_count]]

    largest_component = max(components, key=len, default=[])
    selected_ids = list(largest_component)
    remaining_ids = [tid for tid in owned_ids if tid not in selected_ids]
    rng.shuffle(remaining_ids)
    selected_ids.extend(remaining_ids[: target_count - len(selected_ids)])
    return [state.territories[tid] for tid in selected_ids[:target_count]]


def allocate_rebel_player(state: GameState, rng=random) -> Tuple[int, bool]:
    """Cree toujours un nouveau joueur IA pour revolte, revolution ou chaos."""
    new_player = state.num_players
    state.num_players += 1
    state.base_ai_players.add(new_player)
    state.human_controlled_players.discard(new_player)
    state.auto_controlled_players.discard(new_player)
    assign_ai_personality_to_player(state, new_player, None, rng)
    ensure_player_economy(state, new_player)
    bind_eternal_ally_if_possible(state, new_player)
    return new_player, False


def build_global_chaos_event_message(state: GameState, rng=random, prefix: Optional[str] = None) -> Optional[str]:
    active_players = [
        player for player in get_active_players(state)
        if player not in state.nation_players
    ]
    if not active_players:
        return None

    original_owned = {
        player: [terr for terr in state.territories if terr.owner == player]
        for player in active_players
    }
    territory_changes: List[Tuple[Territory, int, Optional[int]]] = []
    summary_parts: List[str] = []

    for player in active_players:
        owned = original_owned[player]
        lost_count = len(owned) // 3
        if lost_count <= 0:
            continue
        territories_to_lose = choose_owned_contiguous_block(state, player, lost_count, rng)
        if not territories_to_lose:
            continue
        lost_count = len(territories_to_lose)
        summary_parts.append(f"J{player + 1} perd {lost_count}")
        for terr in territories_to_lose:
            receiver: Optional[int]
            if rng.random() < 0.5:
                receiver = None
            else:
                eligible_receivers = [p for p in active_players if p != player]
                receiver = rng.choice(eligible_receivers) if eligible_receivers else None
            territory_changes.append((terr, player, receiver))

    if not territory_changes:
        return None

    independent_groups: dict[int, List[Territory]] = {}
    transferred_count = 0
    for terr, previous_owner, receiver in territory_changes:
        if receiver is None:
            independent_groups.setdefault(previous_owner, []).append(terr)
        else:
            terr.owner = receiver
            transferred_count += 1

    independent_count = 0
    returning_players: List[int] = []
    new_ai_players: List[int] = []
    for previous_owner, territories in independent_groups.items():
        rebel_player, returning_human = allocate_rebel_player(state, rng)
        if returning_human:
            returning_players.append(rebel_player)
        else:
            new_ai_players.append(rebel_player)
        for terr in territories:
            terr.owner = rebel_player
        independent_count += len(territories)

    refresh_eliminated_human_players(state)
    state.turn_phase = "attack"
    detail = ", ".join(summary_parts[:5])
    if len(summary_parts) > 5:
        detail += ", ..."
    comeback_text = ""
    if returning_players:
        comeback_text = " Retour humain: " + ", ".join(f"J{player + 1}" for player in returning_players) + "."
    elif new_ai_players:
        comeback_text = " Nouveau(x) joueur(s) IA: " + ", ".join(f"J{player + 1}" for player in new_ai_players) + "."

    event_prefix = prefix if prefix is not None else f"Tour {state.turn}: episode de chaos."
    return (
        f"{event_prefix} {detail}. "
        f"{independent_count} territoire(s) independant(s), {transferred_count} transfere(s) a d'autres joueurs."
        + comeback_text
    )


def trigger_sanctuary_annexation_event(state: GameState, human_player: int, rng=random) -> str:
    """Sanction appliquee quand un humain annexe un territoire ONU."""
    owned = [terr for terr in state.territories if terr.owner == human_player]
    if len(owned) < 2:
        return "ONU annexee par un humain : sanction impossible, empire trop petit."

    event_type = rng.choice(["revolt_new", "revolt_transfer", "chaos"])

    if event_type == "chaos":
        message = build_global_chaos_event_message(
            state, rng,
            f"Sanctuaire ONU annexe par J{human_player + 1}: chaos mondial.",
        )
        if message is not None:
            return message
        return "Sanctuaire ONU annexe : chaos mondial impossible, trop peu de territoires a bouleverser."

    default_lost_count = min(5, len(owned))
    lost_count = calculate_cultural_revolt_or_betrayal_loss_count(state, human_player, default_lost_count)
    if lost_count <= 0:
        return f"Sanctuaire ONU annexe : sanction de revolte/trahison sans perte pour J{human_player + 1}{get_culture_protection_suffix(state, human_player)}."
    # La sanction est une revolte ou une trahison : en version simplifiee, les
    # forteresses y echappent comme aux evenements d'empire.
    territories_to_transfer = choose_owned_contiguous_block(
        state, human_player, lost_count, rng, exclude_fortresses=True,
        exclude_religion_protected=True,
    )
    if not territories_to_transfer:
        hors = "hors capitale et forteresse" if is_simple_mode(state) else "hors capitale"
        return f"Sanctuaire ONU annexe : sanction de revolte/trahison impossible, aucune cible valide {hors} pour J{human_player + 1}."
    lost_count = len(territories_to_transfer)

    if event_type == "revolt_transfer":
        active_players = [
            player for player in get_active_players(state)
            if player != human_player and not is_commercial_city_player(state, player)
        ]
        if active_players:
            territory_counts = {
                player: sum(1 for terr in state.territories if terr.owner == player)
                for player in active_players
            }
            min_count = min(territory_counts.values())
            receivers = [player for player, count in territory_counts.items() if count == min_count]
            beneficiary_player = rng.choice(receivers)
            for terr in territories_to_transfer:
                terr.owner = beneficiary_player
            refresh_eliminated_human_players(state)
            return f"Sanctuaire ONU annexe : trahison punitive. {lost_count} territoire(s) de J{human_player + 1} passent a J{beneficiary_player + 1}."

    new_player, returning_human = allocate_rebel_player(state, rng)
    for terr in territories_to_transfer:
        terr.owner = new_player
    refresh_eliminated_human_players(state)
    comeback = "nouveau joueur IA"
    return f"Sanctuaire ONU annexe : revolte punitive. {lost_count} territoire(s) de J{human_player + 1} passent a J{new_player + 1} ({comeback})."


# ----------------------------------------------------------------------
# Combat
# ----------------------------------------------------------------------

@dataclass
class AttackResult:
    """Resultat d'une passe de combat (retour x45 enrichi des messages).

    x45 stockait les messages dans des attributs d'instance
    (``last_special_conquest_message``, ``last_alliance_break_message``) et
    affichait l'elimination immediatement ; ici tout est renvoye a l'appelant.
    """

    att_text: str
    def_text: str
    conquered: bool
    special_conquest_message: str = ""
    alliance_break_message: str = ""
    elimination_message: Optional[str] = None


def can_attack_specific_target(
    state: GameState, src: Territory, dst: Territory, ignore_adjacency: bool = False,
) -> bool:
    """``ignore_adjacency=True`` : continuation d'un debarquement maritime
    (la cible n'est pas voisine, la flotte combat depuis la mer)."""
    if is_colonized_player(state, state.current_player):
        return False
    if src.owner != state.current_player or dst.owner == state.current_player or src.regiments < 2:
        return False
    if not ignore_adjacency and dst.id not in src.neighbors:
        return False
    if is_ai_player(state, src.owner) and is_territory_protected_from_ai_attacks(state, dst.id):
        return False
    if is_attack_blocked_by_alliance(state, src.owner, dst.owner):
        return False
    return True


def resolve_attack_once(
    state: GameState,
    src: Territory,
    dst: Territory,
    rng=random,
    submit_decider=None,
    max_attack_dice: Optional[int] = None,
) -> AttackResult:
    """Resout une passe d'attaque de ``src`` sur ``dst`` (miroir x45).

    ``submit_decider`` est transmis a ``should_submit_conquered_territory``
    pour les nations humaines. ``max_attack_dice`` plafonne les des de
    l'attaquant (handicap de debarquement des expeditions maritimes).
    """
    if is_ai_player(state, src.owner) and is_territory_protected_from_ai_attacks(state, dst.id):
        return AttackResult("attaque interdite", "territoire protege par le Rempart d'Ivoire", False)
    alliance_break_message = break_alliance_due_to_human_attack(state, src.owner, dst.owner) or ""
    if src.regiments >= 5 and can_player_attack_with_four_dice(state, src.owner):
        att_dice = 4
    else:
        att_dice = 1 if src.regiments == 2 else 2 if src.regiments == 3 else 3
    if max_attack_dice is not None:
        att_dice = min(att_dice, max_attack_dice)
    if dst.id in state.fortress_territory_ids and dst.regiments >= 3:
        def_dice = 3
    else:
        def_dice = 1 if dst.regiments == 1 else min(2, dst.regiments)

    att_rolls = sorted([rng.randint(1, 6) for _ in range(att_dice)], reverse=True)
    def_rolls = sorted([rng.randint(1, 6) for _ in range(def_dice)], reverse=True)

    comparisons = min(len(att_rolls), len(def_rolls))
    att_losses = 0
    def_losses = 0
    for i in range(comparisons):
        if att_rolls[i] > def_rolls[i]:
            def_losses += 1
        else:
            att_losses += 1

    defender_regiments_before_loss = dst.regiments
    src.regiments = max(1, src.regiments - att_losses)
    dst.regiments = max(0, dst.regiments - def_losses)

    if dst.regiments <= 0:
        previous_owner = dst.owner
        was_sanctuary = is_sanctuary_territory(state, dst.id)
        was_submitted = is_submitted_territory(state, dst.id)
        attacker = src.owner
        submitted_regiments = max(1, min(def_losses, defender_regiments_before_loss))
        submit_instead_of_annex = (
            not was_sanctuary
            and not was_submitted
            and should_submit_conquered_territory(
                state, attacker, dst, submitted_regiments, rng, submit_decider,
            )
        )
        dst.owner = attacker
        moved = src.regiments - 1 if src.regiments > 1 else 0
        if submit_instead_of_annex:
            dst.regiments = submitted_regiments
        else:
            src.regiments -= moved
            dst.regiments = moved

        culture_preserves_last_stand = (
            not submit_instead_of_annex
            and attacker in state.last_stand_bonus_players
            and has_culture_advantage(state, attacker, previous_owner)
        )
        # Une soumission n'est pas une annexion : le territoire bascule en
        # protectorat ONU et ne doit jamais faire perdre le statut de paradis
        # fiscal a l'attaquant.
        lost_last_stand_bonus = (
            False
            if submit_instead_of_annex or culture_preserves_last_stand
            else deactivate_last_stand_bonus_after_conquest(state, attacker)
        )
        special_capture_messages = register_special_capture(state, dst.id) if not submit_instead_of_annex else []
        original_capital_owner = get_regular_capital_owner(state, dst.id)
        if original_capital_owner is not None:
            if original_capital_owner == attacker:
                special_capture_messages.insert(0, f"{dst.name} redevient la capitale de J{attacker + 1}: revenu x10 restaure.")
            else:
                special_capture_messages.insert(0, f"{dst.name} est capturee : elle perd son statut de capitale de J{original_capital_owner + 1}.")

        if submit_instead_of_annex:
            forced_by_limit = should_force_submit_for_nation_limit(state, attacker)
            submit_conquered_territory(state, dst.id, attacker, submitted_regiments)
            if forced_by_limit:
                special_capture_messages.insert(0, f"{dst.name} est automatiquement soumis par J{attacker + 1}: limite nationale atteinte ({get_nation_territory_limit(state, attacker)} territoires controles).")
            else:
                special_capture_messages.insert(0, f"{dst.name} est soumis par J{attacker + 1}: tribut actif, garnison locale maintenue a {submitted_regiments} regiment(s).")

        if culture_preserves_last_stand:
            special_capture_messages.insert(0, f"J{attacker + 1} conserve son paradis fiscal grace a son avantage culturel.")
        elif lost_last_stand_bonus:
            special_capture_messages.insert(0, f"J{attacker + 1} perd son avantage financier de dernier bastion.")

        if was_sanctuary:
            state.sanctuary_territory_ids.discard(dst.id)
            state.submitted_territory_ids.discard(dst.id)
            state.submitted_territory_overlords.pop(dst.id, None)
            state.submitted_territory_created_turns.pop(dst.id, None)
            if is_human_player_id(state, attacker):
                special_conquest_message = trigger_sanctuary_annexation_event(state, attacker, rng)
            else:
                special_conquest_message = f"Ordinateur J{attacker + 1}: annexion d'un sanctuaire ONU. Aucun effet special."
            if special_capture_messages:
                special_conquest_message += " " + " ".join(special_capture_messages)
            nation_notes = refresh_nation_states(state, trigger_player=attacker)
            if nation_notes:
                special_conquest_message += " " + " ".join(nation_notes)
            record_replay_snapshot(
                state,
                f"Tour {state.turn} - J{attacker + 1} annexe le sanctuaire {dst.name}",
            )
            return AttackResult(
                f"{att_rolls}", f"{def_rolls}", True,
                special_conquest_message, alliance_break_message,
            )

        special_conquest_message = " ".join(special_capture_messages) if special_capture_messages else ""

        enforce_last_stand_bonus_limits(state)

        elimination_message: Optional[str] = None
        if previous_owner >= 0 and not any(t.owner == previous_owner for t in state.territories):
            if (
                state.final_duel_active
                and previous_owner in set(state.final_duel_champions or ())
            ):
                attacker_bloc = state.final_duel_alliances.get(
                    attacker,
                    attacker if attacker in set(state.final_duel_champions or ()) else None,
                )
                if attacker_bloc is not None and attacker_bloc != previous_owner:
                    state.final_duel_pending_winner = attacker_bloc
            mark_eliminated_player_if_human(state, previous_owner)
            refresh_eliminated_human_players(state)
            winner = attacker
            owned = [t for t in state.territories if t.owner == winner]
            for _ in range(5):
                if not owned:
                    break
                terr = rng.choice(owned)
                terr.regiments += 1
            money_note = transfer_eliminated_player_money(state, previous_owner, winner)
            elimination_message = (
                f"Le joueur {previous_owner + 1} est elimine ! "
                f"Le joueur {winner + 1} recoit 5 regiments de bonus." + money_note
            )
        nation_notes = refresh_nation_states(state, trigger_player=attacker)
        if nation_notes:
            if special_conquest_message:
                special_conquest_message += " " + " ".join(nation_notes)
            else:
                special_conquest_message = " ".join(nation_notes)
        action = "soumet" if submit_instead_of_annex else "conquiert"
        record_replay_snapshot(
            state,
            f"Tour {state.turn} - J{attacker + 1} {action} {dst.name}",
        )
        return AttackResult(
            f"{att_rolls}", f"{def_rolls}", True,
            special_conquest_message, alliance_break_message, elimination_message,
        )

    return AttackResult(f"{att_rolls}", f"{def_rolls}", False, "", alliance_break_message)


# ----------------------------------------------------------------------
# Science du tour
# ----------------------------------------------------------------------

def get_university_science_output(state: GameState, territory_id: int) -> int:
    age = max(0, int(state.university_ages.get(territory_id, 0)))
    if age >= 100:
        return 10
    if age >= 40:
        return 4
    if age >= 10:
        return 2
    return 1


def calculate_territory_science(state: GameState, territory: Territory) -> int:
    if territory.owner == state.onu_player_id or territory.id not in state.university_territory_ids:
        return 0
    return get_university_science_output(state, territory.id)


def calculate_player_science_income(state: GameState, player: int) -> int:
    if player < 0 or is_onu_player(state, player):
        return 0
    return sum(
        calculate_territory_science(state, terr)
        for terr in state.territories if terr.owner == player
    )


def get_base_player_science(state: GameState, player: int) -> int:
    if player < 0 or is_onu_player(state, player):
        return 0
    state.player_science.setdefault(player, 0)
    return state.player_science.get(player, 0)


def add_science_for_player(state: GameState, player: int) -> int:
    science_income = calculate_player_science_income(state, player)
    if science_income > 0:
        state.player_science[player] = get_base_player_science(state, player) + science_income
    else:
        state.player_science.setdefault(player, get_base_player_science(state, player))
    return science_income


def age_cultural_centers_one_turn(state: GameState) -> None:
    for tid in list(state.cultural_center_ages):
        state.cultural_center_ages[tid] = [age + 1 for age in state.cultural_center_ages.get(tid, [])]


def age_universities_one_turn(state: GameState) -> None:
    for tid in list(state.university_ages):
        if tid in state.university_territory_ids:
            state.university_ages[tid] = max(0, int(state.university_ages.get(tid, 0))) + 1
        else:
            state.university_ages.pop(tid, None)


# ----------------------------------------------------------------------
# Religion : fondation et expansion
# ----------------------------------------------------------------------

def get_religion_name(state: GameState, religion_id: int) -> str:
    if 0 <= religion_id < len(RELIGIONS):
        return str(RELIGIONS[religion_id]["name"])
    return "Religion inconnue"


def get_religion_symbol(state: GameState, religion_id: int) -> str:
    if 0 <= religion_id < len(RELIGIONS):
        return str(RELIGIONS[religion_id]["symbol"])
    return "?"


def is_wonder_religion(religion_id: Optional[int]) -> bool:
    """Elyrion et Solmyre : les religions nees d'une merveille."""
    return religion_id in WONDER_RELIGION_IDS


def get_founded_wonder_religion_ids(state: GameState) -> List[int]:
    """Les religions conquerantes dont la merveille fondatrice existe."""
    return [
        religion_id for religion_id, wonder_type in sorted(WONDER_RELIGION_SOURCES.items())
        if wonder_type in state.wonder_territories
    ]


def get_wonder_religion_id_for_wonder(wonder_type: Optional[str]) -> Optional[int]:
    for religion_id, source in WONDER_RELIGION_SOURCES.items():
        if source == wonder_type:
            return religion_id
    return None


def get_religion_founder(state: GameState, religion_id: int) -> Optional[int]:
    if is_wonder_religion(religion_id):
        return get_wonder_controller(state, WONDER_RELIGION_SOURCES[religion_id])
    for player, founded_religion_id in state.religion_founders.items():
        if founded_religion_id == religion_id:
            return player
    return None


def get_religion_spread_interval(state: GameState, religion_id: int) -> Optional[int]:
    founder = get_religion_founder(state, religion_id)
    if founder is None:
        return None
    temple_count = get_player_temple_count(state, founder)
    if temple_count <= 0:
        return None
    capped_count = min(7, temple_count)
    return RELIGION_SPREAD_INTERVAL_BY_TEMPLE_COUNT[capped_count]


def can_religion_replace(state: GameState, religion_id: int, territory_id: int) -> bool:
    """Cette religion peut-elle s'imposer sur un territoire deja acquis ?

    Une religion nationale ne recouvre jamais rien. Une religion conquerante
    recouvre tout, sauf l'autre religion conquerante : Elyrion et Solmyre
    sont l'unique rempart l'une contre l'autre.
    """
    if not is_wonder_religion(religion_id):
        return False
    installed = state.religious_influence.get(territory_id)
    if installed is None or installed == religion_id:
        return False
    return not is_wonder_religion(installed)


def apply_initial_religious_influence(state: GameState, religion_id: int, holy_site_id: int) -> None:
    candidates = [holy_site_id]
    if 0 <= holy_site_id < len(state.territories):
        candidates.extend(state.territories[holy_site_id].neighbors)
    for tid in candidates:
        if not (0 <= tid < len(state.territories)):
            continue
        if is_territory_tax_haven_immune_to_religion(state, tid):
            continue
        if (
            tid != holy_site_id
            and tid in state.religious_influence
            and not can_religion_replace(state, religion_id, tid)
        ):
            continue
        state.religious_influence[tid] = religion_id


def found_religion_if_possible(state: GameState, player: int, territory_id: int) -> Optional[str]:
    sanitize_religion_state(state)
    if player in state.religion_founders:
        return None
    used_religions = set(state.religion_founders.values())
    available = [religion_id for religion_id in range(WONDER_RELIGION_ID) if religion_id not in used_religions]
    if not available:
        return None
    religion_id = available[0]
    state.religion_founders[player] = religion_id
    state.religion_foundation_turns[religion_id] = state.turn
    state.religion_last_spread_turns[religion_id] = state.turn
    state.religion_holy_sites[religion_id] = territory_id
    apply_initial_religious_influence(state, religion_id, territory_id)
    name = get_religion_name(state, religion_id)
    symbol = get_religion_symbol(state, religion_id)
    return f"J{player + 1} fonde la religion {name} ({symbol}) sur {state.territories[territory_id].name}."


def expand_religious_influences_if_due(state: GameState) -> List[str]:
    sanitize_religion_state(state)
    messages: List[str] = []
    for religion_id in sorted(state.religion_foundation_turns):
        founder = get_religion_founder(state, religion_id)
        if founder is None:
            continue
        temple_count = get_player_temple_count(state, founder)
        interval = get_religion_spread_interval(state, religion_id)
        if interval is None:
            # Sans temple, l'expansion est completement arretee et son compteur
            # ne continue pas a accumuler des tours en attente.
            state.religion_last_spread_turns[religion_id] = state.turn
            continue
        founded_turn = state.religion_foundation_turns.get(religion_id, state.turn)
        last_spread_turn = state.religion_last_spread_turns.get(religion_id, founded_turn)
        if state.turn - last_spread_turn < interval:
            continue
        current_ids = [tid for tid, rid in state.religious_influence.items() if rid == religion_id]
        expansion_ids: Set[int] = set()
        for tid in current_ids:
            if not (0 <= tid < len(state.territories)):
                continue
            for neighbor_id in state.territories[tid].neighbors:
                if not (0 <= neighbor_id < len(state.territories)):
                    continue
                if is_territory_tax_haven_immune_to_religion(state, neighbor_id):
                    continue
                if (
                    neighbor_id not in state.religious_influence
                    or can_religion_replace(state, religion_id, neighbor_id)
                ):
                    expansion_ids.add(neighbor_id)
        for tid in sorted(expansion_ids):
            if tid not in state.religious_influence or can_religion_replace(state, religion_id, tid):
                state.religious_influence[tid] = religion_id
        state.religion_last_spread_turns[religion_id] = state.turn
        if expansion_ids:
            messages.append(
                f"{get_religion_name(state, religion_id)} etend son influence sur "
                f"{len(expansion_ids)} territoire(s) avec {temple_count} temple(s) "
                f"(rythme: tous les {interval} tour(s))."
            )
    return messages


# ----------------------------------------------------------------------
# Constructions (batiments et merveilles)
# ----------------------------------------------------------------------

def has_temple(state: GameState, territory_id: int) -> bool:
    return territory_id in state.temple_territory_ids


def has_university(state: GameState, territory_id: int) -> bool:
    return territory_id in state.university_territory_ids


def add_industrial_structure(state: GameState, territory_id: int, structure_type: str) -> bool:
    structure_sets = {
        "factory": state.factory_territory_ids,
        "airport": state.airport_territory_ids,
        "port": state.port_territory_ids,
    }
    target_set = structure_sets.get(structure_type)
    if target_set is None or not (0 <= territory_id < len(state.territories)):
        return False
    if territory_id in target_set:
        return False
    if get_industrial_structure_count(state, territory_id) > 0:
        return False
    target_set.add(territory_id)
    state.industrial_capture_counts.setdefault(territory_id, 0)
    _sync_legacy_industry_aliases(state)
    return True


def can_add_university(state: GameState, territory_id: int) -> bool:
    return 0 <= territory_id < len(state.territories) and territory_id not in state.university_territory_ids


def add_university(state: GameState, territory_id: int) -> bool:
    if not can_add_university(state, territory_id):
        return False
    state.university_territory_ids.add(territory_id)
    state.university_capture_counts.setdefault(territory_id, 0)
    state.university_ages.setdefault(territory_id, 0)
    return True


def can_add_temple(state: GameState, territory_id: int) -> bool:
    return 0 <= territory_id < len(state.territories) and territory_id not in state.temple_territory_ids


def add_temple(state: GameState, territory_id: int) -> bool:
    if not can_add_temple(state, territory_id):
        return False
    state.temple_territory_ids.add(territory_id)
    state.temple_capture_counts.setdefault(territory_id, 0)
    # Transient (jamais serialise) : derniere note de fondation de religion,
    # lue par l'interface de x45 apres un achat de temple.
    state.last_religion_foundation_message = None
    owner = state.territories[territory_id].owner
    if 0 <= owner < state.num_players:
        note = found_religion_if_possible(state, owner, territory_id)
        if note:
            state.last_religion_foundation_message = note
            record_major_event(state, f"Tour {state.turn}: {note}")
    return True


def can_add_cultural_center(state: GameState, territory_id: int) -> bool:
    if not (0 <= territory_id < len(state.territories)):
        return False
    if has_ruin(state, territory_id):
        # La ruine occupe la place : on ne rebatit pas sur ses pierres.
        return False
    return get_cultural_center_count(state, territory_id) < MAX_CULTURAL_CENTERS_PER_TERRITORY


def add_cultural_center(state: GameState, territory_id: int, age: int = 0) -> bool:
    if not can_add_cultural_center(state, territory_id):
        return False
    state.cultural_center_ages.setdefault(territory_id, []).append(max(0, int(age)))
    state.cultural_capture_counts.setdefault(territory_id, 0)
    return True


def get_wonder_name(wonder_type: Optional[str]) -> str:
    definition = WONDER_DEFINITIONS.get(wonder_type or "")
    return str(definition["name"]) if definition else "Merveille inconnue"


def get_wonder_effect(wonder_type: Optional[str]) -> str:
    definition = WONDER_DEFINITIONS.get(wonder_type or "")
    return str(definition["effect"]) if definition else ""


def get_available_wonder_types(state: GameState) -> List[str]:
    built = set(state.wonder_territories)
    return [wonder_type for wonder_type in WONDER_DEFINITIONS if wonder_type not in built]


def get_wonder_science_threshold(state: GameState, player: int) -> int:
    if is_ai_player(state, player):
        return AI_SCIENCE_WONDER_THRESHOLD
    return SCIENCE_WONDER_THRESHOLD


def can_player_build_wonder(state: GameState, player: int) -> bool:
    return has_science_level(state, player, get_wonder_science_threshold(state, player))


def is_cultural_wonder_type(wonder_type: Optional[str]) -> bool:
    definition = WONDER_DEFINITIONS.get(wonder_type or "")
    return bool(definition) and definition.get("kind") == "culture"


def is_late_wonder_type(wonder_type: Optional[str]) -> bool:
    """Merveille tardive : aucun seuil de science ni de culture, mais un tour."""
    definition = WONDER_DEFINITIONS.get(wonder_type or "")
    return bool(definition) and definition.get("kind") == "late"


def can_player_build_late_wonder(state: GameState, player: int) -> bool:
    return state.turn >= LATE_WONDER_FIRST_TURN


def get_wonder_cost(state: GameState, player: int, wonder_type: Optional[str]) -> int:
    """Le prix d'une merveille pour ce joueur.

    Les merveilles tardives coutent plus cher a un humain qu'a une IA ; les
    autres gardent leur prix unique.
    """
    if not is_late_wonder_type(wonder_type):
        return WONDER_COST
    return AI_LATE_WONDER_COST if is_ai_player(state, player) else LATE_WONDER_COST


def get_wonder_culture_threshold(state: GameState, player: int) -> int:
    if is_ai_player(state, player):
        return AI_CULTURE_WONDER_THRESHOLD
    return CULTURE_WONDER_THRESHOLD


def can_player_build_cultural_wonder(state: GameState, player: int) -> bool:
    return calculate_player_culture(state, player) >= get_wonder_culture_threshold(state, player)


def has_built_wonder_this_turn(state: GameState, player: int) -> bool:
    """Une seule merveille par joueur et par tour.

    Le registre vit en memoire de session (pas dans les sauvegardes) : il
    est reinitialise au chargement, comme la selection de la boutique.
    """
    return getattr(state, "wonder_construction_turns", {}).get(player) == state.turn


def can_player_build_wonder_type(state: GameState, player: int, wonder_type: str) -> bool:
    if is_late_wonder_type(wonder_type):
        return can_player_build_late_wonder(state, player)
    if is_cultural_wonder_type(wonder_type):
        return can_player_build_cultural_wonder(state, player)
    return can_player_build_wonder(state, player)


def get_buildable_wonder_types(state: GameState, player: int) -> List[str]:
    return [
        wonder_type for wonder_type in get_available_wonder_types(state)
        if can_player_build_wonder_type(state, player, wonder_type)
    ]


def get_wonder_type_at_territory(state: GameState, territory_id: int) -> Optional[str]:
    for wonder_type, wonder_territory_id in state.wonder_territories.items():
        if wonder_territory_id == territory_id:
            return wonder_type
    return None


def build_wonder(state: GameState, territory_id: int, wonder_type: str, record_event: bool = True) -> bool:
    if wonder_type not in WONDER_DEFINITIONS:
        return False
    if wonder_type in state.wonder_territories:
        return False
    if not (0 <= territory_id < len(state.territories)):
        return False
    if get_wonder_type_at_territory(state, territory_id) is not None:
        return False
    territory = state.territories[territory_id]
    if territory.owner < 0 or is_onu_player(state, territory.owner):
        return False
    state.wonder_territories[wonder_type] = territory_id
    # Registre en memoire du "une merveille par tour" (non sauvegarde).
    if not hasattr(state, "wonder_construction_turns"):
        state.wonder_construction_turns = {}
    state.wonder_construction_turns[territory.owner] = state.turn
    wonder_religion_id = get_wonder_religion_id_for_wonder(wonder_type)
    if wonder_religion_id is not None:
        state.religion_foundation_turns[wonder_religion_id] = state.turn
        state.religion_last_spread_turns[wonder_religion_id] = state.turn
        state.religion_holy_sites[wonder_religion_id] = territory_id
        apply_initial_religious_influence(state, wonder_religion_id, territory_id)
    elif wonder_type == "golden_pact_palace":
        enforce_commercial_city_wonder_exclusivity(state)
    if record_event:
        message = (
            f"Tour {state.turn}: J{territory.owner + 1} construit {get_wonder_name(wonder_type)} "
            f"sur {territory.name}. {get_wonder_effect(wonder_type)}."
        )
        record_major_event(state, message)
        record_replay_snapshot(state, message, force=True)
    return True


# ----------------------------------------------------------------------
# Expansion culturelle
# ----------------------------------------------------------------------

def is_territory_adjacent_to_player(state: GameState, territory_id: int, player: int) -> bool:
    if not (0 <= territory_id < len(state.territories)):
        return False
    return any(
        0 <= neighbor_id < len(state.territories)
        and state.territories[neighbor_id].owner == player
        for neighbor_id in state.territories[territory_id].neighbors
    )


def is_commercial_city_capital(state: GameState, territory_id: int) -> bool:
    if not (0 <= territory_id < len(state.territories)):
        return False
    owner = state.territories[territory_id].owner
    return is_commercial_city_player(state, owner) and get_commercial_city_capital_id(state, owner) == territory_id


def is_commercial_city_territory(state: GameState, territory_id: int) -> bool:
    return is_commercial_city_capital(state, territory_id)


def can_commercial_city_gain_territory(state: GameState, player: int, territory_id: int) -> bool:
    if player not in state.commercial_city_players:
        return True
    if is_any_capital_territory(state, territory_id):
        return False
    return is_territory_adjacent_to_player(state, territory_id, player)


def get_culture_expansion_target_ids(state: GameState, player: int) -> Set[int]:
    owned_ids = {territory.id for territory in state.territories if territory.owner == player}
    targets: Set[int] = set()
    for territory_id in owned_ids:
        if not (0 <= territory_id < len(state.territories)):
            continue
        for neighbor_id in state.territories[territory_id].neighbors:
            if 0 <= neighbor_id < len(state.territories) and neighbor_id not in owned_ids:
                target_owner = state.territories[neighbor_id].owner
                if target_owner in state.commercial_city_players:
                    continue
                if can_commercial_city_gain_territory(state, player, neighbor_id):
                    targets.add(neighbor_id)
    return targets


def annex_territory_by_culture(state: GameState, territory_id: int, player: int) -> Optional[int]:
    if not (0 <= territory_id < len(state.territories)):
        return None
    if state.territories[territory_id].owner in state.commercial_city_players:
        return None
    if not can_commercial_city_gain_territory(state, player, territory_id):
        return None
    territory = state.territories[territory_id]
    previous_owner = territory.owner
    if previous_owner == player:
        return None
    territory.owner = player

    # L'expansion culturelle est une annexion directe, pas une capture
    # militaire : la garnison et les constructions restent, mais les statuts
    # ONU disparaissent (les vassaux sont une mecanique abandonnee).
    state.sanctuary_territory_ids.discard(territory_id)
    state.submitted_territory_ids.discard(territory_id)
    state.submitted_territory_overlords.pop(territory_id, None)
    state.submitted_territory_created_turns.pop(territory_id, None)
    for territory_ids in state.integrated_submitted_territories.values():
        territory_ids.discard(territory_id)
    return previous_owner


def trigger_culture_expansions_if_due(state: GameState, player: int, rng=random) -> Tuple[List[str], int]:
    if player < 0 or is_onu_player(state, player):
        return [], 0

    culture = calculate_player_culture(state, player)
    previous_milestone = max(0, int(state.culture_expansion_milestones.get(player, 0)) // 50 * 50)
    reached_milestone = max(0, int(culture) // 50 * 50)
    if reached_milestone <= previous_milestone:
        return [], culture

    # Chaque palier de 50 franchi n'annexe plus qu'UN seul territoire
    # voisin, tire au hasard parmi les cibles contigues. Un palier est
    # consomme meme si aucun voisin n'est disponible. Les paliers franchis
    # pendant la vague (centres culturels annexes) sont consommes de la
    # meme facon.
    consumed_milestone = previous_milestone
    annexed_ids: List[int] = []
    while consumed_milestone < reached_milestone:
        consumed_milestone += 50
        target_ids = get_culture_expansion_target_ids(state, player)
        if target_ids:
            territory_id = rng.choice(sorted(target_ids))
            annex_territory_by_culture(state, territory_id, player)
            annexed_ids.append(territory_id)
        culture = calculate_player_culture(state, player)
        reached_milestone = max(reached_milestone, max(0, int(culture) // 50 * 50))
    state.culture_expansion_milestones[player] = reached_milestone

    refresh_last_stand_bonus_state(state)
    enforce_commercial_city_wonder_exclusivity(state)
    refresh_destroyed_commercial_cities(state)
    refresh_eliminated_human_players(state)
    refresh_nation_states(state, trigger_player=player)

    culture = calculate_player_culture(state, player)

    captured_names = ", ".join(state.territories[tid].name for tid in annexed_ids[:6])
    if len(annexed_ids) > 6:
        captured_names += ", ..."
    detail = f" ({captured_names})" if captured_names else ""
    crossed_count = max(1, (reached_milestone - previous_milestone) // 50)
    milestone_label = (
        f"Palier culturel {reached_milestone}"
        if crossed_count == 1
        else f"Paliers culturels franchis jusqu'a {reached_milestone}"
    )
    message = (
        f"{milestone_label}: J{player + 1} annexe au hasard "
        f"{len(annexed_ids)} territoire(s) adjacent(s){detail}."
    )
    record_major_event(state, f"Tour {state.turn}: {message}")
    record_replay_snapshot(state, f"Tour {state.turn}: {message}", force=True)
    return [message], culture


def calculate_cultural_revolution_loss_count(state: GameState, player: int, territory_count: int) -> int:
    protection_level = get_culture_protection_level(state, player)
    if protection_level >= 150:
        return 0
    denominator_by_level = {25: 4, 50: 5, 75: 6, 100: 7, 125: 10}
    denominator = denominator_by_level.get(protection_level, 3)
    return territory_count // denominator


# ----------------------------------------------------------------------
# Cites commerçantes : apparitions et acquisitions
# ----------------------------------------------------------------------

def spawn_pending_commercial_cities(state: GameState, rng=random) -> List[str]:
    spawn_count = max(0, int(state.pending_commercial_city_spawns))
    if spawn_count <= 0 or not state.territories:
        return []
    messages: List[str] = []
    for _ in range(spawn_count):
        # Jamais de CC sur un territoire a merveille : une CC nee sur le
        # Rempart d'Ivoire serait intouchable pour les IA (et pour l'allie
        # du Palais), ce qui peut geler la partie.
        forbidden = (
            set(state.sanctuary_territory_ids)
            | set(state.commercial_city_capital_ids.values())
            | set(state.player_capital_ids.values())
            | set(state.wonder_territories.values())
        )
        candidates = [
            terr for terr in state.territories
            if terr.id not in forbidden
            and terr.owner != state.onu_player_id
        ]
        if not candidates:
            candidates = [
                terr for terr in state.territories
                if terr.owner != state.onu_player_id
                and not is_any_capital_territory(state, terr.id)
                and terr.id not in set(state.wonder_territories.values())
            ]
        if not candidates:
            break
        territory = rng.choice(candidates)
        previous_owner = territory.owner
        new_player = state.num_players
        state.num_players += 1
        state.base_ai_players.add(new_player)
        state.human_controlled_players.discard(new_player)
        state.auto_controlled_players.discard(new_player)
        state.commercial_city_players.add(new_player)
        state.commercial_city_capital_ids[new_player] = territory.id
        assign_ai_personality_to_player(state, new_player, "aggressive")
        ensure_player_economy(state, new_player)

        # La nouvelle CC reprend le territoire tel quel : meme garnison,
        # meme bonus et memes amenagements.
        state.sanctuary_territory_ids.discard(territory.id)
        territory.owner = new_player

        if previous_owner >= 0 and not any(t.owner == previous_owner for t in state.territories):
            mark_eliminated_player_if_human(state, previous_owner)
        message = f"Tour {state.turn}: nouvelle Cite commercante fondee sur {territory.name} sous le nom J{new_player + 1}."
        record_major_event(state, message)
        messages.append(message)
    state.pending_commercial_city_spawns = max(0, spawn_count - len(messages))
    refresh_last_stand_bonus_state(state)
    refresh_eliminated_human_players(state)
    return messages


def calculate_corruption_surcharge(state: GameState, territory_id: int) -> int:
    surcharge = 0
    if territory_id in state.fortress_territory_ids:
        surcharge += CORRUPTION_FORTRESS_SURCHARGE
    surcharge += get_industrial_structure_count(state, territory_id) * CORRUPTION_INDUSTRIAL_SURCHARGE
    surcharge += get_cultural_center_count(state, territory_id) * CORRUPTION_CULTURAL_CENTER_SURCHARGE
    if territory_id in state.ultra_super_territory_ids or state.territories[territory_id].reinforcement_bonus >= 3:
        surcharge += CORRUPTION_BONUS_TERRITORY_SURCHARGE
    return surcharge


def calculate_corruption_cost(
    state: GameState, terr: Territory, attacker: Optional[int] = None,
) -> Tuple[int, int, int]:
    attacker = state.current_player if attacker is None else attacker
    cost_per_regiment = (
        REDUCED_CORRUPTION_COST_PER_REGIMENT
        if has_culture_advantage(state, attacker, terr.owner)
        else CORRUPTION_COST_PER_REGIMENT
    )
    base_cost = max(1, terr.regiments) * cost_per_regiment
    surcharge = calculate_corruption_surcharge(state, terr.id)
    return base_cost + surcharge, base_cost, surcharge


def transfer_territory_to_commercial_city(state: GameState, territory_id: int, player: int) -> None:
    if not (0 <= territory_id < len(state.territories)):
        return
    if not can_commercial_city_gain_territory(state, player, territory_id):
        return
    previous_owner = state.territories[territory_id].owner
    state.sanctuary_territory_ids.discard(territory_id)
    state.submitted_territory_ids.discard(territory_id)
    state.submitted_territory_overlords.pop(territory_id, None)
    state.submitted_territory_created_turns.pop(territory_id, None)
    state.territories[territory_id].owner = player
    if previous_owner >= 0 and not any(t.owner == previous_owner for t in state.territories):
        mark_eliminated_player_if_human(state, previous_owner)
        refresh_eliminated_human_players(state)
    refresh_last_stand_bonus_state(state)


# ----------------------------------------------------------------------
# Ponts (geometrie en cellules, dimensions de cellule en pixels injectees)
# ----------------------------------------------------------------------

def get_bridge_coastal_cells(state: GameState, territory_id: int) -> List[Tuple[int, int]]:
    cache = getattr(state, "bridge_coastal_cells_cache", None)
    if cache is None:
        state.bridge_coastal_cells_cache = {}
        cache = state.bridge_coastal_cells_cache
    if territory_id in cache:
        return cache[territory_id]
    if not (0 <= territory_id < len(state.territories)):
        return []
    coastal = [
        (row, col)
        for row, col in state.territories[territory_id].cells
        if any(state.grid_territory[nr][nc] < 0 for nr, nc in state.neighbors4(row, col))
    ]
    cache[territory_id] = coastal
    return coastal


def bridge_segment_is_over_water(
    state: GameState,
    territory_a: int,
    territory_b: int,
    start: Tuple[int, int],
    end: Tuple[int, int],
) -> bool:
    dr = end[0] - start[0]
    dc = end[1] - start[1]
    steps = max(2, int(max(abs(dr), abs(dc)) * 5))
    crossed_water = False
    reached_b = False
    for index in range(steps + 1):
        ratio = index / steps
        row = max(0, min(state.rows - 1, int(round(start[0] + dr * ratio))))
        col = max(0, min(state.cols - 1, int(round(start[1] + dc * ratio))))
        territory_id = state.grid_territory[row][col]
        if territory_id == territory_a:
            if crossed_water or reached_b:
                return False
        elif territory_id < 0:
            if reached_b:
                return False
            crossed_water = True
        elif territory_id == territory_b:
            if not crossed_water:
                return False
            reached_b = True
        else:
            return False
    return crossed_water and reached_b


def find_bridge_connection_points(
    state: GameState,
    territory_a: int,
    territory_b: int,
    cell_width: float,
    cell_height: float,
) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
    key = tuple(sorted((int(territory_a), int(territory_b))))
    cache = getattr(state, "bridge_geometry_cache", None)
    if cache is None:
        state.bridge_geometry_cache = {}
        cache = state.bridge_geometry_cache
    if key in cache:
        return cache[key]
    a, b = key
    if a == b or not (0 <= a < len(state.territories) and 0 <= b < len(state.territories)):
        cache[key] = None
        return None
    coast_a = get_bridge_coastal_cells(state, a)
    coast_b = get_bridge_coastal_cells(state, b)
    if not coast_a or not coast_b:
        cache[key] = None
        return None

    min_row_a, max_row_a = min(row for row, _col in coast_a), max(row for row, _col in coast_a)
    min_col_a, max_col_a = min(col for _row, col in coast_a), max(col for _row, col in coast_a)
    min_row_b, max_row_b = min(row for row, _col in coast_b), max(row for row, _col in coast_b)
    min_col_b, max_col_b = min(col for _row, col in coast_b), max(col for _row, col in coast_b)
    row_gap = max(0, min_row_b - max_row_a, min_row_a - max_row_b) * cell_height
    col_gap = max(0, min_col_b - max_col_a, min_col_a - max_col_b) * cell_width
    if math.hypot(row_gap, col_gap) > BRIDGE_MAX_LENGTH_PX:
        cache[key] = None
        return None

    max_distance_sq = BRIDGE_MAX_LENGTH_PX ** 2
    possible_pairs: List[Tuple[float, Tuple[int, int], Tuple[int, int]]] = []
    for cell_a in coast_a:
        ax = (cell_a[1] + 0.5) * cell_width
        ay = (cell_a[0] + 0.5) * cell_height
        for cell_b in coast_b:
            bx = (cell_b[1] + 0.5) * cell_width
            by = (cell_b[0] + 0.5) * cell_height
            distance_sq = (bx - ax) ** 2 + (by - ay) ** 2
            if distance_sq <= max_distance_sq:
                possible_pairs.append((distance_sq, cell_a, cell_b))
    possible_pairs.sort(key=lambda item: item[0])
    for _distance_sq, start, end in possible_pairs:
        if bridge_segment_is_over_water(state, a, b, start, end):
            cache[key] = (start, end)
            return cache[key]
    cache[key] = None
    return None


def get_valid_bridge_candidates(
    state: GameState, cell_width: float, cell_height: float,
) -> List[Tuple[Tuple[int, int], Tuple[Tuple[int, int], Tuple[int, int]]]]:
    candidates = []
    for territory_a in range(len(state.territories)):
        for territory_b in range(territory_a + 1, len(state.territories)):
            key = (territory_a, territory_b)
            if territory_b in state.territories[territory_a].neighbors or key in state.bridge_links:
                continue
            points = find_bridge_connection_points(state, territory_a, territory_b, cell_width, cell_height)
            if points is not None:
                candidates.append((key, points))
    return candidates


def get_territory_graph_distance(state: GameState, start: int, target: int) -> int:
    if start == target:
        return 0
    visited = {start}
    frontier = [(start, 0)]
    while frontier:
        current, distance = frontier.pop(0)
        for neighbor in state.territories[current].neighbors:
            if neighbor == target:
                return distance + 1
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append((neighbor, distance + 1))
    return len(state.territories) + 1


def add_bridge(
    state: GameState,
    key: Tuple[int, int],
    points: Tuple[Tuple[int, int], Tuple[int, int]],
    fragile: bool = False,
) -> None:
    normalized = tuple(sorted(key))
    state.bridge_links.add(normalized)
    state.bridge_link_points[normalized] = points
    if fragile:
        state.fragile_bridge_links.add(normalized)
    else:
        state.fragile_bridge_links.discard(normalized)
    state.apply_bridge_links_to_neighbors()


def maybe_spawn_random_bridge(
    state: GameState, cell_width: float, cell_height: float, rng=random,
) -> Optional[str]:
    if rng.randint(1, BRIDGE_SPAWN_DENOMINATOR) != 1:
        return None
    candidates = get_valid_bridge_candidates(state, cell_width, cell_height)
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: get_territory_graph_distance(state, item[0][0], item[0][1]),
        reverse=True,
    )
    preferred_count = max(1, math.ceil(len(ranked) / 4))
    key, points = rng.choice(ranked[:preferred_count])
    add_bridge(state, key, points, fragile=True)
    a, b = key
    message = (
        f"Tour {state.turn}: un pont apparait entre {state.territories[a].name} "
        f"et {state.territories[b].name}."
    )
    record_major_event(state, message)
    record_replay_snapshot(state, message, force=True)
    return message


def maybe_collapse_fragile_bridges(state: GameState, rng=random) -> Optional[str]:
    bridges = sorted(set(state.bridge_links) & set(state.fragile_bridge_links))
    if not bridges or rng.randint(1, BRIDGE_COLLAPSE_DENOMINATOR) != 1:
        return None

    key = rng.choice(bridges)
    a, b = key
    label = ""
    if 0 <= a < len(state.territories) and 0 <= b < len(state.territories):
        label = f"{state.territories[a].name}-{state.territories[b].name}"
    state.bridge_links.discard(key)
    state.fragile_bridge_links.discard(key)
    state.bridge_link_points.pop(key, None)
    state.recompute_neighbors_from_grid()

    message = f"Tour {state.turn}: un pont s'effondre"
    if label:
        message += f" ({label})"
    message += "."
    record_major_event(state, message)
    record_replay_snapshot(state, message, force=True)
    return message


# ----------------------------------------------------------------------
# Expeditions maritimes (attaque a travers une etendue d'eau continue)
# ----------------------------------------------------------------------

def _get_expedition_cache(state: GameState) -> dict:
    cache = getattr(state, "expedition_geometry_cache", None)
    if cache is None:
        cache = {}
        state.expedition_geometry_cache = cache
    return cache


def get_water_body_grid(state: GameState) -> List[List[int]]:
    """Identifie les plans d'eau connexes de la carte.

    Retourne une grille de la taille de la carte : -1 pour la terre, sinon
    l'identifiant du plan d'eau de la cellule. La connexite suit la meme
    adjacence que les territoires (toroidale sur les cartes personnalisees).
    La grille ne change jamais en cours de partie : le resultat est mis en
    cache sur l'etat.
    """
    cache = _get_expedition_cache(state)
    if "bodies" in cache:
        return cache["bodies"]
    body_grid = [[-1] * state.cols for _ in range(state.rows)]
    next_body = 0
    for row in range(state.rows):
        for col in range(state.cols):
            if state.grid_territory[row][col] >= 0 or body_grid[row][col] != -1:
                continue
            body_grid[row][col] = next_body
            stack = [(row, col)]
            while stack:
                current_row, current_col = stack.pop()
                for nr, nc in state.iter_adjacency_neighbors(current_row, current_col):
                    if state.grid_territory[nr][nc] < 0 and body_grid[nr][nc] == -1:
                        body_grid[nr][nc] = next_body
                        stack.append((nr, nc))
            next_body += 1
    cache["bodies"] = body_grid
    return body_grid


def get_territory_coasts_by_water_body(state: GameState, territory_id: int) -> Dict[int, List[Tuple[int, int]]]:
    """Les cellules cotieres d'un territoire, groupees par plan d'eau borde."""
    cache = _get_expedition_cache(state)
    coasts = cache.setdefault("coasts", {})
    if territory_id in coasts:
        return coasts[territory_id]
    result: Dict[int, Set[Tuple[int, int]]] = {}
    if 0 <= territory_id < len(state.territories):
        body_grid = get_water_body_grid(state)
        for row, col in state.territories[territory_id].cells:
            for nr, nc in state.iter_adjacency_neighbors(row, col):
                if state.grid_territory[nr][nc] < 0:
                    result.setdefault(body_grid[nr][nc], set()).add((row, col))
    normalized = {body: sorted(cells) for body, cells in result.items()}
    coasts[territory_id] = normalized
    return normalized


def get_expedition_route_distance(
    state: GameState,
    territory_a: int,
    territory_b: int,
    cell_width: float,
    cell_height: float,
) -> Optional[float]:
    """Distance en pixels de la route maritime entre deux territoires.

    Les deux territoires doivent border un meme plan d'eau connexe ; la
    distance est celle des deux points cotiers les plus proches (centres de
    cellules) donnant sur ce plan d'eau. Sur les cartes personnalisees
    (toroidales), la distance passe par le bord le plus court, comme
    l'adjacence. Retourne None si aucune etendue d'eau continue ne relie
    les deux territoires.
    """
    key = (min(territory_a, territory_b), max(territory_a, territory_b))
    cache = _get_expedition_cache(state)
    routes = cache.setdefault("routes", {})
    if key in routes:
        return routes[key]
    a, b = key
    distance: Optional[float] = None
    if a != b and 0 <= a < len(state.territories) and 0 <= b < len(state.territories):
        coasts_a = get_territory_coasts_by_water_body(state, a)
        coasts_b = get_territory_coasts_by_water_body(state, b)
        toroidal = state.map_mode == "custom"
        best_sq: Optional[float] = None
        for body in sorted(set(coasts_a) & set(coasts_b)):
            for row_a, col_a in coasts_a[body]:
                for row_b, col_b in coasts_b[body]:
                    row_gap = abs(row_a - row_b)
                    col_gap = abs(col_a - col_b)
                    if toroidal:
                        row_gap = min(row_gap, state.rows - row_gap)
                        col_gap = min(col_gap, state.cols - col_gap)
                    dx = col_gap * cell_width
                    dy = row_gap * cell_height
                    distance_sq = dx * dx + dy * dy
                    if best_sq is None or distance_sq < best_sq:
                        best_sq = distance_sq
        if best_sq is not None:
            distance = math.sqrt(best_sq)
    routes[key] = distance
    return distance


def get_territory_border_cells(state: GameState, territory_id: int) -> List[Tuple[int, int]]:
    """Les cellules du territoire qui touchent autre chose que lui-meme.

    La distance minimale entre deux territoires disjoints est toujours
    atteinte sur leurs bords : les comparer suffit, et cela evite de
    parcourir des interieurs entiers.
    """
    cache = _get_expedition_cache(state)
    borders = cache.setdefault("borders", {})
    if territory_id in borders:
        return borders[territory_id]
    cells: List[Tuple[int, int]] = []
    if 0 <= territory_id < len(state.territories):
        for row, col in state.territories[territory_id].cells:
            for neighbor_row, neighbor_col in state.iter_adjacency_neighbors(row, col):
                if state.grid_territory[neighbor_row][neighbor_col] != territory_id:
                    cells.append((row, col))
                    break
        if not cells:
            # Un territoire qui couvre toute la grille n'a pas de bord.
            cells = [tuple(cell) for cell in state.territories[territory_id].cells]
    borders[territory_id] = cells
    return cells


def get_territory_pixel_distance(
    state: GameState,
    territory_a: int,
    territory_b: int,
    cell_width: float,
    cell_height: float,
) -> Optional[float]:
    """Distance a vol d'oiseau, en pixels, entre deux territoires.

    De centre de cellule a centre de cellule, comme les routes maritimes,
    et par le bord le plus court sur les cartes personnalisees (toroidales).
    Contrairement a une route maritime, elle ne demande aucune eau commune :
    un missile survole ce qu'il veut.
    """
    if not (0 <= territory_a < len(state.territories)):
        return None
    if not (0 <= territory_b < len(state.territories)):
        return None
    if territory_a == territory_b:
        return 0.0
    toroidal = state.map_mode == "custom"
    cells_b = get_territory_border_cells(state, territory_b)
    best_sq: Optional[float] = None
    for row_a, col_a in get_territory_border_cells(state, territory_a):
        for row_b, col_b in cells_b:
            row_gap = abs(row_a - row_b)
            col_gap = abs(col_a - col_b)
            if toroidal:
                row_gap = min(row_gap, state.rows - row_gap)
                col_gap = min(col_gap, state.cols - col_gap)
            dx = col_gap * cell_width
            dy = row_gap * cell_height
            distance_sq = dx * dx + dy * dy
            if best_sq is None or distance_sq < best_sq:
                best_sq = distance_sq
    return math.sqrt(best_sq) if best_sq is not None else None


def get_distance_to_nearest_owned_territory(
    state: GameState,
    territory_id: int,
    player: int,
    cell_width: float,
    cell_height: float,
) -> Optional[float]:
    """Distance en pixels du territoire le plus proche appartenant au joueur."""
    if is_territory_adjacent_to_player(state, territory_id, player):
        # Voisins immediats : inutile de mesurer, c'est le minimum possible.
        return 0.0
    best: Optional[float] = None
    for terr in state.territories:
        if terr.owner != player or terr.id == territory_id:
            continue
        distance = get_territory_pixel_distance(
            state, territory_id, terr.id, cell_width, cell_height,
        )
        if distance is not None and (best is None or distance < best):
            best = distance
    return best


def get_expedition_risk_faces(distance_px: float) -> Tuple[int, ...]:
    """Les faces perdantes (25/50/75/100 %) du de a 64 faces pour une distance."""
    for max_distance, faces in EXPEDITION_RISK_TIERS:
        if max_distance is None or distance_px <= max_distance:
            return faces
    return EXPEDITION_RISK_TIERS[-1][1]


def can_player_launch_expeditions(state: GameState, player: int) -> bool:
    """Ce joueur a-t-il le droit d'embarquer en ce moment de la partie ?

    Les Cites commercantes restent a quai jusqu'au tour
    ``COMMERCIAL_CITY_EXPEDITION_FIRST_TURN`` : leurs debarquements de debut
    de partie faisaient trop mal aux joueurs humains.
    """
    if is_commercial_city_player(state, player):
        return state.turn >= COMMERCIAL_CITY_EXPEDITION_FIRST_TURN
    return True


def can_launch_expedition(
    state: GameState,
    src: Territory,
    dst: Territory,
    cell_width: float,
    cell_height: float,
) -> bool:
    """Une expedition maritime de ``src`` vers ``dst`` est-elle possible ?

    Memes conditions qu'une attaque classique, sauf l'adjacence : la cible
    ne doit PAS etre voisine (les voisins s'attaquent normalement) et les
    deux territoires doivent border la meme etendue d'eau continue. Les
    Cites commercantes n'embarquent pas avant le tour
    ``COMMERCIAL_CITY_EXPEDITION_FIRST_TURN``.
    """
    if is_colonized_player(state, state.current_player):
        return False
    if not can_player_launch_expeditions(state, state.current_player):
        return False
    if (
        src.owner != state.current_player
        or dst.owner == state.current_player
        or src.id == dst.id
        or dst.id in src.neighbors
        or src.regiments < 2
    ):
        return False
    if is_ai_player(state, src.owner) and is_territory_protected_from_ai_attacks(state, dst.id):
        return False
    if is_attack_blocked_by_alliance(state, src.owner, dst.owner):
        return False
    return get_expedition_route_distance(state, src.id, dst.id, cell_width, cell_height) is not None


def has_any_expedition_target(
    state: GameState,
    src: Territory,
    cell_width: float,
    cell_height: float,
) -> bool:
    """Une expedition maritime peut-elle partir de ``src`` vers une cible ?

    Sert aux interfaces : un territoire sans ennemi voisin reste un
    attaquant valable s'il peut embarquer par-dela les mers.
    """
    return any(
        can_launch_expedition(state, src, dst, cell_width, cell_height)
        for dst in state.territories
    )


def get_expedition_preview(
    state: GameState,
    src: Territory,
    dst: Territory,
    cell_width: float,
    cell_height: float,
) -> Optional[dict]:
    """L'apercu de l'encart de confirmation : distance, flotte et chances.

    Retourne None si l'expedition est impossible.
    """
    if not can_launch_expedition(state, src, dst, cell_width, cell_height):
        return None
    distance = get_expedition_route_distance(state, src.id, dst.id, cell_width, cell_height)
    faces = get_expedition_risk_faces(distance)
    return {
        "source": src.id,
        "cible": dst.id,
        "distance": round(distance, 1),
        "flotte": src.regiments - 1,
        "faces": EXPEDITION_DIE_FACES,
        "faces_indemne": EXPEDITION_DIE_FACES - sum(faces),
        "faces_pertes": {
            str(percent): count
            for percent, count in zip(EXPEDITION_LOSS_PERCENTS, faces)
        },
    }


def roll_sea_crossing_losses(
    fleet_size: int, distance_px: Optional[float], rng=random,
) -> Tuple[int, int, int]:
    """Tire le de a 64 faces d'une traversee et en deduit les pertes.

    Partage par les expeditions d'attaque et les transports maritimes de fin
    de tour : meme de, memes paliers de distance, meme arrondi (au plus
    proche, avec au moins un regiment perdu des qu'il y a sinistre).
    Retourne ``(jet, pourcentage_de_pertes, regiments_perdus)``.
    """
    faces = get_expedition_risk_faces(distance_px)
    roll = rng.randint(1, EXPEDITION_DIE_FACES)
    loss_percent = 0
    threshold = 0
    for percent, count in zip(EXPEDITION_LOSS_PERCENTS, faces):
        threshold += count
        if roll <= threshold:
            loss_percent = percent
            break
    if loss_percent == 0:
        regiments_lost = 0
    else:
        regiments_lost = min(
            fleet_size, max(1, int(fleet_size * loss_percent / 100 + 0.5)),
        )
    return roll, loss_percent, regiments_lost


@dataclass
class ExpeditionCrossing:
    """Resultat de la traversee (jet du de a 64 faces), avant le debarquement."""

    src_id: int
    dst_id: int
    distance_px: float
    fleet_size: int        # regiments embarques (tout sauf 1)
    roll: int              # le jet du de a 64 faces
    loss_percent: int      # 0, 25, 50, 75 ou 100
    regiments_lost: int
    survivors: int
    destroyed: bool        # plus personne pour debarquer
    message: str = ""


def resolve_expedition_crossing(
    state: GameState,
    src: Territory,
    dst: Territory,
    cell_width: float,
    cell_height: float,
    rng=random,
) -> ExpeditionCrossing:
    """Embarque tous les regiments de ``src`` sauf un et resout la traversee.

    Mute l'etat : apres l'appel, ``src.regiments`` vaut 1 + survivants (la
    flotte au large reste comptee sur son port d'attache le temps du
    debarquement). Le combat se resout ensuite passe par passe par
    l'appelant via ``resolve_attack_once(..., max_attack_dice=
    EXPEDITION_MAX_ATTACK_DICE)`` tant que ``can_attack_specific_target(...,
    ignore_adjacency=True)`` : la flotte ne peut pas battre en retraite,
    elle conquiert ou disparait.
    """
    distance = get_expedition_route_distance(state, src.id, dst.id, cell_width, cell_height)
    fleet_size = src.regiments - 1
    roll, loss_percent, regiments_lost = roll_sea_crossing_losses(
        fleet_size, distance, rng,
    )
    survivors = fleet_size - regiments_lost
    src.regiments = 1 + survivors
    destroyed = survivors <= 0
    if destroyed:
        message = (
            f"Expedition maritime de {src.name} vers {dst.name} : naufrage en mer, "
            f"les {fleet_size} regiment(s) embarques disparaissent sans combattre."
        )
        record_major_event(state, f"Tour {state.turn}: {message}")
    elif regiments_lost:
        message = (
            f"Expedition maritime de {src.name} vers {dst.name} : sinistre en mer, "
            f"{regiments_lost} regiment(s) perdus ({loss_percent} % de la flotte). "
            f"{survivors} regiment(s) debarquent."
        )
    else:
        message = (
            f"Expedition maritime de {src.name} vers {dst.name} : traversee indemne, "
            f"{survivors} regiment(s) debarquent."
        )
    record_replay_snapshot(
        state,
        f"Tour {state.turn} - expedition maritime de J{src.owner + 1} : "
        f"{src.name} vers {dst.name}",
        force=True,
    )
    return ExpeditionCrossing(
        src.id, dst.id, distance, fleet_size, roll, loss_percent,
        regiments_lost, survivors, destroyed, message,
    )


# ----------------------------------------------------------------------
# Transports maritimes (phase de deplacement)
# ----------------------------------------------------------------------

def get_sea_transport_max_regiments(state: GameState, src: Territory) -> int:
    """Combien de regiments ``src`` peut embarquer maintenant.

    Deux plafonds : la garnison (il reste toujours au moins 1 regiment sur
    place, comme pour un deplacement terrestre) et le quota de deplacements
    de fin de tour encore disponible — chaque regiment transporte coute un
    deplacement.
    """
    if src.owner != state.current_player:
        return 0
    budget = get_end_turn_move_limit(state) - state.turn_move_count
    return max(0, min(src.regiments - 1, budget))


def can_transport_by_sea(
    state: GameState,
    src: Territory,
    dst: Territory,
    cell_width: float,
    cell_height: float,
) -> bool:
    """Un transport maritime de ``src`` vers ``dst`` est-il possible ?

    Memes conditions qu'un deplacement de fin de tour (deux territoires du
    joueur courant, garnison suffisante, quota disponible) sauf la continuite
    terrestre : elle doit justement manquer — si une chaine de territoires
    allies relie les deux, le deplacement ordinaire suffit et ne risque
    rien. Les deux territoires doivent border la meme etendue d'eau
    continue, comme pour une expedition d'attaque.
    """
    if src.id == dst.id:
        return False
    if src.owner != state.current_player or dst.owner != state.current_player:
        return False
    if get_sea_transport_max_regiments(state, src) <= 0:
        return False
    if can_move_between(state, src, dst):
        return False
    return get_expedition_route_distance(state, src.id, dst.id, cell_width, cell_height) is not None


def has_any_sea_transport_target(
    state: GameState,
    src: Territory,
    cell_width: float,
    cell_height: float,
) -> bool:
    """``src`` peut-il embarquer des troupes vers un territoire a lui ?

    Sert aux interfaces : elles n'annoncent le transport que s'il existe une
    destination possible.
    """
    return any(
        can_transport_by_sea(state, src, dst, cell_width, cell_height)
        for dst in state.territories
    )


def get_sea_transport_preview(
    state: GameState,
    src: Territory,
    dst: Territory,
    regiments: int,
    cell_width: float,
    cell_height: float,
) -> Optional[dict]:
    """L'apercu de l'encart « Entreprendre un voyage a travers les oceans ? ».

    Memes chances qu'une expedition d'attaque (de a 64 faces, paliers de
    distance). ``regiments`` est ramene entre 1 et le maximum autorise.
    Retourne None si le transport est impossible.
    """
    if not can_transport_by_sea(state, src, dst, cell_width, cell_height):
        return None
    maximum = get_sea_transport_max_regiments(state, src)
    try:
        embarques = int(regiments)
    except (TypeError, ValueError):
        embarques = 1
    embarques = max(1, min(embarques, maximum))
    distance = get_expedition_route_distance(state, src.id, dst.id, cell_width, cell_height)
    faces = get_expedition_risk_faces(distance)
    return {
        "source": src.id,
        "cible": dst.id,
        "distance": round(distance, 1),
        "regiments": embarques,
        "maximum": maximum,
        "faces": EXPEDITION_DIE_FACES,
        "faces_indemne": EXPEDITION_DIE_FACES - sum(faces),
        "faces_pertes": {
            str(percent): count
            for percent, count in zip(EXPEDITION_LOSS_PERCENTS, faces)
        },
    }


@dataclass
class SeaTransportResult:
    """Resultat d'un transport maritime de fin de tour."""

    src_id: int
    dst_id: int
    distance_px: float
    embarked: int          # regiments partis du territoire source
    roll: int              # le jet du de a 64 faces
    loss_percent: int      # 0, 25, 50, 75 ou 100
    regiments_lost: int
    survivors: int         # regiments effectivement debarques
    destroyed: bool        # plus personne n'arrive a bon port
    moves_spent: int       # deplacements consommes (= regiments embarques)
    message: str = ""


def resolve_sea_transport(
    state: GameState,
    src: Territory,
    dst: Territory,
    regiments: int,
    cell_width: float,
    cell_height: float,
    rng=random,
) -> Optional[SeaTransportResult]:
    """Transporte ``regiments`` de ``src`` vers ``dst`` par la mer.

    Mute l'etat : les regiments embarques quittent la source, les survivants
    arrivent a destination, et le quota de deplacements est debite du nombre
    embarque — ceux qui ont peri en mer avaient bel et bien pris le large.
    Retourne None si le transport n'est pas permis.
    """
    if not can_transport_by_sea(state, src, dst, cell_width, cell_height):
        return None
    maximum = get_sea_transport_max_regiments(state, src)
    try:
        embarked = int(regiments)
    except (TypeError, ValueError):
        return None
    if embarked < 1:
        return None
    embarked = min(embarked, maximum)

    distance = get_expedition_route_distance(state, src.id, dst.id, cell_width, cell_height)
    roll, loss_percent, regiments_lost = roll_sea_crossing_losses(embarked, distance, rng)
    survivors = embarked - regiments_lost

    src.regiments -= embarked
    dst.regiments += survivors
    state.turn_move_count += embarked
    destroyed = survivors <= 0

    if destroyed:
        message = (
            f"Transport maritime de {src.name} vers {dst.name} : naufrage en mer, "
            f"les {embarked} regiment(s) embarques disparaissent corps et biens."
        )
        record_major_event(state, f"Tour {state.turn}: {message}")
    elif regiments_lost:
        message = (
            f"Transport maritime de {src.name} vers {dst.name} : sinistre en mer, "
            f"{regiments_lost} regiment(s) perdus ({loss_percent} % du convoi). "
            f"{survivors} regiment(s) arrivent a bon port."
        )
    else:
        message = (
            f"Transport maritime de {src.name} vers {dst.name} : traversee indemne, "
            f"{survivors} regiment(s) arrivent a bon port."
        )
    record_replay_snapshot(
        state,
        f"Tour {state.turn} - transport maritime de J{src.owner + 1} : "
        f"{src.name} vers {dst.name}",
        force=True,
    )
    return SeaTransportResult(
        src.id, dst.id, distance, embarked, roll, loss_percent,
        regiments_lost, survivors, destroyed, embarked, message,
    )


# ----------------------------------------------------------------------
# Ressources programmees et marche
# ----------------------------------------------------------------------

def count_bonus_5_resources(state: GameState) -> int:
    return sum(1 for terr in state.territories if terr.reinforcement_bonus == 5)


def count_precious_mineral_mines(state: GameState) -> int:
    return len(state.precious_mineral_mine_ids)


def spawn_bonus_5_resource(
    state: GameState, rng=random, exclude: Optional[int] = None,
) -> Optional[str]:
    """Pose une ressource +5 sur un territoire tire au hasard.

    ``exclude`` ecarte un territoire du tirage : le gisement qui vient de
    s'epuiser ne peut pas se rallumer sur place.
    """
    candidates = [
        terr for terr in state.territories
        if terr.owner >= 0
        and not is_onu_player(state, terr.owner)
        and not is_sanctuary_territory(state, terr.id)
        and terr.reinforcement_bonus == 1
        and terr.id != exclude
    ]
    if not candidates:
        return None
    territory = rng.choice(candidates)
    territory.reinforcement_bonus = 5
    state.bonus_5_spawn_turns[territory.id] = state.turn
    return (
        f"une ressource +5 apparait sur {territory.name} "
        f"(5 renforts par tour, plafond militaire porte a 200, "
        f"epuisee dans {LATE_RESOURCE_LIFETIME_TURNS} tours)"
    )


def spawn_precious_mineral_mine(
    state: GameState, rng=random, exclude: Optional[int] = None,
) -> Optional[str]:
    """Pose une mine de minerais precieux sur un territoire tire au hasard.

    ``exclude`` ecarte un territoire du tirage : la mine qui vient de
    s'epuiser ne peut pas se reouvrir sur place.
    """
    candidates = [
        terr for terr in state.territories
        if terr.owner >= 0
        and not is_onu_player(state, terr.owner)
        and not is_sanctuary_territory(state, terr.id)
        and terr.id not in state.precious_mineral_mine_ids
        and terr.id != exclude
    ]
    if not candidates:
        return None
    territory = rng.choice(candidates)
    state.precious_mineral_mine_ids.add(territory.id)
    state.precious_mineral_mine_spawn_turns[territory.id] = state.turn
    return (
        f"une mine de minerais precieux apparait sur {territory.name} "
        f"({PRECIOUS_MINERAL_MINE_INCOME} ecus par tour, "
        f"epuisee dans {LATE_RESOURCE_LIFETIME_TURNS} tours)"
    )


def get_territory_name_or_default(state: GameState, territory_id: int) -> str:
    if 0 <= territory_id < len(state.territories):
        return state.territories[territory_id].name
    return "un territoire disparu"


def get_late_resource_remaining_turns(
    state: GameState, territory_id: int, kind: str,
) -> Optional[int]:
    """Tours restants avant l'epuisement d'une ressource tardive.

    ``kind`` vaut "bonus_5" ou "mine". Retourne None si le territoire ne
    porte pas cette ressource, ou si son compteur n'a pas encore ete cale
    (sauvegarde ancienne : il le sera au prochain changement de tour).
    """
    spawn_turns = (
        state.bonus_5_spawn_turns if kind == "bonus_5"
        else state.precious_mineral_mine_spawn_turns
    )
    spawn_turn = spawn_turns.get(territory_id)
    if spawn_turn is None:
        return None
    return max(0, LATE_RESOURCE_LIFETIME_TURNS - (state.turn - int(spawn_turn)))


def _replacement_note(spawn, state: GameState, rng, expired_id: int, remaining: int) -> str:
    """Fait apparaitre le remplacant d'un gisement epuise, et le raconte.

    Rien n'est remplace si la sorte est deja au plafond : c'est ainsi qu'une
    partie commencee avec quatre gisements revient a trois.
    """
    if remaining >= LATE_RESOURCE_TARGET_COUNT:
        return (
            f" et n'est pas remplacee : il en reste {remaining}, "
            f"le maximum desormais en jeu."
        )
    arrival = spawn(state, rng, exclude=expired_id)
    if arrival:
        return f" ; {arrival}."
    return " (aucun territoire libre pour la remplacer)."


def rotate_expired_late_resources(state: GameState, rng=random) -> List[str]:
    """Epuise les ressources tardives arrivees au bout de leurs vingt tours.

    Chaque gisement epuise est aussitot remplace par un equivalent sur un
    autre territoire tire au hasard : le nombre de ressources en jeu ne
    change pas, seule leur position tourne.
    """
    sync_late_resource_lifetimes(state)
    messages: List[str] = []

    for territory_id, spawn_turn in sorted(state.bonus_5_spawn_turns.items()):
        if state.turn - spawn_turn < LATE_RESOURCE_LIFETIME_TURNS:
            continue
        state.bonus_5_spawn_turns.pop(territory_id, None)
        name = get_territory_name_or_default(state, territory_id)
        if 0 <= territory_id < len(state.territories):
            terr = state.territories[territory_id]
            if terr.reinforcement_bonus == 5:
                terr.reinforcement_bonus = 1
        messages.append(
            f"Tour {state.turn}: la ressource +5 de {name} est epuisee apres "
            f"{LATE_RESOURCE_LIFETIME_TURNS} tours"
            + _replacement_note(
                spawn_bonus_5_resource, state, rng, territory_id,
                count_bonus_5_resources(state),
            )
        )

    for territory_id, spawn_turn in sorted(state.precious_mineral_mine_spawn_turns.items()):
        if state.turn - spawn_turn < LATE_RESOURCE_LIFETIME_TURNS:
            continue
        state.precious_mineral_mine_spawn_turns.pop(territory_id, None)
        name = get_territory_name_or_default(state, territory_id)
        state.precious_mineral_mine_ids.discard(territory_id)
        messages.append(
            f"Tour {state.turn}: la mine de {name} est epuisee apres "
            f"{LATE_RESOURCE_LIFETIME_TURNS} tours"
            + _replacement_note(
                spawn_precious_mineral_mine, state, rng, territory_id,
                count_precious_mineral_mines(state),
            )
        )

    return messages


def maybe_spawn_scheduled_resources(state: GameState, rng=random) -> List[str]:
    """Fait apparaitre les ressources prevues au debut d'un nouveau tour global,
    et fait tourner celles qui arrivent au bout de leur duree de vie.

    En version simplifiee, seules les ressources +5 apparaissent : les mines
    de minerais precieux ne rapportent que des ecus.
    """
    messages: List[str] = []

    if (
        state.turn in BONUS_5_SPAWN_TURNS
        and count_bonus_5_resources(state) < LATE_RESOURCE_TARGET_COUNT
    ):
        arrival = spawn_bonus_5_resource(state, rng)
        if arrival:
            messages.append(f"Tour {state.turn}: {arrival}.")

    if (
        not is_simple_mode(state)
        and state.turn in PRECIOUS_MINERAL_MINE_SPAWN_TURNS
        and count_precious_mineral_mines(state) < LATE_RESOURCE_TARGET_COUNT
    ):
        arrival = spawn_precious_mineral_mine(state, rng)
        if arrival:
            messages.append(f"Tour {state.turn}: {arrival}.")

    messages.extend(rotate_expired_late_resources(state, rng))

    for message in messages:
        record_major_event(state, message)
    if messages:
        record_replay_snapshot(state, " | ".join(messages), force=True)
    return messages


def maybe_spawn_random_fortress(state: GameState, rng=random) -> Optional[str]:
    """Fait reapparaitre une forteresse (version simplifiee uniquement).

    Sans boutique, le stock de forteresses ne peut que diminuer : chacune est
    detruite a sa troisieme capture (``register_special_capture``). Ce tirage
    de debut de tour global en repose une ailleurs tant qu'il en reste moins
    que la cible, ponderee par la connectivite du territoire comme a la mise
    en place. Aucune exclusion : un sanctuaire ONU peut en recevoir une, comme
    c'est deja le cas au placement initial.
    """
    if not is_simple_mode(state):
        return None
    if len(state.fortress_territory_ids) >= SIMPLE_FORTRESS_TARGET_COUNT:
        return None
    if rng.randint(1, SIMPLE_FORTRESS_SPAWN_DENOMINATOR) != 1:
        return None

    candidates = [
        terr for terr in state.territories
        if terr.id not in state.fortress_territory_ids
    ]
    if not candidates:
        return None
    weights = [max(1, len(terr.neighbors)) ** 2 for terr in candidates]
    pick = rng.uniform(0, sum(weights))
    chosen = candidates[-1]
    running = 0.0
    for terr, weight in zip(candidates, weights):
        running += weight
        if pick <= running:
            chosen = terr
            break

    state.fortress_territory_ids.add(chosen.id)
    state.fortress_capture_counts[chosen.id] = 0
    message = (
        f"Tour {state.turn}: une forteresse est batie sur {chosen.name} "
        f"(3 des en defense des 3 regiments, detruite apres 3 captures)."
    )
    record_major_event(state, message)
    record_replay_snapshot(state, message, force=True)
    return message


def maybe_trigger_market_event(state: GameState, rng=random) -> Optional[str]:
    if not state.player_money:
        return None
    event_type: Optional[str] = None
    if rng.randint(1, 50) == 1:
        event_type = "crash"
    elif rng.randint(1, 10) == 1:
        event_type = "crise"
    if event_type is None:
        return None

    total_lost = 0
    if event_type == "crash":
        for player in list(state.player_money):
            current = state.player_money[player]
            lost = (current * 2) // 3
            state.player_money[player] = current - lost
            total_lost += lost
        message = f"Tour {state.turn}: crash boursier. Tous les joueurs perdent deux tiers de leurs ecus economises ({total_lost} ecu(s) perdus)."
    else:
        for player in list(state.player_money):
            current = state.player_money[player]
            lost = current // 3
            state.player_money[player] = current - lost
            total_lost += lost
        message = f"Tour {state.turn}: crise boursiere. Tous les joueurs perdent un tiers de leurs ecus economises ({total_lost} ecu(s) perdus)."
    record_major_event(state, message)
    return message


# ----------------------------------------------------------------------
# ONU : apparitions, liberations, integrations
# ----------------------------------------------------------------------

def get_onu_spawn_denominator(state: GameState) -> int:
    return 7 if state.difficulty_level == "gouvernement_mondial" else 10


def get_onu_release_denominator(state: GameState) -> int:
    return 10 if state.difficulty_level == "gouvernement_mondial" else 15


def get_submitted_territory_overlord(state: GameState, territory_id: int) -> Optional[int]:
    overlord = state.submitted_territory_overlords.get(territory_id)
    if overlord is None or overlord < 0 or overlord >= state.num_players:
        return None
    return overlord


def convert_territory_to_sanctuary(state: GameState, territory_id: int, regiments: Optional[int] = None) -> bool:
    if not (0 <= territory_id < len(state.territories)):
        return False
    if (
        territory_id in state.golden_territory_ids
        or is_commercial_city_territory(state, territory_id)
        or is_regular_capital_territory(state, territory_id)
    ):
        return False
    terr = state.territories[territory_id]
    terr.owner = state.onu_player_id
    terr.regiments = regiments if regiments is not None else max(1, terr.regiments)
    terr.reinforcement_bonus = 1
    state.sanctuary_territory_ids.add(territory_id)
    state.submitted_territory_ids.discard(territory_id)
    state.submitted_territory_overlords.pop(territory_id, None)
    state.submitted_territory_created_turns.pop(territory_id, None)
    state.ultra_super_territory_ids.discard(territory_id)
    state.super_territory_ids.discard(territory_id)
    return True


def maybe_spawn_random_sanctuary_territory(state: GameState, rng=random) -> Optional[str]:
    """Un territoire ordinaire peut devenir territoire ONU."""
    if rng.randint(1, get_onu_spawn_denominator(state)) != 1:
        return None
    tax_haven_capitals = get_all_tax_haven_capital_ids(state)
    forbidden = (
        set(state.sanctuary_territory_ids)
        | set(state.ultra_super_territory_ids)
        | set(state.golden_territory_ids)
        | set(state.precious_mineral_mine_ids)
        | {terr.id for terr in state.territories if terr.reinforcement_bonus >= 3}
        | tax_haven_capitals
        | {terr.id for terr in state.territories if is_commercial_city_player(state, terr.owner)}
        | set(state.player_capital_ids.values())
    )
    candidates = [terr for terr in state.territories if terr.owner >= 0 and terr.id not in forbidden]
    if not candidates:
        return None
    terr = rng.choice(candidates)
    previous_owner = terr.owner
    previous_regiments = terr.regiments
    convert_territory_to_sanctuary(state, terr.id, regiments=previous_regiments)
    refresh_eliminated_human_players(state)
    return f"Tour {state.turn}: intervention de l'ONU. {terr.name} quitte J{previous_owner + 1} et devient territoire ONU fige."


def maybe_release_random_sanctuary_territory(state: GameState, rng=random) -> Optional[str]:
    """Un territoire ONU peut redevenir un territoire ordinaire d'un joueur actif."""
    if rng.randint(1, get_onu_release_denominator(state)) != 1:
        return None
    sanctuary_ids = [
        tid for tid in state.sanctuary_territory_ids
        if 0 <= tid < len(state.territories) and not is_submitted_territory(state, tid)
    ]
    if not sanctuary_ids:
        return None
    active_players = [player for player in get_active_players(state) if not is_commercial_city_player(state, player)]
    if not active_players:
        return None

    territory_id = rng.choice(sanctuary_ids)
    terr = state.territories[territory_id]
    new_owner = rng.choice(active_players)
    state.sanctuary_territory_ids.discard(territory_id)
    terr.owner = new_owner
    terr.reinforcement_bonus = 1
    terr.regiments = max(1, terr.regiments)

    refresh_eliminated_human_players(state)
    return f"Tour {state.turn}: retrait de l'ONU. {terr.name} devient un territoire ordinaire de J{new_owner + 1}."


def integrate_due_submitted_territories(state: GameState) -> List[str]:
    """Integre les territoires soumis aux nations apres vingt tours consecutifs."""
    sanitize_submitted_territories(state)
    messages: List[str] = []
    for territory_id in sorted(list(state.submitted_territory_ids)):
        if not (0 <= territory_id < len(state.territories)):
            continue
        overlord = get_submitted_territory_overlord(state, territory_id)
        if overlord is None or overlord not in state.nation_players:
            # Le compteur reste valable uniquement tant que le suzerain est
            # toujours une nation, qu'elle soit humaine ou IA.
            state.submitted_territory_created_turns[territory_id] = state.turn
            continue
        created_turn = state.submitted_territory_created_turns.get(territory_id, state.turn)
        if state.turn - created_turn < SUBMITTED_TERRITORY_INTEGRATION_DELAY_TURNS:
            continue

        terr = state.territories[territory_id]
        state.sanctuary_territory_ids.discard(territory_id)
        state.submitted_territory_ids.discard(territory_id)
        state.submitted_territory_overlords.pop(territory_id, None)
        state.submitted_territory_created_turns.pop(territory_id, None)
        terr.owner = overlord
        terr.reinforcement_bonus = 1
        terr.regiments = max(1, terr.regiments)
        state.integrated_submitted_territories.setdefault(overlord, set()).add(territory_id)

        messages.append(
            f"Tour {state.turn}: {terr.name}, soumis depuis vingt tours consecutifs, "
            f"est integre a la nation J{overlord + 1}."
        )
    if messages:
        refresh_eliminated_human_players(state)
    return messages


def maybe_release_unstable_submitted_territories(state: GameState, rng=random) -> List[str]:
    """Chaque territoire soumis peut perdre son statut independamment (1 sur 40)."""
    sanitize_submitted_territories(state)
    submitted_ids = sorted(
        tid for tid in state.submitted_territory_ids
        if 0 <= tid < len(state.territories)
    )
    if not submitted_ids:
        return []

    active_players = [player for player in get_active_players(state) if not is_commercial_city_player(state, player)]
    if not active_players:
        return []

    messages: List[str] = []
    for territory_id in submitted_ids:
        if rng.randint(1, SUBMITTED_TERRITORY_INSTABILITY_DENOMINATOR) != 1:
            continue
        terr = state.territories[territory_id]
        previous_overlord = get_submitted_territory_overlord(state, territory_id)
        ai_recipients = [player for player in active_players if is_ai_player(state, player)]
        new_owner = rng.choice(ai_recipients or active_players)

        state.sanctuary_territory_ids.discard(territory_id)
        state.submitted_territory_ids.discard(territory_id)
        state.submitted_territory_overlords.pop(territory_id, None)
        state.submitted_territory_created_turns.pop(territory_id, None)
        terr.owner = new_owner
        terr.reinforcement_bonus = 1
        terr.regiments = max(1, terr.regiments)

        if previous_overlord is not None:
            messages.append(
                f"Tour {state.turn}: instabilite du territoire soumis. {terr.name} cesse d'etre soumis a J{previous_overlord + 1} "
                f"et devient un territoire ordinaire de J{new_owner + 1}."
            )
        else:
            messages.append(
                f"Tour {state.turn}: instabilite du territoire soumis. {terr.name} devient un territoire ordinaire de J{new_owner + 1}."
            )

    if messages:
        refresh_eliminated_human_players(state)
    return messages


# ----------------------------------------------------------------------
# Sedition, chaos et evenements d'empire
# ----------------------------------------------------------------------

def calculate_sedition_chance_points(state: GameState, territory: Territory) -> int:
    if territory.owner in state.nation_players or is_commercial_city_player(state, territory.owner):
        return 0
    if is_active_regular_capital(state, territory.id) or has_university(state, territory.id):
        return 0
    if is_protected_from_revolt_by_national_religion(state, territory.id):
        return 0
    regiments = max(0, int(territory.regiments))
    return min(SEDITION_DENOMINATOR, regiments * regiments)


def get_random_ai_recipient_for_sedition(state: GameState, previous_owner: int, rng=random) -> int:
    candidates = [
        player for player in get_active_players(state)
        if player != previous_owner and is_ai_player(state, player) and not is_commercial_city_player(state, player)
    ]
    if candidates:
        return rng.choice(candidates)

    new_player = state.num_players
    state.num_players += 1
    state.base_ai_players.add(new_player)
    assign_ai_personality_to_player(state, new_player, None, rng)
    ensure_player_economy(state, new_player)
    bind_eternal_ally_if_possible(state, new_player)
    return new_player


def maybe_trigger_sedition_at_end_of_turn(state: GameState, rng=random) -> Optional[str]:
    tax_haven_capitals = get_all_tax_haven_capital_ids(state)
    seditions: List[Tuple[str, int, int]] = []

    for terr in state.territories:
        if terr.owner < 0 or is_sanctuary_territory(state, terr.id) or terr.owner == state.onu_player_id:
            continue
        if is_commercial_city_player(state, terr.owner):
            continue
        if terr.id in tax_haven_capitals:
            continue

        chance_points = calculate_sedition_chance_points(state, terr)
        if chance_points <= 0:
            continue
        if rng.randint(1, SEDITION_DENOMINATOR) > chance_points:
            continue

        previous_owner = terr.owner
        new_owner = get_random_ai_recipient_for_sedition(state, previous_owner, rng)
        terr.owner = new_owner
        seditions.append((terr.name, previous_owner, new_owner))

    if not seditions:
        return None

    refresh_last_stand_bonus_state(state)
    enforce_last_stand_bonus_limits(state)
    for _name, previous_owner, _new_owner in seditions:
        if previous_owner >= 0 and not any(t.owner == previous_owner for t in state.territories):
            mark_eliminated_player_if_human(state, previous_owner)
    refresh_eliminated_human_players(state)

    details = ", ".join(
        f"{name}: J{previous_owner + 1} -> J{new_owner + 1}"
        for name, previous_owner, new_owner in seditions[:5]
    )
    if len(seditions) > 5:
        details += ", ..."
    plural = "s" if len(seditions) > 1 else ""
    message = f"Fin du tour {state.turn}: sedition. {len(seditions)} territoire{plural} change{plural} de camp ({details})."
    record_major_event(state, message)
    return message


def maybe_trigger_chaos_event(state: GameState, rng=random) -> Optional[str]:
    if state.difficulty_level != "chaos" or state.turn % 10 == 0:
        return None
    if rng.randint(1, 20) != 1:
        return None

    message = build_global_chaos_event_message(state, rng)
    if message is None:
        return None
    record_major_event(state, message)
    return message


def maybe_trigger_empire_event(state: GameState, rng=random) -> List[str]:
    """Evenements globaux de debut de tour ; retourne les messages a afficher."""
    if state.last_empire_event_turn == state.turn:
        return []

    state.last_empire_event_turn = state.turn
    state.turn_phase = "attack"
    shown_messages: List[str] = []

    turn_event_messages = []
    spawned_onu_message = maybe_spawn_random_sanctuary_territory(state, rng)
    if spawned_onu_message:
        turn_event_messages.append(spawned_onu_message)
    turn_event_messages.extend(integrate_due_submitted_territories(state))
    turn_event_messages.extend(maybe_release_unstable_submitted_territories(state, rng))
    # integrate_due_vassals : mecanique abandonnee, toujours vide.
    released_onu_message = maybe_release_random_sanctuary_territory(state, rng)
    if released_onu_message:
        turn_event_messages.append(released_onu_message)
    if turn_event_messages:
        combined_event_message = " | ".join(turn_event_messages)
        record_major_event(state, combined_event_message)
        shown_messages.append(combined_event_message)

    if state.turn < 10:
        chaos_message = maybe_trigger_chaos_event(state, rng)
        if chaos_message:
            shown_messages.append(chaos_message)
        return shown_messages

    # Version simplifiee : les revolutions generales sont ecartees, les tours
    # multiples de 40 tombent donc dans la branche trahison/revolte ci-dessous.
    if state.turn % 40 == 0 and not is_simple_mode(state):
        active_players = get_active_players(state)
        if not active_players:
            return shown_messages

        revolution_type = rng.choice(["separate_rebels", "single_rebel_bloc"])
        split_count = 0
        skipped_players: List[int] = []
        summary_parts: List[str] = []
        pending_transfers: List[Tuple[int, int, List[Territory]]] = []

        for player in active_players:
            if player in state.nation_players or is_commercial_city_player(state, player):
                skipped_players.append(player)
                continue
            owned = [terr for terr in state.territories if terr.owner == player]
            if len(owned) < 3:
                skipped_players.append(player)
                continue

            lost_count = calculate_cultural_revolution_loss_count(state, player, len(owned))
            if lost_count <= 0:
                skipped_players.append(player)
                continue

            territories_to_split = choose_owned_contiguous_block(
                state, player, lost_count, rng, exclude_religion_protected=True,
            )
            if not territories_to_split:
                skipped_players.append(player)
                continue
            lost_count = len(territories_to_split)

            pending_transfers.append((player, lost_count, territories_to_split))

        if not pending_transfers:
            event_message = f"Tour {state.turn}: aucune revolution possible, tous les empires restants sont trop petits ou immunises."
            record_major_event(state, event_message)
            shown_messages.append(event_message)
            return shown_messages

        if revolution_type == "single_rebel_bloc":
            new_player, returning_human = allocate_rebel_player(state, rng)
            total_lost = 0
            for player, lost_count, territories_to_split in pending_transfers:
                for terr in territories_to_split:
                    terr.owner = new_player
                total_lost += len(territories_to_split)
                summary_parts.append(f"J{player + 1} perd {lost_count}")
            split_count = len(pending_transfers)
            comeback_label = "nouveau joueur IA"
            revolution_label = (
                f"revolution generale centralisee. Tous les territoires separes passent a J{new_player + 1} "
                f"({comeback_label}, {total_lost} territoire(s)). "
            )
        else:
            for player, lost_count, territories_to_split in pending_transfers:
                new_player, returning_human = allocate_rebel_player(state, rng)
                for terr in territories_to_split:
                    terr.owner = new_player
                split_count += 1
                comeback_label = " IA"
                summary_parts.append(
                    f"J{player + 1} -> J{new_player + 1}{comeback_label} ({lost_count} territoire(s))"
                )
            revolution_label = "revolution generale des empires. "

        refresh_eliminated_human_players(state)

        skipped_text = ""
        if skipped_players:
            skipped_labels = ", ".join(f"J{player + 1}" for player in skipped_players)
            skipped_text = f" Empires non touches: {skipped_labels}."

        event_message = f"Tour {state.turn}: {revolution_label}" + " | ".join(summary_parts) + skipped_text
        record_major_event(state, event_message)
        shown_messages.append(event_message)
        return shown_messages

    if state.turn % 10 != 0:
        chaos_message = maybe_trigger_chaos_event(state, rng)
        if chaos_message:
            shown_messages.append(chaos_message)
        return shown_messages

    active_players = [
        player
        for player in get_active_players(state)
        if player not in state.nation_players
        and not is_commercial_city_player(state, player)
    ]
    if not active_players:
        event_message = f"Tour {state.turn}: aucun evenement d'empire, aucun joueur actif non immunise."
        record_major_event(state, event_message)
        shown_messages.append(event_message)
        return shown_messages

    territory_counts = {player: sum(1 for terr in state.territories if terr.owner == player) for player in active_players}
    max_count = max(territory_counts.values())
    leaders = [player for player, count in territory_counts.items() if count == max_count]
    target_player = rng.choice(leaders)
    owned = [terr for terr in state.territories if terr.owner == target_player]

    default_lost_count = min(5, len(owned))
    lost_count = calculate_cultural_revolt_or_betrayal_loss_count(state, target_player, default_lost_count)
    if lost_count <= 0:
        event_message = f"Tour {state.turn}: evenement d'empire neutralise pour J{target_player + 1}{get_culture_protection_suffix(state, target_player)}."
        record_major_event(state, event_message)
        shown_messages.append(event_message)
        return shown_messages

    # Sans les revolutions des tours multiples de 40, l'alternance
    # trahison/revolte ne doit plus les decompter.
    if is_simple_mode(state):
        empire_event_index = state.turn // 10
    else:
        empire_event_index = state.turn // 10 - state.turn // 40
    is_betrayal = empire_event_index % 2 == 0
    # Version simplifiee : les forteresses ne se revoltent ni ne trahissent.
    territories_to_transfer = choose_owned_contiguous_block(
        state, target_player, lost_count, rng, exclude_fortresses=True,
        exclude_religion_protected=True,
    )
    if not territories_to_transfer:
        hors = "hors capitale et forteresse" if is_simple_mode(state) else "hors capitale"
        event_message = f"Tour {state.turn}: evenement d'empire impossible pour J{target_player + 1}, aucune cible valide {hors}."
        record_major_event(state, event_message)
        shown_messages.append(event_message)
        return shown_messages
    lost_count = len(territories_to_transfer)

    if is_betrayal:
        eligible_receivers = [
            player for player, count in territory_counts.items()
            if player != target_player and not is_commercial_city_player(state, player)
        ]
        if not eligible_receivers:
            event_message = f"Tour {state.turn}: trahison impossible, aucun autre joueur ne peut recuperer les territoires de J{target_player + 1}."
            record_major_event(state, event_message)
            shown_messages.append(event_message)
            return shown_messages

        min_count = min(territory_counts[player] for player in eligible_receivers)
        weakest_players = [player for player in eligible_receivers if territory_counts[player] == min_count]
        beneficiary_player = rng.choice(weakest_players)

        for terr in territories_to_transfer:
            terr.owner = beneficiary_player

        refresh_eliminated_human_players(state)
        event_message = f"Tour {state.turn}: trahison. J{target_player + 1} perd {lost_count} territoire(s) au profit de J{beneficiary_player + 1}{get_culture_protection_suffix(state, target_player)}."
        record_major_event(state, event_message)
        shown_messages.append(event_message)
        return shown_messages

    new_player, returning_human = allocate_rebel_player(state, rng)

    for terr in territories_to_transfer:
        terr.owner = new_player

    refresh_eliminated_human_players(state)
    comeback_text = " Nouveau joueur controle par l'ordinateur."
    event_message = f"Tour {state.turn}: revolte chez J{target_player + 1}. {lost_count} territoire(s) rebelle(s) passent sous le controle de J{new_player + 1}{get_culture_protection_suffix(state, target_player)}." + comeback_text
    record_major_event(state, event_message)
    shown_messages.append(event_message)
    return shown_messages


# ----------------------------------------------------------------------
# Debut de tour : bastions, mobilisations, alliances IA
# ----------------------------------------------------------------------

def activate_last_stand_bonus_if_needed(state: GameState, player: int) -> Optional[str]:
    # Version simplifiee : le bonus de dernier bastion est un paradis fiscal
    # (revenu x10) double d'une forteresse gratuite — les deux sont ecartes.
    if is_simple_mode(state):
        return None
    if player < 0 or is_onu_player(state, player) or is_commercial_city_player(state, player):
        return None
    owned = [terr for terr in state.territories if terr.owner == player]
    if len(owned) != 1:
        refresh_last_stand_bonus_state(state)
        return None
    terr = owned[0]
    was_active = player in state.last_stand_bonus_players and terr.id in get_player_tax_haven_capital_ids(state, player)
    add_tax_haven_capital(state, player, terr.id)
    if terr.id not in state.fortress_territory_ids:
        state.fortress_territory_ids.add(terr.id)
        state.fortress_capture_counts[terr.id] = 0
        return f"Dernier bastion: forteresse et revenu x10 actives sur {terr.name}."
    if not was_active:
        return f"Dernier bastion: revenu x10 actif sur {terr.name}."
    return None


def get_ai_mobilization_frontier_territories(state: GameState, player: int) -> List[Territory]:
    return [
        terr for terr in state.territories
        if terr.owner == player
        and any(
            state.territories[neighbor_id].owner != player
            for neighbor_id in terr.neighbors
        )
    ]


def maybe_trigger_ai_mobilization(state: GameState, player: int, rng=random) -> Optional[str]:
    if not is_ai_player(state, player):
        return None
    if player in state.nation_players:
        return None
    if rng.randint(1, AI_MOBILIZATION_DENOMINATOR) != 1:
        return None

    owned = [terr for terr in state.territories if terr.owner == player]
    if not owned:
        return None

    frontier_candidates = get_ai_mobilization_frontier_territories(state, player)
    if not frontier_candidates:
        return None

    target = rng.choice(frontier_candidates)
    total_regiments = sum(max(0, terr.regiments) for terr in owned)
    minimum_garrisons = max(0, len(owned) - 1)

    for terr in owned:
        terr.regiments = 1
    target.regiments = max(1, total_regiments - minimum_garrisons)

    moved_regiments = max(0, target.regiments - 1)
    return (
        f"Mobilisation generale de J{player + 1}: {moved_regiments} regiment(s) concentre(s) "
        f"sur {target.name}, territoire frontalier. Les autres territoires gardent 1 regiment."
    )


def maybe_trigger_random_ai_alliance(state: GameState, player: int, rng=random) -> Optional[str]:
    if not is_ai_player(state, player) or player not in state.nation_players:
        return None

    cleanup_expired_alliances(state)
    if rng.randint(1, AI_NATION_ALLIANCE_DENOMINATOR) != 1:
        return None

    active_players = get_active_players(state)
    candidates = [
        candidate
        for candidate in active_players
        if candidate != player
        and is_ai_player(state, candidate)
        and not is_onu_player(state, candidate)
        and not is_ai_alliance_active(state, player, candidate)
    ]

    # Le Palais du Pacte d'Or reserve la Cite commercante a son unique allie.
    if "golden_pact_palace" in state.wonder_territories:
        candidates = [candidate for candidate in candidates if not is_commercial_city_player(state, candidate)]

    if not candidates:
        return None

    ally = rng.choice(candidates)
    key = normalize_ai_alliance_key(player, ally)
    expires_turn = state.turn + ALLIANCE_DURATION_TURNS
    state.active_ai_alliances[key] = expires_turn
    state.ai_alliance_start_turns[key] = state.turn
    message = (
        f"Alliance IA conclue entre la nation J{player + 1} et J{ally + 1} "
        f"jusqu'au tour {expires_turn}."
    )
    record_major_event(state, message)
    return message


# ----------------------------------------------------------------------
# IA economique (achats de fin de tour)
# ----------------------------------------------------------------------

def find_player_nation_development_component(state: GameState, player: int, rng=random) -> Optional[List[int]]:
    if player < 0 or is_onu_player(state, player):
        return None
    candidates = [
        component for component in get_owned_components(state, player)
        if len(component) >= NATION_MIN_TERRITORIES
    ]
    if not candidates:
        return None
    capital_id = (
        get_commercial_city_capital_id(state, player)
        if is_commercial_city_player(state, player)
        else get_active_regular_capital_id_for_player(state, player)
    )
    return max(
        candidates,
        key=lambda component: (
            count_component_nation_structure_kinds(state, component),
            1 if capital_id in component else 0,
            len(component),
            rng.random(),
        ),
    )


def count_component_nation_structure_kinds(state: GameState, territory_ids: List[int]) -> int:
    territory_set = set(territory_ids)
    score = 0
    if state.fortress_territory_ids & territory_set:
        score += 1
    if state.factory_territory_ids & territory_set:
        score += 1
    if state.port_territory_ids & territory_set:
        score += 1
    if state.airport_territory_ids & territory_set:
        score += 1
    if state.temple_territory_ids & territory_set:
        score += 1
    if any(get_cultural_center_count(state, tid) > 0 for tid in territory_set):
        score += 1
    if state.university_territory_ids & territory_set:
        score += 1
    return score


def get_component_industrial_types(state: GameState, territory_ids: List[int]) -> Set[str]:
    territory_set = set(territory_ids)
    types: Set[str] = set()
    for structure_type, structure_ids in (
        ("factory", state.factory_territory_ids),
        ("airport", state.airport_territory_ids),
        ("port", state.port_territory_ids),
    ):
        if structure_ids & territory_set:
            types.add(structure_type)
    return types


def get_missing_component_industrial_types(state: GameState, territory_ids: List[int], rng=random) -> List[str]:
    existing = get_component_industrial_types(state, territory_ids)
    missing = [structure_type for structure_type in ("factory", "airport", "port") if structure_type not in existing]
    rng.shuffle(missing)
    return missing


def component_has_temple(state: GameState, territory_ids: List[int]) -> bool:
    return bool(state.temple_territory_ids & set(territory_ids))


def component_has_cultural_center(state: GameState, territory_ids: List[int]) -> bool:
    return any(get_cultural_center_count(state, tid) > 0 for tid in territory_ids)


def component_has_university(state: GameState, territory_ids: List[int]) -> bool:
    return bool(state.university_territory_ids & set(territory_ids))


def get_player_industrial_types(state: GameState, player: int) -> Set[str]:
    owned_ids = {terr.id for terr in state.territories if terr.owner == player}
    types: Set[str] = set()
    for structure_type, territory_ids in (
        ("factory", state.factory_territory_ids),
        ("airport", state.airport_territory_ids),
        ("port", state.port_territory_ids),
    ):
        if territory_ids & owned_ids:
            types.add(structure_type)
    return types


def get_missing_player_industrial_types(state: GameState, player: int, rng=random) -> List[str]:
    existing = get_player_industrial_types(state, player)
    missing = [structure_type for structure_type in ("factory", "airport", "port") if structure_type not in existing]
    rng.shuffle(missing)
    return missing


def get_connected_landmass_ids(state: GameState, territory_id: int) -> List[int]:
    """Les territoires atteignables depuis celui-ci par voie terrestre.

    Suit l'adjacence des territoires — ponts et liaisons terrestres compris,
    exactement comme les blocs nationaux de ``get_owned_components`` — sans
    tenir compte des proprietaires : c'est la masse de terre accessible, pas
    l'empire. Une ile sans pont ne renvoie qu'elle-meme.
    """
    if not (0 <= territory_id < len(state.territories)):
        return []
    seen = {territory_id}
    stack = [territory_id]
    while stack:
        current = stack.pop()
        for neighbor_id in state.territories[current].neighbors:
            if neighbor_id not in seen and 0 <= neighbor_id < len(state.territories):
                seen.add(neighbor_id)
                stack.append(neighbor_id)
    return sorted(seen)


def is_isolated_island_territory(state: GameState, territory_id: int) -> bool:
    """Ce territoire est-il sur une ile trop petite pour porter une nation ?

    Moins de ``AI_MAINLAND_MIN_TERRITORIES`` territoires accessibles : meme
    en conquerant toute l'ile, le bloc d'un seul tenant exige par le statut
    de nation ne pourra jamais y etre atteint.
    """
    landmass = get_connected_landmass_ids(state, territory_id)
    return bool(landmass) and len(landmass) < AI_MAINLAND_MIN_TERRITORIES


def get_ai_mainland_capital_candidates(state: GameState, player: int) -> List[Territory]:
    """Les territoires du joueur situes sur une masse de terre assez grande."""
    return [
        terr for terr in state.territories
        if terr.owner == player
        and not is_sanctuary_territory(state, terr.id)
        and not is_isolated_island_territory(state, terr.id)
    ]


def choose_ai_mainland_capital_target(
    state: GameState, player: int, rng=random,
) -> Optional[Territory]:
    """Ou une IA insulaire rapatrie sa capitale : meme choix que d'habitude
    (revenu, voisins, garnison), restreint au continent."""
    candidates = get_ai_mainland_capital_candidates(state, player)
    if not candidates:
        return None
    return max(candidates, key=lambda terr: (
        calculate_territory_income(state, terr), len(terr.neighbors), terr.regiments, rng.random(),
    ))


def ai_should_move_capital_to_mainland(state: GameState, player: int) -> bool:
    """Une IA doit-elle quitter son ile pour esperer devenir une nation ?

    Sa capitale est posee sur une ile isolee (cf.
    ``is_isolated_island_territory``) : elle demenage sur le continent des
    qu'elle y possede un territoire. Les nations deja formees ne bougent
    pas — notamment celles qui tiennent leur statut du Capitole d'Aurelia,
    qu'un demenagement leur ferait perdre.
    """
    if not is_ai_player(state, player) or is_onu_player(state, player):
        return False
    if is_potential_commercial_city_player(state, player):
        return False
    if player in state.nation_players:
        return False
    capital_id = get_active_regular_capital_id_for_player(state, player)
    if capital_id is None or not is_isolated_island_territory(state, capital_id):
        return False
    return bool(get_ai_mainland_capital_candidates(state, player))


def ai_needs_new_capital_as_nation(state: GameState, player: int) -> bool:
    if not is_ai_player(state, player):
        return False
    if is_commercial_city_player(state, player) or is_onu_player(state, player):
        return False
    if get_active_regular_capital_id_for_player(state, player) is not None:
        return False
    return (
        player in state.nation_players
        or player_has_nation_structures_but_needs_capital(state, player)
    )


def player_has_nation_structures_but_needs_capital(state: GameState, player: int) -> bool:
    return (
        find_player_nation_component(state, player, require_capital=False) is not None
        and find_player_nation_component(state, player, require_capital=True) is None
    )


def choose_ai_new_capital_target(state: GameState, player: int, rng=random) -> Optional[Territory]:
    owned = [
        terr for terr in state.territories
        if terr.owner == player and not is_sanctuary_territory(state, terr.id)
    ]
    if not owned:
        return None
    qualifying_component = find_player_nation_component(state, player, require_capital=False)
    if qualifying_component is not None:
        preferred = [terr for terr in owned if terr.id in qualifying_component]
        if preferred:
            owned = preferred
    return max(owned, key=lambda terr: (
        calculate_territory_income(state, terr), len(terr.neighbors), terr.regiments, rng.random(),
    ))


def change_ai_capital_without_ui(state: GameState, player: int, territory_id: int) -> None:
    if not (0 <= territory_id < len(state.territories)):
        return
    state.player_capital_ids[player] = territory_id
    state.sanctuary_territory_ids.discard(territory_id)
    sanitize_player_capitals(state)


def add_regular_ai_fortress(state: GameState, territory_id: int) -> None:
    if not (0 <= territory_id < len(state.territories)):
        return
    state.fortress_territory_ids.add(territory_id)
    state.fortress_capture_counts[territory_id] = 0


def add_commercial_city_fortress(state: GameState, territory_id: int) -> None:
    state.fortress_territory_ids.add(territory_id)
    state.fortress_capture_counts[territory_id] = 0


def choose_regular_ai_development_target(
    state: GameState, candidates: List[Territory], player: int, rng=random,
) -> Territory:
    candidate_ids = {terr.id for terr in candidates}
    nation_component = find_player_nation_development_component(state, player, rng)
    if nation_component is not None:
        nation_pool = [terr for terr in candidates if terr.id in nation_component]
        if nation_pool:
            candidates = nation_pool
            candidate_ids = {terr.id for terr in candidates}
    capital_id = get_active_regular_capital_id_for_player(state, player)
    if capital_id is not None and capital_id in candidate_ids:
        for terr in candidates:
            if terr.id == capital_id:
                return terr
    return max(candidates, key=lambda terr: (len(terr.neighbors), terr.regiments, rng.random()))


def choose_regular_ai_university_target(
    state: GameState, candidates: List[Territory], player: int, rng=random,
) -> Territory:
    nation_component = find_player_nation_development_component(state, player, rng)
    if nation_component is not None:
        nation_pool = [terr for terr in candidates if terr.id in nation_component]
        if nation_pool:
            candidates = nation_pool
    capital_id = get_active_regular_capital_id_for_player(state, player)
    non_capital_candidates = [terr for terr in candidates if terr.id != capital_id]
    pool = non_capital_candidates or candidates
    return max(pool, key=lambda terr: (len(terr.neighbors), terr.regiments, rng.random()))


def add_regular_ai_mercenaries(state: GameState, owned: List[Territory], quantity: int, rng=random) -> None:
    active_owned = [
        terr for terr in owned
        if 0 <= terr.id < len(state.territories) and state.territories[terr.id].owner == terr.owner
    ]
    pool = active_owned or owned
    if not pool:
        return
    for _ in range(max(0, quantity)):
        rng.choice(pool).regiments += 1


def find_regular_ai_fortress_purchase(state: GameState, player: int, owned: List[Territory], rng=random):
    if any(terr.id in state.fortress_territory_ids for terr in owned):
        return None
    candidates = [terr for terr in owned if terr.id not in state.fortress_territory_ids]
    if not candidates:
        return None
    capital_id = get_active_regular_capital_id_for_player(state, player)
    if capital_id is not None:
        capital = state.territories[capital_id]
        if capital.owner == player and capital.id not in state.fortress_territory_ids:
            return FORTRESS_COST, lambda terr=capital: add_regular_ai_fortress(state, terr.id)
    target = choose_regular_ai_development_target(state, candidates, player, rng)
    return FORTRESS_COST, lambda terr=target: add_regular_ai_fortress(state, terr.id)


def find_regular_ai_industrial_purchase(
    state: GameState,
    player: int,
    owned: List[Territory],
    preferred_missing_types: Optional[List[str]],
    rng=random,
):
    candidates = [terr for terr in owned if get_industrial_structure_count(state, terr.id) == 0]
    if not candidates:
        return None
    structure_types = list(preferred_missing_types) if preferred_missing_types else ["factory", "airport", "port"]
    if not structure_types:
        return None
    structure_type = rng.choice(structure_types)
    cost = {"factory": FACTORY_COST, "airport": AIRPORT_COST, "port": PORT_COST}[structure_type]
    target = choose_regular_ai_development_target(state, candidates, player, rng)
    return cost, lambda terr=target, structure_type=structure_type: add_industrial_structure(state, terr.id, structure_type)


def find_regular_ai_mercenary_purchase(state: GameState, player: int, owned: List[Territory], rng=random):
    quantity = state.player_money[player] // MERCENARY_COST
    if quantity <= 0:
        return None
    return quantity * MERCENARY_COST, lambda quantity=quantity, owned=list(owned): add_regular_ai_mercenaries(state, owned, quantity, rng)


def find_ai_wonder_purchase(state: GameState, player: int, rng=random):
    if not is_ai_player(state, player) or has_built_wonder_this_turn(state, player):
        return None
    available_wonders = get_buildable_wonder_types(state, player)
    if not available_wonders:
        return None
    candidates = [
        territory for territory in state.territories
        if territory.owner == player
        and not is_sanctuary_territory(state, territory.id)
        and get_wonder_type_at_territory(state, territory.id) is None
    ]
    if not candidates:
        return None
    wonder_type = available_wonders[0]
    target = max(
        candidates,
        key=lambda territory: (
            calculate_territory_income(state, territory),
            len(territory.neighbors),
            territory.regiments,
            -territory.id,
        ),
    )
    return (
        get_wonder_cost(state, player, wonder_type),
        lambda terr=target, kind=wonder_type: build_wonder(state, terr.id, kind),
    )


def find_next_regular_ai_purchase(state: GameState, player: int, rng=random):
    owned = [terr for terr in state.territories if terr.owner == player]
    if not owned:
        return None
    owned.sort(key=lambda terr: terr.id)

    # Les achats IA visent d'abord le bloc contigu qui peut devenir nation.
    nation_component = find_player_nation_development_component(state, player, rng)
    development_ids = set(nation_component) if nation_component is not None else {terr.id for terr in owned}
    development_owned = [terr for terr in owned if terr.id in development_ids]
    if not development_owned:
        development_owned = owned

    fortress_action = find_regular_ai_fortress_purchase(state, player, development_owned, rng)
    if fortress_action is not None:
        return fortress_action

    industrial_types = get_component_industrial_types(state, [terr.id for terr in development_owned])
    if not industrial_types:
        return find_regular_ai_industrial_purchase(state, player, development_owned, None, rng)

    development_tid_list = [terr.id for terr in development_owned]
    if not component_has_temple(state, development_tid_list):
        temple_candidates = [terr for terr in development_owned if can_add_temple(state, terr.id)]
        if temple_candidates:
            target = choose_regular_ai_development_target(state, temple_candidates, player, rng)
            return TEMPLE_COST, lambda terr=target: add_temple(state, terr.id)

    if not component_has_cultural_center(state, development_tid_list):
        cultural_candidates = [terr for terr in development_owned if can_add_cultural_center(state, terr.id)]
        if cultural_candidates:
            target = choose_regular_ai_development_target(state, cultural_candidates, player, rng)
            return CULTURAL_CENTER_COST, lambda terr=target: add_cultural_center(state, terr.id, age=0)

    if not component_has_university(state, development_tid_list):
        university_candidates = [terr for terr in development_owned if can_add_university(state, terr.id)]
        if university_candidates:
            target = choose_regular_ai_university_target(state, university_candidates, player, rng)
            return UNIVERSITY_COST, lambda terr=target: add_university(state, terr.id)

    if len(industrial_types) < 2:
        action = find_regular_ai_industrial_purchase(
            state, player, development_owned,
            get_missing_component_industrial_types(state, development_tid_list, rng), rng,
        )
        if action is not None:
            return action
        return find_regular_ai_mercenary_purchase(state, player, owned, rng)

    if len(industrial_types) < 3:
        action = find_regular_ai_industrial_purchase(
            state, player, development_owned,
            get_missing_component_industrial_types(state, development_tid_list, rng), rng,
        )
        if action is not None:
            return action
        return find_regular_ai_mercenary_purchase(state, player, owned, rng)

    return find_regular_ai_mercenary_purchase(state, player, owned, rng)


def find_next_commercial_city_purchase(state: GameState, player: int, rng=random):
    if not is_commercial_city_player(state, player):
        return None
    owned = [terr for terr in state.territories if terr.owner == player]
    if not owned:
        return None
    owned.sort(key=lambda terr: terr.id)
    capital_id = get_commercial_city_capital_id(state, player)
    if capital_id is None:
        return None
    capital = state.territories[capital_id]

    # Ordre d'achat CC : capitale d'abord, puis diversification industrielle
    # sur les territoires acquis avant de continuer l'expansion.
    if capital.id not in state.fortress_territory_ids:
        return FORTRESS_COST, lambda terr=capital: add_commercial_city_fortress(state, terr.id)

    if get_industrial_structure_count(state, capital.id) == 0:
        structure_type = rng.choice(["factory", "airport", "port"])
        cost = {"factory": FACTORY_COST, "airport": AIRPORT_COST, "port": PORT_COST}[structure_type]
        return cost, lambda terr=capital, structure_type=structure_type: add_industrial_structure(state, terr.id, structure_type)

    if not has_temple(state, capital.id):
        return TEMPLE_COST, lambda terr=capital: add_temple(state, terr.id)

    if get_cultural_center_count(state, capital.id) < 1 and can_add_cultural_center(state, capital.id):
        return CULTURAL_CENTER_COST, lambda terr=capital: add_cultural_center(state, terr.id, age=0)

    if can_add_university(state, capital.id):
        return UNIVERSITY_COST, lambda terr=capital: add_university(state, terr.id)

    missing_industries = get_missing_player_industrial_types(state, player, rng)
    if missing_industries:
        industrial_candidates = [terr for terr in owned if get_industrial_structure_count(state, terr.id) == 0]
        if industrial_candidates:
            structure_type = rng.choice(missing_industries)
            cost = {"factory": FACTORY_COST, "airport": AIRPORT_COST, "port": PORT_COST}[structure_type]
            target = choose_regular_ai_development_target(state, industrial_candidates, player, rng)
            return cost, lambda terr=target, structure_type=structure_type: add_industrial_structure(state, terr.id, structure_type)

    candidates = [
        terr for terr in state.territories
        if terr.owner != player
        and terr.id not in state.golden_territory_ids
        and not is_commercial_city_capital(state, terr.id)
        and not is_any_capital_territory(state, terr.id)
        and can_commercial_city_gain_territory(state, player, terr.id)
    ]
    if not candidates:
        return None
    terr = rng.choice(candidates)
    cost = max(1, calculate_corruption_cost(state, terr, attacker=player)[0])
    return cost, lambda terr=terr: transfer_territory_to_commercial_city(state, terr.id, player)


def execute_commercial_city_economic_actions(state: GameState, player: int, rng=random) -> int:
    ensure_player_economy(state, player)
    actions = 0
    if ai_needs_new_capital_as_nation(state, player):
        target = choose_ai_new_capital_target(state, player, rng)
        if target is not None and state.player_money[player] >= CHANGE_CAPITAL_COST:
            state.player_money[player] -= CHANGE_CAPITAL_COST
            change_ai_capital_without_ui(state, player, target.id)
            message = f"Tour {state.turn}: J{player + 1}, nation sans capitale controlee, deplace sa capitale a {target.name}."
            record_major_event(state, message)
            actions += 1
        if actions > 0:
            refresh_nation_states(state, trigger_player=player)
            return actions
    while True:
        action = find_next_commercial_city_purchase(state, player, rng)
        if action is None:
            break
        cost, callback = action
        if state.player_money[player] < cost:
            break
        state.player_money[player] -= cost
        callback()
        actions += 1
    if actions > 0:
        refresh_nation_states(state, trigger_player=player)
    return actions


def execute_ai_economic_actions(state: GameState, player: int, rng=random) -> int:
    if not is_ai_player(state, player) or is_onu_player(state, player):
        return 0
    if is_colonized_player(state, player):
        return 0
    if is_commercial_city_player(state, player):
        return execute_commercial_city_economic_actions(state, player, rng)
    ensure_player_economy(state, player)
    actions = 0

    # Priorite absolue des IA : construire les merveilles disponibles des que
    # le seuil (science ou culture selon la merveille) et le prix sont
    # atteints. Si l'argent manque, l'IA epargne au lieu de le disperser
    # dans des achats secondaires.
    while get_buildable_wonder_types(state, player):
        wonder_action = find_ai_wonder_purchase(state, player, rng)
        if wonder_action is None:
            break
        cost, callback = wonder_action
        if state.player_money[player] < cost:
            return actions
        state.player_money[player] -= cost
        callback()
        actions += 1

    if ai_needs_new_capital_as_nation(state, player):
        target = choose_ai_new_capital_target(state, player, rng)
        if target is not None and state.player_money[player] >= CHANGE_CAPITAL_COST:
            state.player_money[player] -= CHANGE_CAPITAL_COST
            change_ai_capital_without_ui(state, player, target.id)
            message = f"Tour {state.turn}: J{player + 1}, nation sans capitale controlee, deplace sa capitale a {target.name}."
            record_major_event(state, message)
            actions += 1
        if actions > 0:
            refresh_nation_states(state, trigger_player=player)
            return actions
    elif ai_should_move_capital_to_mainland(state, player):
        target = choose_ai_mainland_capital_target(state, player, rng)
        if target is not None and state.player_money[player] >= CHANGE_CAPITAL_COST:
            state.player_money[player] -= CHANGE_CAPITAL_COST
            change_ai_capital_without_ui(state, player, target.id)
            message = (
                f"Tour {state.turn}: J{player + 1}, capitale prisonniere d'une ile isolee, "
                f"la deplace sur le continent a {target.name}."
            )
            record_major_event(state, message)
            actions += 1
        if actions > 0:
            refresh_nation_states(state, trigger_player=player)
            return actions
    while True:
        action = find_next_regular_ai_purchase(state, player, rng)
        if action is None:
            break
        cost, callback = action
        if state.player_money[player] < cost:
            break
        state.player_money[player] -= cost
        callback()
        actions += 1
    if actions > 0:
        refresh_nation_states(state, trigger_player=player)
    return actions
