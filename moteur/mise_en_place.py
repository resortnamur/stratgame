"""Mise en place d'une nouvelle partie (etape 2b de la migration).

Miroir fidele de ``start_game_session`` de x45 (hors interface et generation
aleatoire de carte) : a partir d'une carte chargee, configure les joueurs,
ajoute les cites commercantes, distribue territoires et armees, place les
bonus, territoires dores et sanctuaires, remet l'economie a zero et pose les
structures initiales.

Point d'entree : ``nouvelle_partie(carte_payload, num_players,
ai_player_count, ...)`` — c'est ce que le serveur appelle quand le lobby cree
une partie neuve depuis une carte de ``cartes_sauvegardees/``.

Comme partout dans le moteur, l'aleatoire est injectable (``rng=random``) et
l'ordre des tirages reproduit exactement celui de x45 (parite verifiee par
``tests/test_parite_mise_en_place.py`` contre x45-original).
"""

from __future__ import annotations

import heapq
import random
from typing import Callable, Dict, List, Optional, Set, Tuple

from . import regles
from .etat import GameState, normalize_difficulty_level

# Constantes de x45 (GraphicalGame).
INITIAL_FORTRESS_COUNT = 5
INITIAL_INDUSTRY_COUNT = 5
INITIAL_CULTURAL_CENTER_COUNT = 5
INITIAL_COMMERCIAL_CITY_COUNT = 1

AI_PROFILES_ORDER = ["standard", "aggressive", "defensive", "variable"]


def nouvelle_partie(
    carte_payload: dict,
    num_players: int,
    ai_player_count: int,
    difficulty_level: str = "normal",
    tribes_mode: bool = False,
    simple_mode: bool = False,
    rng=random,
) -> GameState:
    """Cree une partie prete a jouer depuis une carte sauvegardee.

    Miroir de ``start_game_session`` (x45) : la carte remplace
    ``generate_grid_map``, le reste de la sequence est identique, y compris
    le double appel a ``assign_random_bonus_territories`` (une fois via
    ``_distribute_armies``, une fois explicitement). L'appelant enchaine
    ensuite sur ``actions.begin_player_turn(state, 0, rng)``.

    ``simple_mode=True`` cree une partie en version simplifiee : ni cite
    commercante, ni capitale, ni industrie ou centre culturel — seules les
    forteresses restent parmi les structures initiales. Les bonus +3, les
    territoires dores et les sanctuaires ONU sont poses comme d'habitude.
    """
    if not (2 <= num_players <= 10):
        raise ValueError("Nombre de joueurs invalide (2-10).")
    if not (0 <= ai_player_count <= num_players):
        raise ValueError("Nombre d'IA invalide.")

    state = GameState.from_map_payload(carte_payload)

    # Miroir de setup_players (partie configuration, sans les questions).
    state.num_players = num_players
    state.ai_player_count = ai_player_count
    state.initial_num_players = num_players
    state.initial_ai_player_count = ai_player_count
    state.difficulty_level = normalize_difficulty_level(difficulty_level)
    state.tribes_mode = bool(tribes_mode) and ai_player_count > 0
    state.simple_mode = bool(simple_mode)
    state.base_ai_players = set(range(ai_player_count))
    state.auto_controlled_players = set()
    state.commercial_city_players = set()
    state.commercial_city_capital_ids = {}
    state.player_capital_ids = {}
    state.pending_commercial_city_spawns = 0
    state.nation_players = set()
    state.nation_qualification_start_turns = {}
    state.nation_capital_loss_start_turns = {}
    state.submitted_territory_ids = set()
    state.submitted_territory_overlords = {}
    state.submitted_territory_created_turns = {}
    state.integrated_submitted_territories = {}
    state.union_members = {}
    state.union_original_territories = {}
    state.final_duel_active = False
    state.final_duel_champions = None
    state.final_duel_alliances = {}
    state.final_duel_pending_winner = None
    assign_ai_personalities(state)

    # Miroir de start_game_session apres le chargement de la carte.
    state.eliminated_human_players = set()
    state.human_controlled_players = set()
    # Memorise le relief de la carte avant que la mise en place ne remette
    # l'economie a zero : reset_economy_state s'en sert pour rendre a la
    # partie les ponts que la carte dessinait.
    state.map_bridge_links = set(state.bridge_links)
    state.map_fragile_bridge_links = set(state.fragile_bridge_links)
    state.map_bridge_link_points = dict(state.bridge_link_points)
    if not state.simple_mode:
        prepare_initial_commercial_cities(state, rng)
    assign_initial_ownership_and_armies(state, rng)
    assign_random_bonus_territories(state, rng)
    assign_golden_territories(state, rng)
    assign_sanctuary_territories(state, rng)
    reset_economy_state(state)
    assign_initial_economic_structures(state, rng)
    state.replay_history = []
    state.phase = "playing"
    state.turn_phase = "attack"
    state.turn_move_count = 0
    state.last_empire_event_turn = 0
    regles.snapshot_tax_haven_turn_start_territory_counts(state)
    state.current_player = 0
    state.turn = 1
    regles.record_replay_snapshot(state, "Debut de la partie", force=True)
    return state


