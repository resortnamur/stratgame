"""Decisions de combat et de deplacement des IA (etape 1c.3).

Miroirs fideles des fonctions de x45 : choix d'une attaque
(``find_ai_attack`` + ``ai_attack_score``), choix d'une concentration de fin
de tour (``compute_ai_move_target`` + ``compute_ai_move_sources`` +
``execute_ai_move_phase``). Aucun affichage : les fonctions retournent des
structures que l'appelant met en scene (x45) ou rediffuse (serveur).

Le pilote de tour IA complet (``play_ai_turn``) vit dans ``moteur/actions.py``.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import regles
from .etat import GameState, Territory

COMMERCIAL_CITY_TERRITORY_LIMIT = 10


def get_ai_behavior(state: GameState, player: int, rng=random) -> str:
    if regles.is_commercial_city_player(state, player):
        return "aggressive"
    if regles.is_ai_player(state, player) and player in state.last_stand_bonus_players:
        return "defensive"
    profile = regles.get_ai_personality(state, player, rng)
    if profile == "variable":
        return state.ai_current_behavior.get(player, "standard")
    return profile


def get_offensive_alliance_target_for_ai(state: GameState, ai_player: int) -> Optional[int]:
    regles.cleanup_expired_alliances(state)
    candidates: List[Tuple[int, int]] = []
    for (_human, ai), (target, expires_turn) in state.active_offensive_alliances.items():
        if ai == ai_player and state.turn < expires_turn and any(terr.owner == target for terr in state.territories):
            candidates.append((expires_turn, target))
    if not candidates:
        return None
    return max(candidates)[1]


def is_ai_attack_blocked_by_culture(state: GameState, attacker: int, defender: int) -> bool:
    # Ancienne immunite culturelle IA desactivee, comme dans x45.
    return False


def ai_attack_score(
    state: GameState, src: Territory, dst: Territory, behavior: str, rng=random,
) -> Optional[Tuple[Tuple[int, int, int, int, int], bool]]:
    diff = src.regiments - dst.regiments
    if behavior == "very_aggressive":
        if src.regiments < 2:
            return None
        total_attack = diff >= 2 or src.regiments >= 6
        score = (
            1 if total_attack else 0,
            src.regiments + max(0, -diff),
            diff,
            -dst.regiments,
            -dst.id,
        )
    elif behavior == "aggressive":
        if src.regiments < 3:
            return None
        total_attack = diff >= 6 or (src.regiments >= 8 and rng.random() < 0.18)
        score = (
            1 if total_attack else 0,
            src.regiments,
            diff,
            -dst.regiments,
            -dst.id,
        )
    elif behavior == "defensive":
        if src.regiments < 5 or diff < 3:
            return None
        total_attack = diff > 14
        enemy_pressure = sum(
            state.territories[n].regiments
            for n in src.neighbors
            if state.territories[n].owner != state.current_player
            and not regles.is_attack_blocked_by_alliance(state, state.current_player, state.territories[n].owner)
        )
        score = (
            1 if total_attack else 0,
            diff,
            -enemy_pressure,
            -dst.regiments,
            -dst.id,
        )
    else:
        if src.regiments < 4:
            return None
        total_attack = diff > 10
        score = (
            1 if total_attack else 0,
            diff,
            src.regiments,
            -dst.regiments,
            -dst.id,
        )
    return score, total_attack


def find_ai_attack(state: GameState, rng=random) -> Optional[Tuple[Territory, Territory, bool]]:
    if regles.is_colonized_player(state, state.current_player):
        return None
    current_is_commercial = regles.is_commercial_city_player(state, state.current_player)
    palace_built = current_is_commercial and "golden_pact_palace" in state.wonder_territories
    if (
        current_is_commercial
        and not palace_built
        and regles.count_player_territories(state, state.current_player) >= COMMERCIAL_CITY_TERRITORY_LIMIT
    ):
        return None
    behavior = get_ai_behavior(state, state.current_player, rng)
    if palace_built:
        # Avec le Palais du Pacte d'Or, la CC agit comme une puissance
        # offensive contre tous sauf son unique allie — le controleur du
        # Palais. Sans controleur valide (territoire a l'ONU, fige ou aux
        # mains de la CC), elle attaque tout le monde ; la limite de
        # territoires est levee tant que le Palais existe.
        behavior = "very_aggressive"
    offensive_target = get_offensive_alliance_target_for_ai(state, state.current_player)
    if offensive_target is not None:
        behavior = "very_aggressive"
    candidates: List[Tuple[Tuple[int, int, int, int, int], Territory, Territory, bool]] = []

    for src in state.territories:
        if src.owner != state.current_player:
            continue

        for neighbor_id in src.neighbors:
            dst = state.territories[neighbor_id]
            if dst.owner == state.current_player:
                continue
            if current_is_commercial and regles.is_any_capital_territory(state, dst.id):
                continue
            if offensive_target is not None and dst.owner != offensive_target:
                continue
            if regles.is_attack_blocked_by_alliance(state, state.current_player, dst.owner):
                continue
            if is_ai_attack_blocked_by_culture(state, state.current_player, dst.owner):
                continue
            if regles.is_territory_protected_from_ai_attacks(state, dst.id):
                continue
            if regles.is_submitted_territory(state, dst.id):
                continue
            if regles.is_sanctuary_territory(state, dst.id) and src.regiments < 40:
                # Les IA ignorent les sanctuaires ONU, sauf si le territoire
                # attaquant concentre au moins 40 regiments.
                continue
            scored = ai_attack_score(state, src, dst, behavior, rng)
            if scored is None:
                continue
            score, total_attack = scored
            candidates.append((score, src, dst, total_attack))

    if not candidates:
        return None
    best_move = max(candidates, key=lambda item: item[0])
    return best_move[1], best_move[2], best_move[3]


def shortest_owned_path(state: GameState, start_id: int, target_id: int, owner: int) -> Optional[List[int]]:
    if start_id == target_id:
        return [start_id]
    queue = deque([start_id])
    previous: dict[int, Optional[int]] = {start_id: None}
    while queue:
        current = queue.popleft()
        for neighbor_id in state.territories[current].neighbors:
            neighbor = state.territories[neighbor_id]
            if neighbor.owner != owner or neighbor_id in previous:
                continue
            previous[neighbor_id] = current
            if neighbor_id == target_id:
                path = [target_id]
                cursor = current
                while cursor is not None:
                    path.append(cursor)
                    cursor = previous[cursor]
                path.reverse()
                return path
            queue.append(neighbor_id)
    return None


def compute_ai_move_target(state: GameState, rng=random) -> Optional[Tuple[Territory, Territory]]:
    behavior = get_ai_behavior(state, state.current_player, rng)
    current_is_commercial = state.current_player in state.commercial_city_players
    frontline_enemies = [
        enemy for enemy in state.territories
        if enemy.owner != state.current_player
        and not (current_is_commercial and regles.is_any_capital_territory(state, enemy.id))
        and not regles.is_attack_blocked_by_alliance(state, state.current_player, enemy.owner)
        and any(state.territories[n].owner == state.current_player for n in enemy.neighbors)
    ]
    offensive_target = get_offensive_alliance_target_for_ai(state, state.current_player)
    if offensive_target is not None:
        targeted_frontline = [enemy for enemy in frontline_enemies if enemy.owner == offensive_target]
        if targeted_frontline:
            frontline_enemies = targeted_frontline
            behavior = "aggressive"

    if not frontline_enemies:
        return None

    if behavior == "aggressive":
        target_enemy = max(frontline_enemies, key=lambda terr: (
            terr.owner == offensive_target, terr.regiments, len(terr.neighbors), -terr.id))
    elif behavior == "defensive":
        owned_borders = [
            terr for terr in state.territories
            if terr.owner == state.current_player
            and any(state.territories[n].owner != state.current_player for n in terr.neighbors)
        ]
        if not owned_borders:
            return None
        weakest_border = min(owned_borders, key=lambda terr: (terr.regiments, terr.id))
        enemy_neighbors = [
            state.territories[n]
            for n in weakest_border.neighbors
            if state.territories[n].owner != state.current_player
            and not (current_is_commercial and regles.is_any_capital_territory(state, n))
            and not regles.is_attack_blocked_by_alliance(state, state.current_player, state.territories[n].owner)
        ]
        if not enemy_neighbors:
            return None
        target_enemy = max(enemy_neighbors, key=lambda terr: (terr.regiments, -terr.id))
    else:
        target_enemy = max(frontline_enemies, key=lambda terr: (terr.regiments, -terr.id))

    border_candidates = [
        state.territories[nid]
        for nid in target_enemy.neighbors
        if state.territories[nid].owner == state.current_player
    ]
    if not border_candidates:
        return None

    best_border: Optional[Tuple[Tuple[int, int, int, int], Territory]] = None
    for border in border_candidates:
        reachable_sources = [
            src for src in state.territories
            if src.owner == state.current_player
            and src.regiments > 1
            and src.id != border.id
            and regles.can_move_between(state, src, border)
        ]
        movable_total = sum(src.regiments - 1 for src in reachable_sources)
        if behavior == "aggressive":
            score = (movable_total, target_enemy.regiments, -border.regiments, -border.id)
        elif behavior == "defensive":
            pressure = sum(
                state.territories[n].regiments
                for n in border.neighbors
                if state.territories[n].owner != state.current_player
                and not regles.is_attack_blocked_by_alliance(state, state.current_player, state.territories[n].owner)
            )
            score = (pressure, -border.regiments, movable_total, -border.id)
        else:
            score = (movable_total, -border.regiments, target_enemy.regiments, -border.id)
        if best_border is None or score > best_border[0]:
            best_border = (score, border)

    if best_border is None or best_border[0][0] <= 0:
        return None
    return target_enemy, best_border[1]


def compute_ai_move_sources(state: GameState, border_id: int) -> List[Tuple[Territory, int]]:
    candidates: List[Tuple[Tuple[int, int, int], Territory, int]] = []
    for src in state.territories:
        if src.owner != state.current_player or src.regiments <= 1 or src.id == border_id:
            continue
        path = shortest_owned_path(state, src.id, border_id, state.current_player)
        if path is None:
            continue
        movable = src.regiments - 1
        distance = len(path) - 1
        score = (movable, -distance, -src.id)
        candidates.append((score, src, movable))

    candidates.sort(reverse=True, key=lambda item: item[0])
    return [(src, movable) for _, src, movable in candidates]


@dataclass
class AiMoveReport:
    """Concentration de fin de tour d'une IA (pour l'affichage/diffusion)."""

    moved: int
    border_id: int
    target_enemy_id: int
    used_sources: List[str] = field(default_factory=list)


def execute_ai_move_phase(state: GameState, rng=random) -> Optional[AiMoveReport]:
    move_limit = regles.get_end_turn_move_limit(state)
    if state.turn_move_count >= move_limit:
        return None
    move_target = compute_ai_move_target(state, rng)
    if move_target is None:
        return None

    target_enemy, border = move_target
    sources = compute_ai_move_sources(state, border.id)
    if not sources:
        return None

    moved = 0
    used_sources: List[str] = []
    remaining = move_limit - state.turn_move_count
    for src, movable in sources:
        if remaining <= 0:
            break
        to_move = min(remaining, movable)
        moved_from_source = 0
        while moved_from_source < to_move and state.turn_move_count < move_limit and src.regiments > 1:
            ok, _code = regles.move_one_regiment(state, src, border)
            if not ok:
                break
            moved_from_source += 1
            moved += 1
            remaining -= 1
        if moved_from_source > 0:
            used_sources.append(f"{src.name} ({moved_from_source})")

    if moved <= 0:
        return None
    return AiMoveReport(moved, border.id, target_enemy.id, used_sources)
