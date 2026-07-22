"""Boucle de tour et vocabulaire d'actions (etape 1c de la migration).

Deux niveaux :

- ``begin_player_turn`` / ``advance_turn`` : miroirs purs de
  ``begin_player_turn`` / ``complete_turn`` de x45, qui retournent des
  rapports structures (l'affichage reste a l'appelant : x45 aujourd'hui,
  le serveur web demain).
- ``apply_action`` : le vocabulaire d'actions que le serveur recevra des
  clients — ``attaquer``, ``assaut_total``, ``deplacer``,
  ``terminer_attaque``, ``terminer_achats``, ``fin_de_tour`` — valide
  contre l'etat courant (phase, tour, proprietaires) puis applique via les
  regles du moteur.

Les dimensions de cellule (``cell_width``/``cell_height``) parametrent la
geometrie des ponts, heritee de l'affichage de x45 : x45 passe les siennes,
le serveur fixera des valeurs logiques constantes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import regles
from .etat import GameState


@dataclass
class BeginTurnReport:
    """Evenements de debut de tour d'un joueur (miroir de begin_player_turn)."""

    turn_notes: List[str] = field(default_factory=list)
    income: int = 0
    science_income: int = 0
    culture: int = 0
    science: int = 0
    skipped: bool = False  # phase != "playing" : rien n'a ete fait


@dataclass
class TurnAdvanceReport:
    """Evenements d'une fin de tour (miroir de complete_turn)."""

    has_active_players: bool = True
    winner: Optional[int] = None
    winner_reason: str = ""
    new_global_turn: bool = False
    reinforcement_report: Optional[regles.ReinforcementReport] = None
    sedition_message: Optional[str] = None
    resource_messages: List[str] = field(default_factory=list)
    religion_messages: List[str] = field(default_factory=list)
    market_message: Optional[str] = None
    empire_messages: List[str] = field(default_factory=list)
    begin_turn: Optional[BeginTurnReport] = None


def begin_player_turn(state: GameState, player: int, rng=random) -> BeginTurnReport:
    """Demarre le tour de ``player`` : evenements, revenus, science, culture."""
    if state.phase != "playing":
        return BeginTurnReport(skipped=True)
    if regles.is_human_player_id(state, player):
        pending_events = state.pending_major_events_for_humans.pop(player, [])
        if pending_events:
            regles.queue_major_event_modal(
                state,
                "Evenements survenus pendant les autres tours",
                pending_events,
            )
    regles.ensure_player_economy(state, player)
    regles.cleanup_expired_alliances(state)
    destroyed_cc_notes = regles.refresh_destroyed_commercial_cities(state)
    spawn_cc_notes = (
        regles.spawn_pending_commercial_cities(state, rng)
        if player == min(regles.get_active_players(state), default=player)
        else []
    )
    limit_note = regles.enforce_last_stand_bonus_limits(state, begin_of_turn=True)
    mobilization_note = regles.maybe_trigger_ai_mobilization(state, player, rng)
    last_stand_note = regles.activate_last_stand_bonus_if_needed(state, player)
    ai_alliance_note = regles.maybe_trigger_random_ai_alliance(state, player, rng)
    nation_notes = regles.refresh_nation_states(state, trigger_player=player)
    income = regles.collect_income_for_player(state, player)
    science_income = regles.add_science_for_player(state, player)
    culture = regles.calculate_player_culture(state, player)
    culture_expansion_notes, culture = regles.trigger_culture_expansions_if_due(state, player)
    science = regles.get_player_science(state, player)
    turn_notes = [
        *destroyed_cc_notes, *spawn_cc_notes, *nation_notes, *culture_expansion_notes,
        *[note for note in (limit_note, mobilization_note, last_stand_note, ai_alliance_note) if note],
    ]
    regles.record_replay_snapshot(state, f"Tour {state.turn} - debut du tour de J{player + 1}")
    # Miroir de la partie regles de reset_ai_turn_state (x45) : le
    # comportement du tour des IA est fixe maintenant, les profils
    # "variable" retirent au sort.
    if state.phase == "playing" and regles.is_ai_player(state, state.current_player):
        regles.prepare_ai_behavior_for_turn(state, state.current_player, rng)
    return BeginTurnReport(turn_notes, income, science_income, culture, science)