def assign_ai_personalities(state: GameState) -> None:
    """Miroir de assign_ai_personalities (x45) : repartition deterministe."""
    state.ai_personalities = {}
    state.ai_current_behavior = {}
    for index, player in enumerate(sorted(state.base_ai_players)):
        state.ai_personalities[player] = AI_PROFILES_ORDER[index % len(AI_PROFILES_ORDER)]


def prepare_initial_commercial_cities(state: GameState, rng=random) -> None:
    """Miroir de prepare_initial_commercial_cities (x45)."""
    state.commercial_city_players = set()
    state.commercial_city_capital_ids = {}
    state.pending_commercial_city_spawns = 0
    for _ in range(INITIAL_COMMERCIAL_CITY_COUNT):
        player = state.num_players
        state.num_players += 1
        state.base_ai_players.add(player)
        state.human_controlled_players.discard(player)
        state.auto_controlled_players.discard(player)
        state.commercial_city_players.add(player)
        regles.assign_ai_personality_to_player(state, player, "aggressive", rng)
        regles.ensure_player_economy(state, player)


# ----------------------------------------------------------------------
# Distribution des territoires et des armees
# ----------------------------------------------------------------------

def assign_initial_ownership_and_armies(state: GameState, rng=random) -> None:
    """Miroir de assign_initial_ownership_and_armies (x45).

    En version simplifiee, aucune capitale n'est posee : les joueurs
    demarrent donc entierement disperses (ou en blocs contigus en mode
    Tribus), sans le regroupement capitale + voisins directs.
    """
    if state.tribes_mode and state.base_ai_players:
        _assign_ownership_tribes(state, rng)
    else:
        _assign_ownership_random(state, rng)
    if not regles.is_simple_mode(state):
        assign_initial_player_capitals(state, rng)


def _assign_ownership_random(state: GameState, rng=random) -> None:
    ids = list(range(len(state.territories)))
    rng.shuffle(ids)
    commercial_players = sorted(
        player for player in state.commercial_city_players if 0 <= player < state.num_players
    )
    for player, tid in zip(commercial_players, ids[:len(commercial_players)]):
        state.territories[tid].owner = player
        state.commercial_city_capital_ids[player] = tid
    remaining_ids = ids[len(commercial_players):]
    regular_players = [p for p in range(state.num_players) if p not in state.commercial_city_players]
    if not regular_players:
        regular_players = list(range(state.num_players))
    for current_index, tid in enumerate(remaining_ids):
        state.territories[tid].owner = regular_players[current_index % len(regular_players)]
    _distribute_armies(state, rng)


