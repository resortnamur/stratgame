"""Etat de partie pur et serialisable.

Ce module reproduit fidelement le format de sauvegarde de x45.py :
- ``GameState.from_payload``  <->  ``GraphicalGame.apply_saved_game_state``
  (partie chargement uniquement, sans les sanitisations de regles)
- ``GameState.to_payload``    <->  ``GraphicalGame.build_game_payload``

Regles de fidelite :
- Les champs abandonnes par x45 au chargement (vassaux, guerre froide,
  colonisation, diplomatie nationale) sont abandonnes ici de la meme facon.
- Les cellules et voisins des territoires sont recalcules depuis la grille,
  comme dans ``apply_saved_map``.
- Les cles heritees (industry_territory_ids, industry_capture_counts) sont
  emises pour rester compatibles avec les anciennes versions du jeu.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

SAVE_SCHEMA_VERSION = 13
ALLIANCE_DURATION_TURNS = 10
MAX_REPLAY_SNAPSHOTS = 1200
DEFAULT_ROWS = 144
DEFAULT_COLS = 180

Cell = Tuple[int, int]
LinkKey = Tuple[int, int]


def normalize_difficulty_level(raw_value: Any) -> str:
    if isinstance(raw_value, str):
        value = raw_value.strip().lower().replace(" ", "_")
        if value == "chaos":
            return "chaos"
        if value in ("gouvernement_mondial", "world_government"):
            return "gouvernement_mondial"
    return "normal"


def sanitize_major_event_modal(modal: object) -> Optional[dict]:
    if not isinstance(modal, dict):
        return None
    title = " ".join(str(modal.get("title", "Evenement important")).split())
    raw_events = modal.get("events", [])
    if not isinstance(raw_events, list):
        return None
    events = [" ".join(str(event).split()) for event in raw_events if str(event).strip()]
    if not events:
        return None
    return {"title": title or "Evenement important", "events": events[-20:]}


def normalize_tax_haven_capital_payload(raw_payload: Any) -> Dict[int, Set[int]]:
    """Restaure les capitales paradis fiscal depuis une sauvegarde ancienne ou nouvelle."""
    normalized: Dict[int, Set[int]] = {}
    if not isinstance(raw_payload, dict):
        return normalized
    for raw_player, raw_value in raw_payload.items():
        try:
            player = int(raw_player)
        except (TypeError, ValueError):
            continue
        if isinstance(raw_value, (list, tuple, set)):
            values = raw_value
        else:
            values = [raw_value]
        capital_ids: Set[int] = set()
        for raw_tid in values:
            try:
                capital_ids.add(int(raw_tid))
            except (TypeError, ValueError):
                continue
        if capital_ids:
            normalized[player] = capital_ids
    return normalized


@dataclass
class Territory:
    id: int
    name: str
    owner: int
    regiments: int
    cells: List[Cell] = field(default_factory=list)
    neighbors: List[int] = field(default_factory=list)
    reinforcement_bonus: int = 1


@dataclass
class GameState:
    """Etat complet d'une partie, sans aucune dependance a pygame."""

    # --- Carte ---
    map_mode: str = "standard"
    rows: int = DEFAULT_ROWS
    cols: int = DEFAULT_COLS
    grid_territory: List[List[int]] = field(default_factory=list)
    territories: List[Territory] = field(default_factory=list)
    territory_continent: Dict[int, int] = field(default_factory=dict)
    terre_links: List[LinkKey] = field(default_factory=list)
    terre_link_points: Dict[LinkKey, Tuple[Cell, Cell]] = field(default_factory=dict)
    bridge_links: Set[LinkKey] = field(default_factory=set)
    fragile_bridge_links: Set[LinkKey] = field(default_factory=set)
    bridge_link_points: Dict[LinkKey, Tuple[Cell, Cell]] = field(default_factory=dict)
    # Geometrie des expeditions maritimes (plans d'eau connexes, cotes par
    # mer, distances entre territoires) : recalculee a la demande et videe
    # des que la grille change. Transient, jamais serialise.
    expedition_geometry_cache: dict = field(default_factory=dict)

    # --- Joueurs et configuration ---
    num_players: int = 0
    initial_num_players: int = 0
    ai_player_count: int = 0
    initial_ai_player_count: int = 0
    difficulty_level: str = "normal"
    tribes_mode: bool = False
    # Version simplifiee : partie uniquement basee sur le combat (ni achats,
    # ni argent, science, culture, capitales, nations, religions, paradis
    # fiscaux, cites commercantes). Voir regles.is_simple_mode.
    simple_mode: bool = False
    base_ai_players: Set[int] = field(default_factory=set)
    auto_controlled_players: Set[int] = field(default_factory=set)
    human_controlled_players: Set[int] = field(default_factory=set)
    eliminated_human_players: Set[int] = field(default_factory=set)
    ai_personalities: Dict[int, str] = field(default_factory=dict)
    ai_current_behavior: Dict[int, str] = field(default_factory=dict)
    # Dernier tour ou chaque IA a tire un missile : c'est ce qui tient le
    # delai de rechargement de sa doctrine (cf. regles.AI_MISSILE_COOLDOWN_TURNS).
    ai_last_missile_turns: Dict[int, int] = field(default_factory=dict)
    ai_speed_mode: str = "normal"
    fast_ai_movements: bool = False

    # --- Cites commerciales, nations, unions ---
    commercial_city_players: Set[int] = field(default_factory=set)
    commercial_city_capital_ids: Dict[int, int] = field(default_factory=dict)
    player_capital_ids: Dict[int, int] = field(default_factory=dict)
    pending_commercial_city_spawns: int = 0
    nation_players: Set[int] = field(default_factory=set)
    nation_qualification_start_turns: Dict[int, int] = field(default_factory=dict)
    nation_capital_loss_start_turns: Dict[int, int] = field(default_factory=dict)
    submitted_territory_ids: Set[int] = field(default_factory=set)
    submitted_territory_overlords: Dict[int, int] = field(default_factory=dict)
    submitted_territory_created_turns: Dict[int, int] = field(default_factory=dict)
    integrated_submitted_territories: Dict[int, Set[int]] = field(default_factory=dict)
    union_members: Dict[int, Set[int]] = field(default_factory=dict)
    union_original_territories: Dict[int, Set[int]] = field(default_factory=dict)

    # --- Duel final ---
    final_duel_active: bool = False
    final_duel_champions: Optional[Tuple[int, ...]] = None
    final_duel_alliances: Dict[int, int] = field(default_factory=dict)
    final_duel_pending_winner: Optional[int] = None

    # --- Deroulement de la partie ---
    current_player: int = 0
    turn: int = 1
    turn_phase: str = "attack"
    turn_move_count: int = 0
    last_empire_event_turn: int = 0
    phase: str = "setup"

    # --- Territoires speciaux ---
    super_territory_ids: Set[int] = field(default_factory=set)
    ultra_super_territory_ids: Set[int] = field(default_factory=set)
    golden_territory_ids: Set[int] = field(default_factory=set)
    sanctuary_territory_ids: Set[int] = field(default_factory=set)
    onu_player_id: int = -2

    # --- Economie et structures ---
    player_money: Dict[int, int] = field(default_factory=dict)
    precious_mineral_mine_ids: Set[int] = field(default_factory=set)
    # Tour d'apparition des ressources tardives (+5 et mines), par
    # territoire : elles s'epuisent au bout de vingt tours et reapparaissent
    # ailleurs (cf. regles.rotate_expired_late_resources).
    bonus_5_spawn_turns: Dict[int, int] = field(default_factory=dict)
    precious_mineral_mine_spawn_turns: Dict[int, int] = field(default_factory=dict)
    fortress_territory_ids: Set[int] = field(default_factory=set)
    fortress_capture_counts: Dict[int, int] = field(default_factory=dict)
    factory_territory_ids: Set[int] = field(default_factory=set)
    airport_territory_ids: Set[int] = field(default_factory=set)
    port_territory_ids: Set[int] = field(default_factory=set)
    industrial_capture_counts: Dict[int, int] = field(default_factory=dict)
    cultural_center_ages: Dict[int, List[int]] = field(default_factory=dict)
    cultural_capture_counts: Dict[int, int] = field(default_factory=dict)
    # Un centre culturel detruit laisse une ruine, que rien ne detruit jamais.
    ruin_territory_ids: Set[int] = field(default_factory=set)
    university_territory_ids: Set[int] = field(default_factory=set)
    university_capture_counts: Dict[int, int] = field(default_factory=dict)
    university_ages: Dict[int, int] = field(default_factory=dict)
    temple_territory_ids: Set[int] = field(default_factory=set)
    temple_capture_counts: Dict[int, int] = field(default_factory=dict)

    # --- Religion, science, culture, merveilles ---
    religion_founders: Dict[int, int] = field(default_factory=dict)
    religion_foundation_turns: Dict[int, int] = field(default_factory=dict)
    religion_last_spread_turns: Dict[int, int] = field(default_factory=dict)
    religion_holy_sites: Dict[int, int] = field(default_factory=dict)
    religious_influence: Dict[int, int] = field(default_factory=dict)
    player_science: Dict[int, int] = field(default_factory=dict)
    culture_expansion_milestones: Dict[int, int] = field(default_factory=dict)
    wonder_territories: Dict[str, int] = field(default_factory=dict)
    # Le joueur lie au Serment d'Orvane : allie definitif de qui tient la
    # merveille. Un seul a la fois ; a sa mort, le suivant prend sa place.
    eternal_ally_player: Optional[int] = None
    # A qui il a prete serment : si la merveille change de mains, le
    # serment tombe au lieu de suivre son nouveau proprietaire.
    eternal_ally_patron: Optional[int] = None
    # Les paliers de victoire deja franchis, dans l'ordre : chacun ne se
    # franchit qu'une fois et vaut un point de victoire a son auteur.
    victory_milestones: List[dict] = field(default_factory=list)
    # Registre "une merveille par joueur et par tour" : memoire de session
    # uniquement, volontairement absent des sauvegardes (parite du format
    # avec x45-original).
    wonder_construction_turns: Dict[int, int] = field(default_factory=dict)

    # --- Paradis fiscaux ---
    last_stand_bonus_players: Set[int] = field(default_factory=set)
    last_stand_bonus_territory: Dict[int, Set[int]] = field(default_factory=dict)
    tax_haven_turn_start_territory_counts: Dict[int, int] = field(default_factory=dict)

    # --- Alliances ---
    active_alliances: Dict[LinkKey, int] = field(default_factory=dict)
    alliance_start_turns: Dict[LinkKey, int] = field(default_factory=dict)
    active_ai_alliances: Dict[LinkKey, int] = field(default_factory=dict)
    ai_alliance_start_turns: Dict[LinkKey, int] = field(default_factory=dict)
    active_offensive_alliances: Dict[LinkKey, Tuple[int, int]] = field(default_factory=dict)
    offensive_alliance_start_turns: Dict[LinkKey, int] = field(default_factory=dict)

    # --- Evenements et replay ---
    # Transient (jamais serialise) : vrai pendant les evenements entre deux
    # tours globaux, comme l'attribut homonyme de x45. Les evenements majeurs
    # ne creent alors pas de modale immediate pour le joueur courant.
    collecting_between_turn_events: bool = False
    recent_major_events: List[str] = field(default_factory=list)
    major_event_modal: Optional[dict] = None
    major_event_modal_queue: List[dict] = field(default_factory=list)
    pending_major_events_for_humans: Dict[int, List[str]] = field(default_factory=dict)
    replay_history: List[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Geometrie de la carte (repris de x45 : neighbors4 & co)
    # ------------------------------------------------------------------

    def neighbors4(self, r: int, c: int) -> Iterator[Cell]:
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                yield nr, nc

    def toroidal_neighbors4(self, r: int, c: int) -> Iterator[Cell]:
        yielded = set()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr = (r + dr) % self.rows
            nc = (c + dc) % self.cols
            if (nr, nc) not in yielded:
                yielded.add((nr, nc))
                yield nr, nc

    def iter_adjacency_neighbors(self, r: int, c: int) -> Iterator[Cell]:
        if self.map_mode == "custom":
            yield from self.toroidal_neighbors4(r, c)
        else:
            yield from self.neighbors4(r, c)

    def invalidate_expedition_geometry_cache(self) -> None:
        """Oublie les plans d'eau et routes maritimes memorises.

        A appeler des que la grille change (editeur de cartes, chargement) :
        la geometrie des expeditions maritimes en depend entierement.
        """
        self.expedition_geometry_cache = {}

    def rebuild_cells_from_grid(self) -> None:
        cells_by_tid: Dict[int, List[Cell]] = {terr.id: [] for terr in self.territories}
        for r in range(self.rows):
            for c in range(self.cols):
                tid = self.grid_territory[r][c]
                if tid in cells_by_tid:
                    cells_by_tid[tid].append((r, c))
        for terr in self.territories:
            terr.cells = cells_by_tid.get(terr.id, [])
        self.invalidate_expedition_geometry_cache()

    def recompute_neighbors_from_grid(self) -> None:
        self.invalidate_expedition_geometry_cache()
        if not self.territories:
            return
        valid_ids = {terr.id for terr in self.territories}
        neighbor_sets: Dict[int, Set[int]] = {terr.id: set() for terr in self.territories}
        for r in range(self.rows):
            for c in range(self.cols):
                tid = self.grid_territory[r][c]
                if tid not in valid_ids:
                    continue
                for nr, nc in self.iter_adjacency_neighbors(r, c):
                    ntid = self.grid_territory[nr][nc]
                    if ntid in valid_ids and ntid != tid:
                        neighbor_sets[tid].add(ntid)
        for terr in self.territories:
            terr.neighbors = sorted(neighbor_sets[terr.id])
        self.apply_terre_links_to_neighbors()
        self.apply_bridge_links_to_neighbors()

    def apply_terre_links_to_neighbors(self) -> None:
        if self.map_mode != "terre":
            return
        for a, b in self.terre_links:
            if 0 <= a < len(self.territories) and 0 <= b < len(self.territories) and a != b:
                self.territories[a].neighbors = sorted(set(self.territories[a].neighbors) | {b})
                self.territories[b].neighbors = sorted(set(self.territories[b].neighbors) | {a})

    def apply_bridge_links_to_neighbors(self) -> None:
        for a, b in self.bridge_links:
            if 0 <= a < len(self.territories) and 0 <= b < len(self.territories) and a != b:
                self.territories[a].neighbors = sorted(set(self.territories[a].neighbors) | {b})
                self.territories[b].neighbors = sorted(set(self.territories[b].neighbors) | {a})

    def rebuild_terre_continents_from_layout(self) -> None:
        continent_ids: Dict[int, int] = {}
        next_continent = 0
        for terr in self.territories:
            if terr.id in continent_ids:
                continue
            stack = [terr.id]
            continent_ids[terr.id] = next_continent
            while stack:
                current = stack.pop()
                for neighbor_id in self.territories[current].neighbors:
                    if neighbor_id in continent_ids:
                        continue
                    shared_border = False
                    current_cells = set(self.territories[current].cells)
                    for r, c in self.territories[neighbor_id].cells:
                        if any((nr, nc) in current_cells for nr, nc in self.neighbors4(r, c)):
                            shared_border = True
                            break
                    if shared_border:
                        continent_ids[neighbor_id] = next_continent
                        stack.append(neighbor_id)
            next_continent += 1
        self.territory_continent = continent_ids

    # ------------------------------------------------------------------
    # Requetes utilisees par la serialisation
    # ------------------------------------------------------------------

    def get_commercial_city_capital_id(self, player: int) -> Optional[int]:
        capital_id = self.commercial_city_capital_ids.get(player)
        if capital_id is not None:
            if 0 <= capital_id < len(self.territories) and self.territories[capital_id].owner == player:
                return capital_id
            return None
        owned = sorted(terr.id for terr in self.territories if terr.owner == player)
        if not owned:
            return None
        # Compatibilite anciennes sauvegardes : meme repli que x45, sans mise en cache.
        return owned[0]

    def get_player_tax_haven_capital_ids(self, player: int) -> Set[int]:
        if player in self.commercial_city_players:
            capital_id = self.get_commercial_city_capital_id(player)
            return {capital_id} if capital_id is not None else set()
        raw_value = self.last_stand_bonus_territory.get(player, set())
        if isinstance(raw_value, set):
            return set(raw_value)
        if isinstance(raw_value, (list, tuple)):
            return {int(tid) for tid in raw_value}
        if raw_value is None:
            return set()
        return {int(raw_value)}

    # ------------------------------------------------------------------
    # Chargement (miroir de apply_saved_map + apply_saved_game_state)
    # ------------------------------------------------------------------

    @classmethod
    def from_payload(cls, payload: dict) -> "GameState":
        state = cls()
        state._load_map(payload)
        state._load_game(payload)
        return state

    @classmethod
    def from_map_payload(cls, payload: dict) -> "GameState":
        """Charge une carte seule (cartes_sauvegardees/*.json), sans partie.

        L'etat reste en phase "setup" : c'est le point de depart de
        ``mise_en_place.nouvelle_partie``.
        """
        state = cls()
        state._load_map(payload)
        return state

    def _load_map(self, payload: dict) -> None:
        rows = payload.get("rows")
        cols = payload.get("cols")
        territories_data = payload.get("territories")
        grid = payload.get("grid_territory")

        if not isinstance(rows, int) or not isinstance(cols, int) or rows <= 0 or cols <= 0:
            raise ValueError("Format de carte incompatible : dimensions invalides.")
        self.rows = rows
        self.cols = cols
        if not isinstance(territories_data, list) or not isinstance(grid, list) or len(grid) != self.rows:
            raise ValueError("Format de carte incompatible : contenu invalide.")

        normalized_grid: List[List[int]] = []
        for row in grid:
            if not isinstance(row, list) or len(row) != self.cols:
                raise ValueError("Format de carte incompatible : grille invalide.")
            normalized_grid.append([int(cell) for cell in row])

        raw_territories: Dict[int, dict] = {}
        for terr_data in territories_data:
            raw_territories[int(terr_data["id"])] = terr_data

        territory_ids_in_grid = sorted({cell for row in normalized_grid for cell in row if cell >= 0})
        if not territory_ids_in_grid:
            raise ValueError("Carte invalide : aucun territoire trouve.")

        self.map_mode = payload.get("map_mode", "standard")
        self.grid_territory = normalized_grid
        self.territories = []
        self.territory_continent = {}
        self.terre_links = []
        self.terre_link_points = {}
        self.bridge_links = set()
        self.fragile_bridge_links = set()
        self.bridge_link_points = {}

        for terr_id in territory_ids_in_grid:
            terr_data = raw_territories.get(terr_id, {})
            self.territories.append(Territory(
                id=terr_id,
                name=str(terr_data.get("name", "")) or f"T{terr_id + 1}",
                owner=-1,
                regiments=0,
                cells=[],
                neighbors=[],
                reinforcement_bonus=int(terr_data.get("reinforcement_bonus", 1)),
            ))
            continent = terr_data.get("continent")
            if continent is not None:
                self.territory_continent[terr_id] = int(continent)

        self.territories.sort(key=lambda terr: terr.id)
        if [terr.id for terr in self.territories] != list(range(len(self.territories))):
            raise ValueError("Carte invalide : identifiants de territoires non consecutifs.")

        self.rebuild_cells_from_grid()
        self.recompute_neighbors_from_grid()

        if self.map_mode == "terre":
            for item in payload.get("terre_links", []):
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    a = int(item[0])
                    b = int(item[1])
                    if 0 <= a < len(self.territories) and 0 <= b < len(self.territories) and a != b:
                        key = tuple(sorted((a, b)))
                        if key not in self.terre_links:
                            self.terre_links.append(key)

            for item in payload.get("terre_link_points", []):
                try:
                    a = int(item["a"])
                    b = int(item["b"])
                    start = (int(item["start"][0]), int(item["start"][1]))
                    end = (int(item["end"][0]), int(item["end"][1]))
                except (KeyError, TypeError, ValueError, IndexError):
                    continue
                key = tuple(sorted((a, b)))
                if key in self.terre_links:
                    self.terre_link_points[key] = (start, end)

            self.apply_terre_links_to_neighbors()
            if len(self.territory_continent) != len(self.territories):
                self.rebuild_terre_continents_from_layout()

        for item in payload.get("bridge_links", []):
            if isinstance(item, (list, tuple)) and len(item) == 2:
                a = int(item[0])
                b = int(item[1])
                if 0 <= a < len(self.territories) and 0 <= b < len(self.territories) and a != b:
                    self.bridge_links.add(tuple(sorted((a, b))))

        for item in payload.get("bridge_link_points", []):
            try:
                a = int(item["a"])
                b = int(item["b"])
                start = (int(item["start"][0]), int(item["start"][1]))
                end = (int(item["end"][0]), int(item["end"][1]))
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            key = tuple(sorted((a, b)))
            if key in self.bridge_links:
                self.bridge_link_points[key] = (start, end)

        for item in payload.get("fragile_bridge_links", []):
            if isinstance(item, (list, tuple)) and len(item) == 2:
                key = tuple(sorted((int(item[0]), int(item[1]))))
                if key in self.bridge_links:
                    self.fragile_bridge_links.add(key)
        self.apply_bridge_links_to_neighbors()

    def _load_game(self, payload: dict) -> None:
        # Joueurs et configuration IA
        self.num_players = int(payload["num_players"])
        self.initial_num_players = int(payload.get("initial_num_players", self.num_players))
        self.ai_player_count = int(payload.get("ai_player_count", 0))
        self.initial_ai_player_count = int(payload.get("initial_ai_player_count", self.ai_player_count))
        self.difficulty_level = normalize_difficulty_level(payload.get("difficulty_level", "normal"))
        self.tribes_mode = bool(payload.get("tribes_mode", False))
        self.simple_mode = bool(payload.get("simple_mode", False))
        self.base_ai_players = {int(x) for x in payload.get("base_ai_players", [])}
        self.auto_controlled_players = {int(x) for x in payload.get("auto_controlled_players", [])}
        self.human_controlled_players = {int(x) for x in payload.get("human_controlled_players", [])}
        self.eliminated_human_players = {int(x) for x in payload.get("eliminated_human_players", [])}
        self.ai_personalities = {int(k): v for k, v in payload.get("ai_personalities", {}).items()}
        self.ai_current_behavior = {int(k): v for k, v in payload.get("ai_current_behavior", {}).items()}
        self.ai_last_missile_turns = {
            int(k): int(v) for k, v in payload.get("ai_last_missile_turns", {}).items()
        }
        self.commercial_city_players = {int(x) for x in payload.get("commercial_city_players", [])}
        self.commercial_city_capital_ids = {int(k): int(v) for k, v in payload.get("commercial_city_capital_ids", {}).items()}
        self.player_capital_ids = {int(k): int(v) for k, v in payload.get("player_capital_ids", {}).items()}
        self.pending_commercial_city_spawns = max(0, int(payload.get("pending_commercial_city_spawns", 0)))
        self.nation_players = {int(x) for x in payload.get("nation_players", [])}
        self.nation_qualification_start_turns = {
            int(k): max(1, int(v))
            for k, v in payload.get("nation_qualification_start_turns", {}).items()
        }
        self.nation_capital_loss_start_turns = {
            int(k): max(1, int(v))
            for k, v in payload.get("nation_capital_loss_start_turns", {}).items()
        }
        # Comme x45 : la diplomatie nationale speciale, la guerre froide, la
        # colonisation et la vassalisation ne sont plus restaurees.
        self.submitted_territory_ids = {int(x) for x in payload.get("submitted_territory_ids", [])}
        self.submitted_territory_overlords = {
            int(k): int(v) for k, v in payload.get("submitted_territory_overlords", {}).items()
        }
        self.submitted_territory_created_turns = {
            int(k): max(1, int(v)) for k, v in payload.get("submitted_territory_created_turns", {}).items()
        }
        self.integrated_submitted_territories = {
            int(player): {int(tid) for tid in territory_ids}
            for player, territory_ids in payload.get("integrated_submitted_territories", {}).items()
        }
        self.union_members = {
            int(player): {int(member) for member in members}
            for player, members in payload.get("union_members", {}).items()
        }
        self.union_original_territories = {
            int(player): {int(tid) for tid in territory_ids}
            for player, territory_ids in payload.get("union_original_territories", {}).items()
        }
        self.final_duel_active = bool(payload.get("final_duel_active", False))
        raw_champions = payload.get("final_duel_champions", [])
        self.final_duel_champions = tuple(int(p) for p in raw_champions) if len(raw_champions) >= 2 else None
        self.final_duel_alliances = {
            int(player): int(champion)
            for player, champion in payload.get("final_duel_alliances", {}).items()
        }
        pending_winner = payload.get("final_duel_pending_winner")
        self.final_duel_pending_winner = int(pending_winner) if pending_winner is not None else None
        raw_ai_speed_mode = payload.get("ai_speed_mode")
        if raw_ai_speed_mode in ("normal", "fast", "instant"):
            self.ai_speed_mode = raw_ai_speed_mode
        else:
            self.ai_speed_mode = "instant" if bool(payload.get("fast_ai_movements", False)) else "normal"
        self.fast_ai_movements = self.ai_speed_mode == "instant"

        # Etat de la partie
        self.current_player = int(payload["current_player"])
        self.turn = int(payload["turn"])
        self.turn_phase = payload.get("turn_phase", "attack")
        self.turn_move_count = int(payload.get("turn_move_count", 0))
        self.last_empire_event_turn = int(payload.get("last_empire_event_turn", 0))

        # Territoires speciaux
        self.super_territory_ids = {int(x) for x in payload.get("super_territory_ids", [])}
        self.ultra_super_territory_ids = {int(x) for x in payload.get("ultra_super_territory_ids", [])}
        self.golden_territory_ids = {int(x) for x in payload.get("golden_territory_ids", [])}
        self.onu_player_id = int(payload.get("onu_player_id", -2))
        self.sanctuary_territory_ids = {int(x) for x in payload.get("sanctuary_territory_ids", [])}

        # Economie et structures
        self.player_money = {int(k): int(v) for k, v in payload.get("player_money", {}).items()}
        self.precious_mineral_mine_ids = {int(x) for x in payload.get("precious_mineral_mine_ids", [])}
        self.bonus_5_spawn_turns = {
            int(k): int(v) for k, v in payload.get("bonus_5_spawn_turns", {}).items()
        }
        self.precious_mineral_mine_spawn_turns = {
            int(k): int(v)
            for k, v in payload.get("precious_mineral_mine_spawn_turns", {}).items()
        }
        self.fortress_territory_ids = {int(x) for x in payload.get("fortress_territory_ids", [])}
        self.fortress_capture_counts = {int(k): int(v) for k, v in payload.get("fortress_capture_counts", {}).items()}
        legacy_industries = {int(x) for x in payload.get("industry_territory_ids", [])}
        self.factory_territory_ids = {int(x) for x in payload.get("factory_territory_ids", legacy_industries)}
        self.airport_territory_ids = {int(x) for x in payload.get("airport_territory_ids", [])}
        self.port_territory_ids = {int(x) for x in payload.get("port_territory_ids", [])}
        legacy_counts = {int(k): int(v) for k, v in payload.get("industry_capture_counts", {}).items()}
        self.industrial_capture_counts = {int(k): int(v) for k, v in payload.get("industrial_capture_counts", legacy_counts).items()}
        self.cultural_center_ages = {int(k): [int(age) for age in ages] for k, ages in payload.get("cultural_center_ages", {}).items()}
        self.cultural_capture_counts = {int(k): int(v) for k, v in payload.get("cultural_capture_counts", {}).items()}
        self.ruin_territory_ids = {int(x) for x in payload.get("ruin_territory_ids", [])}
        self.university_territory_ids = {int(x) for x in payload.get("university_territory_ids", [])}
        self.university_capture_counts = {int(k): int(v) for k, v in payload.get("university_capture_counts", {}).items()}
        self.university_ages = {int(k): max(0, int(v)) for k, v in payload.get("university_ages", {}).items()}
        self.temple_territory_ids = {int(x) for x in payload.get("temple_territory_ids", [])}
        self.temple_capture_counts = {int(k): int(v) for k, v in payload.get("temple_capture_counts", {}).items()}

        # Religion, science, culture, merveilles
        self.religion_founders = {
            int(player): int(religion_id)
            for player, religion_id in payload.get("religion_founders", {}).items()
        }
        self.religion_foundation_turns = {
            int(religion_id): max(1, int(turn))
            for religion_id, turn in payload.get("religion_foundation_turns", {}).items()
        }
        saved_last_spread_turns = payload.get("religion_last_spread_turns")
        if isinstance(saved_last_spread_turns, dict):
            self.religion_last_spread_turns = {
                int(religion_id): max(1, int(turn))
                for religion_id, turn in saved_last_spread_turns.items()
            }
        else:
            # Anciennes sauvegardes : le compteur repart du tour charge.
            self.religion_last_spread_turns = {
                religion_id: self.turn
                for religion_id in self.religion_foundation_turns
            }
        self.religion_holy_sites = {
            int(religion_id): int(tid)
            for religion_id, tid in payload.get("religion_holy_sites", {}).items()
        }
        self.religious_influence = {
            int(tid): int(religion_id)
            for tid, religion_id in payload.get("religious_influence", {}).items()
        }
        self.player_science = {int(k): max(0, int(v)) for k, v in payload.get("player_science", {}).items()}
        self.culture_expansion_milestones = {
            int(player): max(0, int(milestone) // 50 * 50)
            for player, milestone in payload.get("culture_expansion_milestones", {}).items()
        }
        self.wonder_territories = {
            str(wonder_type): int(tid)
            for wonder_type, tid in payload.get("wonder_territories", {}).items()
        }
        allie = payload.get("eternal_ally_player")
        self.eternal_ally_player = None if allie is None else int(allie)
        patron = payload.get("eternal_ally_patron")
        self.eternal_ally_patron = None if patron is None else int(patron)
        self.victory_milestones = [
            palier for palier in payload.get("victory_milestones", [])
            if isinstance(palier, dict)
        ]
        self.wonder_construction_turns = {}

        # Paradis fiscaux
        self.last_stand_bonus_players = {int(x) for x in payload.get("last_stand_bonus_players", [])}
        self.last_stand_bonus_territory = normalize_tax_haven_capital_payload(payload.get("last_stand_bonus_territory", {}))
        self.tax_haven_turn_start_territory_counts = {
            int(k): int(v)
            for k, v in payload.get("tax_haven_turn_start_territory_counts", {}).items()
        }

        # Alliances
        self.active_alliances = {}
        self.alliance_start_turns = {}
        for item in payload.get("active_alliances", []):
            try:
                human = int(item["human"])
                ai = int(item["ai"])
                expires_turn = int(item["expires_turn"])
                start_turn = int(item.get("start_turn", max(1, expires_turn - ALLIANCE_DURATION_TURNS)))
            except (KeyError, TypeError, ValueError):
                continue
            self.active_alliances[(human, ai)] = expires_turn
            self.alliance_start_turns[(human, ai)] = start_turn
        self.active_ai_alliances = {}
        self.ai_alliance_start_turns = {}
        for item in payload.get("active_ai_alliances", []):
            try:
                ai_a = int(item["ai_a"])
                ai_b = int(item["ai_b"])
                expires_turn = int(item["expires_turn"])
                start_turn = int(item.get("start_turn", max(1, expires_turn - ALLIANCE_DURATION_TURNS)))
            except (KeyError, TypeError, ValueError):
                continue
            key = (min(ai_a, ai_b), max(ai_a, ai_b))
            self.active_ai_alliances[key] = expires_turn
            self.ai_alliance_start_turns[key] = start_turn
        self.active_offensive_alliances = {}
        self.offensive_alliance_start_turns = {}
        for item in payload.get("active_offensive_alliances", []):
            try:
                human = int(item["human"])
                ai = int(item["ai"])
                target = int(item["target"])
                expires_turn = int(item["expires_turn"])
                start_turn = int(item.get("start_turn", max(1, expires_turn - ALLIANCE_DURATION_TURNS)))
            except (KeyError, TypeError, ValueError):
                continue
            self.active_offensive_alliances[(human, ai)] = (target, expires_turn)
            self.offensive_alliance_start_turns[(human, ai)] = start_turn

        # Evenements et replay
        self.recent_major_events = [str(item) for item in payload.get("recent_major_events", [])][-8:]
        self.major_event_modal = sanitize_major_event_modal(payload.get("major_event_modal"))
        self.major_event_modal_queue = [
            modal
            for modal in (
                sanitize_major_event_modal(item)
                for item in payload.get("major_event_modal_queue", [])
            )
            if modal is not None
        ]
        self.pending_major_events_for_humans = {
            int(player): [" ".join(str(event).split()) for event in events if str(event).strip()][-20:]
            for player, events in payload.get("pending_major_events_for_humans", {}).items()
            if isinstance(events, list)
        }
        self.replay_history = [
            item for item in payload.get("replay_history", []) if isinstance(item, dict)
        ][-MAX_REPLAY_SNAPSHOTS:]

        if not self.player_money:
            self.player_money = {player: 0 for player in range(self.num_players)}

        # Etat par territoire (owner, regiments, reinforcement_bonus)
        territories_state = {int(ts["id"]): ts for ts in payload.get("territories_state", [])}
        for terr in self.territories:
            ts = territories_state.get(terr.id)
            if ts is None:
                raise ValueError(f"Etat manquant pour le territoire {terr.id}.")
            terr.owner = int(ts["owner"])
            terr.regiments = int(ts["regiments"])
            terr.reinforcement_bonus = int(ts.get("reinforcement_bonus", 1))

        self.phase = "playing"

    # ------------------------------------------------------------------
    # Serialisation (miroir de build_map_payload + build_game_payload)
    # ------------------------------------------------------------------

    def to_payload(self) -> dict:
        payload = self._build_map_payload()
        payload.update({
            "kind": "game",
            "num_players": self.num_players,
            "initial_num_players": self.initial_num_players or self.num_players,
            "ai_player_count": self.ai_player_count,
            "initial_ai_player_count": self.initial_ai_player_count or self.ai_player_count,
            "difficulty_level": self.difficulty_level,
            "tribes_mode": self.tribes_mode,
            "base_ai_players": sorted(self.base_ai_players),
            "auto_controlled_players": sorted(self.auto_controlled_players),
            "human_controlled_players": sorted(self.human_controlled_players),
            "eliminated_human_players": sorted(self.eliminated_human_players),
            "ai_personalities": {str(k): v for k, v in self.ai_personalities.items()},
            "ai_current_behavior": {str(k): v for k, v in self.ai_current_behavior.items()},
            "ai_last_missile_turns": {str(k): int(v) for k, v in self.ai_last_missile_turns.items()},
            "commercial_city_players": sorted(self.commercial_city_players),
            "commercial_city_capital_ids": {str(k): int(v) for k, v in self.commercial_city_capital_ids.items()},
            "player_capital_ids": {str(k): int(v) for k, v in self.player_capital_ids.items()},
            "pending_commercial_city_spawns": int(self.pending_commercial_city_spawns),
            "nation_players": sorted(int(player) for player in self.nation_players),
            "nation_qualification_start_turns": {
                str(player): int(start_turn)
                for player, start_turn in self.nation_qualification_start_turns.items()
            },
            "nation_capital_loss_start_turns": {
                str(player): int(start_turn)
                for player, start_turn in self.nation_capital_loss_start_turns.items()
            },
            # Mecaniques abandonnees : emises vides pour rester compatibles.
            "nation_alliances": [],
            "nation_wars": [],
            "cold_war_active": False,
            "cold_war_nations": [],
            "cold_war_alliances": {},
            "colonized_players": [],
            "submitted_territory_ids": sorted(int(tid) for tid in self.submitted_territory_ids),
            "submitted_territory_overlords": {
                str(tid): int(overlord)
                for tid, overlord in self.submitted_territory_overlords.items()
            },
            "submitted_territory_created_turns": {
                str(tid): int(created_turn)
                for tid, created_turn in self.submitted_territory_created_turns.items()
            },
            "vassal_territory_overlords": {},
            "vassal_territory_created_turns": {},
            "vassal_players": {},
            "integrated_vassal_territories": {},
            "integrated_submitted_territories": {
                str(player): sorted(int(tid) for tid in territory_ids)
                for player, territory_ids in self.integrated_submitted_territories.items()
            },
            "union_members": {
                str(player): sorted(int(member) for member in members)
                for player, members in self.union_members.items()
            },
            "union_original_territories": {
                str(player): sorted(int(tid) for tid in territory_ids)
                for player, territory_ids in self.union_original_territories.items()
            },
            "final_duel_active": bool(self.final_duel_active),
            "final_duel_champions": list(self.final_duel_champions or []),
            "final_duel_alliances": {
                str(player): int(champion)
                for player, champion in self.final_duel_alliances.items()
            },
            "final_duel_pending_winner": self.final_duel_pending_winner,
            "fast_ai_movements": self.fast_ai_movements,
            "ai_speed_mode": self.ai_speed_mode,
            "current_player": self.current_player,
            "turn": self.turn,
            "turn_phase": self.turn_phase,
            "turn_move_count": self.turn_move_count,
            "last_empire_event_turn": self.last_empire_event_turn,
            "super_territory_ids": sorted(self.super_territory_ids),
            "ultra_super_territory_ids": sorted(self.ultra_super_territory_ids),
            "golden_territory_ids": sorted(self.golden_territory_ids),
            "sanctuary_territory_ids": sorted(self.sanctuary_territory_ids),
            "onu_player_id": self.onu_player_id,
            "player_money": {str(k): int(v) for k, v in self.player_money.items()},
            "precious_mineral_mine_ids": sorted(int(tid) for tid in self.precious_mineral_mine_ids),
            "bonus_5_spawn_turns": {
                str(k): int(v) for k, v in sorted(self.bonus_5_spawn_turns.items())
            },
            "precious_mineral_mine_spawn_turns": {
                str(k): int(v)
                for k, v in sorted(self.precious_mineral_mine_spawn_turns.items())
            },
            "fortress_territory_ids": sorted(self.fortress_territory_ids),
            "fortress_capture_counts": {str(k): int(v) for k, v in self.fortress_capture_counts.items()},
            "industry_territory_ids": sorted(self.factory_territory_ids),
            "industry_capture_counts": {str(k): int(v) for k, v in self.industrial_capture_counts.items() if k in self.factory_territory_ids},
            "factory_territory_ids": sorted(self.factory_territory_ids),
            "airport_territory_ids": sorted(self.airport_territory_ids),
            "port_territory_ids": sorted(self.port_territory_ids),
            "industrial_capture_counts": {str(k): int(v) for k, v in self.industrial_capture_counts.items()},
            "cultural_center_ages": {str(k): [int(age) for age in ages] for k, ages in self.cultural_center_ages.items()},
            "cultural_capture_counts": {str(k): int(v) for k, v in self.cultural_capture_counts.items()},
            "ruin_territory_ids": sorted(self.ruin_territory_ids),
            "university_territory_ids": sorted(self.university_territory_ids),
            "university_capture_counts": {str(k): int(v) for k, v in self.university_capture_counts.items()},
            "university_ages": {str(k): int(v) for k, v in self.university_ages.items()},
            "temple_territory_ids": sorted(self.temple_territory_ids),
            "temple_capture_counts": {str(k): int(v) for k, v in self.temple_capture_counts.items()},
            "religion_founders": {str(player): int(religion_id) for player, religion_id in self.religion_founders.items()},
            "religion_foundation_turns": {str(religion_id): int(turn) for religion_id, turn in self.religion_foundation_turns.items()},
            "religion_last_spread_turns": {str(religion_id): int(turn) for religion_id, turn in self.religion_last_spread_turns.items()},
            "religion_holy_sites": {str(religion_id): int(tid) for religion_id, tid in self.religion_holy_sites.items()},
            "religious_influence": {str(tid): int(religion_id) for tid, religion_id in self.religious_influence.items()},
            "player_science": {str(k): int(v) for k, v in self.player_science.items()},
            "culture_expansion_milestones": {
                str(player): int(milestone)
                for player, milestone in self.culture_expansion_milestones.items()
            },
            "wonder_territories": {
                str(wonder_type): int(tid)
                for wonder_type, tid in self.wonder_territories.items()
            },
            "eternal_ally_player": (
                None if self.eternal_ally_player is None else int(self.eternal_ally_player)
            ),
            "eternal_ally_patron": (
                None if self.eternal_ally_patron is None else int(self.eternal_ally_patron)
            ),
            "victory_milestones": [dict(palier) for palier in self.victory_milestones],
            "last_stand_bonus_players": sorted(self.last_stand_bonus_players),
            "last_stand_bonus_territory": {
                str(k): sorted(int(tid) for tid in self.get_player_tax_haven_capital_ids(k))
                for k in sorted(set(self.last_stand_bonus_players) | set(self.last_stand_bonus_territory))
            },
            "tax_haven_turn_start_territory_counts": {
                str(k): int(v)
                for k, v in self.tax_haven_turn_start_territory_counts.items()
            },
            "active_alliances": [
                {
                    "human": int(human),
                    "ai": int(ai),
                    "start_turn": int(self.alliance_start_turns.get((human, ai), max(1, expires_turn - ALLIANCE_DURATION_TURNS))),
                    "expires_turn": int(expires_turn),
                }
                for (human, ai), expires_turn in sorted(self.active_alliances.items())
            ],
            "active_ai_alliances": [
                {
                    "ai_a": int(ai_a),
                    "ai_b": int(ai_b),
                    "start_turn": int(self.ai_alliance_start_turns.get((ai_a, ai_b), max(1, expires_turn - ALLIANCE_DURATION_TURNS))),
                    "expires_turn": int(expires_turn),
                }
                for (ai_a, ai_b), expires_turn in sorted(self.active_ai_alliances.items())
            ],
            "active_offensive_alliances": [
                {
                    "human": int(human),
                    "ai": int(ai),
                    "target": int(target),
                    "start_turn": int(self.offensive_alliance_start_turns.get((human, ai), max(1, expires_turn - ALLIANCE_DURATION_TURNS))),
                    "expires_turn": int(expires_turn),
                }
                for (human, ai), (target, expires_turn) in sorted(self.active_offensive_alliances.items())
            ],
            "recent_major_events": list(self.recent_major_events[-8:]),
            "major_event_modal": self.major_event_modal,
            "major_event_modal_queue": list(self.major_event_modal_queue),
            "pending_major_events_for_humans": {
                str(player): list(events[-20:])
                for player, events in self.pending_major_events_for_humans.items()
                if events
            },
            "replay_history": list(self.replay_history[-MAX_REPLAY_SNAPSHOTS:]),
            "territories_state": [
                {
                    "id": terr.id,
                    "owner": terr.owner,
                    "regiments": terr.regiments,
                    "reinforcement_bonus": terr.reinforcement_bonus,
                }
                for terr in self.territories
            ],
        })
        # La version simplifiee est une option recente : la cle n'est emise que
        # lorsqu'elle est active, pour qu'une partie ordinaire produise
        # exactement le payload v13 d'origine (parite avec x45 verifiee cle
        # par cle par tests/test_parite_original.py).
        if self.simple_mode:
            payload["simple_mode"] = True
        return payload

    def _build_map_payload(self) -> dict:
        return {
            "schema_version": SAVE_SCHEMA_VERSION,
            "kind": "map",
            "map_mode": self.map_mode,
            "rows": self.rows,
            "cols": self.cols,
            "grid_territory": [list(row) for row in self.grid_territory],
            "territories": [
                {
                    "id": terr.id,
                    "name": terr.name,
                    "cells": [list(cell) for cell in terr.cells],
                    "neighbors": list(terr.neighbors),
                    "continent": self.territory_continent.get(terr.id),
                    "reinforcement_bonus": terr.reinforcement_bonus,
                }
                for terr in self.territories
            ],
            "terre_links": [list(link) for link in self.terre_links],
            "terre_link_points": [
                {
                    "a": a,
                    "b": b,
                    "start": list(start),
                    "end": list(end),
                }
                for (a, b), (start, end) in sorted(self.terre_link_points.items())
            ],
            "bridge_links": [list(link) for link in sorted(self.bridge_links)],
            "fragile_bridge_links": [
                list(link) for link in sorted(self.fragile_bridge_links)
            ],
            "bridge_link_points": [
                {
                    "a": a,
                    "b": b,
                    "start": list(start),
                    "end": list(end),
                }
                for (a, b), (start, end) in sorted(self.bridge_link_points.items())
            ],
        }

    # ------------------------------------------------------------------
    # Fichiers
    # ------------------------------------------------------------------

    @classmethod
    def from_json_file(cls, path: Path | str) -> "GameState":
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_payload(payload)

    def to_json_file(self, path: Path | str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_payload(), handle, ensure_ascii=False, indent=2)
