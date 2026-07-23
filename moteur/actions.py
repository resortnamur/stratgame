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

from . import achats
from . import ia
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


@dataclass
class AiTurnReport:
    """Deroulement complet d'un tour IA joue par le moteur."""

    skipped: bool = False  # joueur courant humain ou partie inactive
    attack_passes: int = 0
    winner: Optional[int] = None
    winner_reason: str = ""
    move_report: Optional[ia.AiMoveReport] = None
    turn_report: Optional[TurnAdvanceReport] = None


@dataclass
class AiAttackStep:
    """Une passe d'attaque d'un tour IA, pour la retransmission en direct.

    ``territoires`` porte l'etat a jour des territoires touches (source et
    cible), au format des entrees ``territories_state`` : le client peut
    mettre sa carte a jour sans recevoir l'etat complet. Les mutations plus
    larges mais rares (chaos mondial...) sont couvertes par l'etat complet
    diffuse en fin de tour.
    """

    src_id: int
    dst_id: int
    result: regles.AttackResult
    territoires: List[dict] = field(default_factory=list)


def _territoire_snapshot(terr) -> dict:
    return {
        "id": terr.id,
        "owner": terr.owner,
        "regiments": terr.regiments,
        "reinforcement_bonus": terr.reinforcement_bonus,
    }


def play_ai_turn_steps(
    state: GameState,
    cell_width: float,
    cell_height: float,
    rng=random,
    submit_decider=None,
    max_actions: int = 2000,
):
    """Deroule le tour IA courant en generant une ``AiAttackStep`` par passe.

    Miroir exact de l'ancien ``play_ai_turn`` (memes appels, meme ordre de
    tirage aleatoire) : attaques passe par passe, puis deplacements et fin
    de tour d'un bloc. La valeur de retour du generateur (StopIteration)
    est l'``AiTurnReport`` complet.
    """
    report = AiTurnReport()
    if state.phase != "playing" or not regles.is_ai_player(state, state.current_player):
        report.skipped = True
        return report

    for _ in range(max_actions):
        move = ia.find_ai_attack(state, rng)
        if move is None:
            break
        src, dst, total_attack = move
        if total_attack:
            # Miroir de resolve_attack_until_end.
            while state.phase == "playing" and regles.can_attack_specific_target(state, src, dst):
                result = regles.resolve_attack_once(state, src, dst, rng, submit_decider)
                report.attack_passes += 1
                yield AiAttackStep(src.id, dst.id, result,
                                   [_territoire_snapshot(src), _territoire_snapshot(dst)])
                if result.conquered:
                    break
        else:
            result = regles.resolve_attack_once(state, src, dst, rng, submit_decider)
            report.attack_passes += 1
            yield AiAttackStep(src.id, dst.id, result,
                               [_territoire_snapshot(src), _territoire_snapshot(dst)])
        winner, reason = regles.evaluate_winner(state)
        if winner is not None:
            report.winner = winner
            report.winner_reason = reason
            return report

    # Phase de deplacement (miroir de start_move_phase + execute_ai_move_phase).
    state.turn_phase = "move"
    state.turn_move_count = 0
    report.move_report = ia.execute_ai_move_phase(state, rng)

    # Fin de tour.
    report.turn_report = advance_turn(state, cell_width, cell_height, rng)
    if report.turn_report.winner is not None:
        report.winner = report.turn_report.winner
        report.winner_reason = report.turn_report.winner_reason
    return report


def play_ai_turn(
    state: GameState,
    cell_width: float,
    cell_height: float,
    rng=random,
    submit_decider=None,
    max_actions: int = 2000,
) -> AiTurnReport:
    """Joue le tour complet du joueur IA courant (miroir de process_ai_turn).

    Consomme ``play_ai_turn_steps`` d'une traite : meme chemin de code que
    la retransmission passe par passe du serveur.
    """
    steps = play_ai_turn_steps(
        state, cell_width, cell_height, rng, submit_decider, max_actions,
    )
    while True:
        try:
            next(steps)
        except StopIteration as fin:
            return fin.value


# ----------------------------------------------------------------------
# Vocabulaire d'actions
# ----------------------------------------------------------------------

ACTION_TYPES = (
    "attaquer", "assaut_total", "deplacer",
    "terminer_attaque", "terminer_achats", "fin_de_tour",
    "acheter",
)

# Achats disponibles pendant la phase d'achats, avec leurs parametres :
# {"type": "acheter", "achat": "mercenaires", "territoire": 3, "quantite": 5}
ACHATS = (
    "mercenaires",            # territoire, quantite
    "vendre_territoire",      # territoire
    "donner_territoire",      # territoire, joueur
    "donner_argent",          # joueur, montant
    "forteresse",             # territoire
    "detruire_forteresse",    # territoire
    "usine", "aeroport", "port",  # territoire
    "temple",                 # territoire
    "centre_culturel",        # territoire
    "universite",             # territoire
    "detruire_universite",    # territoire
    "merveille",              # territoire, merveille
    "capitale",               # territoire
    "corruption",             # territoire
    "revolte",                # territoire
    "pont",                   # territoire, territoire_b
    "detruire_pont",          # territoire, territoire_b
    "alliance",               # territoire (du joueur IA cible)
    "alliance_offensive",     # allie, cible (joueurs)
    "figer_onu",              # territoire
    "liberer_onu",            # territoire
    "association_pf",         # territoire (capitale PF de l'IA)
)