def _assign_ownership_tribes(state: GameState, rng=random) -> None:
    """Mode Tribus (miroir x45) : blocs contigus pour les IA (BFS depuis un
    germe), le reste distribue aleatoirement aux humains."""
    num_terr = len(state.territories)
    if num_terr == 0:
        _distribute_armies(state, rng)
        return

    ai_players = sorted(p for p in state.base_ai_players if p not in state.commercial_city_players)
    human_players = [
        p for p in range(state.num_players)
        if p not in state.base_ai_players and p not in state.commercial_city_players
    ]
    num_ai = len(ai_players)

    base_count = num_terr // state.num_players
    remainder = num_terr % state.num_players
    player_quota: Dict[int, int] = {}
    for i, p in enumerate(ai_players + human_players):
        player_quota[p] = base_count + (1 if i < remainder else 0)

    for terr in state.territories:
        terr.owner = -1
    unassigned = set(range(num_terr))

    commercial_players = sorted(
        player for player in state.commercial_city_players if 0 <= player < state.num_players
    )
    commercial_seeds = rng.sample(list(unassigned), min(len(commercial_players), len(unassigned)))
    for player, tid in zip(commercial_players, commercial_seeds):
        state.territories[tid].owner = player
        state.commercial_city_capital_ids[player] = tid
        unassigned.discard(tid)

    # Phase 1 : germes bien espaces puis BFS contigu pour chaque IA.
    ai_seeds: List[int] = []
    available_seeds = list(unassigned)
    rng.shuffle(available_seeds)
    if num_ai > 0:
        ai_seeds.append(rng.choice(available_seeds))
        for _ in range(num_ai - 1):
            if not available_seeds:
                break
            ai_seeds.append(max(
                available_seeds,
                key=lambda t: min(_bfs_distance_approx(state, t, s) for s in ai_seeds),
            ))

    frontiers: Dict[int, list] = {p: [] for p in ai_players}
    assigned_count: Dict[int, int] = {p: 0 for p in ai_players}
    for idx, p in enumerate(ai_players):
        if idx < len(ai_seeds):
            seed = ai_seeds[idx]
            state.territories[seed].owner = p
            unassigned.discard(seed)
            assigned_count[p] = 1
            for nb in state.territories[seed].neighbors:
                if nb in unassigned:
                    heapq.heappush(frontiers[p], (rng.random(), nb))

    active_ai = [p for p in ai_players if assigned_count[p] < player_quota[p]]
    while active_ai:
        rng.shuffle(active_ai)
        progressed = False
        for p in list(active_ai):
            if assigned_count[p] >= player_quota[p]:
                active_ai.remove(p)
                continue
            picked = None
            while frontiers[p]:
                _, candidate = heapq.heappop(frontiers[p])
                if candidate in unassigned:
                    picked = candidate
                    break
            if picked is not None:
                state.territories[picked].owner = p
                unassigned.discard(picked)
                assigned_count[p] += 1
                progressed = True
                for nb in state.territories[picked].neighbors:
                    if nb in unassigned:
                        heapq.heappush(frontiers[p], (rng.random(), nb))
                if assigned_count[p] >= player_quota[p]:
                    active_ai.remove(p)
            else:
                # Plus de voisin contigu : exception, territoire distant.
                if unassigned and assigned_count[p] < player_quota[p]:
                    fallback = rng.choice(list(unassigned))
                    state.territories[fallback].owner = p
                    unassigned.discard(fallback)
                    assigned_count[p] += 1
                    progressed = True
                    for nb in state.territories[fallback].neighbors:
                        if nb in unassigned:
                            heapq.heappush(frontiers[p], (rng.random(), nb))
                if assigned_count[p] >= player_quota[p]:
                    active_ai.remove(p)
        if not progressed:
            break

    # Phase 2 : les humains recoivent le reste, au hasard.
    remaining = list(unassigned)
    rng.shuffle(remaining)
    idx_human = 0
    for tid in remaining:
        if not human_players:
            state.territories[tid].owner = 0
            continue
        state.territories[tid].owner = human_players[idx_human % len(human_players)]
        idx_human += 1

    for terr in state.territories:
        if terr.owner == -1:
            terr.owner = rng.randint(0, state.num_players - 1)

    _distribute_armies(state, rng)


def _bfs_distance_approx(state: GameState, start: int, end: int) -> int:
    """Distance graphe approximative (BFS limite a 30 pas), miroir x45."""
    if start == end:
        return 0
    visited = {start}
    frontier = [start]
    dist = 0
    max_depth = 30
    while frontier and dist < max_depth:
        dist += 1
        next_frontier = []
        for tid in frontier:
            for nb in state.territories[tid].neighbors:
                if nb == end:
                    return dist
                if nb not in visited:
                    visited.add(nb)
                    next_frontier.append(nb)
        frontier = next_frontier
    return max_depth


