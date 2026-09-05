"""Actions d'achat de la boutique (etape 1c.2 de la migration).

Chaque fonction est le miroir fidele d'un ``execute_shop_*`` de x45 :
memes validations dans le meme ordre, memes couts, memes textes de message.
Les differences voulues :

- les flux « en deux clics » de x45 (choisir un territoire puis un
  beneficiaire, une extremite de pont puis l'autre...) deviennent des
  fonctions a parametres explicites — ce que le client web enverra ;
- aucun affichage : chaque fonction retourne un ``AchatResult`` (succes ou
  refus + message), l'appelant decide quoi en faire ;
- l'aleatoire est injectable (``rng``).

Les quantites ajustables de l'interface (mercenaires, montant du don) sont
des parametres ; leur bornage interactif reste cote client.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import regles
from .etat import GameState, Territory

DESTROY_FORTRESS_COST = 100
BUILD_BRIDGE_COST = 300
DESTROY_BRIDGE_COST = 150
REVOLT_COST_LOW = 200
REVOLT_COST_MEDIUM = 400
REVOLT_COST_HIGH = 600
TAX_HAVEN_INTEGRATION_COST = 500
ONU_MANIPULATION_COST_PER_REGIMENT = 50
SCIENCE_ONU_MANIPULATION_THRESHOLD = 50
SCIENCE_BRIDGE_THRESHOLD = 150
SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD = 200
# Le missile est aussi une arme des IA : ses constantes vivent dans
# ``regles`` (comme MISSION_COST), la boutique les relaie sous leurs noms
# historiques.
MISSILE_COST = regles.MISSILE_COST
SCIENCE_MISSILE_THRESHOLD = regles.SCIENCE_MISSILE_THRESHOLD
SCIENCE_MISSILE_RANGE_THRESHOLD = regles.SCIENCE_MISSILE_RANGE_THRESHOLD
SCIENCE_MISSILE_TOTAL_THRESHOLD = regles.SCIENCE_MISSILE_TOTAL_THRESHOLD
MISSILE_RANGE_PX = regles.MISSILE_RANGE_PX
ALLIANCE_COST_PER_TERRITORY = 20
OFFENSIVE_ALLIANCE_COST_PER_TERRITORY = 25


@dataclass
class AchatResult:
    """Resultat d'un achat : accepte ou refuse, avec le message de x45."""

    ok: bool
    message: str


def _refus(message: str) -> AchatResult:
    return AchatResult(False, message)


def _succes(message: str) -> AchatResult:
    return AchatResult(True, message)


# ----------------------------------------------------------------------
# Monnaie et couts
# ----------------------------------------------------------------------

def get_player_money(state: GameState, player: Optional[int] = None) -> int:
    player = state.current_player if player is None else player
    regles.ensure_player_economy(state, player)
    return state.player_money.get(player, 0)


def spend_player_money(state: GameState, player: int, amount: int) -> bool:
    regles.ensure_player_economy(state, player)
    if amount < 0 or state.player_money[player] < amount:
        return False
    state.player_money[player] -= amount
    return True


def calculate_sale_structure_bonus(state: GameState, territory: Territory) -> int:
    bonus_count = 0
    if territory.id in state.fortress_territory_ids:
        bonus_count += 1
    bonus_count += regles.get_industrial_structure_count(state, territory.id)
    bonus_count += regles.get_cultural_center_count(state, territory.id)
    if territory.id in state.university_territory_ids:
        bonus_count += 1
    if territory.id in state.temple_territory_ids:
        bonus_count += 1
    if territory.reinforcement_bonus >= 3:
        bonus_count += 1
    return bonus_count * 50


def calculate_territory_sale_price(state: GameState, territory: Territory) -> int:
    return max(0, territory.regiments) * 10 + calculate_sale_structure_bonus(state, territory)


def calculate_revolt_cost_for_target_player(state: GameState, target_player: int) -> int:
    territory_count = sum(1 for terr in state.territories if terr.owner == target_player)
    if territory_count < 10:
        return REVOLT_COST_LOW
    if territory_count <= 18:
        return REVOLT_COST_MEDIUM
    return REVOLT_COST_HIGH