def advance_turn(
    state: GameState,
    cell_width: float,
    cell_height: float,
    rng=random,
    begin_next_turn: bool = True,
) -> TurnAdvanceReport:
    """Termine le tour du joueur courant et passe au suivant (miroir de complete_turn).

    ``begin_next_turn=False`` laisse l'appelant declencher lui-meme
    ``begin_player_turn`` (utilise par x45, qui y greffe son interface).
    """
    report = TurnAdvanceReport()
    state.turn_phase = "attack"
    state.turn_move_count = 0
    regles.cleanup_expired_alliances(state)
    previous_player = state.current_player
    regles.execute_ai_economic_actions(state, previous_player, rng)
    report.reinforcement_report = regles.grant_reinforcements(state, previous_player, rng)
    active_players = regles.get_active_players(state)
    report.has_active_players = bool(active_players)
    if active_players:
        sorted_players = sorted(active_players)
        next_player = sorted_players[0]
        for player in sorted_players:
            if player > previous_player:
                next_player = player
                break
        state.current_player = next_player
        if state.current_player <= previous_player:
            state.collecting_between_turn_events = True
            report.new_global_turn = True
            report.sedition_message = regles.maybe_trigger_sedition_at_end_of_turn(state, rng)
            winner, reason = regles.evaluate_winner(state)
            if winner is not None:
                state.collecting_between_turn_events = False
                report.winner = winner
                report.winner_reason = reason
                return report
            state.turn += 1
            resource_messages = regles.maybe_spawn_scheduled_resources(state, rng)
            collapse_message = regles.maybe_collapse_fragile_bridges(state, rng)
            if collapse_message:
                resource_messages.append(collapse_message)
            bridge_message = regles.maybe_spawn_random_bridge(state, cell_width, cell_height, rng)
            if bridge_message:
                resource_messages.append(bridge_message)
            report.resource_messages = resource_messages
            religion_notes = regles.expand_religious_influences_if_due(state)
            if religion_notes:
                regles.record_major_event(state, f"Tour {state.turn}: " + " ".join(religion_notes))
            report.religion_messages = religion_notes
            regles.snapshot_tax_haven_turn_start_territory_counts(state)
            regles.age_cultural_centers_one_turn(state)
            regles.age_universities_one_turn(state)
            report.market_message = regles.maybe_trigger_market_event(state, rng)
            report.empire_messages = regles.maybe_trigger_empire_event(state, rng)
            active_players = regles.get_active_players(state)
            sorted_players = sorted(active_players)
            if sorted_players:
                state.current_player = sorted_players[0]
            state.collecting_between_turn_events = False
    if active_players and begin_next_turn:
        report.begin_turn = begin_player_turn(state, state.current_player, rng)
    return report


# ----------------------------------------------------------------------
# Vocabulaire d'actions
# ----------------------------------------------------------------------

ACTION_TYPES = (
    "attaquer", "assaut_total", "deplacer",
    "terminer_attaque", "terminer_achats", "fin_de_tour",
)


@dataclass
class ActionOutcome:
    """Resultat de l'application d'une action.

    ``ok=False`` : action refusee, ``code`` explique pourquoi
    ("action_inconnue", "phase_invalide", "territoire_invalide",
    "attaque_invalide", ou un code de refus de deplacement : "limite",
    "proprietaire", "meme_territoire", "garnison", "continuite").
    """

    ok: bool
    code: str = "ok"
    attack_passes: List[regles.AttackResult] = field(default_factory=list)
    next_phase: Optional[str] = None
    turn_report: Optional[TurnAdvanceReport] = None
    winner: Optional[int] = None
    winner_reason: str = ""