def _distribute_armies(state: GameState, rng=random) -> None:
    """Miroir de _distribute_armies (x45) : armees initiales + bonus."""
    territory_per_player = {p: 0 for p in range(state.num_players)}
    for terr in state.territories:
        if 0 <= terr.owner < state.num_players:
            territory_per_player[terr.owner] += 1

    max_territories = max(territory_per_player.values())
    starting_regiments = max_territories + 10
    regiments_left = {p: starting_regiments for p in range(state.num_players)}
    for terr in state.territories:
        terr.regiments = 1
        if 0 <= terr.owner < state.num_players:
            regiments_left[terr.owner] -= 1
    for player in range(state.num_players):
        owned_ids = [t.id for t in state.territories if t.owner == player]
        remaining = regiments_left[player]
        while remaining > 0 and owned_ids:
            tid = rng.choice(owned_ids)
            state.territories[tid].regiments += 1
            remaining -= 1

    for player in range(state.num_players):
        owned = [t for t in state.territories if t.owner == player]
        if not owned:
            continue
        rng.choice(owned).regiments += 5

    assign_random_bonus_territories(state, rng)


def assign_initial_player_capitals(state: GameState, rng=random) -> None:
    """Miroir de assign_initial_player_capitals (x45) : capitale + rattachement
    des voisins directs, joueurs ordinaires uniquement."""
    state.player_capital_ids = {}
    if not state.territories:
        return
    regular_players = [
        player for player in range(state.num_players)
        if player not in state.commercial_city_players and player != state.onu_player_id
    ]
    reserved: Set[int] = set()
    cc_owned_ids = {
        terr.id for terr in state.territories if terr.owner in state.commercial_city_players
    }

    for player in regular_players:
        owned_ids = [
            terr.id for terr in state.territories
            if terr.owner == player and terr.id not in cc_owned_ids
        ]
        if not owned_ids:
            continue

        def capital_score(tid: int) -> Tuple[int, int, int, float]:
            neighbors = set(state.territories[tid].neighbors)
            closed = neighbors | {tid}
            cc_neighbors = len(neighbors & cc_owned_ids)
            reserved_overlap = len(closed & reserved)
            missing_neighbors = sum(
                1 for nid in neighbors
                if 0 <= nid < len(state.territories)
                and state.territories[nid].owner not in (player, state.onu_player_id)
                and state.territories[nid].owner not in state.commercial_city_players
            )
            return (cc_neighbors, reserved_overlap, missing_neighbors, rng.random())

        capital_id = min(owned_ids, key=capital_score)
        state.player_capital_ids[player] = capital_id
        reserved.update(state.territories[capital_id].neighbors)
        reserved.add(capital_id)

    capital_ids = set(state.player_capital_ids.values())
    for player, capital_id in state.player_capital_ids.items():
        if not (0 <= capital_id < len(state.territories)):
            continue
        capital = state.territories[capital_id]
        capital.owner = player
        capital.regiments = regles.INITIAL_CAPITAL_REGIMENTS
        for neighbor_id in capital.neighbors:
            if not (0 <= neighbor_id < len(state.territories)):
                continue
            if neighbor_id in capital_ids:
                continue
            neighbor = state.territories[neighbor_id]
            if neighbor.owner == state.onu_player_id or neighbor.owner in state.commercial_city_players:
                continue
            neighbor.owner = player
    regles.sanitize_player_capitals(state)


# ----------------------------------------------------------------------
# Territoires speciaux
# ----------------------------------------------------------------------

def assign_random_bonus_territories(state: GameState, rng=random) -> None:
    """Miroir de assign_random_bonus_territories (x45) : 4 territoires +3."""
    state.super_territory_ids = set()
    state.ultra_super_territory_ids = set()
    for terr in state.territories:
        terr.reinforcement_bonus = 1
    if not state.territories:
        return
    territory_ids = list(range(len(state.territories)))
    rng.shuffle(territory_ids)
    ultra_ids = territory_ids[:min(4, len(territory_ids))]
    for tid in ultra_ids:
        state.territories[tid].reinforcement_bonus = 3
    state.ultra_super_territory_ids = set(ultra_ids)


def compute_territory_distances(state: GameState, start_id: int) -> Dict[int, int]:
    """Miroir de compute_territory_distances (x45) : BFS complet."""
    if not (0 <= start_id < len(state.territories)):
        return {}
    distances = {start_id: 0}
    queue = [start_id]
    index = 0
    while index < len(queue):
        current = queue[index]
        index += 1
        current_distance = distances[current]
        for neighbor_id in state.territories[current].neighbors:
            if neighbor_id not in distances:
                distances[neighbor_id] = current_distance + 1
                queue.append(neighbor_id)
    return distances