@dataclass
class ActionOutcome:
    """Resultat de l'application d'une action.

    ``ok=False`` : action refusee, ``code`` explique pourquoi
    ("action_inconnue", "phase_invalide", "territoire_invalide",
    "attaque_invalide", "achat_inconnu", "achat_refuse", ou un code de refus
    de deplacement : "limite", "proprietaire", "meme_territoire", "garnison",
    "continuite"). Pour les achats, ``message`` porte le texte de la
    boutique (succes comme refus).
    """

    ok: bool
    code: str = "ok"
    message: str = ""
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

    if action_type == "acheter":
        if state.phase != "shopping":
            return _refuse("phase_invalide")
        return _apply_purchase(state, action, cell_width, cell_height, rng)

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


def _apply_purchase(
    state: GameState,
    action: Dict[str, Any],
    cell_width: float,
    cell_height: float,
    rng=random,
) -> ActionOutcome:
    """Applique un achat de la boutique (phase d'achats deja verifiee)."""
    achat = action.get("achat")
    if achat not in ACHATS:
        return _refuse("achat_inconnu")

    def outcome(result: achats.AchatResult) -> ActionOutcome:
        if result.ok:
            return ActionOutcome(ok=True, message=result.message)
        return ActionOutcome(ok=False, code="achat_refuse", message=result.message)

    def get_int(key: str) -> Optional[int]:
        try:
            return int(action.get(key))
        except (TypeError, ValueError):
            return None

    needs_territory = achat not in ("donner_argent", "alliance_offensive")
    terr = None
    if needs_territory:
        terr = _get_territory(state, action, "territoire")
        if terr is None:
            return _refuse("territoire_invalide")

    if achat == "mercenaires":
        quantity = get_int("quantite")
        if quantity is None or quantity <= 0:
            return _refuse("achat_refuse")
        return outcome(achats.acheter_mercenaires(state, terr, quantity))
    if achat == "vendre_territoire":
        return outcome(achats.vendre_territoire(state, terr, rng))
    if achat == "donner_territoire":
        target_player = get_int("joueur")
        if target_player is None:
            return _refuse("achat_refuse")
        return outcome(achats.donner_territoire(state, terr, target_player))
    if achat == "donner_argent":
        target_player = get_int("joueur")
        amount = get_int("montant")
        if target_player is None or amount is None:
            return _refuse("achat_refuse")
        return outcome(achats.donner_argent(state, target_player, amount))
    if achat == "forteresse":
        return outcome(achats.construire_forteresse(state, terr))
    if achat == "detruire_forteresse":
        return outcome(achats.detruire_forteresse(state, terr))
    if achat in ("usine", "aeroport", "port"):
        structure_type = {"usine": "factory", "aeroport": "airport", "port": "port"}[achat]
        return outcome(achats.construire_industrie(state, terr, structure_type))
    if achat == "temple":
        return outcome(achats.construire_temple(state, terr))
    if achat == "centre_culturel":
        return outcome(achats.construire_centre_culturel(state, terr))
    if achat == "universite":
        return outcome(achats.construire_universite(state, terr))
    if achat == "detruire_universite":
        return outcome(achats.detruire_universite(state, terr))
    if achat == "merveille":
        return outcome(achats.construire_merveille(state, terr, action.get("merveille")))
    if achat == "capitale":
        return outcome(achats.changer_capitale(state, terr))
    if achat == "corruption":
        return outcome(achats.corrompre_territoire(state, terr))
    if achat == "revolte":
        return outcome(achats.financer_revolte(state, terr, rng))
    if achat == "pont":
        other = get_int("territoire_b")
        if other is None or not (0 <= other < len(state.territories)):
            return _refuse("territoire_invalide")
        return outcome(achats.construire_pont(state, terr.id, other, cell_width, cell_height))
    if achat == "detruire_pont":
        other = get_int("territoire_b")
        if other is None or not (0 <= other < len(state.territories)):
            return _refuse("territoire_invalide")
        return outcome(achats.detruire_pont(state, terr.id, other))
    if achat == "alliance":
        return outcome(achats.acheter_alliance(state, terr))
    if achat == "alliance_offensive":
        ai_player = get_int("allie")
        target_player = get_int("cible")
        if ai_player is None or target_player is None:
            return _refuse("achat_refuse")
        return outcome(achats.acheter_alliance_offensive(state, ai_player, target_player))
    if achat == "figer_onu":
        return outcome(achats.figer_territoire(state, terr))
    if achat == "liberer_onu":
        return outcome(achats.liberer_sanctuaire(state, terr, rng))
    if achat == "association_pf":
        return outcome(achats.association_paradis_fiscal(state, terr, rng))

    return _refuse("achat_inconnu")