def _refuse(code: str) -> ActionOutcome:
    return ActionOutcome(ok=False, code=code)


def _get_territory(state: GameState, action: Dict[str, Any], key: str):
    try:
        territory_id = int(action.get(key))
    except (TypeError, ValueError):
        return None
    if not (0 <= territory_id < len(state.territories)):
        return None
    return state.territories[territory_id]


def apply_action(
    state: GameState,
    action: Dict[str, Any],
    cell_width: float,
    cell_height: float,
    rng=random,
    submit_decider=None,
) -> ActionOutcome:
    """Valide et applique une action du joueur courant.

    C'est le point d'entree unique que le serveur exposera : il recoit un
    dictionnaire JSON (``{"type": "attaquer", "source": 3, "cible": 7}``),
    verifie la phase et les regles, mute l'etat et retourne un
    ``ActionOutcome`` structure a rediffuser aux clients.
    """
    action_type = action.get("type")

    if action_type in ("attaquer", "assaut_total"):
        if state.phase != "playing" or state.turn_phase != "attack":
            return _refuse("phase_invalide")
        src = _get_territory(state, action, "source")
        dst = _get_territory(state, action, "cible")
        if src is None or dst is None:
            return _refuse("territoire_invalide")
        if not regles.can_attack_specific_target(state, src, dst):
            return _refuse("attaque_invalide")
        outcome = ActionOutcome(ok=True)
        if action_type == "attaquer":
            outcome.attack_passes.append(
                regles.resolve_attack_once(state, src, dst, rng, submit_decider)
            )
        else:
            # Miroir de resolve_attack_until_end : on enchaine les passes
            # jusqu'a la conquete ou l'epuisement de l'attaque.
            while state.phase == "playing" and regles.can_attack_specific_target(state, src, dst):
                result = regles.resolve_attack_once(state, src, dst, rng, submit_decider)
                outcome.attack_passes.append(result)
                if result.conquered:
                    break
        winner, reason = regles.evaluate_winner(state)
        outcome.winner = winner
        outcome.winner_reason = reason
        return outcome

    if action_type == "deplacer":
        if state.phase != "playing" or state.turn_phase != "move":
            return _refuse("phase_invalide")
        src = _get_territory(state, action, "source")
        dst = _get_territory(state, action, "cible")
        if src is None or dst is None:
            return _refuse("territoire_invalide")
        moved, code = regles.move_one_regiment(state, src, dst)
        if not moved:
            return _refuse(code)
        return ActionOutcome(ok=True)

    if action_type == "terminer_attaque":
        if state.phase != "playing" or state.turn_phase != "attack":
            return _refuse("phase_invalide")
        # Miroir de handle_end_turn_action : les humains passent par la
        # phase d'achats, les IA (et anciens colonises) filent aux deplacements.
        if regles.is_ai_player(state, state.current_player) or regles.is_colonized_player(state, state.current_player):
            state.turn_phase = "move"
            state.turn_move_count = 0
            return ActionOutcome(ok=True, next_phase="move")
        state.phase = "shopping"
        return ActionOutcome(ok=True, next_phase="shopping")

    if action_type == "terminer_achats":
        if state.phase != "shopping":
            return _refuse("phase_invalide")
        state.phase = "playing"
        state.turn_phase = "move"
        state.turn_move_count = 0
        return ActionOutcome(ok=True, next_phase="move")

    if action_type == "fin_de_tour":
        if state.phase != "playing" or state.turn_phase != "move":
            return _refuse("phase_invalide")
        report = advance_turn(state, cell_width, cell_height, rng)
        return ActionOutcome(
            ok=True,
            next_phase="attack",
            turn_report=report,
            winner=report.winner,
            winner_reason=report.winner_reason,
        )

    return _refuse("action_inconnue")