def assign_golden_territories(state: GameState, rng=random) -> None:
    """Miroir de assign_golden_territories (x45) : 4 territoires dores les
    plus espaces possible (essais a distance minimale decroissante)."""
    state.golden_territory_ids = set()
    if len(state.territories) <= 4:
        state.golden_territory_ids = set(range(len(state.territories)))
        return

    all_ids = list(range(len(state.territories)))
    distance_maps = {tid: compute_territory_distances(state, tid) for tid in all_ids}

    for min_distance in (5, 4, 3, 2):
        for _ in range(300):
            rng.shuffle(all_ids)
            selection: List[int] = []
            for tid in all_ids:
                if all(distance_maps[chosen].get(tid, 10 ** 9) >= min_distance for chosen in selection):
                    selection.append(tid)
                    if len(selection) == 4:
                        state.golden_territory_ids = set(selection)
                        return

    best_selection: List[int] = []
    best_score = -1
    for _ in range(400):
        rng.shuffle(all_ids)
        selection = []
        for tid in all_ids:
            if not selection:
                selection.append(tid)
                continue
            candidate_score = min(distance_maps[chosen].get(tid, 10 ** 9) for chosen in selection)
            current_score = min(
                (distance_maps[a].get(b, 10 ** 9) for i, a in enumerate(selection) for b in selection[i + 1:]),
                default=10 ** 9,
            )
            if candidate_score >= current_score or len(selection) < 5:
                selection.append(tid)
            if len(selection) == 4:
                break
        if len(selection) < 4:
            remaining = [tid for tid in all_ids if tid not in selection]
            selection.extend(remaining[: 4 - len(selection)])
        score = min(
            (distance_maps[a].get(b, 10 ** 9) for i, a in enumerate(selection) for b in selection[i + 1:]),
            default=0,
        )
        if score > best_score:
            best_score = score
            best_selection = selection[:4]

    state.golden_territory_ids = set(best_selection[:4] if best_selection else all_ids[:4])


def assign_sanctuary_territories(state: GameState, rng=random) -> None:
    """Miroir de assign_sanctuary_territories (x45) : trois territoires ONU
    neutres, hors +3, dores et capitales."""
    state.sanctuary_territory_ids = set()
    state.submitted_territory_ids = set()
    state.submitted_territory_overlords = {}
    state.submitted_territory_created_turns = {}
    if not state.territories:
        return

    forbidden = (
        set(state.ultra_super_territory_ids)
        | set(state.golden_territory_ids)
        | set(state.player_capital_ids.values())
    )
    candidates = [terr.id for terr in state.territories if terr.id not in forbidden]
    if len(candidates) < 3:
        candidates = [
            terr.id for terr in state.territories
            if terr.id not in state.golden_territory_ids
            and terr.id not in set(state.player_capital_ids.values())
        ]

    selected = rng.sample(candidates, min(3, len(candidates)))
    state.sanctuary_territory_ids = set()
    for tid in selected:
        regles.convert_territory_to_sanctuary(state, tid, regiments=5)


# ----------------------------------------------------------------------
# Economie initiale
# ----------------------------------------------------------------------