def calculate_revolt_loss_count(territory_count: int) -> int:
    return max(1, territory_count // 4)


def get_alliance_cost(state: GameState, ai_player: int) -> int:
    return regles.count_player_territories(state, ai_player) * ALLIANCE_COST_PER_TERRITORY


def get_offensive_alliance_cost(state: GameState, ai_player: int) -> int:
    return regles.count_player_territories(state, ai_player) * OFFENSIVE_ALLIANCE_COST_PER_TERRITORY


def calculate_onu_manipulation_cost(state: GameState, territory: Territory) -> int:
    return max(1, territory.regiments) * ONU_MANIPULATION_COST_PER_REGIMENT


def can_player_manipulate_onu(state: GameState, player: int) -> bool:
    return (
        player in state.last_stand_bonus_players
        or regles.has_science_level(state, player, SCIENCE_ONU_MANIPULATION_THRESHOLD)
    )


def can_player_integrate_tax_haven_by_science(state: GameState, player: int) -> bool:
    return regles.has_science_level(state, player, SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD)


def break_ai_alliance_due_to_offensive_contract(
    state: GameState, ai_player: int, target_player: int,
) -> Optional[str]:
    if not (regles.is_ai_player(state, ai_player) and regles.is_ai_player(state, target_player)):
        return None
    regles.cleanup_expired_alliances(state)
    key = regles.normalize_ai_alliance_key(ai_player, target_player)
    expires_turn = state.active_ai_alliances.get(key)
    if expires_turn is None or state.turn >= expires_turn:
        return None
    state.active_ai_alliances.pop(key, None)
    state.ai_alliance_start_turns.pop(key, None)
    return (
        f"L'alliance IA entre J{ai_player + 1} et J{target_player + 1} est rompue "
        f"par le contrat offensif."
    )


def remove_bridge(state: GameState, key: Tuple[int, int]) -> None:
    normalized = tuple(sorted(key))
    state.bridge_links.discard(normalized)
    state.fragile_bridge_links.discard(normalized)
    state.bridge_link_points.pop(normalized, None)
    state.recompute_neighbors_from_grid()


def cleanup_removed_ai_player(state: GameState, ai_player: int) -> None:
    regles.schedule_commercial_city_replacement_if_destroyed(state, ai_player)
    state.base_ai_players.discard(ai_player)
    state.auto_controlled_players.discard(ai_player)
    state.commercial_city_players.discard(ai_player)
    state.commercial_city_capital_ids.pop(ai_player, None)
    state.ai_personalities.pop(ai_player, None)
    state.ai_current_behavior.pop(ai_player, None)
    state.ai_last_missile_turns.pop(ai_player, None)
    state.player_science.pop(ai_player, None)
    state.culture_expansion_milestones.pop(ai_player, None)
    state.active_alliances = {
        key: expires_turn
        for key, expires_turn in state.active_alliances.items()
        if key[1] != ai_player
    }
    state.alliance_start_turns = {
        key: start for key, start in state.alliance_start_turns.items()
        if key in state.active_alliances
    }
    state.active_ai_alliances = {
        key: expires_turn
        for key, expires_turn in state.active_ai_alliances.items()
        if ai_player not in key
    }
    state.ai_alliance_start_turns = {
        key: start for key, start in state.ai_alliance_start_turns.items()
        if key in state.active_ai_alliances
    }
    state.active_offensive_alliances = {
        key: data
        for key, data in state.active_offensive_alliances.items()
        if key[1] != ai_player and data[0] != ai_player
    }
    state.offensive_alliance_start_turns = {
        key: start for key, start in state.offensive_alliance_start_turns.items()
        if key in state.active_offensive_alliances
    }
    state.nation_players.discard(ai_player)
    # nation_alliances / nation_wars : mecaniques abandonnees, toujours vides.


def get_random_ai_recipient_for_released_sanctuary(
    state: GameState, excluded_players=None, rng=random,
) -> int:
    excluded_players = excluded_players or set()
    candidates = [
        player for player in regles.get_active_players(state)
        if player not in excluded_players
        and regles.is_ai_player(state, player)
        and not regles.is_commercial_city_player(state, player)
    ]
    if candidates:
        return rng.choice(candidates)

    new_player = state.num_players
    state.num_players += 1
    state.base_ai_players.add(new_player)
    regles.assign_ai_personality_to_player(state, new_player, None, rng)
    regles.ensure_player_economy(state, new_player)
    return new_player


# ----------------------------------------------------------------------
# Achats : troupes, territoires, argent
# ----------------------------------------------------------------------

def acheter_mercenaires(state: GameState, terr: Territory, quantity: int) -> AchatResult:
    if terr.owner != state.current_player:
        return _refus("Les mercenaires doivent etre places sur un territoire controle.")
    quantity = max(1, int(quantity))
    cost = quantity * regles.MERCENARY_COST
    if not spend_player_money(state, state.current_player, cost):
        return _refus("Pas assez d'ecus pour ces mercenaires.")
    terr.regiments += quantity
    return _succes(f"{quantity} mercenaire(s) places sur {terr.name} pour {cost} ecu(s).")


def vendre_territoire(state: GameState, terr: Territory, rng=random) -> AchatResult:
    if terr.owner != state.current_player:
        return _refus("Vous ne pouvez vendre qu'un territoire que vous controlez.")
    candidates = [
        player for player in regles.get_active_players(state)
        if player != state.current_player and not regles.is_commercial_city_player(state, player)
    ]
    if not candidates:
        return _refus("Vente impossible : aucun autre joueur actif non cite commercante ne peut recevoir ce territoire.")
    sale_price = calculate_territory_sale_price(state, terr)
    buyer = rng.choice(candidates)
    terr.owner = buyer
    regles.ensure_player_economy(state, state.current_player)
    state.player_money[state.current_player] += sale_price
    regles.refresh_last_stand_bonus_state(state)
    regles.enforce_last_stand_bonus_limits(state)
    elimination_note = ""
    if not any(t.owner == state.current_player for t in state.territories):
        regles.mark_eliminated_player_if_human(state, state.current_player)
        regles.refresh_eliminated_human_players(state)
        elimination_note = f" J{state.current_player + 1} n'a plus de territoire."
    return _succes(
        f"{terr.name} vendu a J{buyer + 1} pour {sale_price} ecu(s) "
        f"({terr.regiments} regiment(s) x 10 + {calculate_sale_structure_bonus(state, terr)} ecu(s) de bonus)."
        + elimination_note
    )


def donner_territoire(state: GameState, source: Territory, target_player: int) -> AchatResult:
    if source.owner != state.current_player:
        return _refus("Don impossible : ce territoire n'est plus controle par vous.")
    if target_player < 0:
        return _refus("Impossible de donner un territoire a l'ONU.")
    if target_player == state.current_player:
        return _refus("Choisissez un autre joueur comme beneficiaire. Se donner sa propre terre, c'est juste rester proprietaire avec des etapes.")
    if not regles.can_commercial_city_gain_territory(state, target_player, source.id):
        return _refus("Don impossible : une Cite commercante ne peut jamais prendre le controle d'une capitale.")

    source.owner = target_player
    regles.refresh_last_stand_bonus_state(state)
    regles.enforce_last_stand_bonus_limits(state)
    elimination_note = ""
    if not any(t.owner == state.current_player for t in state.territories):
        regles.mark_eliminated_player_if_human(state, state.current_player)
        regles.refresh_eliminated_human_players(state)
        elimination_note = f" J{state.current_player + 1} n'a plus de territoire."
    return _succes(
        f"{source.name} donne a J{target_player + 1}. Aucun ecu gagne, juste de la geopolitique charitable."
        + elimination_note
    )


def donner_argent(state: GameState, target_player: int, amount: int) -> AchatResult:
    if target_player < 0:
        return _refus("Impossible de donner de l'argent a l'ONU.")
    if target_player == state.current_player:
        return _refus("Impossible de se donner de l'argent a soi-meme. Meme la comptabilite refuserait.")
    if amount <= 0:
        return _refus("Impossible de donner de l'argent : aucun ecu disponible.")
    if not spend_player_money(state, state.current_player, amount):
        return _refus(f"Don impossible : {amount} ecu(s) non disponibles.")
    regles.ensure_player_economy(state, target_player)
    state.player_money[target_player] += amount
    return _succes(f"J{state.current_player + 1} donne {amount} ecu(s) a J{target_player + 1}.")


# ----------------------------------------------------------------------
# Achats : constructions
# ----------------------------------------------------------------------

def construire_forteresse(state: GameState, terr: Territory) -> AchatResult:
    if terr.owner != state.current_player:
        return _refus("Une forteresse doit etre construite sur un territoire controle.")
    if terr.id in state.fortress_territory_ids:
        return _refus("Ce territoire possede deja une forteresse.")
    if not spend_player_money(state, state.current_player, regles.FORTRESS_COST):
        return _refus("Pas assez d'ecus pour construire une forteresse.")
    state.fortress_territory_ids.add(terr.id)
    state.fortress_capture_counts[terr.id] = 0
    return _succes(f"Forteresse construite sur {terr.name} pour {regles.FORTRESS_COST} ecu(s).")


def detruire_forteresse(state: GameState, terr: Territory) -> AchatResult:
    if terr.id not in state.fortress_territory_ids:
        return _refus("Aucune forteresse a detruire sur ce territoire.")
    if not spend_player_money(state, state.current_player, DESTROY_FORTRESS_COST):
        return _refus("Pas assez d'ecus pour detruire cette forteresse.")
    state.fortress_territory_ids.discard(terr.id)
    state.fortress_capture_counts.pop(terr.id, None)
    return _succes(f"Forteresse de {terr.name} detruite pour {DESTROY_FORTRESS_COST} ecu(s).")


_INDUSTRIAL_LABELS = {"factory": "usine", "airport": "aeroport", "port": "port"}
_INDUSTRIAL_COSTS = {
    "factory": regles.FACTORY_COST,
    "airport": regles.AIRPORT_COST,
    "port": regles.PORT_COST,
}


def construire_industrie(state: GameState, terr: Territory, structure_type: str) -> AchatResult:
    label = _INDUSTRIAL_LABELS.get(structure_type, "industrie")
    cost = _INDUSTRIAL_COSTS.get(structure_type, 0)
    if terr.owner != state.current_player:
        return _refus(f"Un {label} doit etre construit sur un territoire controle.")
    structure_sets = {
        "factory": state.factory_territory_ids,
        "airport": state.airport_territory_ids,
        "port": state.port_territory_ids,
    }
    existing_structure_type = None
    for candidate_type, ids in structure_sets.items():
        if terr.id in ids:
            existing_structure_type = candidate_type
            break
    if terr.id in structure_sets.get(structure_type, set()):
        return _refus(f"Ce territoire possede deja cet amenagement industriel ({_INDUSTRIAL_LABELS.get(structure_type, 'industrie')}).")
    if existing_structure_type is not None:
        return _refus(f"Ce territoire possede deja un amenagement industriel ({_INDUSTRIAL_LABELS.get(existing_structure_type, 'industrie')}).")
    if not spend_player_money(state, state.current_player, cost):
        return _refus(f"Pas assez d'ecus pour construire un {label}.")
    if not regles.add_industrial_structure(state, terr.id, structure_type):
        return _refus(f"Construction impossible pour ce {label}.")
    bonus_note = (
        " Bonus PF trio industriel actif : revenus +50%."
        if regles.is_tax_haven_income_bonus_active(state, state.current_player)
        else ""
    )
    return _succes(f"{label.capitalize()} construit sur {terr.name} pour {cost} ecu(s)." + bonus_note)


def construire_temple(state: GameState, terr: Territory) -> AchatResult:
    if terr.owner != state.current_player:
        return _refus("Un temple doit etre construit sur un territoire controle.")
    if regles.has_temple(state, terr.id):
        return _refus(f"Maximum atteint : un seul temple sur {terr.name}.")
    if not spend_player_money(state, state.current_player, regles.TEMPLE_COST):
        return _refus(f"Pas assez d'ecus pour construire un temple : {regles.TEMPLE_COST} requis.")
    regles.add_temple(state, terr.id)
    religion_note = getattr(state, "last_religion_foundation_message", None)
    if religion_note:
        return _succes(f"Temple construit sur {terr.name}. {religion_note}")
    return _succes(f"Temple construit sur {terr.name} pour {regles.TEMPLE_COST} ecu(s).")


def envoyer_mission(state: GameState, terr: Territory) -> AchatResult:
    """Envoie une mission sur un territoire quelconque de la carte du monde.

    Le territoire choisi se convertit a la religion nationale de l'acheteur.
    Reserve aux religions nationales : la religion de la merveille (Elyrion)
    n'envoie pas de missions.
    """
    religion_id = regles.get_player_national_religion_id(state, state.current_player)
    if religion_id is None:
        return _refus(
            "Mission impossible : vous n'avez pas de religion nationale. "
            "Elle nait avec votre premier temple."
        )
    religion_name = regles.get_religion_name(state, religion_id)
    if regles.is_territory_tax_haven_immune_to_religion(state, terr.id):
        return _refus(f"Mission impossible : {terr.name} est un paradis fiscal, impermeable a toute religion.")
    if state.religious_influence.get(terr.id) == religion_id:
        return _refus(f"{terr.name} est deja sous l'influence de {religion_name}.")
    if not spend_player_money(state, state.current_player, regles.MISSION_COST):
        return _refus(f"Pas assez d'ecus pour envoyer une mission : {regles.MISSION_COST} requis.")
    previous_religion_id = state.religious_influence.get(terr.id)
    state.religious_influence[terr.id] = religion_id
    if previous_religion_id is None:
        conversion_note = ""
    else:
        conversion_note = f" {regles.get_religion_name(state, previous_religion_id)} y perd son influence."
    return _succes(
        f"Mission envoyee sur {terr.name} pour {regles.MISSION_COST} ecu(s) : "
        f"le territoire se convertit a {religion_name}." + conversion_note
    )


def construire_centre_culturel(state: GameState, terr: Territory) -> AchatResult:
    if terr.owner != state.current_player:
        return _refus("Un centre culturel doit etre construit sur un territoire controle.")
    if regles.has_ruin(state, terr.id):
        return _refus(f"On ne rebatit pas sur les ruines de {terr.name} : la place est prise pour toujours.")
    if not regles.can_add_cultural_center(state, terr.id):
        return _refus(f"Maximum atteint : un seul centre culturel sur {terr.name}.")
    if not spend_player_money(state, state.current_player, regles.CULTURAL_CENTER_COST):
        return _refus(f"Pas assez d'ecus pour construire un centre culturel : {regles.CULTURAL_CENTER_COST} requis.")
    regles.add_cultural_center(state, terr.id, age=0)
    return _succes(f"Centre culturel construit sur {terr.name} pour {regles.CULTURAL_CENTER_COST} ecu(s).")


def construire_universite(state: GameState, terr: Territory) -> AchatResult:
    if terr.owner != state.current_player:
        return _refus("Une universite doit etre construite sur un territoire controle.")
    if regles.has_university(state, terr.id):
        return _refus(f"Maximum atteint : une seule universite sur {terr.name}.")
    if not spend_player_money(state, state.current_player, regles.UNIVERSITY_COST):
        return _refus(f"Pas assez d'ecus pour construire une universite : {regles.UNIVERSITY_COST} requis.")
    regles.add_university(state, terr.id)
    return _succes(f"Universite construite sur {terr.name} pour {regles.UNIVERSITY_COST} ecu(s). Elle produit de la science a chaque tour.")


def detruire_universite(state: GameState, terr: Territory) -> AchatResult:
    if not regles.has_university(state, terr.id):
        return _refus("Aucune universite a detruire sur ce territoire.")
    if not spend_player_money(state, state.current_player, regles.UNIVERSITY_COST):
        return _refus(f"Pas assez d'ecus pour detruire cette universite : {regles.UNIVERSITY_COST} requis.")
    regles.remove_university(state, terr.id)
    return _succes(f"Universite de {terr.name} detruite pour {regles.UNIVERSITY_COST} ecu(s).")


def construire_merveille(state: GameState, terr: Territory, wonder_type: Optional[str]) -> AchatResult:
    if wonder_type not in regles.WONDER_DEFINITIONS:
        return _refus("Choisissez d'abord une merveille dans le menu des achats.")
    if regles.has_built_wonder_this_turn(state, state.current_player):
        return _refus("Une seule merveille par tour : la prochaine attendra le tour suivant.")
    if regles.is_late_wonder_type(wonder_type):
        if not regles.can_player_build_late_wonder(state, state.current_player):
            return _refus(
                f"{regles.get_wonder_name(wonder_type)} ne se batit qu'a partir du tour "
                f"{regles.LATE_WONDER_FIRST_TURN} (nous sommes au tour {state.turn})."
            )
    elif regles.is_cultural_wonder_type(wonder_type):
        if not regles.can_player_build_cultural_wonder(state, state.current_player):
            required_culture = regles.get_wonder_culture_threshold(state, state.current_player)
            return _refus(
                f"Culture insuffisante : {required_culture} points requis "
                "pour une merveille culturelle."
            )
    elif not regles.can_player_build_wonder(state, state.current_player):
        required_science = regles.get_wonder_science_threshold(state, state.current_player)
        return _refus(f"Science insuffisante : {required_science} points requis pour une merveille.")
    if terr.owner != state.current_player:
        return _refus("Une merveille doit etre construite sur un territoire controle.")
    if regles.get_wonder_type_at_territory(state, terr.id) is not None:
        return _refus(f"{terr.name} accueille deja une merveille.")
    if wonder_type not in regles.get_available_wonder_types(state):
        return _refus(f"{regles.get_wonder_name(wonder_type)} a deja ete construite.")
    cost = regles.get_wonder_cost(state, state.current_player, wonder_type)
    if not spend_player_money(state, state.current_player, cost):
        return _refus(f"Pas assez d'ecus : {cost} requis pour cette merveille.")
    if not regles.build_wonder(state, terr.id, wonder_type):
        state.player_money[state.current_player] += cost
        return _refus("Construction de la merveille impossible.")
    wonder_name = regles.get_wonder_name(wonder_type)
    wonder_effect = regles.get_wonder_effect(wonder_type)
    return _succes(f"{wonder_name} construite sur {terr.name} pour {cost} ecus. {wonder_effect}.")


def changer_capitale(state: GameState, terr: Territory) -> AchatResult:
    if state.current_player in state.commercial_city_players:
        return _refus("Changement impossible : les Cites commercantes gardent leur capitale CC propre.")
    if terr.owner != state.current_player:
        return _refus("La nouvelle capitale doit etre un territoire que vous controlez.")
    if regles.is_sanctuary_territory(state, terr.id) or terr.owner == state.onu_player_id:
        return _refus("Changement impossible : un territoire ONU ne peut pas devenir capitale.")
    previous_capital_id = state.player_capital_ids.get(state.current_player)
    if previous_capital_id == terr.id and regles.is_active_regular_capital(state, terr.id):
        return _refus(f"{terr.name} est deja votre capitale. Meme l'administration peut eviter un formulaire inutile.")
    if not spend_player_money(state, state.current_player, regles.CHANGE_CAPITAL_COST):
        return _refus(f"Pas assez d'ecus pour changer de capitale : {regles.CHANGE_CAPITAL_COST} requis.")
    old_name = None
    if previous_capital_id is not None and 0 <= previous_capital_id < len(state.territories):
        old_name = state.territories[previous_capital_id].name
    state.player_capital_ids[state.current_player] = terr.id
    state.sanctuary_territory_ids.discard(terr.id)
    regles.sanitize_player_capitals(state)
    old_note = f" Ancienne capitale : {old_name}." if old_name and old_name != terr.name else ""
    return _succes(
        f"{terr.name} devient la capitale de J{state.current_player + 1} pour {regles.CHANGE_CAPITAL_COST} ecu(s)."
        f" Revenu x{regles.CAPITAL_INCOME_MULTIPLIER} et symbole C actifs." + old_note
    )


# ----------------------------------------------------------------------
# Achats : corruption et revolte
# ----------------------------------------------------------------------

def corrompre_territoire(state: GameState, terr: Territory) -> AchatResult:
    current_is_commercial_city = regles.is_commercial_city_player(state, state.current_player)
    if terr.owner == state.current_player:
        return _refus("Ce territoire est deja a vous. La corruption interne, gardons ca pour plus tard.")
    if terr.id in state.golden_territory_ids:
        return _refus("Impossible de corrompre un territoire dore : incorruptible.")
    if (terr.owner < 0 or regles.is_sanctuary_territory(state, terr.id)) and not current_is_commercial_city:
        return _refus("Impossible de corrompre un territoire ONU.")
    if regles.is_commercial_city_territory(state, terr.id):
        return _refus("Impossible de corrompre une cite commercante.")
    if regles.is_last_stand_bonus_territory(state, terr.id) and not current_is_commercial_city:
        return _refus("Impossible de corrompre une capitale en paradis fiscal.")
    if current_is_commercial_city and not regles.is_territory_adjacent_to_player(state, terr.id, state.current_player):
        return _refus("Corruption CC impossible : le territoire doit etre adjacent a une cite deja controlee.")
    cost, base_cost, surcharge = regles.calculate_corruption_cost(state, terr)
    if not spend_player_money(state, state.current_player, cost):
        surcharge_note = f" dont {surcharge} de surcout amenagement/+3" if surcharge > 0 else ""
        return _refus(f"Corruption trop chere : {cost} ecu(s) necessaires{surcharge_note}.")
    previous_owner = terr.owner
    # La branche vassale de x45 est morte (mecanique abandonnee).
    state.sanctuary_territory_ids.discard(terr.id)
    state.submitted_territory_ids.discard(terr.id)
    state.submitted_territory_overlords.pop(terr.id, None)
    state.submitted_territory_created_turns.pop(terr.id, None)
    terr.owner = state.current_player
    regles.refresh_last_stand_bonus_state(state)
    regles.enforce_last_stand_bonus_limits(state)
    elimination_note = ""
    if previous_owner >= 0 and not any(t.owner == previous_owner for t in state.territories):
        regles.mark_eliminated_player_if_human(state, previous_owner)
        regles.refresh_eliminated_human_players(state)
        elimination_note = f" J{previous_owner + 1} est elimine." + regles.transfer_eliminated_player_money(state, previous_owner, state.current_player)
    surcharge_note = f" Base {base_cost} + surcout {surcharge}." if surcharge > 0 else ""
    return _succes(f"{terr.name} corrompu pour {cost} ecu(s).{surcharge_note} Les amenagements restent intacts." + elimination_note)


def financer_revolte(state: GameState, terr: Territory, rng=random) -> AchatResult:
    if terr.owner == state.current_player:
        return _refus("Choisissez un territoire ennemi pour designer la cible de la revolte.")
    if terr.owner < 0:
        return _refus("Impossible de declencher une revolte chez l'ONU.")
    target_player = terr.owner
    if regles.is_commercial_city_player(state, target_player):
        return _refus("Revolte impossible : les Cites Commercantes sont immunisees contre les revoltes.")
    if target_player in state.nation_players:
        return _refus("Revolte impossible : les nations sont immunisees contre les revoltes.")
    owned = [t for t in state.territories if t.owner == target_player]
    if not owned:
        return _refus("Cet ennemi n'a plus de territoire a perdre.")

    revolt_cost = calculate_revolt_cost_for_target_player(state, target_player)
    if not spend_player_money(state, state.current_player, revolt_cost):
        return _refus(f"Pas assez d'ecus pour declencher cette revolte : {revolt_cost} ecu(s) necessaires.")

    lost_count = calculate_revolt_loss_count(len(owned))
    territories_to_transfer = regles.choose_owned_contiguous_block(
        state, target_player, lost_count, rng, exclude_religion_protected=True,
    )
    if not territories_to_transfer:
        state.player_money[state.current_player] += revolt_cost
        return _refus(
            "Revolte impossible : aucune cible valide hors capitale et hors territoire "
            "acquis a la religion nationale de son proprietaire."
        )
    lost_count = len(territories_to_transfer)
    rebel_player, returning_human = regles.allocate_rebel_player(state, rng)
    for territory in territories_to_transfer:
        territory.owner = rebel_player
    regles.refresh_last_stand_bonus_state(state)
    regles.refresh_eliminated_human_players(state)
    elimination_note = ""
    if not any(t.owner == target_player for t in state.territories):
        regles.mark_eliminated_player_if_human(state, target_player)
        elimination_note = f" J{target_player + 1} est elimine." + regles.transfer_eliminated_player_money(state, target_player, state.current_player)
    comeback = "nouveau joueur IA"
    return _succes(
        f"Revolte financee chez J{target_player + 1} pour {revolt_cost} ecu(s): "
        f"{lost_count}/{len(owned)} territoire(s) passent a J{rebel_player + 1} ({comeback})." + elimination_note
    )


# ----------------------------------------------------------------------
# Achats : ponts
# ----------------------------------------------------------------------

def pont_offert_par_la_forge(state: GameState, territory_a: int, territory_b: int) -> bool:
    """Forge de Dedale : les ponts dont une extremite est le territoire de la
    merveille sont geres gratuitement par son controleur (science non requise)."""
    forge_id = state.wonder_territories.get("daedalus_forge")
    if forge_id is None or forge_id not in (territory_a, territory_b):
        return False
    return regles.get_wonder_controller(state, "daedalus_forge") == state.current_player


def get_missile_tier(state: GameState, player: int) -> int:
    """La puissance du missile ouverte a ce joueur par sa science.

    Le palier est une regle du jeu, partagee avec la doctrine des IA :
    cf. ``regles.get_player_missile_tier``.
    """
    return regles.get_player_missile_tier(state, player)


def calculate_missile_regiment_losses(regiments: int, tier: int) -> int:
    """Combien de regiments le missile emporte, sans jamais vider la place.

    Aux deux premiers paliers il en aneantit la moitie, arrondie au
    superieur ; au troisieme il ne laisse qu'un survivant. Dans tous les
    cas il reste au moins un regiment : un missile ne conquiert pas.
    """
    regiments = max(0, int(regiments))
    survivors_max = max(0, regiments - 1)
    if tier >= 3:
        return survivors_max
    return min(survivors_max, math.ceil(regiments / 2))


@dataclass
class MissileStrike:
    """Le detail d'un tir de missile, pour le raconter et l'animer.

    ``src_id`` est le territoire du tireur le plus proche de la cible : la
    regle ne s'en sert pas (la portee se mesure depuis toutes ses terres),
    il ne sert qu'a donner une origine au trait qui traverse la carte.
    """

    player: int
    dst_id: int
    tier: int
    regiments_before: int
    regiments_after: int
    losses: int
    src_id: Optional[int] = None
    destroyed: List[str] = field(default_factory=list)
    message: str = ""


def tirer_missile_detaille(
    state: GameState, terr: Territory, cell_width: float, cell_height: float,
) -> Tuple[AchatResult, Optional[MissileStrike]]:
    """Tire un missile sur un territoire adverse, et raconte le tir.

    La science commande la portee et la puissance (cf. ``get_missile_tier``).
    Le missile ne prend jamais le territoire : il ne fait que detruire. Le
    second element n'existe qu'en cas de tir reussi ; il porte de quoi
    rejouer la frappe cote client.
    """
    player = state.current_player
    science = regles.get_player_science(state, player)
    tier = get_missile_tier(state, player)
    if tier <= 0:
        return _refus(
            f"Missile verrouille : {SCIENCE_MISSILE_THRESHOLD} points de science requis "
            f"(vous en avez {science})."
        ), None
    if terr.owner == player:
        return _refus("Un missile se tire sur un territoire adverse, pas sur le sien."), None
    if terr.owner >= 0 and regles.player_controls_wonder(state, terr.owner, "selene_dome"):
        return _refus(
            f"Missile intercepte : le {regles.get_wonder_name('selene_dome')} protege "
            f"tous les territoires de J{terr.owner + 1}."
        ), None

    if tier == 1 and not regles.is_territory_adjacent_to_player(state, terr.id, player):
        return _refus(
            f"{terr.name} est hors de portee : a {SCIENCE_MISSILE_THRESHOLD} points de science, "
            f"le missile ne frappe qu'un territoire voisin d'un des votres. "
            f"Il faut {SCIENCE_MISSILE_RANGE_THRESHOLD} points pour tirer plus loin."
        ), None
    if tier == 2:
        distance = regles.get_distance_to_nearest_owned_territory(
            state, terr.id, player, cell_width, cell_height,
        )
        if distance is None or distance > MISSILE_RANGE_PX:
            return _refus(
                f"{terr.name} est hors de portee : le missile porte a "
                f"{MISSILE_RANGE_PX:.0f} pixels de vos terres. "
                f"Il faut {SCIENCE_MISSILE_TOTAL_THRESHOLD} points de science pour frapper partout."
            ), None

    if not spend_player_money(state, player, MISSILE_COST):
        return _refus(f"Pas assez d'ecus pour tirer un missile : {MISSILE_COST} requis."), None

    source = regles.get_nearest_owned_territory(
        state, terr.id, player, cell_width, cell_height,
    )
    regiments_before = max(0, int(terr.regiments))
    losses = calculate_missile_regiment_losses(regiments_before, tier)
    terr.regiments = regiments_before - losses
    strike = MissileStrike(
        player=player,
        dst_id=terr.id,
        tier=tier,
        regiments_before=regiments_before,
        regiments_after=terr.regiments,
        losses=losses,
        src_id=source.id if source is not None else None,
    )

    if tier < 3:
        strike.message = (
            f"Missile tire sur {terr.name} pour {MISSILE_COST} ecu(s) : "
            f"{losses} regiment(s) aneanti(s) sur {regiments_before}, il en reste {terr.regiments}."
        )
        return _succes(strike.message), strike

    strike.destroyed = regles.destroy_all_amenities(state, terr.id)
    damage_note = (
        " Rase : " + ", ".join(strike.destroyed) + "." if strike.destroyed
        else " Aucun amenagement a raser."
    )
    strike.message = (
        f"Missile a pleine puissance sur {terr.name} pour {MISSILE_COST} ecu(s) : "
        f"{losses} regiment(s) aneanti(s) sur {regiments_before}, il n'en reste qu'{terr.regiments}."
        + damage_note
    )
    return _succes(strike.message), strike


def tirer_missile(
    state: GameState, terr: Territory, cell_width: float, cell_height: float,
) -> AchatResult:
    """Tire un missile et n'en retourne que le verdict de boutique."""
    result, _strike = tirer_missile_detaille(state, terr, cell_width, cell_height)
    return result


def construire_pont(
    state: GameState, territory_a: int, territory_b: int,
    cell_width: float, cell_height: float,
) -> AchatResult:
    gratuit = pont_offert_par_la_forge(state, territory_a, territory_b)
    if not gratuit and regles.get_player_science(state, state.current_player) < SCIENCE_BRIDGE_THRESHOLD:
        return _refus(f"Ponts verrouilles : {SCIENCE_BRIDGE_THRESHOLD} points de science requis.")
    if territory_a == territory_b:
        return _refus("Choisissez deux territoires differents.")
    # Un pont se construit depuis chez soi : le joueur doit controler au
    # moins une des deux extremites (pas forcement les deux).
    if (state.territories[territory_a].owner != state.current_player
            and state.territories[territory_b].owner != state.current_player):
        return _refus("Pont impossible : vous devez controler au moins un des deux territoires.")
    key = tuple(sorted((territory_a, territory_b)))
    if key in state.bridge_links or territory_b in state.territories[territory_a].neighbors:
        return _refus("Ces deux territoires sont deja directement relies.")
    points = regles.find_bridge_connection_points(state, key[0], key[1], cell_width, cell_height)
    if points is None:
        return _refus("Pont impossible : distance superieure a 2 cm, absence d'eau ou passage au-dessus d'un territoire.")
    if not gratuit and not spend_player_money(state, state.current_player, BUILD_BRIDGE_COST):
        return _refus(f"Pont trop cher : {BUILD_BRIDGE_COST} ecus requis.")
    regles.add_bridge(state, key, points)
    cout = "gratuitement (Forge de Dedale)" if gratuit else f"pour {BUILD_BRIDGE_COST} ecus"
    message = (
        f"J{state.current_player + 1} construit un pont entre {state.territories[key[0]].name} "
        f"et {state.territories[key[1]].name} {cout}."
    )
    regles.record_major_event(state, message)
    regles.record_replay_snapshot(state, message, force=True)
    return _succes(message)


def detruire_pont(state: GameState, territory_a: int, territory_b: int) -> AchatResult:
    gratuit = pont_offert_par_la_forge(state, territory_a, territory_b)
    if not gratuit and regles.get_player_science(state, state.current_player) < SCIENCE_BRIDGE_THRESHOLD:
        return _refus(f"Ponts verrouilles : {SCIENCE_BRIDGE_THRESHOLD} points de science requis.")
    key = tuple(sorted((territory_a, territory_b)))
    if key not in state.bridge_links:
        return _refus("Aucun pont ne relie ces deux territoires.")
    if not gratuit and not spend_player_money(state, state.current_player, DESTROY_BRIDGE_COST):
        return _refus(f"Destruction trop chere : {DESTROY_BRIDGE_COST} ecus requis.")
    remove_bridge(state, key)
    cout = "gratuitement (Forge de Dedale)" if gratuit else f"pour {DESTROY_BRIDGE_COST} ecus"
    message = (
        f"J{state.current_player + 1} detruit le pont entre {state.territories[key[0]].name} "
        f"et {state.territories[key[1]].name} {cout}."
    )
    regles.record_major_event(state, message)
    regles.record_replay_snapshot(state, message, force=True)
    return _succes(message)


# ----------------------------------------------------------------------
# Achats : alliances
# ----------------------------------------------------------------------

def acheter_alliance(state: GameState, terr: Territory) -> AchatResult:
    target_player = terr.owner
    exclusive_ally = regles.get_commercial_city_wonder_ally(state)
    if regles.is_commercial_city_player(state, target_player) and exclusive_ally is not None:
        return _refus(
            f"Alliance impossible : la Cite commercante est exclusivement alliee a J{exclusive_ally + 1} grace au Palais du Pacte d'Or."
        )
    if target_player == state.current_player:
        return _refus("Choisissez un territoire du joueur IA avec qui conclure l'alliance defensive.")
    if target_player < 0 or regles.is_sanctuary_territory(state, terr.id):
        return _refus("Impossible d'acheter une alliance avec l'ONU. Meme la fiction a des limites.")
    if not regles.is_ai_player(state, target_player):
        return _refus("Alliance impossible : la cible doit etre un joueur IA, pas un joueur humain.")
    if not regles.is_human_player_id(state, state.current_player):
        return _refus("Seul un joueur humain peut acheter une alliance.")
    cost = get_alliance_cost(state, target_player)
    if cost <= 0:
        return _refus("Alliance impossible : ce joueur IA ne controle plus aucun territoire.")
    if not spend_player_money(state, state.current_player, cost):
        return _refus(f"Alliance defensive trop chere : {cost} ecu(s) necessaires.")
    expires_turn = state.turn + regles.ALLIANCE_DURATION_TURNS
    state.active_alliances[(state.current_player, target_player)] = expires_turn
    state.alliance_start_turns[(state.current_player, target_player)] = state.turn
    event_message = f"Alliance defensive conclue avec J{target_player + 1} pour {cost} ecu(s). J{target_player + 1} n'attaquera plus J{state.current_player + 1} jusqu'au tour {expires_turn}."
    regles.record_major_event(state, event_message)
    return _succes(event_message)


def acheter_alliance_offensive(state: GameState, ai_player: int, target_player: int) -> AchatResult:
    if not regles.is_human_player_id(state, state.current_player):
        return _refus("Seul un joueur humain peut acheter une alliance offensive.")
    if not regles.is_ai_player(state, ai_player):
        return _refus("Alliance offensive impossible : l'allie doit etre un joueur IA.")
    exclusive_ally = regles.get_commercial_city_wonder_ally(state)
    if regles.is_commercial_city_player(state, ai_player) and exclusive_ally is not None:
        return _refus(f"Alliance offensive impossible : la Cite commercante est exclusivement alliee a J{exclusive_ally + 1}.")
    if target_player < 0:
        return _refus("Cible invalide : l'ONU ne compte pas comme joueur cible pour cette alliance.")
    if target_player == state.current_player:
        return _refus("Cible invalide : payer une IA pour vous attaquer serait audacieux, mais non.")
    if target_player == ai_player:
        return _refus("Cible invalide : l'allie offensif ne va pas s'attaquer lui-meme.")
    if not any(t.owner == ai_player for t in state.territories):
        return _refus("Alliance offensive impossible : l'allie IA n'a plus de territoire.")
    if not any(t.owner == target_player for t in state.territories):
        return _refus("Alliance offensive impossible : la cible n'a plus de territoire.")

    cost = get_offensive_alliance_cost(state, ai_player)
    if not spend_player_money(state, state.current_player, cost):
        return _refus(f"Alliance offensive trop chere : {cost} ecu(s) necessaires.")

    expires_turn = state.turn + regles.ALLIANCE_DURATION_TURNS
    state.active_offensive_alliances[(state.current_player, ai_player)] = (target_player, expires_turn)
    state.offensive_alliance_start_turns[(state.current_player, ai_player)] = state.turn
    broken_ai_alliance_note = break_ai_alliance_due_to_offensive_contract(state, ai_player, target_player)
    event_message = f"Alliance offensive conclue avec J{ai_player + 1} pour {cost} ecu(s). J{ai_player + 1} cible J{target_player + 1} jusqu'au tour {expires_turn}."
    if broken_ai_alliance_note:
        event_message += " " + broken_ai_alliance_note
    regles.record_major_event(state, event_message)
    return _succes(event_message)


# ----------------------------------------------------------------------
# Achats : manipulation de l'ONU et paradis fiscaux
# ----------------------------------------------------------------------

def figer_territoire(state: GameState, terr: Territory) -> AchatResult:
    if not can_player_manipulate_onu(state, state.current_player):
        return _refus(f"Figement impossible : il faut etre en paradis fiscal ou avoir {SCIENCE_ONU_MANIPULATION_THRESHOLD} points de science.")
    if regles.is_sanctuary_territory(state, terr.id) or terr.owner == state.onu_player_id:
        return _refus("Ce territoire est deja un territoire ONU. Meme l'ONU ne peut pas etre plus ONU.")
    if regles.is_last_stand_bonus_territory(state, terr.id):
        return _refus("Figement impossible : une capitale en paradis fiscal ne peut pas devenir territoire ONU.")
    if regles.is_regular_capital_territory(state, terr.id):
        return _refus("Figement impossible : une capitale de joueur ne peut pas devenir territoire ONU.")
    if terr.id in state.golden_territory_ids:
        return _refus("Figement impossible : un territoire dore ne peut jamais devenir territoire ONU.")
    cost = calculate_onu_manipulation_cost(state, terr)
    if not spend_player_money(state, state.current_player, cost):
        return _refus(f"Figement trop cher : {cost} ecu(s) necessaires.")
    previous_owner = terr.owner
    previous_regiments = terr.regiments
    regles.convert_territory_to_sanctuary(state, terr.id, regiments=previous_regiments)
    regles.refresh_last_stand_bonus_state(state)
    regles.refresh_eliminated_human_players(state)
    elimination_note = ""
    if previous_owner >= 0 and not any(t.owner == previous_owner for t in state.territories):
        regles.mark_eliminated_player_if_human(state, previous_owner)
        regles.refresh_eliminated_human_players(state)
        elimination_note = f" J{previous_owner + 1} n'a plus de territoire."
    return _succes(
        f"{terr.name} fige en territoire ONU pour {cost} ecu(s) ({max(1, previous_regiments)} regiment(s) x {ONU_MANIPULATION_COST_PER_REGIMENT})."
        + elimination_note
    )


def liberer_sanctuaire(state: GameState, terr: Territory, rng=random) -> AchatResult:
    if not can_player_manipulate_onu(state, state.current_player):
        return _refus(f"Liberation impossible : il faut etre en paradis fiscal ou avoir {SCIENCE_ONU_MANIPULATION_THRESHOLD} points de science.")
    if not regles.is_sanctuary_territory(state, terr.id) and terr.owner != state.onu_player_id:
        return _refus("Liberation impossible : ce territoire n'est pas un territoire ONU.")
    cost = calculate_onu_manipulation_cost(state, terr)
    if not spend_player_money(state, state.current_player, cost):
        return _refus(f"Liberation trop chere : {cost} ecu(s) necessaires.")
    new_owner = get_random_ai_recipient_for_released_sanctuary(
        state, excluded_players={state.current_player}, rng=rng,
    )
    state.sanctuary_territory_ids.discard(terr.id)
    state.submitted_territory_ids.discard(terr.id)
    state.submitted_territory_overlords.pop(terr.id, None)
    state.submitted_territory_created_turns.pop(terr.id, None)
    terr.owner = new_owner
    terr.reinforcement_bonus = 1
    terr.regiments = max(1, terr.regiments)
    regles.refresh_last_stand_bonus_state(state)
    regles.refresh_eliminated_human_players(state)
    return _succes(f"{terr.name} libere de l'ONU pour {cost} ecu(s) et attribue a l'IA J{new_owner + 1}.")


def _integration_scientifique_paradis_fiscal(state: GameState, terr: Territory, ai_player: int) -> AchatResult:
    human_player = state.current_player
    if not can_player_integrate_tax_haven_by_science(state, human_player):
        return _refus(f"Integration scientifique impossible : {SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD} points de science requis.")
    terr.owner = human_player
    regles.remove_tax_haven_capital(state, ai_player, terr.id)
    if not any(territory.owner == ai_player for territory in state.territories):
        cleanup_removed_ai_player(state, ai_player)
    regles.refresh_last_stand_bonus_state(state)
    regles.refresh_eliminated_human_players(state)
    return _succes(
        f"Integration technologique : J{human_player + 1} integre {terr.name} sans cout ni penalite. Le territoire perd son statut de paradis fiscal."
    )


def _integration_paradis_fiscal(state: GameState, terr: Territory, ai_player: int) -> AchatResult:
    human_player = state.current_player
    cost = TAX_HAVEN_INTEGRATION_COST
    if not spend_player_money(state, human_player, cost):
        return _refus(f"Integration trop chere : {cost} ecu(s) necessaires.")

    terr.owner = human_player
    regles.remove_tax_haven_capital(state, ai_player, terr.id)
    regles.add_tax_haven_capital(state, human_player, terr.id)
    if not any(territory.owner == ai_player for territory in state.territories):
        cleanup_removed_ai_player(state, ai_player)
    regles.refresh_last_stand_bonus_state(state)
    regles.refresh_eliminated_human_players(state)

    return _succes(
        f"Integration conclue : J{human_player + 1} paie {cost} ecu(s) et prend le controle de la capitale x10 {terr.name} de J{ai_player + 1}."
    )


def association_paradis_fiscal(state: GameState, terr: Territory, rng=random) -> AchatResult:
    human_player = state.current_player
    ai_player = terr.owner
    if not regles.is_human_player_id(state, human_player):
        return _refus("Seul un joueur humain peut utiliser cette option de paradis fiscal.")
    if ai_player == human_player:
        return _refus("Choisissez une capitale IA en paradis fiscal, pas votre propre territoire.")
    if ai_player < 0 or regles.is_sanctuary_territory(state, terr.id):
        return _refus("Operation impossible avec l'ONU. La bureaucratie gagne encore.")
    if not regles.is_ai_player(state, ai_player):
        return _refus("Operation impossible : la capitale cible doit appartenir a un joueur IA.")
    if ai_player not in state.last_stand_bonus_players or terr.id not in regles.get_player_tax_haven_capital_ids(state, ai_player):
        return _refus("Operation impossible : ce territoire n'est pas la capitale IA en paradis fiscal.")

    if can_player_integrate_tax_haven_by_science(state, human_player):
        return _integration_scientifique_paradis_fiscal(state, terr, ai_player)

    if human_player in state.last_stand_bonus_players:
        return _integration_paradis_fiscal(state, terr, ai_player)

    absorbed_territories = [territory for territory in state.territories if territory.owner == ai_player]
    if not absorbed_territories:
        return _refus("Association impossible : ce joueur IA n'a plus de territoire actif.")

    previous_ai_money = state.player_money.get(ai_player, 0)
    regles.ensure_player_economy(state, human_player)
    state.player_money[human_player] += previous_ai_money
    state.player_money[ai_player] = 0

    for territory in absorbed_territories:
        territory.owner = human_player

    regles.remove_tax_haven_player(state, ai_player)
    cleanup_removed_ai_player(state, ai_player)

    regles.add_tax_haven_capital(state, human_player, terr.id)

    owned_after_association = [territory for territory in state.territories if territory.owner == human_player]
    loss_count = min(max(0, len(owned_after_association) // 4), max(0, len(owned_after_association) - 1))
    lost_territories: List[Territory] = []
    loss_receiver: Optional[int] = None
    if loss_count > 0:
        loss_candidates = [territory.id for territory in owned_after_association if territory.id != terr.id]
        # On privilegie un bloc contigu sans jamais sacrifier la nouvelle capitale.
        picked = [
            territory for territory in regles.choose_owned_contiguous_block(state, human_player, loss_count, rng)
            if territory.id != terr.id
        ]
        if len(picked) < loss_count:
            picked_ids = {territory.id for territory in picked}
            remaining = [tid for tid in loss_candidates if tid not in picked_ids]
            rng.shuffle(remaining)
            picked.extend(state.territories[tid] for tid in remaining[: loss_count - len(picked)])
        lost_territories = picked[:loss_count]
        loss_receiver, returning_human = regles.allocate_rebel_player(state, rng)
        for territory in lost_territories:
            territory.owner = loss_receiver

    regles.refresh_last_stand_bonus_state(state)
    regles.refresh_eliminated_human_players(state)
    comeback = "nouveau joueur IA"
    loss_note = (
        f" J{human_player + 1} perd {len(lost_territories)} territoire(s) sur {len(owned_after_association)} au profit de J{loss_receiver + 1} ({comeback})."
        if loss_receiver is not None
        else " Aucun territoire perdu : empire trop petit pour prelever un quart sans detruire la capitale."
    )
    money_note = f" Tresor IA recupere : {previous_ai_money} ecu(s)." if previous_ai_money > 0 else ""
    return _succes(
        f"Association conclue : J{human_player + 1} absorbe J{ai_player + 1}, {terr.name} devient sa capitale x10."
        + loss_note
        + money_note
    )