def reset_economy_state(state: GameState) -> None:
    """Miroir de reset_economy_state (x45), champs du moteur uniquement
    (les mecaniques abandonnees — vassaux, guerre froide, colonisation —
    n'existent plus dans GameState)."""
    state.player_money = {player: 0 for player in range(state.num_players)}
    state.precious_mineral_mine_ids = set()
    state.bonus_5_spawn_turns = {}
    state.precious_mineral_mine_spawn_turns = {}
    state.fortress_territory_ids = set()
    state.fortress_capture_counts = {}
    state.factory_territory_ids = set()
    state.airport_territory_ids = set()
    state.port_territory_ids = set()
    state.industrial_capture_counts = {}
    state.cultural_center_ages = {}
    state.cultural_capture_counts = {}
    state.ruin_territory_ids = set()
    state.university_territory_ids = set()
    state.university_capture_counts = {}
    state.university_ages = {}
    state.temple_territory_ids = set()
    state.temple_capture_counts = {}
    state.religion_founders = {}
    state.religion_foundation_turns = {}
    state.religion_last_spread_turns = {}
    state.religion_holy_sites = {}
    state.religious_influence = {}
    state.player_science = {}
    state.culture_expansion_milestones = {}
    state.wonder_territories = {}
    state.wonder_construction_turns = {}
    state.last_stand_bonus_players = set()
    state.last_stand_bonus_territory = {}
    state.tax_haven_turn_start_territory_counts = {}
    state.active_alliances = {}
    state.active_offensive_alliances = {}
    state.active_ai_alliances = {}
    state.alliance_start_turns = {}
    state.offensive_alliance_start_turns = {}
    state.ai_alliance_start_turns = {}
    # Les ponts ne sont pas de l'economie : ils font partie du relief, au
    # meme titre que les liaisons terrestres. Ceux que la carte apporte
    # restent en place, et comptent donc comme voisins ; seuls ceux batis
    # en cours de partie disparaissent avec elle.
    state.bridge_links = set(getattr(state, "map_bridge_links", set()))
    state.fragile_bridge_links = set(
        getattr(state, "map_fragile_bridge_links", set())
    ) & state.bridge_links
    state.bridge_link_points = {
        key: points
        for key, points in getattr(state, "map_bridge_link_points", {}).items()
        if key in state.bridge_links
    }
    state.recompute_neighbors_from_grid()
    state.nation_players = set()
    state.nation_qualification_start_turns = {}
    state.nation_capital_loss_start_turns = {}
    state.submitted_territory_ids = set()
    state.submitted_territory_overlords = {}
    state.submitted_territory_created_turns = {}
    state.integrated_submitted_territories = {}
    state.union_members = {}
    state.union_original_territories = {}
    state.final_duel_active = False
    state.final_duel_champions = None
    state.final_duel_alliances = {}
    state.final_duel_pending_winner = None
    state.recent_major_events = []
    state.major_event_modal = None
    state.major_event_modal_queue = []
    state.pending_major_events_for_humans = {}
    state.collecting_between_turn_events = False


def choose_weighted_territory_ids_from_pool(
    pool: List[int], count: int, weight_func: Callable[[int], float], rng=random,
) -> List[int]:
    """Miroir de choose_weighted_territory_ids_from_pool (x45)."""
    available = list(pool)
    selected: List[int] = []
    while available and len(selected) < count:
        weights = [max(1, int(weight_func(tid))) for tid in available]
        total = sum(weights)
        pick = rng.uniform(0, total)
        running = 0.0
        chosen_index = 0
        for idx, weight in enumerate(weights):
            running += weight
            if pick <= running:
                chosen_index = idx
                break
        selected.append(available.pop(chosen_index))
    return selected


def assign_initial_economic_structures(state: GameState, rng=random) -> None:
    """Miroir de assign_initial_economic_structures (x45) : forteresses
    (ponderees par la connectivite), industries et centres culturels.

    En version simplifiee, seules les forteresses sont posees : industries et
    centres culturels ne produisent que de l'or et de la culture.
    """
    state.fortress_territory_ids = set()
    state.fortress_capture_counts = {}
    state.factory_territory_ids = set()
    state.airport_territory_ids = set()
    state.port_territory_ids = set()
    state.industrial_capture_counts = {}
    state.cultural_center_ages = {}
    state.cultural_capture_counts = {}
    state.ruin_territory_ids = set()
    state.university_territory_ids = set()
    state.university_capture_counts = {}
    if not state.territories:
        return

    non_commercial_ids = [
        tid for tid in range(len(state.territories))
        if not regles.is_commercial_city_territory(state, tid)
    ]
    fortress_pool = non_commercial_ids or list(range(len(state.territories)))
    fortress_ids = choose_weighted_territory_ids_from_pool(
        fortress_pool,
        min(INITIAL_FORTRESS_COUNT, len(fortress_pool)),
        lambda tid: max(1, len(state.territories[tid].neighbors)) ** 2,
        rng,
    )
    state.fortress_territory_ids = set(fortress_ids)
    state.fortress_capture_counts = {tid: 0 for tid in state.fortress_territory_ids}

    if regles.is_simple_mode(state):
        return

    ids = list(non_commercial_ids)
    rng.shuffle(ids)
    for tid in ids[:min(INITIAL_INDUSTRY_COUNT, len(ids))]:
        regles.add_industrial_structure(state, tid, rng.choice(["factory", "airport", "port"]))

    cultural_pool = non_commercial_ids or list(range(len(state.territories)))
    cultural_count = min(INITIAL_CULTURAL_CENTER_COUNT, len(cultural_pool))
    for tid in rng.sample(cultural_pool, cultural_count):
        regles.add_cultural_center(state, tid, age=0)
