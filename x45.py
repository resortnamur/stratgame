import json
import math
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import pygame

# Moteur pur (migration web) : x45 delegue progressivement ses regles au
# module moteur.regles (approche strangler). Les fonctions du moteur operent
# par duck typing sur GraphicalGame, qui expose les memes attributs que
# moteur.etat.GameState.
from moteur import regles as moteur_regles
from moteur import actions as moteur_actions

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog
except ImportError:  # Interface de secours si Tkinter n'est pas disponible.
    tk = None
    messagebox = None
    simpledialog = None


@dataclass
class Territory:
    id: int
    name: str
    owner: int
    regiments: int
    cells: List[Tuple[int, int]] = field(default_factory=list)
    neighbors: List[int] = field(default_factory=list)
    reinforcement_bonus: int = 1


class GraphicalGame:
    WIDTH = 1200
    HEIGHT = 720
    WINDOWED_WIDTH = 1200
    WINDOWED_HEIGHT = 720
    START_FULLSCREEN = False
    FPS = 60
    AI_ACTION_DELAY_MS = 1100
    AI_FAST_ACTION_DELAY_MS = 260
    MAX_END_TURN_MOVES = 5
    EXPANDED_END_TURN_MOVES = 10
    EXPANDED_END_TURN_MOVE_TERRITORY_THRESHOLD = 10
    AI_MOBILIZATION_DENOMINATOR = 100
    SUBMITTED_TERRITORY_INSTABILITY_DENOMINATOR = 40
    SUBMITTED_TERRITORY_INTEGRATION_DELAY_TURNS = 20
    VASSAL_INTEGRATION_DELAY_TURNS = 20
    SCIENCE_ONU_MANIPULATION_THRESHOLD = 50
    SCIENCE_BRIDGE_THRESHOLD = 150
    SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD = 200
    SCIENCE_ATTACK_4_DICE_THRESHOLD = 500

    PLAYER_COLORS = [
        (93, 109, 126),
        (84, 153, 199),
        (88, 214, 141),
        (244, 208, 63),
        (165, 105, 189),
        (236, 112, 99),
        (133, 193, 233),
        (118, 215, 196),
        (214, 162, 92),
        (127, 140, 141),
        # Couleurs supplémentaires pour les joueurs issus des révolutions
        (255, 87, 51),
        (52, 211, 153),
        (139, 92, 246),
        (251, 191, 36),
        (236, 72, 153),
        (20, 184, 166),
        (249, 115, 22),
        (99, 179, 237),
        (161, 220, 93),
        (248, 113, 113),
    ]

    BACKGROUND_COLOR = (18, 32, 52)
    BORDER_COLOR = (20, 20, 20)

    MERCENARY_COST = 50
    FORTRESS_COST = 100
    DESTROY_FORTRESS_COST = 100
    CORRUPTION_COST_PER_REGIMENT = 200
    CORRUPTION_FORTRESS_SURCHARGE = 400
    CORRUPTION_INDUSTRIAL_SURCHARGE = 400
    CORRUPTION_CULTURAL_CENTER_SURCHARGE = 800
    CORRUPTION_BONUS_TERRITORY_SURCHARGE = 400
    ONU_MANIPULATION_COST_PER_REGIMENT = 50
    TAX_HAVEN_INTEGRATION_COST = 500
    TAX_HAVEN_LOSS_TERRITORY_THRESHOLD = 10
    SEDITION_DENOMINATOR = 50000
    REVOLT_COST = 200
    REVOLT_COST_LOW = 200
    REVOLT_COST_MEDIUM = 400
    REVOLT_COST_HIGH = 600
    INDUSTRY_COST = 100
    FACTORY_COST = 100
    AIRPORT_COST = 100
    PORT_COST = 100
    CULTURAL_CENTER_COST = 200
    UNIVERSITY_COST = 200
    TEMPLE_COST = 300
    WONDER_COST = 300
    BUILD_BRIDGE_COST = 300
    DESTROY_BRIDGE_COST = 150
    BRIDGE_SPAWN_DENOMINATOR = 20
    BRIDGE_COLLAPSE_DENOMINATOR = 30
    BRIDGE_MAX_LENGTH_PX = 76.0
    SCIENCE_WONDER_THRESHOLD = 100
    AI_SCIENCE_WONDER_THRESHOLD = 50
    MAX_CULTURAL_CENTERS_PER_TERRITORY = 1
    CULTURE_IMMUNITY_THRESHOLD = 25
    CULTURE_ADVANTAGE_THRESHOLD = 15
    AI_CULTURE_DETERRENCE_MIN_ADVANTAGE = 20
    AI_CULTURE_FORCE_ATTACK_REGIMENTS = 40
    REDUCED_CORRUPTION_COST_PER_REGIMENT = 40
    ALLIANCE_COST_PER_TERRITORY = 20
    OFFENSIVE_ALLIANCE_COST_PER_TERRITORY = 25
    ALLIANCE_DURATION_TURNS = 10
    AI_ALLIANCE_DENOMINATOR = 60
    AI_CULTURE_ALLIANCE_DENOMINATOR = 40
    AI_HIGH_CULTURE_ALLIANCE_DENOMINATOR = 30
    AI_TAX_HAVEN_ALLIANCE_DENOMINATOR = 5
    AI_NATION_ALLIANCE_DENOMINATOR = 20
    INITIAL_FORTRESS_COUNT = 5
    INITIAL_INDUSTRY_COUNT = 5
    INITIAL_CULTURAL_CENTER_COUNT = 5
    INITIAL_COMMERCIAL_CITY_COUNT = 1
    INITIAL_CAPITAL_REGIMENTS = 6
    CAPITAL_INCOME_MULTIPLIER = 10
    CHANGE_CAPITAL_COST = 300
    NATION_MIN_TERRITORIES = 10
    NATION_MAX_TERRITORIES = 10 ** 9
    NATION_INCOME_DIVISOR = 10
    NATION_QUALIFICATION_DELAY_TURNS = 10
    NATION_CAPITAL_LOSS_DELAY_TURNS = 10
    NATION_ALLIANCE_BREAK_DENOMINATOR = 40
    NATION_PEACE_DENOMINATOR = 20
    NATION_PEACE_BASE_COST = 400
    AI_NATION_SUBMISSION_DENOMINATOR = 100
    MAX_REINFORCEMENTS_PER_TURN = 10
    MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS = 120
    MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS_WITH_BONUS_5 = 200
    BONUS_5_SPAWN_TURNS = (35, 43, 51, 59)
    PRECIOUS_MINERAL_MINE_SPAWN_TURNS = (37, 45, 53, 61)
    PRECIOUS_MINERAL_MINE_INCOME = 100
    AI_REINFORCEMENT_BONUS_STAGES = (
        (33, 1),
        (41, 2),
        (49, 3),
        (57, 4),
        (65, 5),
    )
    UNION_COST_PER_TERRITORY = 200
    COLONIZATION_COST_PER_TERRITORY = 200
    COMMERCIAL_CITY_TERRITORY_LIMIT = 10
    SPECIAL_CAPTURE_LIMIT = 3
    RELIGION_SPREAD_INTERVAL_TURNS = 30
    RELIGION_SPREAD_INTERVAL_BY_TEMPLE_COUNT = {
        1: 30,
        2: 25,
        3: 20,
        4: 15,
        5: 10,
        6: 5,
        7: 1,
    }
    RELIGIOUS_INCOME_BONUS_PER_TERRITORY = 2
    RELIGIOUS_REINFORCEMENT_TERRITORIES_PER_BONUS = 3
    RELIGIONS = [
        {"name": "Auralis", "symbol": "A*", "color": (244, 208, 63)},
        {"name": "Noctyra", "symbol": "N)", "color": (165, 105, 189)},
        {"name": "Veridia", "symbol": "V^", "color": (88, 214, 141)},
        {"name": "Pyronis", "symbol": "P!", "color": (236, 112, 99)},
        {"name": "Mareon", "symbol": "M~", "color": (84, 153, 199)},
        {"name": "Elyrion", "symbol": "E+", "color": (174, 235, 255)},
    ]
    WONDER_RELIGION_ID = 5
    WONDER_DEFINITIONS = {
        "elyrion_sanctuary": {
            "name": "Sanctuaire d'Elyrion",
            "effect": "Fonde Elyrion, religion conquerante liee au territoire",
        },
        "thousand_voices_theatre": {
            "name": "Theatre des Mille Voix",
            "effect": "Double la culture de son controleur",
        },
        "atlas_observatory": {
            "name": "Observatoire d'Atlas",
            "effect": "Double la science effective de son controleur",
        },
        "golden_pact_palace": {
            "name": "Palais du Pacte d'Or",
            "effect": "Fait de son controleur l'unique allie de la Cite commercante",
        },
    }
    SAVE_SCHEMA_VERSION = 13
    REPLAY_FRAME_DELAY_MS = 150
    MAX_REPLAY_SNAPSHOTS = 1200
    DETAILS_DOUBLE_CLICK_DELAY_MS = 320

    def __init__(self) -> None:
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        pygame.init()
        pygame.display.set_caption("Jeu de strategie - Version graphique")
        self.windowed_size = (self.WINDOWED_WIDTH, self.WINDOWED_HEIGHT)
        self.fullscreen = self.START_FULLSCREEN
        self.screen = self.set_display_surface(self.fullscreen, refresh_layout=False)
        self.clock = pygame.time.Clock()

        self.font_small = pygame.font.SysFont("consolas", 16)
        self.font_medium = pygame.font.SysFont("consolas", 22, bold=True)
        self.font_large = pygame.font.SysFont("consolas", 32, bold=True)

        self.num_players = 0
        self.initial_num_players = 0
        self.ai_player_count = 0
        self.initial_ai_player_count = 0
        self.difficulty_level = "normal"
        self.base_ai_players: set[int] = set()
        self.auto_controlled_players: set[int] = set()
        self.human_controlled_players: set[int] = set()
        self.eliminated_human_players: set[int] = set()
        self.territories: List[Territory] = []
        self.current_player = 0
        self.turn = 1
        self.selected_source: Optional[int] = None
        self.selected_target: Optional[int] = None
        self.running = True
        self.phase = "setup"
        self.turn_phase = "attack"
        self.turn_move_count = 0
        self.message = ""
        self.message_timer = 0

        self.tribes_mode = False
        self.ai_state = "idle"
        self.ai_next_action_time = 0
        self.fast_ai_movements = False
        self.ai_speed_mode = "normal"
        self.ai_personalities: dict[int, str] = {}
        self.ai_current_behavior: dict[int, str] = {}
        self.commercial_city_players: set[int] = set()
        self.commercial_city_capital_ids: dict[int, int] = {}
        self.player_capital_ids: dict[int, int] = {}
        self.pending_commercial_city_spawns = 0
        self.nation_players: set[int] = set()
        self.nation_qualification_start_turns: dict[int, int] = {}
        self.nation_capital_loss_start_turns: dict[int, int] = {}
        self.nation_alliances: set[tuple[int, int]] = set()
        self.nation_wars: set[tuple[int, int]] = set()
        self.cold_war_active = False
        self.cold_war_nations: tuple[int, int] | None = None
        self.cold_war_alliances: dict[int, int] = {}
        self.colonized_players: set[int] = set()
        self.submitted_territory_ids: set[int] = set()
        self.submitted_territory_overlords: dict[int, int] = {}
        self.submitted_territory_created_turns: dict[int, int] = {}
        self.vassal_territory_overlords: dict[int, int] = {}
        self.vassal_territory_created_turns: dict[int, int] = {}
        self.vassal_players: dict[int, int] = {}
        self.integrated_vassal_territories: dict[int, set[int]] = {}
        self.integrated_submitted_territories: dict[int, set[int]] = {}
        self.union_members: dict[int, set[int]] = {}
        self.union_original_territories: dict[int, set[int]] = {}
        self.final_duel_active = False
        self.final_duel_champions: tuple[int, ...] | None = None
        self.final_duel_alliances: dict[int, int] = {}
        self.final_duel_pending_winner: Optional[int] = None
        self.religion_founders: dict[int, int] = {}
        self.religion_foundation_turns: dict[int, int] = {}
        self.religion_last_spread_turns: dict[int, int] = {}
        self.religion_holy_sites: dict[int, int] = {}
        self.religious_influence: dict[int, int] = {}
        self.last_religion_foundation_message: Optional[str] = None
        self.wonder_territories: dict[str, int] = {}
        self.pending_wonder_type: Optional[str] = None

        self.end_turn_rect = pygame.Rect(self.WIDTH - 190, 14, 170, 36)
        self.geopolitical_button_rect = pygame.Rect(self.WIDTH - 190, 54, 112, 28)
        self.details_button_rect = pygame.Rect(self.WIDTH - 72, 54, 52, 28)
        self.all_icons_button_rect = pygame.Rect(self.WIDTH - 540, 58, 110, 24)
        self.save_map_rect = pygame.Rect(self.WIDTH - 600, 14, 170, 36)
        self.save_game_rect = pygame.Rect(self.WIDTH - 790, 14, 180, 36)
        self.auto_mode_rect = pygame.Rect(self.WIDTH - 400, 18, 170, 28)
        self.fast_ai_rect = pygame.Rect(self.WIDTH - 400, 54, 170, 28)
        self.replay_rect = pygame.Rect(self.WIDTH // 2 - 290, self.HEIGHT - 92, 270, 48)
        self.restart_rect = pygame.Rect(self.WIDTH // 2 + 20, self.HEIGHT - 92, 270, 48)
        self.replay_pause_rect = pygame.Rect(self.WIDTH - 410, 18, 170, 54)
        self.replay_return_rect = pygame.Rect(self.WIDTH - 230, 18, 210, 54)
        self.start_create_map_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 - 60, 380, 48)
        self.start_edit_map_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 - 4, 380, 48)
        self.start_game_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 + 52, 380, 48)
        self.start_load_game_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 + 108, 380, 48)
        self.editor_return_menu_rect = pygame.Rect(self.WIDTH - 410, 14, 180, 36)

        self.rows = 144
        self.cols = 180
        self.map_top = 90
        self.cell_width = self.WIDTH / self.cols
        self.cell_height = (self.HEIGHT - self.map_top - 8) / self.rows
        self.bridge_geometry_cache = {}
        self.grid_territory: List[List[int]] = [[-1 for _ in range(self.cols)] for _ in range(self.rows)]
        self.min_water_ratio = 0.40
        self.max_water_ratio = 0.60
        self.map_mode = "standard"
        self.territory_continent: dict[int, int] = {}
        self.continent_min_water_ratio = 0.20
        self.continent_max_water_ratio = 0.35
        self.continent_dense_min_water_ratio = 0.40
        self.continent_dense_max_water_ratio = 0.50

        self.saved_maps_dir = Path(__file__).resolve().with_name("cartes_sauvegardees")
        self.saved_maps_dir.mkdir(exist_ok=True)
        self.saved_games_dir = Path(__file__).resolve().with_name("parties_en_cours")
        self.saved_games_dir.mkdir(exist_ok=True)
        self.loaded_map_payload: Optional[dict] = None
        self.editing_map_path: Optional[Path] = None
        self.terre_links: List[Tuple[int, int]] = []
        self.terre_link_points: dict[Tuple[int, int], Tuple[Tuple[int, int], Tuple[int, int]]] = {}
        self.bridge_links: set[Tuple[int, int]] = set()
        self.fragile_bridge_links: set[Tuple[int, int]] = set()
        self.bridge_link_points: dict[Tuple[int, int], Tuple[Tuple[int, int], Tuple[int, int]]] = {}
        self.bridge_geometry_cache: dict[Tuple[int, int], Optional[Tuple[Tuple[int, int], Tuple[int, int]]]] = {}
        self.bridge_coastal_cells_cache: dict[int, List[Tuple[int, int]]] = {}
        self.custom_map_size = "medium"
        self.custom_shape = "block"
        self.custom_size_buttons = {
            "medium": pygame.Rect(18, 46, 100, 28),
            "large": pygame.Rect(128, 46, 90, 28),
            "immense": pygame.Rect(228, 46, 110, 28),
        }
        self.custom_shape_buttons = {
            "block": pygame.Rect(470, 46, 85, 28),
            "star": pygame.Rect(565, 46, 85, 28),
        }
        self.fill_custom_map_rect = pygame.Rect(self.WIDTH - 620, 14, 190, 36)
        self.finish_custom_map_rect = pygame.Rect(self.WIDTH - 210, 14, 190, 36)
        self.custom_dragging_territory_id: Optional[int] = None
        self.custom_drag_origin_cells: List[Tuple[int, int]] = []
        self.custom_drag_start_cell: Optional[Tuple[int, int]] = None
        self.custom_selected_territory_id: Optional[int] = None
        self.super_territory_ids: set[int] = set()
        self.ultra_super_territory_ids: set[int] = set()
        self.golden_territory_ids: set[int] = set()
        self.onu_player_id = -2
        self.sanctuary_territory_ids: set[int] = set()
        self.last_victory_reason = ""
        self.victory_winner: Optional[int] = None
        self.victory_summary: dict = {}
        self.replay_history: list[dict] = []
        self.replay_index = 0
        self.replay_next_frame_time = 0
        self.replay_paused = False
        self.replay_finished = False
        self.replay_restore_state: Optional[dict] = None
        self.confetti_particles: list[dict] = []
        self.last_special_conquest_message = ""
        self.last_empire_event_turn = 0

        self.player_money: dict[int, int] = {}
        self.precious_mineral_mine_ids: set[int] = set()
        self.fortress_territory_ids: set[int] = set()
        self.fortress_capture_counts: dict[int, int] = {}
        self.industry_territory_ids: set[int] = set()
        self.industry_capture_counts: dict[int, int] = {}
        self.factory_territory_ids: set[int] = set()
        self.airport_territory_ids: set[int] = set()
        self.port_territory_ids: set[int] = set()
        self.industrial_capture_counts: dict[int, int] = {}
        self.cultural_center_ages: dict[int, list[int]] = {}
        self.cultural_capture_counts: dict[int, int] = {}
        self.university_territory_ids: set[int] = set()
        self.university_capture_counts: dict[int, int] = {}
        self.university_ages: dict[int, int] = {}
        self.temple_territory_ids: set[int] = set()
        self.temple_capture_counts: dict[int, int] = {}
        self.player_science: dict[int, int] = {}
        self.culture_expansion_milestones: dict[int, int] = {}
        self.last_stand_bonus_players: set[int] = set()
        self.last_stand_bonus_territory: dict[int, set[int]] = {}
        self.tax_haven_turn_start_territory_counts: dict[int, int] = {}
        self.active_alliances: dict[tuple[int, int], int] = {}
        self.active_offensive_alliances: dict[tuple[int, int], tuple[int, int]] = {}
        self.active_ai_alliances: dict[tuple[int, int], int] = {}
        self.alliance_start_turns: dict[tuple[int, int], int] = {}
        self.offensive_alliance_start_turns: dict[tuple[int, int], int] = {}
        self.ai_alliance_start_turns: dict[tuple[int, int], int] = {}
        self.pending_offensive_alliance_ai: Optional[int] = None
        self.pending_gift_territory_id: Optional[int] = None
        self.pending_bridge_territory_id: Optional[int] = None
        self.last_alliance_break_message = ""
        self.recent_major_events: list[str] = []
        self.major_event_modal: Optional[dict] = None
        self.major_event_modal_queue: list[dict] = []
        self.pending_major_events_for_humans: dict[int, list[str]] = {}
        self.collecting_between_turn_events = False
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0
        self.geopolitical_panel_rect = pygame.Rect(120, 96, self.WIDTH - 240, self.HEIGHT - 150)
        self.geopolitical_panel_close_rect = pygame.Rect(self.WIDTH // 2 - 90, self.HEIGHT - 86, 180, 34)
        self.empire_panel_visible = False
        self.empire_panel_page = 0
        self.empire_panel_rect = pygame.Rect(80, 96, self.WIDTH - 160, self.HEIGHT - 150)
        self.empire_panel_close_rect = pygame.Rect(self.WIDTH // 2 - 90, self.HEIGHT - 86, 180, 34)

        self.shop_action: Optional[str] = None
        self.shop_mercenary_quantity = 1
        self.shop_gift_amount = 10
        self.hover_details_enabled = False
        self.pending_details_click_time: Optional[int] = None
        self.show_all_map_icons = False
        self.map_icon_view = "fortress"
        self.hovered_territory_id: Optional[int] = None
        self.hovered_territory_pos: Tuple[int, int] = (0, 0)
        # Le panneau complet sert uniquement a choisir une action.
        # Des qu'une action est choisie, il se reduit dans l'en-tete pour ne plus masquer la carte.
        self.shop_panel_collapsed = False
        self.setup_shop_ui_layout()

    def set_display_surface(self, fullscreen: bool, refresh_layout: bool = True) -> pygame.Surface:
        self.fullscreen = fullscreen
        display_info = pygame.display.Info()
        if fullscreen:
            self.WIDTH = max(self.WINDOWED_WIDTH, int(display_info.current_w or self.WINDOWED_WIDTH))
            self.HEIGHT = max(self.WINDOWED_HEIGHT, int(display_info.current_h or self.WINDOWED_HEIGHT))
            surface = pygame.display.set_mode((self.WIDTH, self.HEIGHT), pygame.FULLSCREEN)
        else:
            self.WIDTH, self.HEIGHT = self.windowed_size
            screen_width = max(self.WINDOWED_WIDTH, int(display_info.current_w or self.WINDOWED_WIDTH))
            screen_height = max(self.WINDOWED_HEIGHT, int(display_info.current_h or self.WINDOWED_HEIGHT))
            window_x = max(0, (screen_width - self.WINDOWED_WIDTH) // 2)
            window_y = max(0, (screen_height - self.WINDOWED_HEIGHT) // 2)
            os.environ["SDL_VIDEO_WINDOW_POS"] = f"{window_x},{window_y}"
            surface = pygame.display.set_mode(self.windowed_size)
        if refresh_layout and hasattr(self, "rows"):
            self.refresh_display_layout()
        return surface

    def toggle_fullscreen(self) -> None:
        self.screen = self.set_display_surface(not self.fullscreen)
        mode_label = "plein ecran" if self.fullscreen else "fenetre 1200x720"
        self.show_message(f"Affichage : {mode_label}.", 1800)

    def refresh_display_layout(self) -> None:
        self.end_turn_rect = pygame.Rect(self.WIDTH - 190, 14, 170, 36)
        self.geopolitical_button_rect = pygame.Rect(self.WIDTH - 190, 54, 112, 28)
        self.details_button_rect = pygame.Rect(self.WIDTH - 72, 54, 52, 28)
        self.all_icons_button_rect = pygame.Rect(self.WIDTH - 540, 58, 110, 24)
        self.save_map_rect = pygame.Rect(self.WIDTH - 600, 14, 170, 36)
        self.save_game_rect = pygame.Rect(self.WIDTH - 790, 14, 180, 36)
        self.auto_mode_rect = pygame.Rect(self.WIDTH - 400, 18, 170, 28)
        self.fast_ai_rect = pygame.Rect(self.WIDTH - 400, 54, 170, 28)
        self.replay_rect = pygame.Rect(self.WIDTH // 2 - 290, self.HEIGHT - 92, 270, 48)
        self.restart_rect = pygame.Rect(self.WIDTH // 2 + 20, self.HEIGHT - 92, 270, 48)
        self.replay_pause_rect = pygame.Rect(self.WIDTH - 410, 18, 170, 54)
        self.replay_return_rect = pygame.Rect(self.WIDTH - 230, 18, 210, 54)
        self.start_create_map_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 - 60, 380, 48)
        self.start_edit_map_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 - 4, 380, 48)
        self.start_game_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 + 52, 380, 48)
        self.start_load_game_rect = pygame.Rect(self.WIDTH // 2 - 190, self.HEIGHT // 2 + 108, 380, 48)
        self.editor_return_menu_rect = pygame.Rect(self.WIDTH - 410, 14, 180, 36)
        self.map_top = 90
        self.cell_width = self.WIDTH / self.cols
        self.cell_height = (self.HEIGHT - self.map_top - 8) / self.rows
        self.bridge_geometry_cache = {}
        self.custom_size_buttons = {
            "medium": pygame.Rect(18, 46, 100, 28),
            "large": pygame.Rect(128, 46, 90, 28),
            "immense": pygame.Rect(228, 46, 110, 28),
        }
        self.custom_shape_buttons = {
            "block": pygame.Rect(470, 46, 85, 28),
            "star": pygame.Rect(565, 46, 85, 28),
        }
        self.fill_custom_map_rect = pygame.Rect(self.WIDTH - 620, 14, 190, 36)
        self.finish_custom_map_rect = pygame.Rect(self.WIDTH - 210, 14, 190, 36)
        self.geopolitical_panel_rect = pygame.Rect(120, 96, self.WIDTH - 240, self.HEIGHT - 150)
        self.geopolitical_panel_close_rect = pygame.Rect(self.WIDTH // 2 - 90, self.HEIGHT - 86, 180, 34)
        self.empire_panel_rect = pygame.Rect(80, 96, self.WIDTH - 160, self.HEIGHT - 150)
        self.empire_panel_close_rect = pygame.Rect(self.WIDTH // 2 - 90, self.HEIGHT - 86, 180, 34)
        self.setup_shop_ui_layout()

    def show_message(self, text: str, duration_ms: int = 2000) -> None:
        self.message = text
        self.message_timer = pygame.time.get_ticks() + duration_ms

    def setup_shop_ui_layout(self) -> None:
        panel_width = 430
        panel_height = 620
        panel_x = self.WIDTH - panel_width - 20
        panel_y = 94
        self.shop_panel_rect = pygame.Rect(panel_x, panel_y, panel_width, panel_height)

        button_width = 188
        button_height = 31
        gap_x = 16
        gap_y = 5
        left_x = panel_x + 18
        right_x = left_x + button_width + gap_x
        row1_y = panel_y + 92
        row2_y = row1_y + button_height + gap_y
        row3_y = row2_y + button_height + gap_y
        row4_y = row3_y + button_height + gap_y
        row5_y = row4_y + button_height + gap_y

        row6_y = row5_y + button_height + gap_y
        row7_y = row6_y + button_height + gap_y
        row8_y = row7_y + button_height + gap_y
        row9_y = row8_y + button_height + gap_y
        row10_y = row9_y + button_height + gap_y
        row11_y = row10_y + button_height + gap_y
        row12_y = row11_y + button_height + gap_y

        self.shop_buttons = {
            "mercenaries": pygame.Rect(left_x, row1_y, button_width, button_height),
            "sell_territory": pygame.Rect(right_x, row1_y, button_width, button_height),
            "give_territory": pygame.Rect(left_x, row2_y, button_width, button_height),
            "gift_money": pygame.Rect(right_x, row2_y, button_width, button_height),
            "build_fortress": pygame.Rect(left_x, row3_y, button_width, button_height),
            "destroy_fortress": pygame.Rect(right_x, row3_y, button_width, button_height),
            "corrupt": pygame.Rect(left_x, row4_y, button_width, button_height),
            "revolt": pygame.Rect(right_x, row4_y, button_width, button_height),
            "build_factory": pygame.Rect(left_x, row5_y, button_width, button_height),
            "build_airport": pygame.Rect(right_x, row5_y, button_width, button_height),
            "build_port": pygame.Rect(left_x, row6_y, button_width, button_height),
            "build_temple": pygame.Rect(right_x, row6_y, button_width, button_height),
            "build_cultural_center": pygame.Rect(left_x, row7_y, button_width, button_height),
            "build_university": pygame.Rect(right_x, row7_y, button_width, button_height),
            "alliance": pygame.Rect(left_x, row8_y, button_width, button_height),
            "offensive_alliance": pygame.Rect(right_x, row8_y, button_width, button_height),
            "tax_haven_association": pygame.Rect(left_x, row9_y, button_width, button_height),
            "freeze_territory": pygame.Rect(right_x, row9_y, button_width, button_height),
            "release_sanctuary": pygame.Rect(left_x, row10_y, button_width, button_height),
            "change_capital": pygame.Rect(right_x, row10_y, button_width, button_height),
            "destroy_university": pygame.Rect(right_x, row11_y, button_width, button_height),
            "build_wonder": pygame.Rect(left_x, row11_y, button_width, button_height),
            "build_bridge": pygame.Rect(left_x, row12_y, button_width, button_height),
            "destroy_bridge": pygame.Rect(right_x, row12_y, button_width, button_height),
        }
        # Les controles +/- des mercenaires sont integres au bouton mercenaires :
        # le joueur voit directement "Mercenaires xN" avant de choisir le territoire.
        # Petite revolution ergonomique, donc naturellement deux rectangles minuscules.
        merc_rect = self.shop_buttons["mercenaries"]
        self.shop_minus_rect = pygame.Rect(merc_rect.right - 54, merc_rect.y + 7, 22, 24)
        self.shop_plus_rect = pygame.Rect(merc_rect.right - 28, merc_rect.y + 7, 22, 24)
        gift_rect = self.shop_buttons["gift_money"]
        self.shop_gift_minus_rect = pygame.Rect(gift_rect.right - 54, gift_rect.y + 7, 22, 24)
        self.shop_gift_plus_rect = pygame.Rect(gift_rect.right - 28, gift_rect.y + 7, 22, 24)
        self.finish_shopping_rect = pygame.Rect(panel_x + 18, panel_y + panel_height - 40, panel_width - 36, 30)
        self.shop_reopen_rect = pygame.Rect(self.WIDTH - 390, 52, 170, 28)
        self.shop_finish_compact_rect = pygame.Rect(self.WIDTH - 210, 52, 170, 28)


    @staticmethod
    def ask_int(prompt: str, min_val: int, max_val: int) -> int:
        """Demande un nombre via une petite fenetre, avec repli console."""
        if tk is not None and simpledialog is not None:
            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes("-topmost", True)
            except tk.TclError:
                pass
            try:
                value = simpledialog.askinteger(
                    "Configuration du jeu",
                    f"{prompt}\n\nValeur attendue : entre {min_val} et {max_val}.",
                    minvalue=min_val,
                    maxvalue=max_val,
                    parent=root,
                )
                if value is None:
                    if messagebox is not None:
                        messagebox.showinfo(
                            "Configuration du jeu",
                            f"Aucune valeur choisie. La valeur {min_val} sera utilisee.",
                            parent=root,
                        )
                    return min_val
                return int(value)
            finally:
                root.destroy()

        while True:
            try:
                value = int(input(prompt))
            except ValueError:
                print("Veuillez entrer un nombre entier.")
                continue
            if min_val <= value <= max_val:
                return value
            print(f"Veuillez entrer un nombre entre {min_val} et {max_val}.")

    def start_custom_map_editor(self) -> None:
        self.map_mode = "custom"
        self.loaded_map_payload = None
        self.editing_map_path = None
        self.super_territory_ids = set()
        self.ultra_super_territory_ids = set()
        self.sanctuary_territory_ids = set()
        self.phase = "map_editor"
        self.turn_phase = "attack"
        self.turn_move_count = 0
        self.current_player = 0
        self.turn = 1
        self.reset_custom_map_editor()
        self.show_message("Creation manuelle : choisissez une taille et une forme puis cliquez sur la mer.", 3200)

    def start_existing_map_editor(self) -> None:
        saved_maps = self.list_saved_maps()
        if not saved_maps:
            self.show_message("Aucune carte sauvegardee a modifier. Creez d'abord une carte.", 2600)
            return
        selected_path, payload = self.prompt_select_saved_map(saved_maps)
        if selected_path is None or payload is None:
            self.show_message("Chargement impossible : carte non modifiee.", 2600)
            return
        try:
            self.apply_saved_map(payload)
        except (KeyError, TypeError, ValueError, IndexError):
            self.show_message("Chargement impossible : format de carte invalide.", 3000)
            return

        # Une carte modifiee dans l'editeur devient une carte personnalisee.
        # Cela evite de trainer des liaisons speciales ou des modes de generation qui ne
        # correspondent plus a la geometrie editee. L'humanite survivra a cette trahison.
        self.map_mode = "custom"
        self.terre_links = []
        self.terre_link_points = {}
        self.recompute_neighbors_from_grid()
        self.loaded_map_payload = None
        self.editing_map_path = selected_path
        self.super_territory_ids = set()
        self.ultra_super_territory_ids = {terr.id for terr in self.territories if terr.reinforcement_bonus == 3}
        self.golden_territory_ids = set()
        self.sanctuary_territory_ids = set()
        self.phase = "map_editor"
        self.turn_phase = "attack"
        self.turn_move_count = 0
        self.current_player = 0
        self.turn = 1
        self.selected_source = None
        self.selected_target = None
        self.custom_dragging_territory_id = None
        self.custom_drag_origin_cells = []
        self.custom_drag_start_cell = None
        self.custom_selected_territory_id = None
        self.show_message(f"Modification de la carte {selected_path.stem}. Sauvegarder ecrasera cette carte.", 3600)

    def start_game_session(self) -> None:
        self.setup_players()
        if not self.running:
            return
        if self.loaded_map_payload is not None:
            try:
                self.apply_saved_map(self.loaded_map_payload)
            except (KeyError, TypeError, ValueError, IndexError):
                self.loaded_map_payload = None
                self.generate_grid_map()
                self.show_message("Chargement impossible : nouvelle carte generee a la place.", 3000)
        else:
            self.generate_grid_map()

        self.eliminated_human_players = set()
        self.human_controlled_players = set()
        self.prepare_initial_commercial_cities()
        self.assign_initial_ownership_and_armies()
        self.assign_random_bonus_territories()
        self.assign_golden_territories()
        self.assign_sanctuary_territories()
        self.reset_economy_state()
        self.assign_initial_economic_structures()
        self.last_victory_reason = ""
        self.victory_winner = None
        self.victory_summary = {}
        self.replay_history = []
        self.replay_restore_state = None
        self.confetti_particles = []
        self.phase = "playing"
        self.turn_phase = "attack"
        self.turn_move_count = 0
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0
        self.empire_panel_visible = False
        self.empire_panel_page = 0
        self.last_empire_event_turn = 0
        self.snapshot_tax_haven_turn_start_territory_counts()
        if self.map_mode == "continents":
            mode_label = "continents 20-35%"
        elif self.map_mode == "continents_45":
            mode_label = "continents 40-50%"
        elif self.map_mode == "terre":
            mode_label = "Terre"
        elif self.map_mode == "gigamega":
            mode_label = "GIGA/MEGA"
        elif self.map_mode == "custom":
            mode_label = "personnalisee"
        else:
            mode_label = "standard"
        tribes_label = " - Tribus" if self.tribes_mode else ""
        self.show_message(f"Debut de la partie - carte {mode_label} - mode {self.get_difficulty_label()}{tribes_label}", 2200)
        self.current_player = 0
        self.turn = 1
        self.selected_source = None
        self.selected_target = None
        self.record_replay_snapshot("Debut de la partie", force=True)
        self.begin_player_turn(self.current_player)

    @staticmethod
    def normalize_difficulty_level(raw_value) -> str:
        if isinstance(raw_value, str):
            value = raw_value.strip().lower().replace(" ", "_")
            if value == "chaos":
                return "chaos"
            if value in ("gouvernement_mondial", "world_government"):
                return "gouvernement_mondial"
        return "normal"

    def get_difficulty_label(self) -> str:
        labels = {
            "normal": "normal",
            "chaos": "chaos",
            "gouvernement_mondial": "gouvernement mondial",
        }
        return labels.get(self.difficulty_level, "normal")

    def get_onu_spawn_denominator(self) -> int:
        return 7 if self.difficulty_level == "gouvernement_mondial" else 10

    def get_onu_release_denominator(self) -> int:
        return 10 if self.difficulty_level == "gouvernement_mondial" else 15

    def setup_players(self) -> None:
        self.num_players = self.ask_int("Nombre de joueurs (2-10) : ", 2, 10)
        self.ai_player_count = self.ask_int(
            f"Combien de joueurs doivent etre controles par ordinateur ? (0-{self.num_players}) : ",
            0,
            self.num_players,
        )
        self.initial_num_players = self.num_players
        self.initial_ai_player_count = self.ai_player_count
        difficulty_choice = self.ask_int(
            "Mode de partie :\n"
            "1 - Normal\n"
            "2 - Chaos : revoltes et revolutions existantes, plus episodes aleatoires\n"
            "3 - Gouvernement mondial : ONU tres active, sans episodes de chaos\n\n"
            "Votre choix (1-3) : ",
            1,
            3,
        )
        if difficulty_choice == 2:
            self.difficulty_level = "chaos"
        elif difficulty_choice == 3:
            self.difficulty_level = "gouvernement_mondial"
        else:
            self.difficulty_level = "normal"
        self.tribes_mode = False
        if self.ai_player_count > 0:
            tribes_choice = self.ask_int(
                "Mode Tribus :\n"
                "1 - Non : tous les joueurs ont leurs territoires disperses aleatoirement\n"
                "2 - Oui : les joueurs IA commencent avec des territoires contigus, "
                "les joueurs humains restent disperses aleatoirement\n\n"
                "Votre choix (1-2) : ",
                1,
                2,
            )
            self.tribes_mode = tribes_choice == 2
        self.base_ai_players = set(range(self.ai_player_count))
        self.auto_controlled_players = set()
        self.commercial_city_players = set()
        self.commercial_city_capital_ids = {}
        self.player_capital_ids = {}
        self.pending_commercial_city_spawns = 0
        self.nation_players = set()
        self.nation_qualification_start_turns = {}
        self.nation_capital_loss_start_turns = {}
        self.nation_alliances = set()
        self.nation_wars = set()
        self.cold_war_active = False
        self.cold_war_nations = None
        self.cold_war_alliances = {}
        self.colonized_players = set()
        self.submitted_territory_ids = set()
        self.submitted_territory_overlords = {}
        self.submitted_territory_created_turns = {}
        self.vassal_territory_overlords = {}
        self.vassal_territory_created_turns = {}
        self.vassal_players = {}
        self.integrated_vassal_territories = {}
        self.integrated_submitted_territories = {}
        self.union_members = {}
        self.union_original_territories = {}
        self.final_duel_active = False
        self.final_duel_champions = None
        self.final_duel_alliances = {}
        self.final_duel_pending_winner = None
        self.assign_ai_personalities()
        self.setup_map_source()

    def setup_map_source(self) -> None:
        saved_maps = self.list_saved_maps()
        if saved_maps:
            choice = self.ask_int(
                "Source de la carte :\n"
                "1 - Generer une nouvelle carte\n"
                "2 - Charger une carte sauvegardee\n\n"
                "Votre choix (1-2) : ",
                1,
                2,
            )
            if choice == 2:
                payload = self.prompt_load_saved_map(saved_maps)
                if payload is not None:
                    self.loaded_map_payload = payload
                    self.map_mode = payload.get("map_mode", "standard")
                    return
                print("Chargement impossible, generation d'une nouvelle carte.")
        self.loaded_map_payload = None
        self.setup_map_options()

    def list_saved_maps(self) -> List[Path]:
        return sorted(self.saved_maps_dir.glob("*.json"))

    def prompt_select_saved_map(self, saved_maps: List[Path]) -> Tuple[Optional[Path], Optional[dict]]:
        choices = "\n".join(f"{idx} - {path.stem}" for idx, path in enumerate(saved_maps, start=1))
        choice = self.ask_int(
            f"Cartes sauvegardees disponibles :\n{choices}\n\nChoisissez une carte (1-{len(saved_maps)}) : ",
            1,
            len(saved_maps),
        )
        selected = saved_maps[choice - 1]
        try:
            return selected, json.loads(selected.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return selected, None

    def prompt_load_saved_map(self, saved_maps: List[Path]) -> Optional[dict]:
        _selected, payload = self.prompt_select_saved_map(saved_maps)
        return payload

    def build_map_payload(self) -> dict:
        return {
            "schema_version": self.SAVE_SCHEMA_VERSION,
            "kind": "map",
            "map_mode": self.map_mode,
            "rows": self.rows,
            "cols": self.cols,
            "grid_territory": self.grid_territory,
            "territories": [
                {
                    "id": terr.id,
                    "name": terr.name,
                    "cells": terr.cells,
                    "neighbors": terr.neighbors,
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
            "bridge_links": [list(link) for link in sorted(getattr(self, "bridge_links", set()))],
            "fragile_bridge_links": [
                list(link) for link in sorted(getattr(self, "fragile_bridge_links", set()))
            ],
            "bridge_link_points": [
                {
                    "a": a,
                    "b": b,
                    "start": list(start),
                    "end": list(end),
                }
                for (a, b), (start, end) in sorted(getattr(self, "bridge_link_points", {}).items())
            ],
        }

    def apply_saved_map(self, payload: dict) -> None:
        rows = payload.get("rows")
        cols = payload.get("cols")
        territories_data = payload.get("territories")
        grid = payload.get("grid_territory")

        if rows != self.rows or cols != self.cols:
            raise ValueError("Format de carte incompatible : dimensions invalides.")
        if not isinstance(territories_data, list) or not isinstance(grid, list) or len(grid) != self.rows:
            raise ValueError("Format de carte incompatible : contenu invalide.")

        normalized_grid: List[List[int]] = []
        for row in grid:
            if not isinstance(row, list) or len(row) != self.cols:
                raise ValueError("Format de carte incompatible : grille invalide.")
            normalized_grid.append([int(cell) for cell in row])

        raw_territories: dict[int, dict] = {}
        for terr_data in territories_data:
            terr_id = int(terr_data["id"])
            raw_territories[terr_id] = terr_data

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
        self.bridge_geometry_cache = {}
        self.bridge_coastal_cells_cache = {}

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

    def rebuild_terre_continents_from_layout(self) -> None:
        continent_ids = {}
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

    def save_current_map_to_file(self) -> str:
        existing = self.list_saved_maps()
        filename = f"carte_{len(existing) + 1:03d}.json"
        path = self.saved_maps_dir / filename
        while path.exists():
            filename = f"carte_{random.randint(100, 999)}.json"
            path = self.saved_maps_dir / filename
        path.write_text(json.dumps(self.build_map_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path.stem

    def build_game_payload(self) -> dict:
        map_payload = self.build_map_payload()
        return {
            **map_payload,
            "kind": "game",
            "num_players": self.num_players,
            "initial_num_players": self.initial_num_players or self.num_players,
            "ai_player_count": self.ai_player_count,
            "initial_ai_player_count": self.initial_ai_player_count or self.ai_player_count,
            "difficulty_level": self.difficulty_level,
            "tribes_mode": self.tribes_mode,
            "base_ai_players": list(self.base_ai_players),
            "auto_controlled_players": list(self.auto_controlled_players),
            "human_controlled_players": list(self.human_controlled_players),
            "eliminated_human_players": list(self.eliminated_human_players),
            "ai_personalities": {str(k): v for k, v in self.ai_personalities.items()},
            "ai_current_behavior": {str(k): v for k, v in self.ai_current_behavior.items()},
            "commercial_city_players": list(self.commercial_city_players),
            "commercial_city_capital_ids": {str(k): int(v) for k, v in self.commercial_city_capital_ids.items()},
            "player_capital_ids": {str(k): int(v) for k, v in getattr(self, "player_capital_ids", {}).items()},
            "pending_commercial_city_spawns": int(getattr(self, "pending_commercial_city_spawns", 0)),
            "nation_players": sorted(int(player) for player in getattr(self, "nation_players", set())),
            "nation_qualification_start_turns": {
                str(player): int(start_turn)
                for player, start_turn in getattr(self, "nation_qualification_start_turns", {}).items()
            },
            "nation_capital_loss_start_turns": {
                str(player): int(start_turn)
                for player, start_turn in getattr(self, "nation_capital_loss_start_turns", {}).items()
            },
            "nation_alliances": [
                {"a": int(a), "b": int(b)}
                for a, b in sorted(getattr(self, "nation_alliances", set()))
            ],
            "nation_wars": [
                {"a": int(a), "b": int(b)}
                for a, b in sorted(getattr(self, "nation_wars", set()))
            ],
            "cold_war_active": bool(getattr(self, "cold_war_active", False)),
            "cold_war_nations": list(getattr(self, "cold_war_nations", ()) or []),
            "cold_war_alliances": {
                str(player): int(camp)
                for player, camp in getattr(self, "cold_war_alliances", {}).items()
            },
            "colonized_players": sorted(int(player) for player in getattr(self, "colonized_players", set())),
            "submitted_territory_ids": sorted(int(tid) for tid in getattr(self, "submitted_territory_ids", set())),
            "submitted_territory_overlords": {
                str(tid): int(overlord)
                for tid, overlord in getattr(self, "submitted_territory_overlords", {}).items()
            },
            "submitted_territory_created_turns": {
                str(tid): int(created_turn)
                for tid, created_turn in getattr(self, "submitted_territory_created_turns", {}).items()
            },
            "vassal_territory_overlords": {
                str(tid): int(overlord)
                for tid, overlord in getattr(self, "vassal_territory_overlords", {}).items()
            },
            "vassal_territory_created_turns": {
                str(tid): int(created_turn)
                for tid, created_turn in getattr(self, "vassal_territory_created_turns", {}).items()
            },
            "vassal_players": {
                str(tid): int(player)
                for tid, player in getattr(self, "vassal_players", {}).items()
            },
            "integrated_vassal_territories": {
                str(player): sorted(int(tid) for tid in territory_ids)
                for player, territory_ids in getattr(self, "integrated_vassal_territories", {}).items()
            },
            "integrated_submitted_territories": {
                str(player): sorted(int(tid) for tid in territory_ids)
                for player, territory_ids in getattr(self, "integrated_submitted_territories", {}).items()
            },
            "union_members": {
                str(player): sorted(int(member) for member in members)
                for player, members in getattr(self, "union_members", {}).items()
            },
            "union_original_territories": {
                str(player): sorted(int(tid) for tid in territory_ids)
                for player, territory_ids in getattr(self, "union_original_territories", {}).items()
            },
            "final_duel_active": bool(getattr(self, "final_duel_active", False)),
            "final_duel_champions": list(getattr(self, "final_duel_champions", ()) or []),
            "final_duel_alliances": {
                str(player): int(champion)
                for player, champion in getattr(self, "final_duel_alliances", {}).items()
            },
            "final_duel_pending_winner": getattr(self, "final_duel_pending_winner", None),
            "fast_ai_movements": self.fast_ai_movements,
            "ai_speed_mode": self.ai_speed_mode,
            "current_player": self.current_player,
            "turn": self.turn,
            "turn_phase": self.turn_phase,
            "turn_move_count": self.turn_move_count,
            "last_empire_event_turn": self.last_empire_event_turn,
            "super_territory_ids": list(self.super_territory_ids),
            "ultra_super_territory_ids": list(self.ultra_super_territory_ids),
            "golden_territory_ids": list(self.golden_territory_ids),
            "sanctuary_territory_ids": list(self.sanctuary_territory_ids),
            "onu_player_id": self.onu_player_id,
            "player_money": {str(k): int(v) for k, v in self.player_money.items()},
            "precious_mineral_mine_ids": sorted(int(tid) for tid in self.precious_mineral_mine_ids),
            "fortress_territory_ids": list(self.fortress_territory_ids),
            "fortress_capture_counts": {str(k): int(v) for k, v in self.fortress_capture_counts.items()},
            "industry_territory_ids": list(self.factory_territory_ids),
            "industry_capture_counts": {str(k): int(v) for k, v in self.industrial_capture_counts.items() if k in self.factory_territory_ids},
            "factory_territory_ids": list(self.factory_territory_ids),
            "airport_territory_ids": list(self.airport_territory_ids),
            "port_territory_ids": list(self.port_territory_ids),
            "industrial_capture_counts": {str(k): int(v) for k, v in self.industrial_capture_counts.items()},
            "cultural_center_ages": {str(k): [int(age) for age in ages] for k, ages in self.cultural_center_ages.items()},
            "cultural_capture_counts": {str(k): int(v) for k, v in self.cultural_capture_counts.items()},
            "university_territory_ids": list(self.university_territory_ids),
            "university_capture_counts": {str(k): int(v) for k, v in self.university_capture_counts.items()},
            "university_ages": {str(k): int(v) for k, v in getattr(self, "university_ages", {}).items()},
            "temple_territory_ids": list(getattr(self, "temple_territory_ids", set())),
            "temple_capture_counts": {str(k): int(v) for k, v in getattr(self, "temple_capture_counts", {}).items()},
            "religion_founders": {str(player): int(religion_id) for player, religion_id in getattr(self, "religion_founders", {}).items()},
            "religion_foundation_turns": {str(religion_id): int(turn) for religion_id, turn in getattr(self, "religion_foundation_turns", {}).items()},
            "religion_last_spread_turns": {str(religion_id): int(turn) for religion_id, turn in getattr(self, "religion_last_spread_turns", {}).items()},
            "religion_holy_sites": {str(religion_id): int(tid) for religion_id, tid in getattr(self, "religion_holy_sites", {}).items()},
            "religious_influence": {str(tid): int(religion_id) for tid, religion_id in getattr(self, "religious_influence", {}).items()},
            "player_science": {str(k): int(v) for k, v in getattr(self, "player_science", {}).items()},
            "culture_expansion_milestones": {
                str(player): int(milestone)
                for player, milestone in getattr(self, "culture_expansion_milestones", {}).items()
            },
            "wonder_territories": {
                str(wonder_type): int(tid)
                for wonder_type, tid in getattr(self, "wonder_territories", {}).items()
            },
            "last_stand_bonus_players": list(self.last_stand_bonus_players),
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
                    "start_turn": int(self.alliance_start_turns.get((human, ai), max(1, expires_turn - self.ALLIANCE_DURATION_TURNS))),
                    "expires_turn": int(expires_turn),
                }
                for (human, ai), expires_turn in self.active_alliances.items()
            ],
            "active_ai_alliances": [
                {
                    "ai_a": int(ai_a),
                    "ai_b": int(ai_b),
                    "start_turn": int(self.ai_alliance_start_turns.get((ai_a, ai_b), max(1, expires_turn - self.ALLIANCE_DURATION_TURNS))),
                    "expires_turn": int(expires_turn),
                }
                for (ai_a, ai_b), expires_turn in self.active_ai_alliances.items()
            ],
            "active_offensive_alliances": [
                {
                    "human": int(human),
                    "ai": int(ai),
                    "target": int(target),
                    "start_turn": int(self.offensive_alliance_start_turns.get((human, ai), max(1, expires_turn - self.ALLIANCE_DURATION_TURNS))),
                    "expires_turn": int(expires_turn),
                }
                for (human, ai), (target, expires_turn) in self.active_offensive_alliances.items()
            ],
            "recent_major_events": list(self.recent_major_events[-8:]),
            "major_event_modal": self.major_event_modal,
            "major_event_modal_queue": list(self.major_event_modal_queue),
            "pending_major_events_for_humans": {
                str(player): list(events[-20:])
                for player, events in self.pending_major_events_for_humans.items()
                if events
            },
            "replay_history": list(getattr(self, "replay_history", [])[-self.MAX_REPLAY_SNAPSHOTS:]),
            "territories_state": [
                {
                    "id": terr.id,
                    "owner": terr.owner,
                    "regiments": terr.regiments,
                    "reinforcement_bonus": terr.reinforcement_bonus,
                }
                for terr in self.territories
            ],
        }

    def save_current_game_to_file(self) -> str:
        existing = sorted(self.saved_games_dir.glob("*.json"))
        filename = f"partie_{len(existing) + 1:03d}.json"
        path = self.saved_games_dir / filename
        while path.exists():
            filename = f"partie_{random.randint(100, 999)}.json"
            path = self.saved_games_dir / filename
        path.write_text(json.dumps(self.build_game_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path.stem

    def start_load_saved_game(self) -> None:
        saved_games = sorted(self.saved_games_dir.glob("*.json"))
        if not saved_games:
            self.show_message("Aucune partie sauvegardee dans 'parties_en_cours'.", 2600)
            return
        print("Parties sauvegardees disponibles :")
        for idx, path in enumerate(saved_games, start=1):
            print(f"{idx} - {path.stem}")
        choice = self.ask_int(f"Choisissez une partie (1-{len(saved_games)}) : ", 1, len(saved_games))
        selected = saved_games[choice - 1]
        try:
            payload = json.loads(selected.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.show_message("Chargement impossible : fichier invalide.", 2600)
            return
        try:
            self.apply_saved_game_state(payload)
        except Exception as exc:
            self.show_message(f"Chargement impossible : {exc}", 3000)
            return
        self.show_message(f"Partie '{selected.stem}' chargee - tour {self.turn}, joueur {self.current_player + 1}.", 3000)

    def apply_saved_game_state(self, payload: dict) -> None:
        # Restaure la geometrie de la carte (territoires, grille, liens)
        self.apply_saved_map(payload)

        # Joueurs et configuration IA
        self.num_players = int(payload["num_players"])
        self.initial_num_players = int(payload.get("initial_num_players", self.num_players))
        self.ai_player_count = int(payload.get("ai_player_count", 0))
        self.initial_ai_player_count = int(payload.get("initial_ai_player_count", self.ai_player_count))
        self.difficulty_level = self.normalize_difficulty_level(payload.get("difficulty_level", "normal"))
        self.tribes_mode = bool(payload.get("tribes_mode", False))
        self.base_ai_players = set(int(x) for x in payload.get("base_ai_players", []))
        self.auto_controlled_players = set(int(x) for x in payload.get("auto_controlled_players", []))
        self.human_controlled_players = set(int(x) for x in payload.get("human_controlled_players", []))
        self.eliminated_human_players = set(int(x) for x in payload.get("eliminated_human_players", []))
        self.ai_personalities = {int(k): v for k, v in payload.get("ai_personalities", {}).items()}
        self.ai_current_behavior = {int(k): v for k, v in payload.get("ai_current_behavior", {}).items()}
        self.commercial_city_players = set(int(x) for x in payload.get("commercial_city_players", []))
        self.commercial_city_capital_ids = {int(k): int(v) for k, v in payload.get("commercial_city_capital_ids", {}).items()}
        self.player_capital_ids = {int(k): int(v) for k, v in payload.get("player_capital_ids", {}).items()}
        self.pending_commercial_city_spawns = max(0, int(payload.get("pending_commercial_city_spawns", 0)))
        self.nation_players = set(int(x) for x in payload.get("nation_players", []))
        self.nation_qualification_start_turns = {
            int(k): max(1, int(v))
            for k, v in payload.get("nation_qualification_start_turns", {}).items()
        }
        self.nation_capital_loss_start_turns = {
            int(k): max(1, int(v))
            for k, v in payload.get("nation_capital_loss_start_turns", {}).items()
        }
        # Regles nationales simplifiees : plus de diplomatie nationale speciale,
        # plus de guerre froide et plus de colonisation, y compris au chargement
        # d'anciennes sauvegardes.
        self.nation_alliances = set()
        self.nation_wars = set()
        self.cold_war_active = False
        self.cold_war_nations = None
        self.cold_war_alliances = {}
        self.colonized_players = set()
        self.submitted_territory_ids = set(int(x) for x in payload.get("submitted_territory_ids", []))
        self.submitted_territory_overlords = {
            int(k): int(v) for k, v in payload.get("submitted_territory_overlords", {}).items()
        }
        self.submitted_territory_created_turns = {
            int(k): max(1, int(v)) for k, v in payload.get("submitted_territory_created_turns", {}).items()
        }
        # La vassalisation est supprimee : les anciens marqueurs de vassaux ne sont
        # plus restaures depuis les sauvegardes.
        self.vassal_territory_overlords = {}
        self.vassal_territory_created_turns = {}
        self.vassal_players = {}
        self.integrated_vassal_territories = {}
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
        self.last_victory_reason = ""
        self.selected_source = None
        self.selected_target = None

        # Territoires speciaux
        self.super_territory_ids = set(int(x) for x in payload.get("super_territory_ids", []))
        self.ultra_super_territory_ids = set(int(x) for x in payload.get("ultra_super_territory_ids", []))
        self.golden_territory_ids = set(int(x) for x in payload.get("golden_territory_ids", []))
        self.onu_player_id = int(payload.get("onu_player_id", -2))
        self.sanctuary_territory_ids = set(int(x) for x in payload.get("sanctuary_territory_ids", []))
        self.player_money = {int(k): int(v) for k, v in payload.get("player_money", {}).items()}
        self.precious_mineral_mine_ids = set(int(x) for x in payload.get("precious_mineral_mine_ids", []))
        has_economic_structures = "fortress_territory_ids" in payload or "industry_territory_ids" in payload
        self.fortress_territory_ids = set(int(x) for x in payload.get("fortress_territory_ids", []))
        self.fortress_capture_counts = {int(k): int(v) for k, v in payload.get("fortress_capture_counts", {}).items()}
        legacy_industries = set(int(x) for x in payload.get("industry_territory_ids", []))
        self.factory_territory_ids = set(int(x) for x in payload.get("factory_territory_ids", legacy_industries))
        self.airport_territory_ids = set(int(x) for x in payload.get("airport_territory_ids", []))
        self.port_territory_ids = set(int(x) for x in payload.get("port_territory_ids", []))
        self.industry_territory_ids = set(self.factory_territory_ids)
        legacy_counts = {int(k): int(v) for k, v in payload.get("industry_capture_counts", {}).items()}
        self.industrial_capture_counts = {int(k): int(v) for k, v in payload.get("industrial_capture_counts", legacy_counts).items()}
        self.industry_capture_counts = {tid: self.industrial_capture_counts.get(tid, 0) for tid in self.factory_territory_ids}
        self.cultural_center_ages = {int(k): [int(age) for age in ages] for k, ages in payload.get("cultural_center_ages", {}).items()}
        self.cultural_capture_counts = {int(k): int(v) for k, v in payload.get("cultural_capture_counts", {}).items()}
        self.university_territory_ids = set(int(x) for x in payload.get("university_territory_ids", []))
        self.university_capture_counts = {int(k): int(v) for k, v in payload.get("university_capture_counts", {}).items()}
        self.university_ages = {int(k): max(0, int(v)) for k, v in payload.get("university_ages", {}).items()}
        self.temple_territory_ids = set(int(x) for x in payload.get("temple_territory_ids", []))
        self.temple_capture_counts = {int(k): int(v) for k, v in payload.get("temple_capture_counts", {}).items()}
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
            # Anciennes sauvegardes : l'etat d'influence est deja restaure. Le compteur
            # repart donc du tour charge afin d'eviter une expansion immediate indue.
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
        self.pending_wonder_type = None
        # Le statut paradis fiscal depend du proprietaire des capitales.
        # On le garde donc en attente jusqu'a la restauration des owners, sinon
        # sanitize_economy_state() le supprime en voyant des territoires encore sans proprietaire.
        saved_last_stand_bonus_players = set(int(x) for x in payload.get("last_stand_bonus_players", []))
        saved_last_stand_bonus_territory = self.normalize_tax_haven_capital_payload(payload.get("last_stand_bonus_territory", {}))
        self.tax_haven_turn_start_territory_counts = {
            int(k): int(v)
            for k, v in payload.get("tax_haven_turn_start_territory_counts", {}).items()
        }
        self.last_stand_bonus_players = set()
        self.last_stand_bonus_territory = {}
        self.active_alliances = {}
        self.alliance_start_turns = {}
        for item in payload.get("active_alliances", []):
            try:
                human = int(item["human"])
                ai = int(item["ai"])
                expires_turn = int(item["expires_turn"])
                start_turn = int(item.get("start_turn", max(1, expires_turn - self.ALLIANCE_DURATION_TURNS)))
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
                start_turn = int(item.get("start_turn", max(1, expires_turn - self.ALLIANCE_DURATION_TURNS)))
            except (KeyError, TypeError, ValueError):
                continue
            key = self.normalize_ai_alliance_key(ai_a, ai_b)
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
                start_turn = int(item.get("start_turn", max(1, expires_turn - self.ALLIANCE_DURATION_TURNS)))
            except (KeyError, TypeError, ValueError):
                continue
            self.active_offensive_alliances[(human, ai)] = (target, expires_turn)
            self.offensive_alliance_start_turns[(human, ai)] = start_turn
        self.pending_offensive_alliance_ai = None
        self.pending_gift_territory_id = None
        self.pending_bridge_territory_id = None
        self.last_alliance_break_message = ""
        self.recent_major_events = [str(item) for item in payload.get("recent_major_events", [])][-8:]
        raw_modal = payload.get("major_event_modal")
        self.major_event_modal = self.sanitize_major_event_modal(raw_modal)
        self.major_event_modal_queue = [
            modal
            for modal in (
                self.sanitize_major_event_modal(item)
                for item in payload.get("major_event_modal_queue", [])
            )
            if modal is not None
        ]
        self.pending_major_events_for_humans = {
            int(player): [" ".join(str(event).split()) for event in events if str(event).strip()][-20:]
            for player, events in payload.get("pending_major_events_for_humans", {}).items()
            if isinstance(events, list)
        }
        self.collecting_between_turn_events = False
        raw_replay_history = payload.get("replay_history", [])
        self.replay_history = [item for item in raw_replay_history if isinstance(item, dict)][-self.MAX_REPLAY_SNAPSHOTS:]
        self.replay_index = 0
        self.replay_paused = False
        self.replay_finished = False
        self.replay_restore_state = None
        self.victory_winner = None
        self.victory_summary = {}
        self.confetti_particles = []
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0
        self.empire_panel_visible = False
        self.empire_panel_page = 0
        if not self.player_money:
            self.player_money = {player: 0 for player in range(self.num_players)}
        if not has_economic_structures:
            self.assign_initial_economic_structures()

        # Etat par territoire (owner, regiments, reinforcement_bonus)
        territories_state = {int(ts["id"]): ts for ts in payload.get("territories_state", [])}
        for terr in self.territories:
            ts = territories_state.get(terr.id)
            if ts is None:
                raise ValueError(f"Etat manquant pour le territoire {terr.id}.")
            terr.owner = int(ts["owner"])
            terr.regiments = int(ts["regiments"])
            terr.reinforcement_bonus = int(ts.get("reinforcement_bonus", 1))

        self.sanitize_economy_state()
        self.sanitize_player_capitals()
        self.enforce_golden_territory_onu_immunity()

        self.last_stand_bonus_players = saved_last_stand_bonus_players
        self.last_stand_bonus_territory = saved_last_stand_bonus_territory
        self.refresh_last_stand_bonus_state()
        self.sanitize_religion_state()
        if not self.tax_haven_turn_start_territory_counts:
            self.snapshot_tax_haven_turn_start_territory_counts()
        self.phase = "playing"
        if not self.replay_history:
            self.record_replay_snapshot(f"Reprise de la partie au tour {self.turn}", force=True)
        self.reset_ai_turn_state()

    def assign_random_bonus_territories(self) -> None:
        self.super_territory_ids = set()
        self.ultra_super_territory_ids = set()
        for terr in self.territories:
            terr.reinforcement_bonus = 1
        if not self.territories:
            return
        territory_ids = list(range(len(self.territories)))
        random.shuffle(territory_ids)
        ultra_count = min(4, len(territory_ids))
        ultra_ids = territory_ids[:ultra_count]
        for tid in ultra_ids:
            self.territories[tid].reinforcement_bonus = 3
        self.ultra_super_territory_ids = set(ultra_ids)

    def maybe_spawn_scheduled_resources(self) -> list[str]:
        return moteur_regles.maybe_spawn_scheduled_resources(self)


    def setup_map_options(self) -> None:
        map_choice = self.ask_int(
            "Type de carte :\n"
            "1 - Carte standard\n"
            "2 - Carte continents (entre 20% et 35% d'eau)\n"
            "3 - Carte continents (entre 40% et 50% d'eau)\n"
            "4 - Carte Terre (5 grands continents lisibles et bien separes)\n"
            "5 - Carte GIGA/MEGA (grand archipel dense inspire des cartes sauvegardees)\n\n"
            "Votre choix (1-5) : ",
            1,
            5,
        )
        if map_choice == 1:
            self.map_mode = "standard"
            self.setup_water_density()
        elif map_choice == 2:
            self.map_mode = "continents"
            self.min_water_ratio = self.continent_min_water_ratio
            self.max_water_ratio = self.continent_max_water_ratio
            print("Mode continent : quantite d'eau fixee automatiquement (entre 20% et 35% de la carte).")
        elif map_choice == 3:
            self.map_mode = "continents_45"
            self.min_water_ratio = self.continent_dense_min_water_ratio
            self.max_water_ratio = self.continent_dense_max_water_ratio
            print("Mode continent : quantite d'eau fixee automatiquement (entre 40% et 50% de la carte).")
        elif map_choice == 4:
            self.map_mode = "terre"
            self.min_water_ratio = 0.34
            self.max_water_ratio = 0.50
            print("Mode Terre : 5 grands continents lisibles, entre 34% et 50% d'eau, avec mers plus nettes et liaisons centre-a-centre.")
        else:
            self.map_mode = "gigamega"
            self.min_water_ratio = 0.46
            self.max_water_ratio = 0.58
            print("Mode GIGA/MEGA : 80 a 100 territoires, archipel dense, passages etroits, environ 46% a 58% d'eau.")

    def setup_water_density(self) -> None:
        choice = self.ask_int(
            "Choix de la quantite d'eau :\n"
            "1 - Tres peu d'eau (entre 10% et 20% des cases)\n"
            "2 - Peu d'eau (entre 20% et 40% des cases)\n"
            "3 - Eaux normales (entre 40% et 60% des cases)\n"
            "4 - Beaucoup d'eau (entre 60% et 70% des cases)\n\n"
            "Votre choix (1-4) : ",
            1,
            4,
        )
        if choice == 1:
            self.min_water_ratio = 0.10
            self.max_water_ratio = 0.20
        elif choice == 2:
            self.min_water_ratio = 0.20
            self.max_water_ratio = 0.40
        elif choice == 3:
            self.min_water_ratio = 0.40
            self.max_water_ratio = 0.60
        else:
            self.min_water_ratio = 0.60
            self.max_water_ratio = 0.70

    def assign_ai_personalities(self) -> None:
        """Attribue des profils differencies aux joueurs controles par ordinateur."""
        self.ai_personalities = {}
        self.ai_current_behavior = {}
        profiles = ["standard", "aggressive", "defensive", "variable"]
        labels = {
            "standard": "standard",
            "aggressive": "agressif",
            "defensive": "defensif",
            "variable": "variable",
        }
        ai_players = sorted(self.base_ai_players)
        for index, player in enumerate(ai_players):
            # Repartition deterministe sur les quatre familles pour eviter une partie composee
            # uniquement de clones. Le hasard gouverne deja assez de choses comme ca.
            self.ai_personalities[player] = profiles[index % len(profiles)]
        if ai_players:
            summary = ", ".join(f"J{player + 1}={labels[self.ai_personalities[player]]}" for player in ai_players)
            print(f"Profils IA : {summary}")

    def assign_ai_personality_to_player(self, player: int, profile: Optional[str] = None) -> None:
        profiles = ["standard", "aggressive", "defensive", "variable"]
        self.ai_personalities[player] = profile if profile in profiles else random.choice(profiles)
        self.ai_current_behavior.pop(player, None)

    def get_ai_personality(self, player: int) -> str:
        return moteur_regles.get_ai_personality(self, player)

    def get_ai_behavior(self, player: int) -> str:
        if self.is_commercial_city_player(player):
            return "aggressive"
        if self.is_ai_player(player) and player in self.last_stand_bonus_players:
            return "defensive"
        profile = self.get_ai_personality(player)
        if profile == "variable":
            return self.ai_current_behavior.get(player, "standard")
        return profile

    def get_ai_profile_label(self, player: int, include_current: bool = True) -> str:
        labels = {
            "standard": "standard",
            "aggressive": "agressif",
            "defensive": "defensif",
            "variable": "variable",
        }
        profile = self.get_ai_personality(player)
        if profile == "variable" and include_current:
            behavior = self.get_ai_behavior(player)
            return f"variable/{labels.get(behavior, behavior)}"
        return labels.get(profile, profile)

    def prepare_ai_behavior_for_turn(self, player: int) -> None:
        moteur_regles.prepare_ai_behavior_for_turn(self, player)


    def is_potential_commercial_city_player(self, player: int) -> bool:
        return player in self.commercial_city_players

    def is_commercial_city_player(self, player: int) -> bool:
        if player not in self.commercial_city_players:
            return False
        capital_id = self.get_commercial_city_capital_id(player)
        return capital_id is not None

    def get_commercial_city_capital_id(self, player: int) -> Optional[int]:
        capital_id = self.commercial_city_capital_ids.get(player)
        if capital_id is not None:
            if 0 <= capital_id < len(self.territories) and self.territories[capital_id].owner == player:
                return capital_id
            return None
        owned = sorted(terr.id for terr in self.territories if terr.owner == player)
        if not owned:
            return None
        # Compatibilite avec les anciennes sauvegardes : si aucune capitale CC n'etait
        # stockee, on fige le plus ancien territoire encore possede. Pas parfait, mais
        # nettement mieux que transformer tout le portefeuille immobilier en paradis fiscal.
        capital_id = owned[0]
        self.commercial_city_capital_ids[player] = capital_id
        return capital_id

    def is_commercial_city_definitively_destroyed(self, player: int) -> bool:
        if player not in self.commercial_city_players:
            return False
        capital_id = self.commercial_city_capital_ids.get(player)
        if capital_id is None or not (0 <= capital_id < len(self.territories)):
            return True
        return self.territories[capital_id].owner != player

    def schedule_commercial_city_replacement_if_destroyed(self, player: int) -> Optional[str]:
        if not self.is_commercial_city_definitively_destroyed(player):
            return None
        vassal_ids = [
            tid for tid, vassal_player in getattr(self, "vassal_players", {}).items()
            if vassal_player == player
        ]
        self.commercial_city_players.discard(player)
        self.commercial_city_capital_ids.pop(player, None)
        self.last_stand_bonus_players.discard(player)
        self.last_stand_bonus_territory.pop(player, None)
        for tid in vassal_ids:
            self.vassal_territory_overlords.pop(tid, None)
            self.vassal_territory_created_turns.pop(tid, None)
            self.vassal_players.pop(tid, None)
        self.assign_ai_personality_to_player(player, "standard")
        if vassal_ids:
            message = f"J{player + 1} perd son statut de vassal : aucune Cite commercante de remplacement n'apparait."
        else:
            self.pending_commercial_city_spawns = max(0, getattr(self, "pending_commercial_city_spawns", 0)) + 1
            message = (
                f"J{player + 1} perd definitivement son statut de Cite commercante. "
                "Une nouvelle Cite commercante apparaitra au debut du prochain tour."
            )
        self.record_major_event(message)
        return message

    def refresh_destroyed_commercial_cities(self) -> List[str]:
        messages: List[str] = []
        for player in sorted(list(self.commercial_city_players)):
            message = self.schedule_commercial_city_replacement_if_destroyed(player)
            if message:
                messages.append(message)
        return messages

    def spawn_pending_commercial_cities(self) -> List[str]:
        return moteur_regles.spawn_pending_commercial_cities(self)

    def is_commercial_city_capital(self, territory_id: int) -> bool:
        if not (0 <= territory_id < len(self.territories)):
            return False
        owner = self.territories[territory_id].owner
        return self.is_commercial_city_player(owner) and self.get_commercial_city_capital_id(owner) == territory_id

    def is_commercial_city_territory(self, territory_id: int) -> bool:
        return self.is_commercial_city_capital(territory_id)

    def is_territory_adjacent_to_player(self, territory_id: int, player: int) -> bool:
        if not (0 <= territory_id < len(self.territories)):
            return False
        return any(
            0 <= neighbor_id < len(self.territories)
            and self.territories[neighbor_id].owner == player
            for neighbor_id in self.territories[territory_id].neighbors
        )

    def prepare_initial_commercial_cities(self) -> None:
        """Ajoute les cites commercantes comme joueurs IA autonomes apres les joueurs choisis."""
        self.commercial_city_players = set()
        self.commercial_city_capital_ids = {}
        self.pending_commercial_city_spawns = 0
        for _ in range(self.INITIAL_COMMERCIAL_CITY_COUNT):
            player = self.num_players
            self.num_players += 1
            self.base_ai_players.add(player)
            self.human_controlled_players.discard(player)
            self.auto_controlled_players.discard(player)
            self.commercial_city_players.add(player)
            self.assign_ai_personality_to_player(player, "aggressive")
            self.ensure_player_economy(player)

    def is_ai_player(self, player: int) -> bool:
        if player < 0 or self.is_onu_player(player):
            return False
        return (player in self.base_ai_players or player in self.auto_controlled_players) and player not in self.human_controlled_players

    def can_toggle_auto_mode(self, player: int) -> bool:
        return player >= 0 and not self.is_onu_player(player)

    def is_auto_mode_enabled_for_player(self, player: int) -> bool:
        return self.is_ai_player(player)

    def set_auto_mode_for_player(self, player: int, enabled: bool) -> None:
        if not self.can_toggle_auto_mode(player):
            return
        if enabled:
            self.human_controlled_players.discard(player)
            if player not in self.base_ai_players:
                self.auto_controlled_players.add(player)
            self.assign_ai_personality_to_player(player, "standard")
            if player == self.current_player and self.phase == "playing":
                self.show_message(f"Joueur {player + 1} passe en mode IA.", 1800)
        else:
            self.auto_controlled_players.discard(player)
            self.human_controlled_players.add(player)
            self.ai_personalities.pop(player, None)
            self.ai_current_behavior.pop(player, None)
            if player == self.current_player and self.phase == "playing":
                self.show_message(f"Joueur {player + 1} passe en mode humain.", 1800)
                self.selected_source = None
                self.selected_target = None
                self.turn_phase = "attack"
        if player == self.current_player:
            self.reset_ai_turn_state()

    def toggle_current_player_auto_mode(self) -> None:
        player = self.current_player
        if not self.can_toggle_auto_mode(player):
            return
        self.set_auto_mode_for_player(player, not self.is_ai_player(player))

    def reset_ai_turn_state(self) -> None:
        if self.phase != "playing":
            self.ai_state = "idle"
            return
        if self.is_ai_player(self.current_player):
            self.prepare_ai_behavior_for_turn(self.current_player)
            self.ai_state = "announce"
            self.ai_next_action_time = pygame.time.get_ticks() + self.get_ai_initial_delay_ms()
        else:
            self.ai_state = "idle"

    def generate_territory_names(self, count: int) -> List[str]:
        syllables = [
            "ba", "be", "bi", "bo", "bu", "ca", "ce", "ci", "co", "cu",
            "da", "de", "di", "do", "du", "fa", "fe", "fi", "fo", "ga",
            "ge", "gi", "go", "ha", "ke", "ki", "ko", "la", "le", "li",
            "lo", "ma", "me", "mi", "mo", "na", "ne", "ni", "no", "pa",
            "pe", "pi", "po", "ra", "re", "ri", "ro", "sa", "se", "si",
            "so", "ta", "te", "ti", "to", "va", "ve", "vi", "vo", "za",
        ]
        names: List[str] = []
        seen = set()
        while len(names) < count:
            pattern = random.choice([(2, 2, 1), (1, 2, 2), (2, 1, 2)])
            raw = "".join(random.choice(syllables)[:size] for size in pattern)
            candidate = raw[:5].capitalize()
            if len(candidate) == 5 and candidate.isalpha() and candidate not in seen:
                names.append(candidate)
                seen.add(candidate)
        return names

    def neighbors4(self, r: int, c: int):
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < self.rows and 0 <= nc < self.cols:
                yield nr, nc

    def toroidal_neighbors4(self, r: int, c: int):
        yielded = set()
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr = (r + dr) % self.rows
            nc = (c + dc) % self.cols
            if (nr, nc) not in yielded:
                yielded.add((nr, nc))
                yield nr, nc

    def iter_adjacency_neighbors(self, r: int, c: int):
        if self.map_mode == "custom":
            yield from self.toroidal_neighbors4(r, c)
        else:
            yield from self.neighbors4(r, c)

    def wrap_cell(self, row: int, col: int) -> Tuple[int, int]:
        return row % self.rows, col % self.cols

    def toroidal_delta(self, a: int, b: int, size: int) -> int:
        delta = a - b
        half = size / 2
        if delta > half:
            delta -= size
        elif delta < -half:
            delta += size
        return delta


    def rebuild_cells_from_grid(self) -> None:
        cells_by_tid: dict[int, List[Tuple[int, int]]] = {terr.id: [] for terr in self.territories}
        for r in range(self.rows):
            for c in range(self.cols):
                tid = self.grid_territory[r][c]
                if tid in cells_by_tid:
                    cells_by_tid[tid].append((r, c))
        for terr in self.territories:
            terr.cells = cells_by_tid.get(terr.id, [])

    def recompute_neighbors_from_grid(self) -> None:
        if not self.territories:
            return
        valid_ids = {terr.id for terr in self.territories}
        neighbor_sets = {terr.id: set() for terr in self.territories}
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
        for a, b in getattr(self, "bridge_links", set()):
            if 0 <= a < len(self.territories) and 0 <= b < len(self.territories) and a != b:
                self.territories[a].neighbors = sorted(set(self.territories[a].neighbors) | {b})
                self.territories[b].neighbors = sorted(set(self.territories[b].neighbors) | {a})

    def get_bridge_coastal_cells(self, territory_id: int) -> List[Tuple[int, int]]:
        cache = getattr(self, "bridge_coastal_cells_cache", None)
        if cache is None:
            self.bridge_coastal_cells_cache = {}
            cache = self.bridge_coastal_cells_cache
        if territory_id in cache:
            return cache[territory_id]
        if not (0 <= territory_id < len(self.territories)):
            return []
        coastal = [
            (row, col)
            for row, col in self.territories[territory_id].cells
            if any(self.grid_territory[nr][nc] < 0 for nr, nc in self.neighbors4(row, col))
        ]
        cache[territory_id] = coastal
        return coastal

    def bridge_segment_is_over_water(
        self,
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
            row = max(0, min(self.rows - 1, int(round(start[0] + dr * ratio))))
            col = max(0, min(self.cols - 1, int(round(start[1] + dc * ratio))))
            territory_id = self.grid_territory[row][col]
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
        self, territory_a: int, territory_b: int
    ) -> Optional[Tuple[Tuple[int, int], Tuple[int, int]]]:
        key = tuple(sorted((int(territory_a), int(territory_b))))
        cache = getattr(self, "bridge_geometry_cache", None)
        if cache is None:
            self.bridge_geometry_cache = {}
            cache = self.bridge_geometry_cache
        if key in cache:
            return cache[key]
        a, b = key
        if a == b or not (0 <= a < len(self.territories) and 0 <= b < len(self.territories)):
            cache[key] = None
            return None
        coast_a = self.get_bridge_coastal_cells(a)
        coast_b = self.get_bridge_coastal_cells(b)
        if not coast_a or not coast_b:
            cache[key] = None
            return None

        min_row_a, max_row_a = min(row for row, _col in coast_a), max(row for row, _col in coast_a)
        min_col_a, max_col_a = min(col for _row, col in coast_a), max(col for _row, col in coast_a)
        min_row_b, max_row_b = min(row for row, _col in coast_b), max(row for row, _col in coast_b)
        min_col_b, max_col_b = min(col for _row, col in coast_b), max(col for _row, col in coast_b)
        row_gap = max(0, min_row_b - max_row_a, min_row_a - max_row_b) * self.cell_height
        col_gap = max(0, min_col_b - max_col_a, min_col_a - max_col_b) * self.cell_width
        if math.hypot(row_gap, col_gap) > self.BRIDGE_MAX_LENGTH_PX:
            cache[key] = None
            return None

        max_distance_sq = self.BRIDGE_MAX_LENGTH_PX ** 2
        possible_pairs: List[Tuple[float, Tuple[int, int], Tuple[int, int]]] = []
        for cell_a in coast_a:
            ax = (cell_a[1] + 0.5) * self.cell_width
            ay = (cell_a[0] + 0.5) * self.cell_height
            for cell_b in coast_b:
                bx = (cell_b[1] + 0.5) * self.cell_width
                by = (cell_b[0] + 0.5) * self.cell_height
                distance_sq = (bx - ax) ** 2 + (by - ay) ** 2
                if distance_sq <= max_distance_sq:
                    possible_pairs.append((distance_sq, cell_a, cell_b))
        possible_pairs.sort(key=lambda item: item[0])
        for _distance_sq, start, end in possible_pairs:
            if self.bridge_segment_is_over_water(a, b, start, end):
                cache[key] = (start, end)
                return cache[key]
        cache[key] = None
        return None

    def get_valid_bridge_candidates(
        self,
    ) -> List[Tuple[Tuple[int, int], Tuple[Tuple[int, int], Tuple[int, int]]]]:
        candidates = []
        for territory_a in range(len(self.territories)):
            for territory_b in range(territory_a + 1, len(self.territories)):
                key = (territory_a, territory_b)
                if territory_b in self.territories[territory_a].neighbors or key in self.bridge_links:
                    continue
                points = self.find_bridge_connection_points(territory_a, territory_b)
                if points is not None:
                    candidates.append((key, points))
        return candidates

    def get_territory_graph_distance(self, start: int, target: int) -> int:
        if start == target:
            return 0
        visited = {start}
        frontier = [(start, 0)]
        while frontier:
            current, distance = frontier.pop(0)
            for neighbor in self.territories[current].neighbors:
                if neighbor == target:
                    return distance + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append((neighbor, distance + 1))
        return len(self.territories) + 1

    def add_bridge(
        self,
        key: Tuple[int, int],
        points: Tuple[Tuple[int, int], Tuple[int, int]],
        fragile: bool = False,
    ) -> None:
        normalized = tuple(sorted(key))
        if not hasattr(self, "fragile_bridge_links"):
            self.fragile_bridge_links = set()
        self.bridge_links.add(normalized)
        self.bridge_link_points[normalized] = points
        if fragile:
            self.fragile_bridge_links.add(normalized)
        else:
            self.fragile_bridge_links.discard(normalized)
        self.apply_bridge_links_to_neighbors()

    def remove_bridge(self, key: Tuple[int, int]) -> None:
        normalized = tuple(sorted(key))
        if not hasattr(self, "fragile_bridge_links"):
            self.fragile_bridge_links = set()
        self.bridge_links.discard(normalized)
        self.fragile_bridge_links.discard(normalized)
        self.bridge_link_points.pop(normalized, None)
        self.recompute_neighbors_from_grid()

    def maybe_spawn_random_bridge(self) -> Optional[str]:
        return moteur_regles.maybe_spawn_random_bridge(self, self.cell_width, self.cell_height)

    def maybe_collapse_fragile_bridges(self) -> Optional[str]:
        return moteur_regles.maybe_collapse_fragile_bridges(self)

    def expand_cell_buffer(self, cells: set[Tuple[int, int]], radius: int) -> set[Tuple[int, int]]:
        frontier = set(cells)
        expanded = set(cells)
        for _ in range(radius):
            new_frontier: set[Tuple[int, int]] = set()
            for r, c in frontier:
                for nr, nc in self.neighbors4(r, c):
                    if (nr, nc) not in expanded:
                        new_frontier.add((nr, nc))
            expanded.update(new_frontier)
            frontier = new_frontier
        return expanded

    def choose_terre_centers(self, count: int = 5) -> List[Tuple[int, int]]:
        templates = [
            [(0.13, 0.12), (0.18, 0.56), (0.13, 0.88), (0.78, 0.22), (0.82, 0.82)],
            [(0.14, 0.22), (0.16, 0.78), (0.48, 0.50), (0.82, 0.18), (0.84, 0.80)],
            [(0.12, 0.34), (0.14, 0.82), (0.50, 0.12), (0.58, 0.62), (0.84, 0.86)],
            [(0.16, 0.12), (0.34, 0.54), (0.12, 0.88), (0.80, 0.28), (0.84, 0.86)],
        ]
        points = random.choice(templates)
        if random.random() < 0.5:
            points = [(r, 1.0 - c) for r, c in points]
        if random.random() < 0.5:
            points = [(1.0 - r, c) for r, c in points]
        centers: List[Tuple[int, int]] = []
        for r_norm, c_norm in points[:count]:
            row = int(12 + r_norm * (self.rows - 24) + random.randint(-3, 3))
            col = int(14 + c_norm * (self.cols - 28) + random.randint(-4, 4))
            row = max(12, min(self.rows - 13, row))
            col = max(14, min(self.cols - 15, col))
            centers.append((row, col))
        return centers

    def partition_cells_into_balanced_territories(
        self,
        cells: set[Tuple[int, int]],
        territory_count: int,
    ) -> Tuple[List[List[Tuple[int, int]]], List[set[int]]]:
        import heapq

        cell_list = list(cells)
        cell_set = set(cells)
        if len(cell_list) < territory_count:
            raise ValueError("Pas assez de cases pour partitionner le continent.")

        seeds = [random.choice(cell_list)]
        while len(seeds) < territory_count:
            best = max(
                cell_list,
                key=lambda cell: min(abs(cell[0] - seed[0]) + abs(cell[1] - seed[1]) for seed in seeds),
            )
            seeds.append(best)

        total = len(cell_list)
        base = total // territory_count
        targets = [base] * territory_count
        for i in range(total - base * territory_count):
            targets[i] += 1

        assigned: dict[Tuple[int, int], int] = {}
        regions: List[set[Tuple[int, int]]] = [set() for _ in range(territory_count)]
        frontiers: List[list[Tuple[int, int, float, Tuple[int, int]]]] = [[] for _ in range(territory_count)]

        def push_candidate(tid: int, cell: Tuple[int, int]) -> None:
            same = sum((nr, nc) in regions[tid] for nr, nc in self.neighbors4(*cell))
            distance = abs(cell[0] - seeds[tid][0]) + abs(cell[1] - seeds[tid][1])
            heapq.heappush(frontiers[tid], (-same, distance, random.random(), cell))

        for tid, seed in enumerate(seeds):
            assigned[seed] = tid
            regions[tid].add(seed)

        for tid, seed in enumerate(seeds):
            for nr, nc in self.neighbors4(*seed):
                if (nr, nc) in cell_set and (nr, nc) not in assigned:
                    push_candidate(tid, (nr, nc))

        while len(assigned) < total:
            candidate_ids = [tid for tid in range(territory_count) if frontiers[tid]]
            if not candidate_ids:
                break
            preferred = [tid for tid in candidate_ids if len(regions[tid]) < targets[tid]]
            if preferred:
                candidate_ids = preferred
            tid = min(candidate_ids, key=lambda idx: (len(regions[idx]) / max(1, targets[idx]), len(regions[idx])))

            picked: Optional[Tuple[int, int]] = None
            while frontiers[tid]:
                _, _, _, cell = heapq.heappop(frontiers[tid])
                if cell not in assigned:
                    picked = cell
                    break
            if picked is None:
                continue

            assigned[picked] = tid
            regions[tid].add(picked)
            for nr, nc in self.neighbors4(*picked):
                if (nr, nc) in cell_set and (nr, nc) not in assigned:
                    push_candidate(tid, (nr, nc))

        for cell in cell_list:
            if cell in assigned:
                continue
            adjacent_regions = [assigned[(nr, nc)] for nr, nc in self.neighbors4(*cell) if (nr, nc) in assigned]
            if adjacent_regions:
                counts = {tid: adjacent_regions.count(tid) for tid in set(adjacent_regions)}
                tid = max(counts, key=lambda idx: (counts[idx], -len(regions[idx])))
            else:
                tid = min(
                    range(territory_count),
                    key=lambda idx: abs(cell[0] - seeds[idx][0]) + abs(cell[1] - seeds[idx][1]),
                )
            assigned[cell] = tid
            regions[tid].add(cell)

        territory_neighbors: List[set[int]] = [set() for _ in range(territory_count)]
        for cell, tid in assigned.items():
            for nr, nc in self.neighbors4(*cell):
                other = assigned.get((nr, nc))
                if other is not None and other != tid:
                    territory_neighbors[tid].add(other)

        territories_cells = [sorted(list(region)) for region in regions]
        return territories_cells, territory_neighbors

    def get_boundary_cell_towards(self, territory_id: int, target_row: float, target_col: float) -> Tuple[int, int]:
        territory = self.territories[territory_id]
        if not territory.cells:
            return (0, 0)
        center_row, center_col = self.get_territory_center(territory_id)
        dir_row = target_row - center_row
        dir_col = target_col - center_col
        boundary = [
            (r, c)
            for r, c in territory.cells
            if any(self.grid_territory[nr][nc] != territory_id for nr, nc in self.neighbors4(r, c))
        ]
        if not boundary:
            boundary = territory.cells
        return max(
            boundary,
            key=lambda cell: (
                (cell[0] - center_row) * dir_row + (cell[1] - center_col) * dir_col,
                -(abs(cell[0] - target_row) + abs(cell[1] - target_col)),
            ),
        )

    def register_terre_link(
        self,
        terr_a: int,
        terr_b: int,
        start: Optional[Tuple[int, int]] = None,
        end: Optional[Tuple[int, int]] = None,
    ) -> None:
        if terr_a == terr_b:
            return
        key = tuple(sorted((terr_a, terr_b)))
        if key in self.terre_links:
            return
        self.terre_links.append(key)
        if start is not None and end is not None:
            self.terre_link_points[key] = (start, end)

    def dig_land_corridor(self, mask: List[List[bool]], start: Tuple[int, int], end: Tuple[int, int], width: int = 1) -> None:
        r, c = start
        er, ec = end
        while (r, c) != (er, ec):
            for wr in range(-width, width + 1):
                for wc in range(-width, width + 1):
                    nr, nc = r + wr, c + wc
                    if 0 <= nr < self.rows and 0 <= nc < self.cols:
                        mask[nr][nc] = True
            if abs(er - r) >= abs(ec - c):
                r += 1 if er > r else -1 if er < r else 0
            else:
                c += 1 if ec > c else -1 if ec < c else 0

    def build_continents_land_mask(self) -> List[List[bool]]:
        total_cells = self.rows * self.cols
        if self.map_mode == "continents_45":
            min_water = self.continent_dense_min_water_ratio
            max_water = self.continent_dense_max_water_ratio
        else:
            min_water = self.continent_min_water_ratio
            max_water = self.continent_max_water_ratio

        target_water_ratio = random.uniform(min_water, max_water)
        target_land_cells = int(total_cells * (1.0 - target_water_ratio))
        margin = 4

        def neighbors8(r: int, c: int):
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < self.rows and 0 <= nc < self.cols:
                        yield nr, nc

        def paint_disc(mask: List[List[bool]], center_r: float, center_c: float, radius: int) -> int:
            added = 0
            rr = int(round(center_r))
            cc = int(round(center_c))
            for ar in range(-radius, radius + 1):
                for ac in range(-radius, radius + 1):
                    nr, nc = rr + ar, cc + ac
                    if margin <= nr < self.rows - margin and margin <= nc < self.cols - margin:
                        dist = abs(ar) + abs(ac) * random.uniform(0.65, 1.35)
                        if dist <= radius + random.uniform(0.0, 1.0):
                            if not mask[nr][nc]:
                                mask[nr][nc] = True
                                added += 1
            return added

        def coastal_cells(mask: List[List[bool]], land: bool) -> List[Tuple[int, int]]:
            cells: List[Tuple[int, int]] = []
            for r in range(margin, self.rows - margin):
                for c in range(margin, self.cols - margin):
                    if mask[r][c] != land:
                        continue
                    opposite = sum(1 for nr, nc in neighbors8(r, c) if mask[nr][nc] != land)
                    if opposite >= 1:
                        cells.append((r, c))
            random.shuffle(cells)
            return cells

        def dig_water_channel(mask: List[List[bool]], start: Tuple[int, int], steps: int, width: int) -> None:
            r = float(start[0])
            c = float(start[1])
            dr = random.uniform(-1.0, 1.0)
            dc = random.uniform(-1.0, 1.0)
            if abs(dr) + abs(dc) < 0.2:
                dc = 1.0
            for _ in range(steps):
                rr = int(round(r))
                cc = int(round(c))
                brush = width + (1 if random.random() < 0.22 else 0)
                for ar in range(-brush, brush + 1):
                    for ac in range(-brush, brush + 1):
                        nr, nc = rr + ar, cc + ac
                        if margin <= nr < self.rows - margin and margin <= nc < self.cols - margin:
                            if abs(ar) + abs(ac) * random.uniform(0.7, 1.25) <= brush + random.uniform(0.0, 0.8):
                                mask[nr][nc] = False
                if random.random() < 0.45:
                    dr += random.uniform(-0.85, 0.85)
                    dc += random.uniform(-0.85, 0.85)
                norm = max(0.8, (dr * dr + dc * dc) ** 0.5)
                dr /= norm
                dc /= norm
                r = min(self.rows - margin - 1, max(margin, r + dr * random.uniform(0.9, 1.7)))
                c = min(self.cols - margin - 1, max(margin, c + dc * random.uniform(0.9, 1.9)))

        best_mask = None
        best_gap = None

        for _attempt in range(6):
            mask = [[False for _ in range(self.cols)] for _ in range(self.rows)]
            continent_count = random.randint(4, 6)
            centers: List[Tuple[int, int]] = []
            band_width = (self.cols - 2 * margin) // continent_count
            for idx in range(continent_count):
                band_left = margin + idx * band_width
                band_right = margin + (idx + 1) * band_width - 1
                centers.append((
                    random.randint(self.rows // 5, 4 * self.rows // 5),
                    random.randint(max(margin + 3, band_left + 2), min(self.cols - margin - 4, max(band_left + 2, band_right - 2))),
                ))

            weights = [random.uniform(0.85, 1.2) for _ in range(continent_count)]
            total_weight = sum(weights)
            continent_targets = [max(450, int(target_land_cells * w / total_weight)) for w in weights]
            current_land = 0

            for idx, (sr, sc) in enumerate(centers):
                target = continent_targets[idx]
                walkers = []
                arm_count = random.randint(6, 9)
                for _ in range(arm_count):
                    angle = random.uniform(0.0, 6.28318)
                    walkers.append({
                        "r": float(sr),
                        "c": float(sc),
                        "dr": random.uniform(-0.8, 0.8) + 0.9 * __import__('math').sin(angle),
                        "dc": random.uniform(-0.8, 0.8) + 0.9 * __import__('math').cos(angle),
                        "budget": random.randint(60, 110),
                        "radius": random.randint(2, 4),
                        "branch_chance": random.uniform(0.05, 0.11),
                    })

                continent_land = 0
                branch_budget = 24
                step_budget = min(2200, max(900, target * 2))

                while walkers and continent_land < target and step_budget > 0:
                    walker = walkers.pop(random.randrange(len(walkers)))
                    r = walker["r"]
                    c = walker["c"]
                    dr = walker["dr"]
                    dc = walker["dc"]
                    radius = walker["radius"]
                    budget = walker["budget"]

                    while budget > 0 and continent_land < target and step_budget > 0:
                        painted = paint_disc(mask, r, c, radius)
                        continent_land += painted
                        current_land += painted

                        if budget > 18 and branch_budget > 0 and random.random() < walker["branch_chance"]:
                            walkers.append({
                                "r": r,
                                "c": c,
                                "dr": dr + random.uniform(-1.1, 1.1),
                                "dc": dc + random.uniform(-1.1, 1.1),
                                "budget": random.randint(18, max(22, budget // 2)),
                                "radius": max(1, radius - random.choice([0, 1])),
                                "branch_chance": walker["branch_chance"] * 0.75,
                            })
                            branch_budget -= 1

                        if random.random() < 0.60:
                            dr += random.uniform(-0.95, 0.95)
                            dc += random.uniform(-0.95, 0.95)
                        norm = max(0.75, (dr * dr + dc * dc) ** 0.5)
                        dr /= norm
                        dc /= norm
                        r = min(self.rows - margin - 1, max(margin, r + dr * random.uniform(0.9, 1.7)))
                        c = min(self.cols - margin - 1, max(margin, c + dc * random.uniform(0.9, 1.9)))
                        if random.random() < 0.18:
                            radius = max(1, min(4, radius + random.choice([-1, 0, 1])))
                        budget -= 1
                        step_budget -= 1

            bridge_pairs = []
            ordered = list(range(len(centers)))
            for i in range(len(ordered) - 1):
                bridge_pairs.append((ordered[i], ordered[i + 1]))
            extra_links = random.randint(2, 4)
            for _ in range(extra_links):
                a = random.randrange(len(centers))
                b = random.randrange(len(centers))
                if a != b:
                    bridge_pairs.append((a, b))
            for a, b in bridge_pairs:
                if random.random() < 0.85:
                    self.dig_land_corridor(mask, centers[a], centers[b], width=1)
                    if random.random() < 0.45:
                        mid = (
                            max(margin, min(self.rows - margin - 1, (centers[a][0] + centers[b][0]) // 2 + random.randint(-10, 10))),
                            max(margin, min(self.cols - margin - 1, (centers[a][1] + centers[b][1]) // 2 + random.randint(-14, 14))),
                        )
                        self.dig_land_corridor(mask, centers[a], mid, width=1)
                        self.dig_land_corridor(mask, mid, centers[b], width=1)

            water_cuts = random.randint(12, 18) if self.map_mode != "continents_45" else random.randint(16, 24)
            for _ in range(water_cuts):
                anchor = random.choice(centers)
                start = (
                    max(margin, min(self.rows - margin - 1, anchor[0] + random.randint(-18, 18))),
                    max(margin, min(self.cols - margin - 1, anchor[1] + random.randint(-24, 24))),
                )
                dig_water_channel(mask, start, random.randint(10, 24), random.randint(1, 2))

            for r in range(self.rows):
                for c in range(self.cols):
                    if r < 2 or r >= self.rows - 2 or c < 2 or c >= self.cols - 2:
                        mask[r][c] = False

            current_land = sum(1 for r in range(self.rows) for c in range(self.cols) if mask[r][c])
            delta = target_land_cells - current_land
            if delta > 0:
                added = 0
                for r, c in coastal_cells(mask, False):
                    if added >= delta:
                        break
                    land_neighbors = sum(1 for nr, nc in neighbors8(r, c) if mask[nr][nc])
                    if land_neighbors >= 2:
                        mask[r][c] = True
                        added += 1
            elif delta < 0:
                removed = 0
                for r, c in coastal_cells(mask, True):
                    if removed >= -delta:
                        break
                    water_neighbors = sum(1 for nr, nc in neighbors8(r, c) if not mask[nr][nc])
                    if water_neighbors >= 4:
                        mask[r][c] = False
                        removed += 1

            water_ratio = sum(1 for r in range(self.rows) for c in range(self.cols) if not mask[r][c]) / total_cells
            gap = 0.0
            if water_ratio < min_water:
                gap = min_water - water_ratio
            elif water_ratio > max_water:
                gap = (water_ratio - max_water) * 2.0

            if best_gap is None or gap < best_gap:
                best_gap = gap
                best_mask = [row[:] for row in mask]

            if min_water <= water_ratio <= max_water:
                return mask

        if best_mask is not None:
            return best_mask
        return self.build_connected_land_mask()

    def build_connected_land_mask(self) -> List[List[bool]]:
        total_cells = self.rows * self.cols

        def land_components(grid: List[List[bool]]) -> List[List[Tuple[int, int]]]:
            land = [(r, c) for r in range(self.rows) for c in range(self.cols) if grid[r][c]]
            if not land:
                return []
            seen = set()
            comps: List[List[Tuple[int, int]]] = []
            for cell in land:
                if cell in seen:
                    continue
                stack = [cell]
                comp: List[Tuple[int, int]] = []
                seen.add(cell)
                while stack:
                    cr, cc = stack.pop()
                    comp.append((cr, cc))
                    for nr, nc in self.neighbors4(cr, cc):
                        if grid[nr][nc] and (nr, nc) not in seen:
                            seen.add((nr, nc))
                            stack.append((nr, nc))
                comps.append(comp)
            return comps

        for _ in range(18):
            target_water_ratio = random.uniform(self.min_water_ratio, self.max_water_ratio)
            target_water_cells = int(total_cells * target_water_ratio)

            mask = [[True for _ in range(self.cols)] for _ in range(self.rows)]
            margin = 7
            water_count = 0

            def set_water(r: int, c: int) -> None:
                nonlocal water_count
                if mask[r][c]:
                    mask[r][c] = False
                    water_count += 1

            def set_land(r: int, c: int) -> None:
                nonlocal water_count
                if not mask[r][c]:
                    mask[r][c] = True
                    water_count -= 1

            def carve_water_path(start: Tuple[int, int], orientation: str, width: int, steps: int) -> None:
                r, c = start
                direction = random.choice([-1, 1])
                bridge_every = random.randint(10, 16)
                for step in range(steps):
                    if water_count >= target_water_cells:
                        return

                    if orientation == "horizontal":
                        c += direction
                        if c <= margin or c >= self.cols - margin - 1:
                            direction *= -1
                            c += direction
                        if step % random.randint(4, 7) == 0:
                            r += random.choice([-1, 0, 1])
                    else:
                        r += direction
                        if r <= margin or r >= self.rows - margin - 1:
                            direction *= -1
                            r += direction
                        if step % random.randint(4, 7) == 0:
                            c += random.choice([-1, 0, 1])

                    r = max(margin, min(self.rows - margin - 1, r))
                    c = max(margin, min(self.cols - margin - 1, c))

                    if step % bridge_every in (0, 1):
                        continue

                    for wr in range(-width, width + 1):
                        for wc in range(-width - 1, width + 2):
                            nr, nc = r + wr, c + wc
                            if margin <= nr < self.rows - margin and margin <= nc < self.cols - margin:
                                stretch = 0.6 if orientation == "horizontal" else 1.0
                                distance = abs(wr) + abs(wc) * stretch
                                if distance <= width + random.uniform(0.1, 0.9):
                                    set_water(nr, nc)

            path_count = random.randint(6, 10)
            for i in range(path_count):
                horizontal = i % 2 == 0
                if horizontal:
                    start = (
                        random.randint(margin + 6, self.rows - margin - 7),
                        random.randint(self.cols // 6, 5 * self.cols // 6),
                    )
                    steps = random.randint(self.cols // 3, int(self.cols * 1.1))
                    carve_water_path(start, "horizontal", random.randint(1, 3), steps)
                else:
                    start = (
                        random.randint(self.rows // 6, 5 * self.rows // 6),
                        random.randint(margin + 8, self.cols - margin - 9),
                    )
                    steps = random.randint(self.rows // 3, int(self.rows * 1.1))
                    carve_water_path(start, "vertical", random.randint(1, 3), steps)

            extra_attempts = 0
            while water_count < target_water_cells and extra_attempts < 220:
                extra_attempts += 1
                r = random.randint(margin + 4, self.rows - margin - 5)
                c = random.randint(margin + 4, self.cols - margin - 5)
                orientation = random.choice(["horizontal", "vertical"])
                if not mask[r][c]:
                    carve_water_path(
                        (r, c),
                        orientation,
                        random.randint(1, 3),
                        random.randint(min(self.rows, self.cols) // 8, min(self.rows, self.cols) // 2),
                    )
                else:
                    carve_water_path(
                        (r, c),
                        orientation,
                        random.randint(1, 2),
                        random.randint(min(self.rows, self.cols) // 10, min(self.rows, self.cols) // 3),
                    )

            for r in range(self.rows):
                for c in range(self.cols):
                    if r < margin - 2 or r >= self.rows - (margin - 2) or c < margin - 2 or c >= self.cols - (margin - 2):
                        set_land(r, c)

            comps = land_components(mask)
            while len(comps) > 1:
                base = comps[0]
                others = [cell for comp in comps[1:] for cell in comp]
                best = None
                for a in random.sample(base, min(len(base), 90)):
                    for b in random.sample(others, min(len(others), 90)):
                        dist = abs(a[0] - b[0]) + abs(a[1] - b[1])
                        if best is None or dist < best[0]:
                            best = (dist, a, b)
                _, a, b = best
                self.dig_land_corridor(mask, a, b, width=1)
                comps = land_components(mask)

            current_ratio = sum(1 for r in range(self.rows) for c in range(self.cols) if not mask[r][c]) / total_cells
            if self.min_water_ratio <= current_ratio <= self.max_water_ratio:
                return mask

        raise RuntimeError("Generation de la carte trop lente ou bloquee : essayez une option avec moins d'eau.")

    def generate_ellipse_island(self, center_row: int, center_col: int, radius_row: int, radius_col: int) -> set[Tuple[int, int]]:
        # Nom conserve pour eviter de casser le reste du code, mais ici on genere
        # un continent organique avec lobes, peninsules et baies.
        min_r = max(2, center_row - radius_row - 16)
        max_r = min(self.rows - 3, center_row + radius_row + 16)
        min_c = max(2, center_col - radius_col - 18)
        max_c = min(self.cols - 3, center_col + radius_col + 18)
        cells: set[Tuple[int, int]] = set()

        def paint_disc(rr: float, cc: float, brush_r: float, brush_c: float, jitter: float = 0.25) -> None:
            for r in range(max(min_r, int(rr - brush_r - 2)), min(max_r + 1, int(rr + brush_r + 3))):
                for c in range(max(min_c, int(cc - brush_c - 2)), min(max_c + 1, int(cc + brush_c + 3))):
                    nr = (r - rr) / max(1.0, brush_r * random.uniform(1.0 - jitter, 1.0 + jitter))
                    nc = (c - cc) / max(1.0, brush_c * random.uniform(1.0 - jitter, 1.0 + jitter))
                    if nr * nr + nc * nc <= random.uniform(0.82, 1.20):
                        cells.add((r, c))

        major_angle = random.uniform(-0.55, 0.55)
        major_dr = math.sin(major_angle)
        major_dc = math.cos(major_angle)
        spine_len = random.randint(4, 6)
        step = random.uniform(5.5, 7.5)
        rr = float(center_row) - major_dr * step * (spine_len - 1) / 2
        cc = float(center_col) - major_dc * step * (spine_len - 1) / 2

        for i in range(spine_len):
            t = i / max(1, spine_len - 1)
            local_r = radius_row * random.uniform(0.72, 1.05) * (0.92 + 0.25 * math.sin(t * math.pi))
            local_c = radius_col * random.uniform(0.62, 0.96) * (0.92 + 0.18 * math.cos(t * math.pi))
            paint_disc(rr, cc, local_r, local_c)

            side_count = random.randint(1, 3)
            for _ in range(side_count):
                side_angle = major_angle + random.choice([-1, 1]) * random.uniform(0.75, 1.45)
                side_dist = random.uniform(2.0, max(radius_row, radius_col) * 0.55)
                lobe_r = rr + math.sin(side_angle) * side_dist
                lobe_c = cc + math.cos(side_angle) * side_dist
                paint_disc(
                    lobe_r,
                    lobe_c,
                    local_r * random.uniform(0.35, 0.62),
                    local_c * random.uniform(0.28, 0.56),
                    jitter=0.35,
                )

            rr += major_dr * step + random.uniform(-1.8, 1.8)
            cc += major_dc * step + random.uniform(-2.4, 2.4)

        peninsula_count = random.randint(3, 5)
        for _ in range(peninsula_count):
            angle = major_angle + random.uniform(-2.4, 2.4)
            pr = float(center_row) + math.sin(angle) * random.uniform(radius_row * 0.35, radius_row * 0.85)
            pc = float(center_col) + math.cos(angle) * random.uniform(radius_col * 0.35, radius_col * 0.85)
            length = random.randint(7, 15)
            width_r = random.uniform(1.8, 3.8)
            width_c = random.uniform(2.2, 4.6)
            drift = angle + random.uniform(-0.35, 0.35)
            for _step in range(length):
                paint_disc(pr, pc, width_r, width_c, jitter=0.40)
                pr += math.sin(drift) * random.uniform(1.0, 1.8)
                pc += math.cos(drift) * random.uniform(1.1, 2.0)
                drift += random.uniform(-0.28, 0.28)
                width_r = max(1.2, width_r * random.uniform(0.90, 0.98))
                width_c = max(1.4, width_c * random.uniform(0.90, 0.98))
                if pr < min_r + 2 or pr > max_r - 2 or pc < min_c + 2 or pc > max_c - 2:
                    break

        # Creuse quelques baies pour casser l'effet "bulle".
        for _ in range(random.randint(3, 6)):
            angle = random.uniform(0.0, math.tau)
            bay_r = center_row + math.sin(angle) * random.uniform(radius_row * 0.55, radius_row * 1.1)
            bay_c = center_col + math.cos(angle) * random.uniform(radius_col * 0.55, radius_col * 1.1)
            bay_rr = random.uniform(radius_row * 0.18, radius_row * 0.34)
            bay_cc = random.uniform(radius_col * 0.18, radius_col * 0.34)
            for r in range(max(min_r, int(bay_r - bay_rr - 2)), min(max_r + 1, int(bay_r + bay_rr + 3))):
                for c in range(max(min_c, int(bay_c - bay_cc - 2)), min(max_c + 1, int(bay_c + bay_cc + 3))):
                    nr = (r - bay_r) / max(1.0, bay_rr * random.uniform(0.85, 1.15))
                    nc = (c - bay_c) / max(1.0, bay_cc * random.uniform(0.85, 1.15))
                    if nr * nr + nc * nc <= random.uniform(0.75, 1.15):
                        cells.discard((r, c))

        # Lissage leger sans effacer les irregularites.
        for _ in range(3):
            additions: set[Tuple[int, int]] = set()
            removals: set[Tuple[int, int]] = set()
            for r in range(min_r, max_r + 1):
                for c in range(min_c, max_c + 1):
                    count = sum((nr, nc) in cells for nr, nc in self.neighbors4(r, c))
                    if (r, c) in cells:
                        if count <= 1:
                            removals.add((r, c))
                    elif count >= 3 and random.random() < 0.55:
                        additions.add((r, c))
            cells.difference_update(removals)
            cells.update(additions)

        if not cells:
            cells.add((center_row, center_col))
        anchor = min(cells, key=lambda cell: abs(cell[0] - center_row) + abs(cell[1] - center_col))
        return self.extract_connected_component(cells, anchor)

    def extract_connected_component(self, cells: set[Tuple[int, int]], start: Tuple[int, int]) -> set[Tuple[int, int]]:
        stack = [start]
        seen: set[Tuple[int, int]] = set()
        while stack:
            cell = stack.pop()
            if cell in seen or cell not in cells:
                continue
            seen.add(cell)
            for neighbor in self.neighbors4(*cell):
                if neighbor in cells and neighbor not in seen:
                    stack.append(neighbor)
        return seen

    def choose_island_boundary_cell(self, cells: set[Tuple[int, int]], direction: str) -> Tuple[int, int]:
        boundary = []
        for r, c in cells:
            if any((nr, nc) not in cells for nr, nc in self.neighbors4(r, c)):
                boundary.append((r, c))
        if not boundary:
            boundary = list(cells)
        if direction == "right":
            return max(boundary, key=lambda cell: (cell[1], -abs(cell[0])))
        if direction == "left":
            return min(boundary, key=lambda cell: (cell[1], abs(cell[0])))
        if direction == "down":
            return max(boundary, key=lambda cell: (cell[0], -abs(cell[1])))
        return min(boundary, key=lambda cell: (cell[0], abs(cell[1])))

    def get_territory_center(self, territory_id: int) -> Tuple[float, float]:
        territory = self.territories[territory_id]
        if territory.cells:
            if self.map_mode == "custom":
                row_angles = [2 * math.pi * (r + 0.5) / self.rows for r, _ in territory.cells]
                col_angles = [2 * math.pi * (c + 0.5) / self.cols for _, c in territory.cells]
                avg_row_angle = math.atan2(sum(math.sin(a) for a in row_angles), sum(math.cos(a) for a in row_angles))
                avg_col_angle = math.atan2(sum(math.sin(a) for a in col_angles), sum(math.cos(a) for a in col_angles))
                if avg_row_angle < 0:
                    avg_row_angle += 2 * math.pi
                if avg_col_angle < 0:
                    avg_col_angle += 2 * math.pi
                avg_row = (avg_row_angle / (2 * math.pi)) * self.rows - 0.5
                avg_col = (avg_col_angle / (2 * math.pi)) * self.cols - 0.5
                return avg_row % self.rows, avg_col % self.cols
            avg_row = sum(r for r, _ in territory.cells) / len(territory.cells)
            avg_col = sum(c for _, c in territory.cells) / len(territory.cells)
            return avg_row, avg_col
        for r in range(self.rows):
            for c in range(self.cols):
                if self.grid_territory[r][c] == territory_id:
                    return float(r), float(c)
        return 0.0, 0.0

    def get_territory_center_cell(self, territory_id: int) -> Tuple[int, int]:
        territory = self.territories[territory_id]
        if not territory.cells:
            return (0, 0)
        center_row, center_col = self.get_territory_center(territory_id)
        return min(
            territory.cells,
            key=lambda cell: (
                abs(cell[0] - center_row) + abs(cell[1] - center_col),
                (cell[0] - center_row) ** 2 + (cell[1] - center_col) ** 2,
            ),
        )

    def choose_facing_territory(self, territory_ids: List[int], direction: str) -> int:
        def key_right(tid: int):
            row, col = self.get_territory_center(tid)
            return (col, -abs(row))
        def key_left(tid: int):
            row, col = self.get_territory_center(tid)
            return (col, abs(row))
        def key_down(tid: int):
            row, col = self.get_territory_center(tid)
            return (row, -abs(col))
        def key_up(tid: int):
            row, col = self.get_territory_center(tid)
            return (row, abs(col))
        if direction == "right":
            return max(territory_ids, key=key_right)
        if direction == "left":
            return min(territory_ids, key=key_left)
        if direction == "down":
            return max(territory_ids, key=key_down)
        return min(territory_ids, key=key_up)

    def partition_cells_into_territories(self, cells: set[Tuple[int, int]], territory_count: int) -> Tuple[List[List[Tuple[int, int]]], List[set[int]]]:
        cell_list = list(cells)
        random.shuffle(cell_list)
        centers = []
        for cell in cell_list:
            if all(abs(cell[0] - sr) + abs(cell[1] - sc) >= 8 for sr, sc in centers):
                centers.append(cell)
                if len(centers) == territory_count:
                    break
        while len(centers) < territory_count:
            centers.append(cell_list[len(centers)])

        total = len(cell_list)
        base = total // territory_count
        sizes = [base] * territory_count
        for i in range(total - base * territory_count):
            sizes[i] += 1

        assigned: dict[Tuple[int, int], int] = {}
        territories_cells: List[List[Tuple[int, int]]] = [[] for _ in range(territory_count)]
        frontiers: List[set[Tuple[int, int]]] = [set() for _ in range(territory_count)]

        for tid, cell in enumerate(centers):
            assigned[cell] = tid
            territories_cells[tid].append(cell)
            for nr, nc in self.neighbors4(*cell):
                if (nr, nc) in cells and (nr, nc) not in assigned:
                    frontiers[tid].add((nr, nc))

        while len(assigned) < total:
            candidates = [tid for tid in range(territory_count) if len(territories_cells[tid]) < sizes[tid] and frontiers[tid]]
            if not candidates:
                candidates = [tid for tid in range(territory_count) if frontiers[tid]]
            if not candidates:
                break
            tid = min(candidates, key=lambda idx: (len(territories_cells[idx]), idx))
            best = None
            best_score = None
            for cell in list(frontiers[tid]):
                same = sum((nr, nc) in assigned and assigned[(nr, nc)] == tid for nr, nc in self.neighbors4(*cell))
                other = sum((nr, nc) in assigned and assigned[(nr, nc)] != tid for nr, nc in self.neighbors4(*cell))
                score = (-same, other, cell[0], cell[1])
                if best_score is None or score < best_score:
                    best_score = score
                    best = cell
            if best is None:
                break
            frontiers[tid].discard(best)
            if best in assigned:
                continue
            assigned[best] = tid
            territories_cells[tid].append(best)
            for nr, nc in self.neighbors4(*best):
                if (nr, nc) in cells and (nr, nc) not in assigned:
                    frontiers[tid].add((nr, nc))

        for cell in cell_list:
            if cell in assigned:
                continue
            neighbors = [assigned[(nr, nc)] for nr, nc in self.neighbors4(*cell) if (nr, nc) in assigned]
            tid = min(neighbors, key=lambda idx: (len(territories_cells[idx]), idx)) if neighbors else 0
            assigned[cell] = tid
            territories_cells[tid].append(cell)

        territory_neighbors: List[set[int]] = [set() for _ in range(territory_count)]
        for cell, tid in assigned.items():
            for nr, nc in self.neighbors4(*cell):
                other = assigned.get((nr, nc))
                if other is not None and other != tid:
                    territory_neighbors[tid].add(other)

        return territories_cells, territory_neighbors

    def add_bridge_between_territories(self, terr_a: int, terr_b: int, start: Tuple[int, int], end: Tuple[int, int]) -> None:
        path = []
        r, c = start
        er, ec = end
        while (r, c) != (er, ec):
            if abs(ec - c) >= abs(er - r):
                c += 1 if ec > c else -1 if ec < c else 0
            else:
                r += 1 if er > r else -1 if er < r else 0
            path.append((r, c))
        if not path:
            return
        split = max(1, len(path) // 2)
        for idx, cell in enumerate(path):
            owner_tid = terr_a if idx < split else terr_b
            if cell not in self.territories[owner_tid].cells:
                self.territories[owner_tid].cells.append(cell)
            self.grid_territory[cell[0]][cell[1]] = owner_tid
        self.territories[terr_a].neighbors = sorted(set(self.territories[terr_a].neighbors) | {terr_b})
        self.territories[terr_b].neighbors = sorted(set(self.territories[terr_b].neighbors) | {terr_a})


    def generate_organic_continent(self, center_row: int, center_col: int, target_cells: int, angle: float) -> set[Tuple[int, int]]:
        cells: set[Tuple[int, int]] = set()
        min_r, max_r = 3, self.rows - 4
        min_c, max_c = 3, self.cols - 4

        def paint(rr: float, cc: float, radius: int) -> None:
            for r in range(max(min_r, int(rr - radius - 2)), min(max_r + 1, int(rr + radius + 3))):
                for c in range(max(min_c, int(cc - radius - 2)), min(max_c + 1, int(cc + radius + 3))):
                    dr = r - rr
                    dc = c - cc
                    if dr * dr + dc * dc <= (radius + random.uniform(-0.8, 1.4)) ** 2:
                        cells.add((r, c))

        major_dr = math.sin(angle)
        major_dc = math.cos(angle)
        walkers = []
        for _ in range(random.randint(6, 9)):
            local_angle = angle + random.uniform(-1.4, 1.4)
            walkers.append({
                'r': float(center_row) + random.uniform(-4.0, 4.0),
                'c': float(center_col) + random.uniform(-4.0, 4.0),
                'dr': math.sin(local_angle) * random.uniform(0.8, 1.4),
                'dc': math.cos(local_angle) * random.uniform(0.8, 1.4),
                'radius': random.randint(3, 6),
                'budget': random.randint(28, 60),
                'branch': random.uniform(0.05, 0.10),
            })

        steps = 0
        max_steps = target_cells * 3
        while walkers and len(cells) < target_cells and steps < max_steps:
            walker = walkers.pop(random.randrange(len(walkers)))
            r = walker['r']
            c = walker['c']
            dr = walker['dr']
            dc = walker['dc']
            radius = walker['radius']
            budget = walker['budget']

            while budget > 0 and len(cells) < target_cells and steps < max_steps:
                paint(r, c, radius)
                if budget > 16 and random.random() < walker['branch'] and len(walkers) < 18:
                    split_angle = math.atan2(dr, dc) + random.uniform(-1.2, 1.2)
                    walkers.append({
                        'r': r,
                        'c': c,
                        'dr': math.sin(split_angle) * random.uniform(0.7, 1.3),
                        'dc': math.cos(split_angle) * random.uniform(0.7, 1.3),
                        'radius': max(2, radius - random.choice([0, 1])),
                        'budget': random.randint(12, max(13, budget // 2)),
                        'branch': walker['branch'] * 0.8,
                    })
                dr += major_dr * random.uniform(0.03, 0.18) + random.uniform(-0.55, 0.55)
                dc += major_dc * random.uniform(0.03, 0.18) + random.uniform(-0.60, 0.60)
                norm = max(0.75, (dr * dr + dc * dc) ** 0.5)
                dr /= norm
                dc /= norm
                r = min(max_r, max(min_r, r + dr * random.uniform(1.1, 2.2)))
                c = min(max_c, max(min_c, c + dc * random.uniform(1.2, 2.5)))
                if random.random() < 0.22:
                    radius = max(2, min(7, radius + random.choice([-1, 0, 1])))
                budget -= 1
                steps += 1

        # Creuse des baies pour eviter l'effet boule.
        all_cells = list(cells)
        for _ in range(random.randint(4, 7)):
            if not all_cells:
                break
            br, bc = random.choice(all_cells)
            cut_radius = random.randint(3, 7)
            for r in range(br - cut_radius - 1, br + cut_radius + 2):
                for c in range(bc - cut_radius - 1, bc + cut_radius + 2):
                    if (r, c) in cells and 0 <= r < self.rows and 0 <= c < self.cols:
                        if (r - br) ** 2 + (c - bc) ** 2 <= (cut_radius + random.uniform(-0.5, 1.0)) ** 2 and random.random() < 0.72:
                            cells.discard((r, c))

        # Lissage leger.
        for _ in range(2):
            additions: set[Tuple[int, int]] = set()
            removals: set[Tuple[int, int]] = set()
            if not cells:
                break
            min_rr = max(0, min(r for r, _ in cells) - 2)
            max_rr = min(self.rows - 1, max(r for r, _ in cells) + 2)
            min_cc = max(0, min(c for _, c in cells) - 2)
            max_cc = min(self.cols - 1, max(c for _, c in cells) + 2)
            for r in range(min_rr, max_rr + 1):
                for c in range(min_cc, max_cc + 1):
                    count = sum((nr, nc) in cells for nr, nc in self.neighbors4(r, c))
                    if (r, c) in cells and count <= 1:
                        removals.add((r, c))
                    elif (r, c) not in cells and count >= 3 and random.random() < 0.45:
                        additions.add((r, c))
            cells.difference_update(removals)
            cells.update(additions)

        if not cells:
            cells.add((center_row, center_col))
        anchor = min(cells, key=lambda cell: abs(cell[0] - center_row) + abs(cell[1] - center_col))
        return self.extract_connected_component(cells, anchor)

    def choose_boundary_candidates(self, cells: set[Tuple[int, int]], direction: str, limit: int = 12) -> List[Tuple[int, int]]:
        boundary = []
        for r, c in cells:
            if any((nr, nc) not in cells for nr, nc in self.neighbors4(r, c)):
                boundary.append((r, c))
        if not boundary:
            boundary = list(cells)
        if direction == 'right':
            boundary.sort(key=lambda cell: (-cell[1], abs(cell[0])))
        elif direction == 'left':
            boundary.sort(key=lambda cell: (cell[1], abs(cell[0])))
        elif direction == 'down':
            boundary.sort(key=lambda cell: (-cell[0], abs(cell[1])))
        else:
            boundary.sort(key=lambda cell: (cell[0], abs(cell[1])))
        return boundary[:limit]


    def reset_custom_map_editor(self) -> None:
        self.grid_territory = [[-1 for _ in range(self.cols)] for _ in range(self.rows)]
        self.territories = []
        self.territory_continent = {}
        self.terre_links = []
        self.terre_link_points = {}
        self.sanctuary_territory_ids = set()
        self.selected_source = None
        self.selected_target = None
        self.custom_map_size = "medium"
        self.custom_shape = "block"
        self.custom_dragging_territory_id = None
        self.custom_drag_origin_cells = []
        self.custom_drag_start_cell = None
        self.custom_selected_territory_id = None

    def get_custom_size_config(self, size_name: Optional[str] = None) -> Tuple[int, int, int]:
        size_name = size_name or self.custom_map_size
        if size_name == "large":
            return (250, 6, 10)
        if size_name == "immense":
            return (720, 12, 20)
        return (160, 4, 7)

    def smooth_custom_cells(self, cells: set[Tuple[int, int]], center_cell: Tuple[int, int]) -> set[Tuple[int, int]]:
        if not cells:
            return cells
        for _ in range(2):
            additions = set()
            removals = set()
            min_r = max(0, min(r for r, _ in cells) - 1)
            max_r = min(self.rows - 1, max(r for r, _ in cells) + 1)
            min_c = max(0, min(c for _, c in cells) - 1)
            max_c = min(self.cols - 1, max(c for _, c in cells) + 1)
            for r in range(min_r, max_r + 1):
                for c in range(min_c, max_c + 1):
                    if self.grid_territory[r][c] != -1 and (r, c) not in cells:
                        continue
                    neighbors = sum((nr, nc) in cells for nr, nc in self.neighbors4(r, c))
                    if (r, c) in cells and neighbors <= 1 and (r, c) != center_cell:
                        removals.add((r, c))
                    elif (r, c) not in cells and self.grid_territory[r][c] == -1 and neighbors >= 3 and random.random() < 0.40:
                        additions.add((r, c))
            cells.difference_update(removals)
            cells.update(additions)
        return cells

    def generate_block_custom_shape(self, center_row: int, center_col: int, target_cells: int, min_radius: int, max_radius: int, available: set[Tuple[int, int]]) -> Optional[set[Tuple[int, int]]]:
        cells = {(center_row, center_col)}
        frontier = {(center_row, center_col)}
        attempts = 0
        while frontier and len(cells) < target_cells and attempts < target_cells * 30:
            attempts += 1
            base_r, base_c = random.choice(tuple(frontier))
            options = []
            for nr, nc in self.neighbors4(base_r, base_c):
                if (nr, nc) in cells or (nr, nc) not in available:
                    continue
                dist = abs(nr - center_row) + abs(nc - center_col)
                same_neighbors = sum((xr, xc) in cells for xr, xc in self.neighbors4(nr, nc))
                if dist > max_radius * 3 + random.randint(0, max_radius * 2):
                    continue
                options.append(((same_neighbors, -dist, random.random()), (nr, nc)))
            if not options:
                frontier.discard((base_r, base_c))
                continue
            options.sort(reverse=True)
            nr, nc = options[0][1]
            cells.add((nr, nc))
            if abs(nr - center_row) + abs(nc - center_col) <= min_radius or random.random() < 0.86:
                frontier.add((nr, nc))
            if random.random() < 0.12:
                frontier.add((base_r, base_c))
        if len(cells) < max(24, target_cells // 3):
            return None
        return self.smooth_custom_cells(cells, (center_row, center_col))

    def generate_star_custom_shape(self, center_row: int, center_col: int, target_cells: int, min_radius: int, max_radius: int, available: set[Tuple[int, int]]) -> Optional[set[Tuple[int, int]]]:
        cells = {(center_row, center_col)}
        core_target = max(20, target_cells // 3)
        core_radius = max(2, min_radius)
        frontier = {(center_row, center_col)}
        attempts = 0
        while frontier and len(cells) < core_target and attempts < core_target * 25:
            attempts += 1
            base_r, base_c = random.choice(tuple(frontier))
            candidates = []
            for nr, nc in self.neighbors4(base_r, base_c):
                if (nr, nc) in cells or (nr, nc) not in available:
                    continue
                dist = abs(nr - center_row) + abs(nc - center_col)
                if dist > core_radius * 3:
                    continue
                neighbors = sum((xr, xc) in cells for xr, xc in self.neighbors4(nr, nc))
                candidates.append(((neighbors, -dist, random.random()), (nr, nc)))
            if not candidates:
                frontier.discard((base_r, base_c))
                continue
            candidates.sort(reverse=True)
            cell = candidates[0][1]
            cells.add(cell)
            frontier.add(cell)
            if random.random() < 0.25:
                frontier.add((base_r, base_c))

        arm_count = random.randint(5, 8)
        arm_lengths = [random.randint(max_radius * 2, max_radius * 4) for _ in range(arm_count)]
        base_angles = [2 * math.pi * i / arm_count + random.uniform(-0.22, 0.22) for i in range(arm_count)]
        for angle, arm_len in zip(base_angles, arm_lengths):
            pos_r = float(center_row)
            pos_c = float(center_col)
            direction = angle
            brush = max(1, min_radius // 2)
            for step in range(arm_len):
                pos_r += math.sin(direction) * random.uniform(0.8, 1.4)
                pos_c += math.cos(direction) * random.uniform(0.8, 1.6)
                direction += random.uniform(-0.14, 0.14)
                rr = int(round(pos_r))
                cc = int(round(pos_c))
                arm_cells = {(rr, cc)}
                if step < arm_len * 0.18 or random.random() < 0.35:
                    for nr, nc in self.neighbors4(rr, cc):
                        if random.random() < 0.55:
                            arm_cells.add((nr, nc))
                for ar, ac in list(arm_cells):
                    if brush > 1 and random.random() < 0.35:
                        for nr, nc in self.neighbors4(ar, ac):
                            if random.random() < 0.30:
                                arm_cells.add((nr, nc))
                valid_cells = {(r, c) for r, c in arm_cells if (r, c) in available}
                if not valid_cells:
                    break
                cells.update(valid_cells)
                if len(cells) >= target_cells:
                    break
            if len(cells) >= target_cells:
                break

        if len(cells) < max(26, target_cells // 3):
            return None
        return self.extract_connected_component(cells, (center_row, center_col))

    def generate_custom_territory_shape(self, center_row: int, center_col: int, size_name: Optional[str] = None, shape_name: Optional[str] = None) -> Optional[set[Tuple[int, int]]]:
        target_cells, min_radius, max_radius = self.get_custom_size_config(size_name)
        shape_name = shape_name or self.custom_shape
        available = {(r, c) for r in range(self.rows) for c in range(self.cols) if self.grid_territory[r][c] == -1}
        if (center_row, center_col) not in available:
            return None

        generators = {
            "block": self.generate_block_custom_shape,
            "star": self.generate_star_custom_shape,
        }
        generator = generators.get(shape_name, self.generate_block_custom_shape)
        for _ in range(8):
            cells = generator(center_row, center_col, target_cells, min_radius, max_radius, available)
            if not cells:
                continue
            cells = {(r, c) for r, c in cells if (r, c) in available}
            if (center_row, center_col) not in cells:
                cells.add((center_row, center_col))
            cells = self.extract_connected_component(cells, (center_row, center_col))
            if len(cells) >= max(24, target_cells // 4):
                return cells
        return None

    def add_custom_territory_at(self, pos: Tuple[int, int]) -> bool:
        x, y = pos
        if y < self.map_top:
            return False
        col = int(x // self.cell_width)
        row = int((y - self.map_top) // self.cell_height)
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return False
        if self.grid_territory[row][col] != -1:
            self.show_message("Cette zone est deja occupee par un territoire.", 1800)
            return False
        shape = self.generate_custom_territory_shape(row, col, self.custom_map_size, self.custom_shape)
        if not shape:
            self.show_message("Impossible de generer un territoire ici. Choisissez une autre zone.", 2200)
            return False
        tid = self.create_custom_territory_from_cells(shape)
        name = self.territories[tid].name
        self.rebuild_cells_from_grid()
        self.recompute_neighbors_from_grid()
        self.show_message(f"Territoire {name} ajoute ({self.custom_map_size}, {self.custom_shape}).", 1300)
        return True

    def editor_cell_from_pos(self, pos: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        x, y = pos
        if y < self.map_top:
            return None
        col = int(x // self.cell_width)
        row = int((y - self.map_top) // self.cell_height)
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return None
        return row, col

    def can_place_custom_cells(self, cells: set[Tuple[int, int]], ignore_tid: Optional[int] = None) -> bool:
        normalized = {self.wrap_cell(r, c) for r, c in cells}
        if len(normalized) != len(cells):
            return False
        for r, c in normalized:
            cell_tid = self.grid_territory[r][c]
            if cell_tid != -1 and cell_tid != ignore_tid:
                return False
        return True

    def renumber_custom_territories(self) -> None:
        for new_id, territory in enumerate(self.territories):
            territory.id = new_id
            territory.name = f"T{new_id + 1}"
            territory.neighbors = []
        self.super_territory_ids = set()
        self.ultra_super_territory_ids = {tid for tid, terr in enumerate(self.territories) if terr.reinforcement_bonus == 3}
        self.sanctuary_territory_ids = {tid for tid in self.sanctuary_territory_ids if 0 <= tid < len(self.territories)}
        self.grid_territory = [[-1 for _ in range(self.cols)] for _ in range(self.rows)]
        for territory in self.territories:
            normalized_cells = sorted({self.wrap_cell(r, c) for r, c in territory.cells})
            territory.cells = normalized_cells
            for r, c in normalized_cells:
                self.grid_territory[r][c] = territory.id
        self.recompute_neighbors_from_grid()

    def remove_custom_territory(self, territory_id: int) -> bool:
        if not (0 <= territory_id < len(self.territories)):
            return False
        removed = self.territories[territory_id]
        removed_name = removed.name
        for r, c in removed.cells:
            if 0 <= r < self.rows and 0 <= c < self.cols and self.grid_territory[r][c] == territory_id:
                self.grid_territory[r][c] = -1
        removed.cells = []
        del self.territories[territory_id]
        self.custom_selected_territory_id = None
        self.custom_dragging_territory_id = None
        self.custom_drag_origin_cells = []
        self.custom_drag_start_cell = None
        self.renumber_custom_territories()
        self.rebuild_cells_from_grid()
        self.recompute_neighbors_from_grid()
        self.show_message(f"Territoire {removed_name} supprime.", 1600)
        return True

    def get_empty_component(self, start: Tuple[int, int]) -> set[Tuple[int, int]]:
        stack = [start]
        component: set[Tuple[int, int]] = set()
        while stack:
            cell = stack.pop()
            if cell in component:
                continue
            r, c = cell
            if self.grid_territory[r][c] != -1:
                continue
            component.add(cell)
            for nr, nc in self.neighbors4(r, c):
                if self.grid_territory[nr][nc] == -1 and (nr, nc) not in component:
                    stack.append((nr, nc))
        return component

    def build_fill_shape_from_component(self, component: set[Tuple[int, int]], start: Tuple[int, int]) -> set[Tuple[int, int]]:
        target_cells, _, _ = self.get_custom_size_config(self.custom_map_size)
        if len(component) <= max(24, target_cells // 3):
            return set(component)
        shape = self.generate_custom_territory_shape(start[0], start[1], self.custom_map_size, self.custom_shape)
        if shape:
            candidate = shape & component
            if start in candidate:
                candidate = self.extract_connected_component(candidate, start)
                if len(candidate) >= max(24, target_cells // 4):
                    return candidate
        queue = [start]
        visited = {start}
        ordered = []
        while queue and len(ordered) < target_cells:
            r, c = queue.pop(0)
            ordered.append((r, c))
            neighbors = sorted(
                [cell for cell in self.neighbors4(r, c) if cell in component and cell not in visited],
                key=lambda cell: (abs(cell[0] - start[0]) + abs(cell[1] - start[1]), random.random()),
            )
            for neighbor in neighbors:
                visited.add(neighbor)
                queue.append(neighbor)
        return set(ordered)

    def create_custom_territory_from_cells(self, cells: set[Tuple[int, int]]) -> int:
        tid = len(self.territories)
        territory = Territory(id=tid, name=f"T{tid + 1}", owner=-1, regiments=0, cells=sorted(cells), neighbors=[], reinforcement_bonus=1)
        self.territories.append(territory)
        for r, c in cells:
            self.grid_territory[r][c] = tid
        self.recompute_neighbors_from_grid()
        self.custom_selected_territory_id = tid
        return tid

    def fill_custom_map_completely(self) -> bool:
        empty_cells = [(r, c) for r in range(self.rows) for c in range(self.cols) if self.grid_territory[r][c] == -1]
        if not empty_cells:
            self.show_message("La carte est deja entierement remplie.", 1800)
            return False
        minimum_fill_cells = self.get_custom_size_config("medium")[0]
        added = 0
        watered = 0
        seen: set[Tuple[int, int]] = set()
        for start in empty_cells:
            if start in seen or self.grid_territory[start[0]][start[1]] != -1:
                continue
            component = self.get_empty_component(start)
            seen.update(component)
            remaining = set(component)
            while len(remaining) >= minimum_fill_cells:
                anchor = min(remaining, key=lambda cell: (cell[0], cell[1]))
                cells = self.build_fill_shape_from_component(remaining, anchor)
                cells = set(cells) & remaining
                if len(cells) < minimum_fill_cells:
                    break
                self.create_custom_territory_from_cells(cells)
                added += 1
                remaining.difference_update(cells)
            watered += len(remaining)
        self.rebuild_cells_from_grid()
        self.recompute_neighbors_from_grid()
        if watered > 0:
            self.show_message(
                f"Carte remplie automatiquement : {added} territoire(s) ajoute(s), {watered} case(s) trop petites laissees en eau.",
                3200,
            )
        else:
            self.show_message(f"Carte remplie automatiquement : {added} territoire(s) ajoute(s).", 2600)
        return True

    def place_custom_territory_cells(self, territory_id: int, new_cells: set[Tuple[int, int]]) -> None:
        territory = self.territories[territory_id]
        normalized_cells = {self.wrap_cell(r, c) for r, c in new_cells}
        for r, c in territory.cells:
            self.grid_territory[r][c] = -1
        for r, c in normalized_cells:
            self.grid_territory[r][c] = territory_id
        territory.cells = sorted(normalized_cells)
        self.recompute_neighbors_from_grid()

    def start_custom_drag(self, territory_id: int, start_cell: Tuple[int, int]) -> None:
        self.custom_selected_territory_id = territory_id
        self.custom_dragging_territory_id = territory_id
        self.custom_drag_origin_cells = list(self.territories[territory_id].cells)
        self.custom_drag_start_cell = start_cell
        self.show_message(f"Glisser le territoire {self.territories[territory_id].name} avec le clic maintenu.", 1200)

    def update_custom_drag(self, pos: Tuple[int, int]) -> None:
        if self.custom_dragging_territory_id is None or self.custom_drag_start_cell is None:
            return
        current_cell = self.editor_cell_from_pos(pos)
        if current_cell is None:
            return
        start_row, start_col = self.custom_drag_start_cell
        delta_row = current_cell[0] - start_row
        delta_col = current_cell[1] - start_col
        if delta_row == 0 and delta_col == 0:
            return
        moved_cells = {self.wrap_cell(r + delta_row, c + delta_col) for r, c in self.custom_drag_origin_cells}
        territory_id = self.custom_dragging_territory_id
        if not self.can_place_custom_cells(moved_cells, ignore_tid=territory_id):
            return
        self.place_custom_territory_cells(territory_id, moved_cells)

    def stop_custom_drag(self) -> None:
        if self.custom_dragging_territory_id is not None:
            territory = self.territories[self.custom_dragging_territory_id]
            self.custom_selected_territory_id = territory.id
            self.show_message(f"Territoire {territory.name} repositionne.", 1000)
        self.custom_dragging_territory_id = None
        self.custom_drag_origin_cells = []
        self.custom_drag_start_cell = None

    def finish_custom_map_creation(self) -> bool:
        if not self.territories:
            self.show_message("Ajoutez au moins un territoire avant de sauvegarder la carte.", 2600)
            return False
        if self.editing_map_path is not None:
            self.editing_map_path.write_text(json.dumps(self.build_map_payload(), ensure_ascii=False, indent=2), encoding="utf-8")
            save_name = self.editing_map_path.stem
            self.editing_map_path = None
            self.reset_custom_map_editor()
            self.phase = "start_menu"
            self.show_message(f"Carte modifiee sauvegardee : {save_name}.", 3000)
            return True
        save_name = self.save_current_map_to_file()
        self.reset_custom_map_editor()
        self.show_message(f"Carte personnalisee sauvegardee : {save_name}. Vous pouvez en creer une autre ou revenir au menu.", 3400)
        return True

    def handle_custom_editor_click(self, pos: Tuple[int, int]) -> None:
        for size_name, rect in self.custom_size_buttons.items():
            if rect.collidepoint(pos):
                self.custom_map_size = size_name
                labels = {"medium": "moyen", "large": "grand", "immense": "immense"}
                self.show_message(f"Taille selectionnee : {labels[size_name]}.", 1200)
                return
        for shape_name, rect in self.custom_shape_buttons.items():
            if rect.collidepoint(pos):
                self.custom_shape = shape_name
                labels = {"block": "bloc", "star": "etoile"}
                self.show_message(f"Forme selectionnee : {labels[shape_name]}.", 1200)
                return
        if self.fill_custom_map_rect.collidepoint(pos):
            self.fill_custom_map_completely()
            return
        if self.finish_custom_map_rect.collidepoint(pos):
            self.finish_custom_map_creation()
            return
        if self.editor_return_menu_rect.collidepoint(pos):
            self.editing_map_path = None
            self.phase = "start_menu"
            self.show_message("Retour au menu principal.", 1600)
            return
        territory = self.get_territory_at_pos(pos)
        if territory is not None:
            self.custom_selected_territory_id = territory.id
            start_cell = self.editor_cell_from_pos(pos)
            if start_cell is not None:
                self.start_custom_drag(territory.id, start_cell)
            return
        self.custom_selected_territory_id = None
        self.add_custom_territory_at(pos)

    def find_bridge_path(self, start: Tuple[int, int], end: Tuple[int, int], blocked: set[Tuple[int, int]]) -> Optional[List[Tuple[int, int]]]:
        from collections import deque
        queue = deque([start])
        parent = {start: None}
        while queue:
            cell = queue.popleft()
            if cell == end:
                break
            for nr, nc in self.neighbors4(*cell):
                nxt = (nr, nc)
                if nxt in parent:
                    continue
                if nxt != end and nxt != start and nxt in blocked:
                    continue
                parent[nxt] = cell
                queue.append(nxt)
        if end not in parent:
            return None
        path = []
        cur = end
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        path.reverse()
        return path

    def add_bridge_path_between_territories(self, terr_a: int, terr_b: int, path: List[Tuple[int, int]]) -> None:
        if len(path) <= 2:
            self.territories[terr_a].neighbors = sorted(set(self.territories[terr_a].neighbors) | {terr_b})
            self.territories[terr_b].neighbors = sorted(set(self.territories[terr_b].neighbors) | {terr_a})
            return
        mid = len(path) // 2
        for idx, cell in enumerate(path[1:-1], start=1):
            owner_tid = terr_a if idx < mid else terr_b
            if cell not in self.territories[owner_tid].cells:
                self.territories[owner_tid].cells.append(cell)
            self.grid_territory[cell[0]][cell[1]] = owner_tid
        self.territories[terr_a].neighbors = sorted(set(self.territories[terr_a].neighbors) | {terr_b})
        self.territories[terr_b].neighbors = sorted(set(self.territories[terr_b].neighbors) | {terr_a})

    def generate_terre_map(self) -> None:
        continent_sizes = [8, 7, 7, 7, 7]
        total_cells = self.rows * self.cols

        for _attempt in range(30):
            self.grid_territory = [[-1 for _ in range(self.cols)] for _ in range(self.rows)]
            self.territories = []
            self.territory_continent = {}
            self.terre_links = []
            self.terre_link_points = {}

            centers = self.choose_terre_centers(len(continent_sizes))
            reserved: set[Tuple[int, int]] = set()
            all_land: set[Tuple[int, int]] = set()
            continent_territory_ids: List[List[int]] = []
            territory_index = 0
            success = True

            for continent_id, (center_row, center_col) in enumerate(centers):
                territory_count = continent_sizes[continent_id]
                continent_cells: Optional[set[Tuple[int, int]]] = None
                territory_cells: Optional[List[List[Tuple[int, int]]]] = None
                territory_neighbors: Optional[List[set[int]]] = None

                for _local_attempt in range(14):
                    radius_row = random.randint(22, 26)
                    radius_col = random.randint(36, 42)
                    candidate = self.generate_ellipse_island(center_row, center_col, radius_row, radius_col)
                    candidate = {cell for cell in candidate if cell not in reserved}
                    if (center_row, center_col) not in candidate:
                        candidate.add((center_row, center_col))
                    candidate = self.extract_connected_component(candidate, (center_row, center_col))

                    if len(candidate) < 2200:
                        continue

                    try:
                        local_cells, local_neighbors = self.partition_cells_into_balanced_territories(candidate, territory_count)
                    except ValueError:
                        continue

                    if min(len(cells) for cells in local_cells) < 220:
                        continue

                    continent_cells = candidate
                    territory_cells = local_cells
                    territory_neighbors = local_neighbors
                    break

                if continent_cells is None or territory_cells is None or territory_neighbors is None:
                    success = False
                    break

                ids: List[int] = []
                base_id = territory_index
                for local_id in range(territory_count):
                    tid = base_id + local_id
                    ids.append(tid)
                    for r, c in territory_cells[local_id]:
                        self.grid_territory[r][c] = tid
                    self.territories.append(Territory(
                        id=tid,
                        name="",
                        owner=-1,
                        regiments=0,
                        cells=list(territory_cells[local_id]),
                        neighbors=sorted(base_id + n for n in territory_neighbors[local_id]),
                    ))
                    self.territory_continent[tid] = continent_id
                territory_index += territory_count
                continent_territory_ids.append(ids)
                all_land.update(continent_cells)
                reserved = self.expand_cell_buffer(all_land, 4)

            if not success:
                continue

            land_cells = sum(1 for row in self.grid_territory for tid in row if tid >= 0)
            water_ratio = 1.0 - (land_cells / total_cells)
            if water_ratio > self.max_water_ratio:
                continue

            self.rebuild_cells_from_grid()
            self.recompute_neighbors_from_grid()

            # Relie les continents par un petit reseau visible, sans transformer la carte en racines.
            edges: List[Tuple[float, int, int]] = []
            for i in range(len(centers)):
                for j in range(i + 1, len(centers)):
                    dist = (centers[i][0] - centers[j][0]) ** 2 + (centers[i][1] - centers[j][1]) ** 2
                    edges.append((dist, i, j))
            edges.sort()
            parent = list(range(len(centers)))

            def find(x: int) -> int:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(a: int, b: int) -> bool:
                ra, rb = find(a), find(b)
                if ra == rb:
                    return False
                parent[rb] = ra
                return True

            mandatory_pairs: List[Tuple[int, int]] = []
            for _, a, b in edges:
                if union(a, b):
                    mandatory_pairs.append((a, b))

            extra_candidates = [(a, b) for _, a, b in edges if (a, b) not in mandatory_pairs and (b, a) not in mandatory_pairs]
            random.shuffle(extra_candidates)
            target_link_count = random.randint(4, 7)
            selected_pairs = list(mandatory_pairs)
            for a, b in extra_candidates:
                if len(selected_pairs) >= target_link_count:
                    break
                selected_pairs.append((a, b))

            for a, b in selected_pairs:
                dr = centers[b][0] - centers[a][0]
                dc = centers[b][1] - centers[a][1]
                if abs(dc) >= abs(dr):
                    dir_a = "right" if dc > 0 else "left"
                    dir_b = "left" if dc > 0 else "right"
                else:
                    dir_a = "down" if dr > 0 else "up"
                    dir_b = "up" if dr > 0 else "down"

                terr_a = self.choose_facing_territory(continent_territory_ids[a], dir_a)
                terr_b = self.choose_facing_territory(continent_territory_ids[b], dir_b)
                start = self.get_territory_center_cell(terr_a)
                end = self.get_territory_center_cell(terr_b)
                self.register_terre_link(terr_a, terr_b, start, end)

            self.apply_terre_links_to_neighbors()
            return

        raise RuntimeError("Impossible de generer une carte Terre correcte.")


    def build_gigamega_land_mask(self) -> List[List[bool]]:
        """Genere un grand archipel inspire des cartes GIGA/MEGA sauvegardees.

        Cible observee sur les modeles : environ 80 a 100 territoires, 46% a 58%
        d'eau, un seul graphe jouable, beaucoup de masses organiques reliees par
        des passages etroits. Bref, la mer fait semblant de separer le monde,
        puis la geographie signe un compromis, comme tout le monde.
        """
        total_cells = self.rows * self.cols
        target_water_ratio = random.uniform(0.46, 0.58)
        target_land_cells = int(total_cells * (1.0 - target_water_ratio))
        margin = 3

        def neighbors8(r: int, c: int):
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < self.rows and 0 <= nc < self.cols:
                        yield nr, nc

        def paint_disc(mask: List[List[bool]], row: float, col: float, radius: int) -> int:
            painted = 0
            cr = int(round(row))
            cc = int(round(col))
            radius_sq = radius * radius
            for r in range(max(margin, cr - radius), min(self.rows - margin, cr + radius + 1)):
                for c in range(max(margin, cc - radius), min(self.cols - margin, cc + radius + 1)):
                    if (r - row) * (r - row) + (c - col) * (c - col) <= radius_sq and not mask[r][c]:
                        mask[r][c] = True
                        painted += 1
            return painted

        def dig_land_corridor(mask: List[List[bool]], start: Tuple[int, int], end: Tuple[int, int], width: int) -> None:
            r, c = start
            er, ec = end
            guard = 0
            while (r, c) != (er, ec) and guard < self.rows + self.cols:
                paint_disc(mask, r, c, width)
                if abs(er - r) >= abs(ec - c):
                    r += 1 if er > r else -1 if er < r else 0
                    if random.random() < 0.35:
                        c += random.choice([-1, 0, 1])
                else:
                    c += 1 if ec > c else -1 if ec < c else 0
                    if random.random() < 0.35:
                        r += random.choice([-1, 0, 1])
                r = max(margin, min(self.rows - margin - 1, r))
                c = max(margin, min(self.cols - margin - 1, c))
                guard += 1
            paint_disc(mask, er, ec, width)

        def carve_lagoon(mask: List[List[bool]], start: Tuple[int, int], length: int, width: int) -> None:
            r, c = start
            angle = random.uniform(0.0, math.tau)
            for _ in range(length):
                for rr in range(max(1, r - width), min(self.rows - 1, r + width + 1)):
                    for cc in range(max(1, c - width), min(self.cols - 1, c + width + 1)):
                        if (rr - r) * (rr - r) + (cc - c) * (cc - c) <= width * width:
                            mask[rr][cc] = False
                angle += random.uniform(-0.55, 0.55)
                r = max(1, min(self.rows - 2, int(round(r + math.sin(angle) * random.uniform(1.0, 2.0)))))
                c = max(1, min(self.cols - 2, int(round(c + math.cos(angle) * random.uniform(1.0, 2.0)))))

        def land_components(mask: List[List[bool]]) -> List[List[Tuple[int, int]]]:
            seen: set[Tuple[int, int]] = set()
            comps: List[List[Tuple[int, int]]] = []
            for r in range(self.rows):
                for c in range(self.cols):
                    if not mask[r][c] or (r, c) in seen:
                        continue
                    stack = [(r, c)]
                    seen.add((r, c))
                    comp: List[Tuple[int, int]] = []
                    while stack:
                        cr, cc = stack.pop()
                        comp.append((cr, cc))
                        for nr, nc in self.neighbors4(cr, cc):
                            if mask[nr][nc] and (nr, nc) not in seen:
                                seen.add((nr, nc))
                                stack.append((nr, nc))
                    comps.append(comp)
            return comps

        best_mask: Optional[List[List[bool]]] = None
        best_gap: Optional[int] = None
        for _attempt in range(14):
            mask = [[False for _ in range(self.cols)] for _ in range(self.rows)]
            cluster_count = random.randint(7, 10)
            centers: List[Tuple[int, int]] = []
            for idx in range(cluster_count):
                angle = (math.tau * idx / cluster_count) + random.uniform(-0.28, 0.28)
                radius_row = random.uniform(self.rows * 0.16, self.rows * 0.40)
                radius_col = random.uniform(self.cols * 0.18, self.cols * 0.43)
                center = (
                    int(self.rows / 2 + math.sin(angle) * radius_row + random.randint(-8, 8)),
                    int(self.cols / 2 + math.cos(angle) * radius_col + random.randint(-12, 12)),
                )
                center = (
                    max(margin + 5, min(self.rows - margin - 6, center[0])),
                    max(margin + 5, min(self.cols - margin - 6, center[1])),
                )
                centers.append(center)

            weights = [random.uniform(0.75, 1.35) for _ in centers]
            total_weight = sum(weights)
            targets = [max(700, int(target_land_cells * w / total_weight)) for w in weights]

            for (sr, sc), target in zip(centers, targets):
                painted = 0
                walkers = []
                for _ in range(random.randint(8, 13)):
                    angle = random.uniform(0.0, math.tau)
                    walkers.append([
                        float(sr + random.randint(-5, 5)),
                        float(sc + random.randint(-7, 7)),
                        math.sin(angle) + random.uniform(-0.45, 0.45),
                        math.cos(angle) + random.uniform(-0.45, 0.45),
                        random.randint(38, 86),
                        random.randint(2, 5),
                    ])
                step_guard = max(1000, target * 2)
                while walkers and painted < target and step_guard > 0:
                    walker = walkers.pop(random.randrange(len(walkers)))
                    row, col, dr, dc, budget, radius = walker
                    while budget > 0 and painted < target and step_guard > 0:
                        painted += paint_disc(mask, row, col, radius)
                        if budget > 18 and len(walkers) < 22 and random.random() < 0.09:
                            walkers.append([
                                row, col,
                                dr + random.uniform(-1.0, 1.0),
                                dc + random.uniform(-1.0, 1.0),
                                random.randint(16, max(20, budget // 2)),
                                max(1, radius - random.choice([0, 1])),
                            ])
                        dr += random.uniform(-0.60, 0.60)
                        dc += random.uniform(-0.60, 0.60)
                        norm = max(0.7, (dr * dr + dc * dc) ** 0.5)
                        dr /= norm
                        dc /= norm
                        row = max(margin, min(self.rows - margin - 1, row + dr * random.uniform(0.8, 1.8)))
                        col = max(margin, min(self.cols - margin - 1, col + dc * random.uniform(0.8, 2.1)))
                        if random.random() < 0.16:
                            radius = max(1, min(5, radius + random.choice([-1, 0, 1])))
                        budget -= 1
                        step_guard -= 1

            for idx in range(len(centers)):
                dig_land_corridor(mask, centers[idx], centers[(idx + 1) % len(centers)], random.choice([1, 1, 2]))
            for _ in range(random.randint(4, 7)):
                a, b = random.sample(range(len(centers)), 2)
                if random.random() < 0.72:
                    dig_land_corridor(mask, centers[a], centers[b], 1)

            land_cells = [(r, c) for r in range(self.rows) for c in range(self.cols) if mask[r][c]]
            for _ in range(random.randint(22, 36)):
                if not land_cells:
                    break
                carve_lagoon(mask, random.choice(land_cells), random.randint(12, 32), random.choice([1, 1, 2]))
                land_cells = [(r, c) for r in range(self.rows) for c in range(self.cols) if mask[r][c]]

            for r in range(self.rows):
                for c in range(self.cols):
                    if r < 2 or r >= self.rows - 2 or c < 2 or c >= self.cols - 2:
                        mask[r][c] = False

            comps = land_components(mask)
            if not comps:
                continue
            main = max(comps, key=len)
            main_anchor = main[len(main) // 2]
            for comp in comps:
                if comp is main:
                    continue
                comp_anchor = comp[len(comp) // 2]
                dig_land_corridor(mask, main_anchor, comp_anchor, 1)

            current_land = sum(1 for r in range(self.rows) for c in range(self.cols) if mask[r][c])
            gap = abs(current_land - target_land_cells)
            if best_gap is None or gap < best_gap:
                best_gap = gap
                best_mask = [row[:] for row in mask]
            if gap <= total_cells * 0.025:
                return mask

        return best_mask if best_mask is not None else self.build_connected_land_mask()

    def generate_gigamega_map(self) -> None:
        num_territories = random.randint(81, 100)
        for _ in range(35):
            self.territories = []
            land_mask = self.build_gigamega_land_mask()
            land_cells = [(r, c) for r in range(self.rows) for c in range(self.cols) if land_mask[r][c]]
            total_land = len(land_cells)
            water_ratio = 1.0 - (total_land / (self.rows * self.cols))
            if total_land < num_territories * 58 or not (0.46 <= water_ratio <= 0.58):
                continue

            self.grid_territory = [[-1 for _ in range(self.cols)] for _ in range(self.rows)]
            base_size = total_land // num_territories
            sizes = [base_size for _ in range(num_territories)]
            for i in range(total_land - sum(sizes)):
                sizes[i % num_territories] += 1
            min_size = max(55, int(base_size * 0.58))
            max_size = max(min_size + 1, int(base_size * 1.62))
            for _shuffle in range(num_territories * 18):
                a = random.randrange(num_territories)
                b = random.randrange(num_territories)
                if a != b and sizes[a] < max_size and sizes[b] > min_size:
                    sizes[a] += 1
                    sizes[b] -= 1

            random.shuffle(land_cells)
            seeds: List[Tuple[int, int]] = []
            seed_distance = random.randint(5, 8)
            for cell in land_cells:
                if all(abs(cell[0] - sr) + abs(cell[1] - sc) >= seed_distance for sr, sc in seeds):
                    seeds.append(cell)
                    if len(seeds) == num_territories:
                        break
            if len(seeds) < num_territories:
                seeds = land_cells[:num_territories]

            territories_cells: List[List[Tuple[int, int]]] = [[] for _ in range(num_territories)]
            frontiers: List[set[Tuple[int, int]]] = [set() for _ in range(num_territories)]
            for tid, (r, c) in enumerate(seeds):
                self.grid_territory[r][c] = tid
                territories_cells[tid].append((r, c))
                for nr, nc in self.neighbors4(r, c):
                    if land_mask[nr][nc] and self.grid_territory[nr][nc] == -1:
                        frontiers[tid].add((nr, nc))

            assigned = len(seeds)
            while assigned < total_land:
                candidates = [tid for tid in range(num_territories) if len(territories_cells[tid]) < sizes[tid] and frontiers[tid]]
                if not candidates:
                    candidates = [tid for tid in range(num_territories) if frontiers[tid]]
                if not candidates:
                    break
                tid = random.choice(candidates)
                frontier_list = list(frontiers[tid])

                def score(cell: Tuple[int, int]) -> Tuple[int, int, float]:
                    r, c = cell
                    same = sum(1 for nr, nc in self.neighbors4(r, c) if self.grid_territory[nr][nc] == tid)
                    other = sum(1 for nr, nc in self.neighbors4(r, c) if self.grid_territory[nr][nc] not in (-1, tid))
                    seed_r, seed_c = seeds[tid]
                    dist = abs(r - seed_r) + abs(c - seed_c)
                    return (same, -other, -dist * random.uniform(0.85, 1.15))

                best_score = None
                best_cells: List[Tuple[int, int]] = []
                for cell in frontier_list:
                    cur = score(cell)
                    if best_score is None or cur > best_score:
                        best_score = cur
                        best_cells = [cell]
                    elif cur == best_score:
                        best_cells.append(cell)
                r, c = random.choice(best_cells)
                frontiers[tid].discard((r, c))
                if self.grid_territory[r][c] != -1 or not land_mask[r][c]:
                    continue
                self.grid_territory[r][c] = tid
                territories_cells[tid].append((r, c))
                assigned += 1
                for nr, nc in self.neighbors4(r, c):
                    if land_mask[nr][nc] and self.grid_territory[nr][nc] == -1:
                        frontiers[tid].add((nr, nc))

            progress = True
            while progress:
                progress = False
                for r, c in land_cells:
                    if self.grid_territory[r][c] != -1:
                        continue
                    vois = {
                        self.grid_territory[nr][nc]
                        for nr, nc in self.neighbors4(r, c)
                        if land_mask[nr][nc] and self.grid_territory[nr][nc] != -1
                    }
                    if vois:
                        tid = random.choice(list(vois))
                        self.grid_territory[r][c] = tid
                        territories_cells[tid].append((r, c))
                        progress = True

            if any(self.grid_territory[r][c] == -1 for r, c in land_cells):
                continue
            territory_sizes = [len(cells) for cells in territories_cells]
            if min(territory_sizes) < 55 or max(territory_sizes) > 380:
                continue

            territory_neighbors: List[set[int]] = [set() for _ in range(num_territories)]
            for r, c in land_cells:
                tid = self.grid_territory[r][c]
                for nr, nc in self.neighbors4(r, c):
                    if not land_mask[nr][nc]:
                        continue
                    ntid = self.grid_territory[nr][nc]
                    if ntid != tid:
                        territory_neighbors[tid].add(ntid)

            seen = {0}
            stack = [0]
            while stack:
                tid = stack.pop()
                for ntid in territory_neighbors[tid]:
                    if ntid not in seen:
                        seen.add(ntid)
                        stack.append(ntid)
            if len(seen) != num_territories:
                continue

            self.territories = []
            for tid in range(num_territories):
                self.territories.append(Territory(
                    id=tid,
                    name="",
                    owner=-1,
                    regiments=0,
                    cells=territories_cells[tid],
                    neighbors=sorted(list(territory_neighbors[tid])),
                ))
            self.territory_continent = {}
            self.terre_links = []
            self.terre_link_points = {}
            return

        raise RuntimeError("Impossible de generer une carte GIGA/MEGA correcte.")

    def generate_grid_map(self) -> None:
        if self.map_mode == "custom":
            self.reset_custom_map_editor()
            return
        if self.map_mode == "terre":
            self.generate_terre_map()
            return
        if self.map_mode == "gigamega":
            self.generate_gigamega_map()
            return

        num_territories = 36
        for _ in range(25):
            self.territories = []
            land_mask = self.build_continents_land_mask() if self.map_mode in ("continents", "continents_45") else self.build_connected_land_mask()
            land_cells = [(r, c) for r in range(self.rows) for c in range(self.cols) if land_mask[r][c]]
            total_land = len(land_cells)
            if total_land < num_territories * 12:
                continue

            self.grid_territory = [[-1 for _ in range(self.cols)] for _ in range(self.rows)]
            base_size = total_land // num_territories
            sizes = [base_size for _ in range(num_territories)]
            remainder = total_land - sum(sizes)
            for i in range(remainder):
                sizes[i % num_territories] += 1
            min_size = max(10, int(base_size * 0.65))
            max_size = max(min_size + 1, int(base_size * 1.45))
            for _ in range(500):
                a = random.randrange(num_territories)
                b = random.randrange(num_territories)
                if a == b:
                    continue
                if sizes[a] < max_size and sizes[b] > min_size:
                    sizes[a] += 1
                    sizes[b] -= 1

            random.shuffle(land_cells)
            seeds: List[Tuple[int, int]] = []
            for cell in land_cells:
                if all(abs(cell[0] - sr) + abs(cell[1] - sc) >= 8 for sr, sc in seeds):
                    seeds.append(cell)
                    if len(seeds) == num_territories:
                        break
            if len(seeds) < num_territories:
                seeds = land_cells[:num_territories]

            territories_cells: List[List[Tuple[int, int]]] = [[] for _ in range(num_territories)]
            frontiers: List[set[Tuple[int, int]]] = [set() for _ in range(num_territories)]

            for tid, (r, c) in enumerate(seeds):
                self.grid_territory[r][c] = tid
                territories_cells[tid].append((r, c))
                for nr, nc in self.neighbors4(r, c):
                    if land_mask[nr][nc] and self.grid_territory[nr][nc] == -1:
                        frontiers[tid].add((nr, nc))

            assigned = len(seeds)
            while assigned < total_land:
                candidates = [tid for tid in range(num_territories) if len(territories_cells[tid]) < sizes[tid] and frontiers[tid]]
                if not candidates:
                    candidates = [tid for tid in range(num_territories) if frontiers[tid]]
                if not candidates:
                    break
                tid = random.choice(candidates)
                frontier_list = list(frontiers[tid])

                def score(cell: Tuple[int, int]) -> Tuple[int, int]:
                    r, c = cell
                    same = sum(1 for nr, nc in self.neighbors4(r, c) if self.grid_territory[nr][nc] == tid)
                    other = sum(1 for nr, nc in self.neighbors4(r, c) if self.grid_territory[nr][nc] not in (-1, tid))
                    return (same, -other)

                best_score = None
                best_cells: List[Tuple[int, int]] = []
                for cell in frontier_list:
                    cur = score(cell)
                    if best_score is None or cur < best_score:
                        best_score = cur
                        best_cells = [cell]
                    elif cur == best_score:
                        best_cells.append(cell)
                r, c = random.choice(best_cells)
                frontiers[tid].discard((r, c))
                if self.grid_territory[r][c] != -1 or not land_mask[r][c]:
                    continue
                self.grid_territory[r][c] = tid
                territories_cells[tid].append((r, c))
                assigned += 1
                for nr, nc in self.neighbors4(r, c):
                    if land_mask[nr][nc] and self.grid_territory[nr][nc] == -1:
                        frontiers[tid].add((nr, nc))

            progress = True
            while progress:
                progress = False
                for r, c in land_cells:
                    if self.grid_territory[r][c] != -1:
                        continue
                    vois = {
                        self.grid_territory[nr][nc]
                        for nr, nc in self.neighbors4(r, c)
                        if land_mask[nr][nc] and self.grid_territory[nr][nc] != -1
                    }
                    if vois:
                        tid = random.choice(list(vois))
                        self.grid_territory[r][c] = tid
                        territories_cells[tid].append((r, c))
                        progress = True

            if any(self.grid_territory[r][c] == -1 for r, c in land_cells):
                continue

            territory_neighbors: List[set[int]] = [set() for _ in range(num_territories)]
            for r, c in land_cells:
                tid = self.grid_territory[r][c]
                for nr, nc in self.neighbors4(r, c):
                    if not land_mask[nr][nc]:
                        continue
                    ntid = self.grid_territory[nr][nc]
                    if ntid != tid:
                        territory_neighbors[tid].add(ntid)

            seen = {0}
            stack = [0]
            while stack:
                tid = stack.pop()
                for ntid in territory_neighbors[tid]:
                    if ntid not in seen:
                        seen.add(ntid)
                        stack.append(ntid)
            if len(seen) != num_territories:
                continue

            for tid in range(num_territories):
                self.territories.append(Territory(
                    id=tid,
                    name="",
                    owner=-1,
                    regiments=0,
                    cells=territories_cells[tid],
                    neighbors=sorted(list(territory_neighbors[tid])),
                ))
            self.territory_continent = {}
            return

        raise RuntimeError("Impossible de generer une carte avec eaux connectee.")

    def get_regular_capital_owner(self, territory_id: int) -> Optional[int]:
        for player, capital_id in getattr(self, "player_capital_ids", {}).items():
            if capital_id == territory_id:
                return player
        return None

    def is_regular_capital_territory(self, territory_id: int) -> bool:
        return self.get_regular_capital_owner(territory_id) is not None

    def is_any_capital_territory(self, territory_id: int) -> bool:
        return (
            self.is_regular_capital_territory(territory_id)
            or territory_id in set(getattr(self, "commercial_city_capital_ids", {}).values())
        )

    def is_active_regular_capital(self, territory_id: int) -> bool:
        original_owner = self.get_regular_capital_owner(territory_id)
        return (
            original_owner is not None
            and 0 <= territory_id < len(self.territories)
            and self.territories[territory_id].owner == original_owner
            and not self.is_onu_player(original_owner)
            and not self.is_potential_commercial_city_player(original_owner)
        )

    def sanitize_player_capitals(self) -> None:
        valid_ids = set(range(len(self.territories)))
        self.player_capital_ids = {
            int(player): int(tid)
            for player, tid in getattr(self, "player_capital_ids", {}).items()
            if int(player) >= 0
            and int(player) < self.num_players
            and int(player) not in self.commercial_city_players
            and int(tid) in valid_ids
        }
        self.sanctuary_territory_ids.difference_update(set(self.player_capital_ids.values()))

    def assign_initial_player_capitals(self) -> None:
        """Attribue une capitale initiale aux joueurs ordinaires uniquement.

        Les Cites commercantes gardent leurs regles propres. Les voisins directs
        d'une capitale sont rattaches au meme joueur quand ils ne sont ni une CC,
        ni une autre capitale deja reservee, ni l'ONU. Oui, meme la geographie
        doit faire de l'administration maintenant.
        """
        self.player_capital_ids = {}
        if not self.territories:
            return
        regular_players = [
            player for player in range(self.num_players)
            if player not in self.commercial_city_players and not self.is_onu_player(player)
        ]
        reserved: set[int] = set()
        cc_owned_ids = {terr.id for terr in self.territories if terr.owner in self.commercial_city_players}

        for player in regular_players:
            owned_ids = [terr.id for terr in self.territories if terr.owner == player and terr.id not in cc_owned_ids]
            if not owned_ids:
                continue

            def capital_score(tid: int) -> tuple[int, int, int, float]:
                neighbors = set(self.territories[tid].neighbors)
                closed = neighbors | {tid}
                cc_neighbors = len(neighbors & cc_owned_ids)
                reserved_overlap = len(closed & reserved)
                missing_neighbors = sum(
                    1 for nid in neighbors
                    if 0 <= nid < len(self.territories)
                    and self.territories[nid].owner not in (player, self.onu_player_id)
                    and self.territories[nid].owner not in self.commercial_city_players
                )
                return (cc_neighbors, reserved_overlap, missing_neighbors, random.random())

            capital_id = min(owned_ids, key=capital_score)
            self.player_capital_ids[player] = capital_id
            reserved.update(self.territories[capital_id].neighbors)
            reserved.add(capital_id)

        capital_ids = set(self.player_capital_ids.values())
        for player, capital_id in self.player_capital_ids.items():
            if not (0 <= capital_id < len(self.territories)):
                continue
            capital = self.territories[capital_id]
            capital.owner = player
            capital.regiments = self.INITIAL_CAPITAL_REGIMENTS
            for neighbor_id in capital.neighbors:
                if not (0 <= neighbor_id < len(self.territories)):
                    continue
                if neighbor_id in capital_ids:
                    continue
                neighbor = self.territories[neighbor_id]
                if neighbor.owner == self.onu_player_id or neighbor.owner in self.commercial_city_players:
                    continue
                neighbor.owner = player
        self.sanitize_player_capitals()

    def assign_initial_ownership_and_armies(self) -> None:
        if self.tribes_mode and self.base_ai_players:
            self._assign_ownership_tribes()
        else:
            self._assign_ownership_random()
        self.assign_initial_player_capitals()

    def _assign_ownership_random(self) -> None:
        ids = list(range(len(self.territories)))
        random.shuffle(ids)
        commercial_players = sorted(player for player in self.commercial_city_players if 0 <= player < self.num_players)
        for player, tid in zip(commercial_players, ids[:len(commercial_players)]):
            self.territories[tid].owner = player
            self.commercial_city_capital_ids[player] = tid
        remaining_ids = ids[len(commercial_players):]
        regular_players = [p for p in range(self.num_players) if p not in self.commercial_city_players]
        if not regular_players:
            regular_players = list(range(self.num_players))
        current_index = 0
        for tid in remaining_ids:
            self.territories[tid].owner = regular_players[current_index % len(regular_players)]
            current_index += 1
        self._distribute_armies()
        return

    def _assign_ownership_tribes(self) -> None:
        """Mode Tribus : joueurs IA recoivent des territoires contigus (BFS depuis seed),
        joueurs humains recoivent le reste distribue aleatoirement.
        Environ 10% des territoires IA peuvent etre places hors du bloc contigu (exceptions)."""
        num_terr = len(self.territories)
        if num_terr == 0:
            self._distribute_armies()
            return

        ai_players = sorted(p for p in self.base_ai_players if p not in self.commercial_city_players)
        human_players = [p for p in range(self.num_players) if p not in self.base_ai_players and p not in self.commercial_city_players]
        num_ai = len(ai_players)

        # Territoires par joueur (equitable)
        base_count = num_terr // self.num_players
        remainder = num_terr % self.num_players
        # Attribuer un quota a chaque joueur (ordre: IA d'abord pour le BFS, puis humains)
        player_quota: dict[int, int] = {}
        all_players_ordered = ai_players + human_players
        for i, p in enumerate(all_players_ordered):
            player_quota[p] = base_count + (1 if i < remainder else 0)

        # Initialiser proprietaires a -1
        for terr in self.territories:
            terr.owner = -1

        unassigned = set(range(num_terr))

        commercial_players = sorted(player for player in self.commercial_city_players if 0 <= player < self.num_players)
        commercial_seeds = random.sample(list(unassigned), min(len(commercial_players), len(unassigned)))
        for player, tid in zip(commercial_players, commercial_seeds):
            self.territories[tid].owner = player
            self.commercial_city_capital_ids[player] = tid
            unassigned.discard(tid)

        # --- Phase 1 : BFS contigu pour chaque joueur IA ---
        # Choisir des seeds bien espaces entre IA
        import heapq as _hq

        ai_seeds: list[int] = []
        available_seeds = list(unassigned)
        random.shuffle(available_seeds)

        if num_ai > 0:
            # Premier seed aleatoire
            seed0 = random.choice(available_seeds)
            ai_seeds.append(seed0)
            # Suivants : maximiser la distance graphe depuis les seeds deja choisis
            for _ in range(num_ai - 1):
                if not available_seeds:
                    break
                best_seed = max(
                    available_seeds,
                    key=lambda t: min(
                        self._bfs_distance_approx(t, s) for s in ai_seeds
                    ),
                )
                ai_seeds.append(best_seed)

        # BFS simultane (priority queue par ratio remplissage)
        # Chaque IA grandit depuis son seed jusqu'a atteindre son quota
        frontiers: dict[int, list] = {p: [] for p in ai_players}
        assigned_count: dict[int, int] = {p: 0 for p in ai_players}

        for idx, p in enumerate(ai_players):
            if idx < len(ai_seeds):
                seed = ai_seeds[idx]
                self.territories[seed].owner = p
                unassigned.discard(seed)
                assigned_count[p] = 1
                for nb in self.territories[seed].neighbors:
                    if nb in unassigned:
                        _hq.heappush(frontiers[p], (random.random(), nb))

        # Expansion BFS round-robin jusqu'a remplissage des quotas
        active_ai = [p for p in ai_players if assigned_count[p] < player_quota[p]]
        while active_ai:
            random.shuffle(active_ai)  # eviter biais d'ordre
            progressed = False
            for p in list(active_ai):
                if assigned_count[p] >= player_quota[p]:
                    active_ai.remove(p)
                    continue
                # Chercher une cellule frontiere non assignee
                picked = None
                while frontiers[p]:
                    _, candidate = _hq.heappop(frontiers[p])
                    if candidate in unassigned:
                        picked = candidate
                        break
                if picked is not None:
                    self.territories[picked].owner = p
                    unassigned.discard(picked)
                    assigned_count[p] += 1
                    progressed = True
                    for nb in self.territories[picked].neighbors:
                        if nb in unassigned:
                            _hq.heappush(frontiers[p], (random.random(), nb))
                    if assigned_count[p] >= player_quota[p]:
                        active_ai.remove(p)
                else:
                    # Plus de voisins contigus disponibles : prendre un territoire distant (exception)
                    if unassigned and assigned_count[p] < player_quota[p]:
                        fallback = random.choice(list(unassigned))
                        self.territories[fallback].owner = p
                        unassigned.discard(fallback)
                        assigned_count[p] += 1
                        progressed = True
                        for nb in self.territories[fallback].neighbors:
                            if nb in unassigned:
                                _hq.heappush(frontiers[p], (random.random(), nb))
                    if assigned_count[p] >= player_quota[p]:
                        active_ai.remove(p)
            if not progressed:
                break

        # --- Phase 2 : humains recoivent le reste (aléatoire) ---
        remaining = list(unassigned)
        random.shuffle(remaining)
        idx_human = 0
        for tid in remaining:
            if not human_players:
                # Fallback: donner au joueur humain 0 ou distribuer aux IA depassant quota
                self.territories[tid].owner = 0
                continue
            p = human_players[idx_human % len(human_players)]
            self.territories[tid].owner = p
            idx_human += 1

        # Securite : aucun territoire ne doit rester a -1
        for terr in self.territories:
            if terr.owner == -1:
                terr.owner = random.randint(0, self.num_players - 1)

        self._distribute_armies()

    def _bfs_distance_approx(self, start: int, end: int) -> int:
        """Distance graphe approximative entre deux territoires (BFS, limite a 30 pas)."""
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
                for nb in self.territories[tid].neighbors:
                    if nb == end:
                        return dist
                    if nb not in visited:
                        visited.add(nb)
                        next_frontier.append(nb)
            frontier = next_frontier
        return max_depth

    def _distribute_armies(self) -> None:
        """Distribue les armees initiales apres assignation des proprietaires."""
        territory_per_player = {p: 0 for p in range(self.num_players)}
        for terr in self.territories:
            if 0 <= terr.owner < self.num_players:
                territory_per_player[terr.owner] += 1

        max_territories = max(territory_per_player.values())
        starting_regiments = max_territories + 10
        regiments_left = {p: starting_regiments for p in range(self.num_players)}
        for terr in self.territories:
            terr.regiments = 1
            if 0 <= terr.owner < self.num_players:
                regiments_left[terr.owner] -= 1
        for player in range(self.num_players):
            owned_ids = [t.id for t in self.territories if t.owner == player]
            remaining = regiments_left[player]
            while remaining > 0 and owned_ids:
                tid = random.choice(owned_ids)
                self.territories[tid].regiments += 1
                remaining -= 1

        for player in range(self.num_players):
            owned = [t for t in self.territories if t.owner == player]
            if not owned:
                continue
            bonus_territory = random.choice(owned)
            bonus_territory.regiments += 5

        self.assign_random_bonus_territories()

    def compute_territory_distances(self, start_id: int) -> dict[int, int]:
        if not (0 <= start_id < len(self.territories)):
            return {}
        distances = {start_id: 0}
        queue = [start_id]
        index = 0
        while index < len(queue):
            current = queue[index]
            index += 1
            current_distance = distances[current]
            for neighbor_id in self.territories[current].neighbors:
                if neighbor_id not in distances:
                    distances[neighbor_id] = current_distance + 1
                    queue.append(neighbor_id)
        return distances

    def assign_golden_territories(self) -> None:
        self.golden_territory_ids = set()
        if len(self.territories) <= 4:
            self.golden_territory_ids = set(range(len(self.territories)))
            return

        all_ids = list(range(len(self.territories)))
        distance_maps = {tid: self.compute_territory_distances(tid) for tid in all_ids}
        min_distance_targets = [5, 4, 3, 2]

        for min_distance in min_distance_targets:
            for _ in range(300):
                random.shuffle(all_ids)
                selection: list[int] = []
                for tid in all_ids:
                    if all(distance_maps[chosen].get(tid, 10 ** 9) >= min_distance for chosen in selection):
                        selection.append(tid)
                        if len(selection) == 4:
                            self.golden_territory_ids = set(selection)
                            return

        best_selection: list[int] = []
        best_score = -1
        for _ in range(400):
            random.shuffle(all_ids)
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

        self.golden_territory_ids = set(best_selection[:4] if best_selection else all_ids[:4])

    def is_onu_player(self, player: int) -> bool:
        return player == self.onu_player_id

    def is_sanctuary_territory(self, territory_id: int) -> bool:
        return territory_id in self.sanctuary_territory_ids

    def is_submitted_territory(self, territory_id: int) -> bool:
        return territory_id in getattr(self, "submitted_territory_ids", set())

    def get_submitted_territory_overlord(self, territory_id: int) -> Optional[int]:
        overlord = getattr(self, "submitted_territory_overlords", {}).get(territory_id)
        if overlord is None or overlord < 0 or overlord >= self.num_players:
            return None
        return overlord

    def is_vassal_territory(self, territory_id: int) -> bool:
        return False

    def get_vassal_overlord(self, territory_id: int) -> Optional[int]:
        return None

    def get_vassal_player(self, territory_id: int) -> Optional[int]:
        return None

    def can_player_create_vassal_from_corruption(self, player: int) -> bool:
        return False

    def sanitize_vassal_territories(self) -> None:
        self.vassal_territory_overlords = {}
        self.vassal_territory_created_turns = {}
        self.vassal_players = {}
        self.integrated_vassal_territories = {}

    def create_vassal_from_corruption(self, territory_id: int, overlord: int) -> Optional[int]:
        return None

    def integrate_due_vassals(self, display: bool = True) -> List[str]:
        self.sanitize_vassal_territories()
        return []

    def sanitize_submitted_territories(self) -> None:
        valid_ids = set(range(len(self.territories)))
        self.submitted_territory_ids = {
            tid for tid in getattr(self, "submitted_territory_ids", set())
            if tid in valid_ids and self.territories[tid].owner == self.onu_player_id
        }
        self.submitted_territory_overlords = {
            tid: int(overlord)
            for tid, overlord in getattr(self, "submitted_territory_overlords", {}).items()
            if tid in self.submitted_territory_ids and 0 <= int(overlord) < self.num_players
        }
        self.submitted_territory_created_turns = {
            tid: max(1, int(getattr(self, "submitted_territory_created_turns", {}).get(tid, self.turn)))
            for tid in self.submitted_territory_ids
            if tid in self.submitted_territory_overlords
        }
        self.integrated_submitted_territories = {
            int(player): {
                int(tid) for tid in territory_ids
                if 0 <= int(tid) < len(self.territories) and self.territories[int(tid)].owner == int(player)
            }
            for player, territory_ids in getattr(self, "integrated_submitted_territories", {}).items()
            if 0 <= int(player) < self.num_players
        }
        self.sanctuary_territory_ids.update(self.submitted_territory_ids)

    def is_ai_nation_player(self, player: int) -> bool:
        return self.is_ai_player(player) and player in getattr(self, "nation_players", set())

    def integrate_due_submitted_territories(self, display: bool = True) -> List[str]:
        messages = moteur_regles.integrate_due_submitted_territories(self)
        if messages and display:
            self.show_message(" | ".join(messages), 6200)
        return messages

    def calculate_submitted_territory_tribute(self, player: int) -> int:
        return moteur_regles.calculate_submitted_territory_tribute(self, player)

    def calculate_submitted_territory_income(self, territory: Territory) -> int:
        return moteur_regles.calculate_submitted_territory_income(self, territory)

    def get_union_members(self, player: int) -> set[int]:
        return {player} if isinstance(player, int) and player >= 0 else set()

    def get_nation_territory_limit(self, player: int) -> int:
        return 10 ** 9

    def ensure_union_origin_snapshot(self, player: int) -> set[int]:
        return {terr.id for terr in self.territories if terr.owner == player}

    def should_force_submit_for_nation_limit(self, attacker: int) -> bool:
        return False

    def sanitize_union_state(self) -> None:
        self.union_members = {}
        self.union_original_territories = {}

    def enforce_nation_territory_limits(self) -> list[str]:
        return []

    def ask_human_submission_choice(self, attacker: int, territory: Territory, defeated_regiments: int = 1) -> bool:
        """Dialogue Tkinter demandant a une nation humaine si elle soumet le territoire."""
        if tk is None or messagebox is None:
            return False
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            return bool(messagebox.askyesno(
                "Territoire conquis",
                f"{territory.name} est vaincu.\n\nOui : soumettre le territoire.\nNon : annexer normalement.",
                parent=root,
            ))
        finally:
            root.destroy()

    def should_submit_conquered_territory(self, attacker: int, territory: Territory, defeated_regiments: int = 1) -> bool:
        return moteur_regles.should_submit_conquered_territory(
            self, attacker, territory, defeated_regiments,
            submit_decider=self.ask_human_submission_choice,
        )

    def submit_conquered_territory(self, territory_id: int, overlord: int, regiments: int) -> bool:
        submitted = moteur_regles.submit_conquered_territory(self, territory_id, overlord, regiments)
        if submitted:
            if self.selected_source == territory_id:
                self.selected_source = None
            if self.selected_target == territory_id:
                self.selected_target = None
        return submitted

    def is_golden_territory(self, territory_id: int) -> bool:
        return territory_id in self.golden_territory_ids

    def enforce_golden_territory_onu_immunity(self) -> None:
        if not self.golden_territory_ids:
            return
        golden_ids = {tid for tid in self.golden_territory_ids if 0 <= tid < len(self.territories)}
        if not golden_ids:
            return
        self.sanctuary_territory_ids.difference_update(golden_ids)
        active_players = [player for player in range(self.num_players) if player >= 0 and not self.is_onu_player(player)]
        for territory_id in golden_ids:
            terr = self.territories[territory_id]
            if terr.owner == self.onu_player_id or terr.owner < 0:
                terr.owner = random.choice(active_players) if active_players else 0
                terr.regiments = max(1, terr.regiments)

    def choose_owned_contiguous_block(self, player: int, count: int) -> List[Territory]:
        """Choisit si possible un bloc contigu de territoires appartenant au joueur.

        Sert aux revoltes, trahisons et revolutions : un morceau d'empire se detache
        au lieu d'une salade de confettis diplomatiques, ce qui est tout de meme
        moins grotesque. Les capitales ordinaires actives sont exclues du tirage :
        elles ne font jamais sedition, ne se revoltent jamais et ne trahissent jamais.
        """
        owned_ids = [
            terr.id for terr in self.territories
            if terr.owner == player and not self.is_active_regular_capital(terr.id)
        ]
        if count <= 0 or not owned_ids:
            return []
        target_count = min(count, len(owned_ids))
        owned_set = set(owned_ids)

        components: List[List[int]] = []
        seen: set[int] = set()
        for tid in owned_ids:
            if tid in seen:
                continue
            stack = [tid]
            seen.add(tid)
            component: List[int] = []
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbor_id in self.territories[current].neighbors:
                    if neighbor_id in owned_set and neighbor_id not in seen:
                        seen.add(neighbor_id)
                        stack.append(neighbor_id)
            components.append(component)

        eligible_components = [component for component in components if len(component) >= target_count]
        if eligible_components:
            component = random.choice(eligible_components)
            start_id = random.choice(component)
            selected: List[int] = [start_id]
            selected_set = {start_id}
            frontier = [nid for nid in self.territories[start_id].neighbors if nid in component]
            random.shuffle(frontier)
            while frontier and len(selected) < target_count:
                picked = frontier.pop(0)
                if picked in selected_set:
                    continue
                selected.append(picked)
                selected_set.add(picked)
                next_neighbors = [
                    nid for nid in self.territories[picked].neighbors
                    if nid in component and nid not in selected_set and nid not in frontier
                ]
                random.shuffle(next_neighbors)
                frontier.extend(next_neighbors)
            if len(selected) < target_count:
                remaining = [tid for tid in component if tid not in selected_set]
                random.shuffle(remaining)
                selected.extend(remaining[: target_count - len(selected)])
            return [self.territories[tid] for tid in selected[:target_count]]

        largest_component = max(components, key=len, default=[])
        selected_ids = list(largest_component)
        remaining_ids = [tid for tid in owned_ids if tid not in selected_ids]
        random.shuffle(remaining_ids)
        selected_ids.extend(remaining_ids[: target_count - len(selected_ids)])
        return [self.territories[tid] for tid in selected_ids[:target_count]]

    def convert_territory_to_sanctuary(self, territory_id: int, regiments: Optional[int] = None) -> bool:
        if not (0 <= territory_id < len(self.territories)):
            return False
        if (
            self.is_golden_territory(territory_id)
            or self.is_commercial_city_territory(territory_id)
            or self.is_regular_capital_territory(territory_id)
        ):
            return False
        terr = self.territories[territory_id]
        terr.owner = self.onu_player_id
        terr.regiments = regiments if regiments is not None else max(1, terr.regiments)
        terr.reinforcement_bonus = 1
        self.sanctuary_territory_ids.add(territory_id)
        self.submitted_territory_ids.discard(territory_id)
        self.submitted_territory_overlords.pop(territory_id, None)
        self.submitted_territory_created_turns.pop(territory_id, None)
        self.vassal_territory_overlords.pop(territory_id, None)
        self.vassal_territory_created_turns.pop(territory_id, None)
        self.vassal_players.pop(territory_id, None)
        for territory_ids in getattr(self, "integrated_vassal_territories", {}).values():
            territory_ids.discard(territory_id)
        self.ultra_super_territory_ids.discard(territory_id)
        self.super_territory_ids.discard(territory_id)
        if self.selected_source == territory_id:
            self.selected_source = None
        if self.selected_target == territory_id:
            self.selected_target = None
        return True

    def maybe_spawn_random_sanctuary_territory(self, display: bool = True) -> Optional[str]:
        message = moteur_regles.maybe_spawn_random_sanctuary_territory(self)
        if message and display:
            self.show_message(message, 4600)
        return message

    def maybe_release_random_sanctuary_territory(self, display: bool = True) -> Optional[str]:
        message = moteur_regles.maybe_release_random_sanctuary_territory(self)
        if message and display:
            self.show_message(message, 4600)
        return message

    def maybe_release_unstable_submitted_territories(self, display: bool = True) -> List[str]:
        messages = moteur_regles.maybe_release_unstable_submitted_territories(self)
        if messages and display:
            self.show_message(" | ".join(messages), 6200)
        return messages

    def assign_sanctuary_territories(self) -> None:
        """Place trois territoires ONU neutres, sans conflit avec les +3 ni les territoires dores."""
        self.sanctuary_territory_ids = set()
        self.submitted_territory_ids = set()
        self.submitted_territory_overlords = {}
        self.submitted_territory_created_turns = {}
        self.vassal_territory_overlords = {}
        self.vassal_territory_created_turns = {}
        self.vassal_players = {}
        if not self.territories:
            return

        forbidden = set(self.ultra_super_territory_ids) | set(self.golden_territory_ids) | set(getattr(self, "player_capital_ids", {}).values())
        candidates = [terr.id for terr in self.territories if terr.id not in forbidden]
        if len(candidates) < 3:
            candidates = [
                terr.id for terr in self.territories
                if terr.id not in self.golden_territory_ids
                and terr.id not in set(getattr(self, "player_capital_ids", {}).values())
            ]

        selected = random.sample(candidates, min(3, len(candidates)))
        self.sanctuary_territory_ids = set()
        for tid in selected:
            self.convert_territory_to_sanctuary(tid, regiments=5)

    def reset_economy_state(self) -> None:
        self.player_money = {player: 0 for player in range(self.num_players)}
        self.precious_mineral_mine_ids = set()
        self.fortress_territory_ids = set()
        self.fortress_capture_counts = {}
        self.industry_territory_ids = set()
        self.industry_capture_counts = {}
        self.factory_territory_ids = set()
        self.airport_territory_ids = set()
        self.port_territory_ids = set()
        self.industrial_capture_counts = {}
        self.cultural_center_ages = {}
        self.cultural_capture_counts = {}
        self.university_territory_ids = set()
        self.university_capture_counts = {}
        self.university_ages = {}
        self.temple_territory_ids = set()
        self.temple_capture_counts = {}
        self.religion_founders = {}
        self.religion_foundation_turns = {}
        self.religion_last_spread_turns = {}
        self.religion_holy_sites = {}
        self.religious_influence = {}
        self.last_religion_foundation_message = None
        self.player_science = {}
        self.culture_expansion_milestones = {}
        self.wonder_territories = {}
        self.pending_wonder_type = None
        self.last_stand_bonus_players = set()
        self.last_stand_bonus_territory = {}
        self.tax_haven_turn_start_territory_counts = {}
        self.active_alliances = {}
        self.active_offensive_alliances = {}
        self.active_ai_alliances = {}
        self.alliance_start_turns = {}
        self.offensive_alliance_start_turns = {}
        self.ai_alliance_start_turns = {}
        self.pending_offensive_alliance_ai = None
        self.pending_gift_territory_id = None
        self.pending_bridge_territory_id = None
        self.bridge_links = set()
        self.fragile_bridge_links = set()
        self.bridge_link_points = {}
        self.bridge_geometry_cache = {}
        self.bridge_coastal_cells_cache = {}
        self.recompute_neighbors_from_grid()
        self.last_alliance_break_message = ""
        self.nation_players = set()
        self.nation_qualification_start_turns = {}
        self.nation_capital_loss_start_turns = {}
        self.nation_alliances = set()
        self.nation_wars = set()
        self.cold_war_active = False
        self.cold_war_nations = None
        self.cold_war_alliances = {}
        self.colonized_players = set()
        self.submitted_territory_ids = set()
        self.submitted_territory_overlords = {}
        self.submitted_territory_created_turns = {}
        self.vassal_territory_overlords = {}
        self.vassal_territory_created_turns = {}
        self.vassal_players = {}
        self.integrated_vassal_territories = {}
        self.integrated_submitted_territories = {}
        self.union_members = {}
        self.union_original_territories = {}
        self.final_duel_active = False
        self.final_duel_champions = None
        self.final_duel_alliances = {}
        self.final_duel_pending_winner = None
        self.recent_major_events = []
        self.major_event_modal = None
        self.major_event_modal_queue = []
        self.pending_major_events_for_humans = {}
        self.collecting_between_turn_events = False
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0
        self.shop_action = None
        self.shop_mercenary_quantity = 1
        self.shop_gift_amount = 10

    def sanitize_economy_state(self) -> None:
        valid_ids = set(range(len(self.territories)))
        self.sanitize_player_capitals()
        self.sanitize_submitted_territories()
        self.sanitize_vassal_territories()
        self.fortress_territory_ids = {tid for tid in self.fortress_territory_ids if tid in valid_ids}
        self.precious_mineral_mine_ids = {
            tid for tid in getattr(self, "precious_mineral_mine_ids", set()) if tid in valid_ids
        }
        sanitized_wonders: dict[str, int] = {}
        occupied_wonder_territories: set[int] = set()
        for wonder_type, territory_id in getattr(self, "wonder_territories", {}).items():
            if wonder_type not in self.WONDER_DEFINITIONS:
                continue
            territory_id = int(territory_id)
            if territory_id not in valid_ids or territory_id in occupied_wonder_territories:
                continue
            sanitized_wonders[wonder_type] = territory_id
            occupied_wonder_territories.add(territory_id)
        self.wonder_territories = sanitized_wonders
        raw_factory_ids = {tid for tid in getattr(self, "factory_territory_ids", set()) if tid in valid_ids}
        raw_airport_ids = {tid for tid in getattr(self, "airport_territory_ids", set()) if tid in valid_ids}
        raw_port_ids = {tid for tid in getattr(self, "port_territory_ids", set()) if tid in valid_ids}

        # Regle generale : un seul amenagement industriel par territoire.
        # Les cites commercantes n'ont plus d'exception : elles diversifient leurs
        # installations sur plusieurs territoires au lieu d'empiler toute la quincaillerie
        # au meme endroit, parce que meme le capitalisme a fini par lire le reglement.
        self.factory_territory_ids = set(raw_factory_ids)
        self.airport_territory_ids = {
            tid for tid in raw_airport_ids
            if tid not in self.factory_territory_ids
        }
        self.port_territory_ids = {
            tid for tid in raw_port_ids
            if tid not in self.factory_territory_ids and tid not in self.airport_territory_ids
        }
        self.industry_territory_ids = set(self.factory_territory_ids)
        self.fortress_capture_counts = {
            tid: max(0, int(self.fortress_capture_counts.get(tid, 0)))
            for tid in self.fortress_territory_ids
        }
        self.industrial_capture_counts = {
            tid: max(0, int(getattr(self, "industrial_capture_counts", {}).get(tid, 0)))
            for tid in (self.factory_territory_ids | self.airport_territory_ids | self.port_territory_ids)
        }
        self.industry_capture_counts = {tid: self.industrial_capture_counts.get(tid, 0) for tid in self.factory_territory_ids}
        self.cultural_center_ages = {
            tid: [max(0, int(age)) for age in ages[:self.MAX_CULTURAL_CENTERS_PER_TERRITORY]]
            for tid, ages in getattr(self, "cultural_center_ages", {}).items()
            if tid in valid_ids and ages
        }
        self.cultural_capture_counts = {
            tid: max(0, int(getattr(self, "cultural_capture_counts", {}).get(tid, 0)))
            for tid in self.cultural_center_ages
        }
        self.university_territory_ids = {
            tid for tid in getattr(self, "university_territory_ids", set())
            if tid in valid_ids
        }
        self.university_capture_counts = {
            tid: max(0, int(getattr(self, "university_capture_counts", {}).get(tid, 0)))
            for tid in self.university_territory_ids
        }
        self.university_ages = {
            tid: max(0, int(getattr(self, "university_ages", {}).get(tid, 0)))
            for tid in self.university_territory_ids
        }
        self.temple_territory_ids = {
            tid for tid in getattr(self, "temple_territory_ids", set())
            if tid in valid_ids
        }
        self.temple_capture_counts = {
            tid: max(0, int(getattr(self, "temple_capture_counts", {}).get(tid, 0)))
            for tid in self.temple_territory_ids
        }
        self.sanitize_religion_state()
        self.player_science = {
            int(player): max(0, int(points))
            for player, points in getattr(self, "player_science", {}).items()
            if 0 <= int(player) < self.num_players
        }
        self.culture_expansion_milestones = {
            int(player): max(0, int(milestone) // 50 * 50)
            for player, milestone in getattr(self, "culture_expansion_milestones", {}).items()
            if 0 <= int(player) < self.num_players
        }
        self.commercial_city_capital_ids = {
            int(player): int(tid)
            for player, tid in getattr(self, "commercial_city_capital_ids", {}).items()
            if int(player) in self.commercial_city_players
            and int(tid) in valid_ids
        }
        self.refresh_destroyed_commercial_cities()
        self.enforce_commercial_city_cultural_center_limit(self.current_player)
        self.refresh_last_stand_bonus_state()
        self.enforce_commercial_city_wonder_exclusivity()
        for player in range(self.num_players):
            self.ensure_player_economy(player)

    def is_territory_adjacent_to_ocean(self, territory_id: int) -> bool:
        if not (0 <= territory_id < len(self.territories)):
            return False
        for r, c in self.territories[territory_id].cells:
            for nr, nc in self.neighbors4(r, c):
                if self.grid_territory[nr][nc] < 0:
                    return True
        return False

    def get_industrial_structure_sets(self) -> dict[str, set[int]]:
        return {
            "factory": self.factory_territory_ids,
            "airport": self.airport_territory_ids,
            "port": self.port_territory_ids,
        }

    def get_industrial_structure_count(self, territory_id: int) -> int:
        return sum(1 for ids in self.get_industrial_structure_sets().values() if territory_id in ids)

    def get_industrial_structure_type(self, territory_id: int) -> Optional[str]:
        for structure_type, ids in self.get_industrial_structure_sets().items():
            if territory_id in ids:
                return structure_type
        return None

    def calculate_sale_structure_bonus(self, territory: Territory) -> int:
        bonus_count = 0
        if territory.id in self.fortress_territory_ids:
            bonus_count += 1
        bonus_count += self.get_industrial_structure_count(territory.id)
        bonus_count += self.get_cultural_center_count(territory.id)
        if territory.id in self.university_territory_ids:
            bonus_count += 1
        if territory.id in getattr(self, "temple_territory_ids", set()):
            bonus_count += 1
        if territory.reinforcement_bonus >= 3:
            bonus_count += 1
        return bonus_count * 50

    def calculate_territory_sale_price(self, territory: Territory) -> int:
        return max(0, territory.regiments) * 10 + self.calculate_sale_structure_bonus(territory)


    def player_has_complete_industrial_set(self, player: int) -> bool:
        if player < 0 or self.is_onu_player(player):
            return False
        owned_ids = {terr.id for terr in self.territories if terr.owner == player}
        return (
            bool(self.factory_territory_ids & owned_ids)
            and bool(self.airport_territory_ids & owned_ids)
            and bool(self.port_territory_ids & owned_ids)
        )

    def add_industrial_structure(self, territory_id: int, structure_type: str) -> bool:
        return moteur_regles.add_industrial_structure(self, territory_id, structure_type)

    def remove_all_industrial_structures(self, territory_id: int) -> int:
        return moteur_regles.remove_all_industrial_structures(self, territory_id)

    def get_cultural_center_count(self, territory_id: int) -> int:
        return len(self.cultural_center_ages.get(territory_id, []))

    def can_add_cultural_center(self, territory_id: int) -> bool:
        if not (0 <= territory_id < len(self.territories)):
            return False
        owner = self.territories[territory_id].owner
        if self.is_commercial_city_player(owner):
            capital_id = self.get_commercial_city_capital_id(owner)
            if territory_id != capital_id or self.count_commercial_city_cultural_centers(owner) >= 1:
                return False
        return self.get_cultural_center_count(territory_id) < self.MAX_CULTURAL_CENTERS_PER_TERRITORY

    def add_cultural_center(self, territory_id: int, age: int = 0) -> bool:
        return moteur_regles.add_cultural_center(self, territory_id, age)

    def count_commercial_city_cultural_centers(self, player: int) -> int:
        if not self.is_commercial_city_player(player):
            return 0
        capital_id = self.get_commercial_city_capital_id(player)
        return self.get_cultural_center_count(capital_id) if capital_id is not None else 0

    def enforce_commercial_city_cultural_center_limit(self, player: Optional[int] = None) -> None:
        players = [player] if player is not None else sorted(self.commercial_city_players)
        valid_ids = set(range(len(self.territories)))
        for cc_player in players:
            if not self.is_commercial_city_player(cc_player):
                continue
            capital_id = self.get_commercial_city_capital_id(cc_player)
            owned_with_centers = [
                tid for tid in self.cultural_center_ages
                if tid in valid_ids
                and self.territories[tid].owner == cc_player
                and self.cultural_center_ages.get(tid)
            ]
            if capital_id is None:
                continue
            for tid in owned_with_centers:
                if tid != capital_id:
                    self.cultural_center_ages.pop(tid, None)
                    self.cultural_capture_counts.pop(tid, None)
            if self.cultural_center_ages.get(capital_id):
                self.cultural_center_ages[capital_id] = [max(self.cultural_center_ages.get(capital_id, [0]))]
                self.cultural_capture_counts.setdefault(capital_id, 0)

    def can_commercial_city_gain_territory(self, player: int, territory_id: int) -> bool:
        if player not in getattr(self, "commercial_city_players", set()):
            return True
        if self.is_any_capital_territory(territory_id):
            return False
        return self.is_territory_adjacent_to_player(territory_id, player)

    def add_commercial_city_mercenary(self, player: int) -> None:
        owned = [terr for terr in self.territories if terr.owner == player]
        if owned:
            random.choice(owned).regiments += 1

    def has_university(self, territory_id: int) -> bool:
        return territory_id in self.university_territory_ids

    def can_add_university(self, territory_id: int) -> bool:
        return 0 <= territory_id < len(self.territories) and territory_id not in self.university_territory_ids

    def add_university(self, territory_id: int) -> bool:
        return moteur_regles.add_university(self, territory_id)

    def remove_university(self, territory_id: int) -> bool:
        return moteur_regles.remove_university(self, territory_id)

    def has_temple(self, territory_id: int) -> bool:
        return territory_id in getattr(self, "temple_territory_ids", set())

    def can_add_temple(self, territory_id: int) -> bool:
        return 0 <= territory_id < len(self.territories) and territory_id not in getattr(self, "temple_territory_ids", set())

    def add_temple(self, territory_id: int) -> bool:
        return moteur_regles.add_temple(self, territory_id)

    def remove_temple(self, territory_id: int) -> bool:
        return moteur_regles.remove_temple(self, territory_id)

    def get_wonder_name(self, wonder_type: Optional[str]) -> str:
        definition = self.WONDER_DEFINITIONS.get(wonder_type or "")
        return str(definition["name"]) if definition else "Merveille inconnue"

    def get_wonder_effect(self, wonder_type: Optional[str]) -> str:
        definition = self.WONDER_DEFINITIONS.get(wonder_type or "")
        return str(definition["effect"]) if definition else ""

    def get_available_wonder_types(self) -> list[str]:
        built = set(getattr(self, "wonder_territories", {}))
        return [wonder_type for wonder_type in self.WONDER_DEFINITIONS if wonder_type not in built]

    def get_wonder_science_threshold(self, player: int) -> int:
        if self.is_ai_player(player):
            return self.AI_SCIENCE_WONDER_THRESHOLD
        return self.SCIENCE_WONDER_THRESHOLD

    def can_player_build_wonder(self, player: int) -> bool:
        return self.has_science_level(player, self.get_wonder_science_threshold(player))

    def get_wonder_type_at_territory(self, territory_id: int) -> Optional[str]:
        for wonder_type, wonder_territory_id in getattr(self, "wonder_territories", {}).items():
            if wonder_territory_id == territory_id:
                return wonder_type
        return None

    def get_wonder_controller(self, wonder_type: str) -> Optional[int]:
        territory_id = getattr(self, "wonder_territories", {}).get(wonder_type)
        if territory_id is None or not (0 <= territory_id < len(self.territories)):
            return None
        owner = self.territories[territory_id].owner
        if owner < 0 or self.is_onu_player(owner):
            return None
        return owner

    def player_controls_wonder(self, player: int, wonder_type: str) -> bool:
        return self.get_wonder_controller(wonder_type) == player

    def build_wonder(self, territory_id: int, wonder_type: str, record_event: bool = True) -> bool:
        return moteur_regles.build_wonder(self, territory_id, wonder_type, record_event)

    def get_religion_name(self, religion_id: int) -> str:
        if 0 <= religion_id < len(self.RELIGIONS):
            return str(self.RELIGIONS[religion_id]["name"])
        return f"Religion {religion_id + 1}"

    def get_religion_symbol(self, religion_id: int) -> str:
        if 0 <= religion_id < len(self.RELIGIONS):
            return str(self.RELIGIONS[religion_id]["symbol"])
        return "?"

    def get_religion_color(self, religion_id: int) -> Tuple[int, int, int]:
        if 0 <= religion_id < len(self.RELIGIONS):
            return self.RELIGIONS[religion_id]["color"]
        return (200, 200, 200)

    def is_religion_view_active(self) -> bool:
        return getattr(self, "map_icon_view", "all" if getattr(self, "show_all_map_icons", False) else "fortress") == "religion"

    def is_territory_tax_haven_immune_to_religion(self, territory_id: int) -> bool:
        return self.is_last_stand_bonus_territory(territory_id)

    def sanitize_religion_state(self) -> None:
        valid_ids = set(range(len(self.territories)))
        valid_religions = set(range(len(self.RELIGIONS)))
        self.religion_founders = {
            int(player): int(religion_id)
            for player, religion_id in getattr(self, "religion_founders", {}).items()
            if 0 <= int(player) < self.num_players and int(religion_id) in valid_religions
        }
        used_religions = set(self.religion_founders.values())
        if "elyrion_sanctuary" in getattr(self, "wonder_territories", {}):
            used_religions.add(self.WONDER_RELIGION_ID)
        self.religion_foundation_turns = {
            int(religion_id): max(1, int(turn))
            for religion_id, turn in getattr(self, "religion_foundation_turns", {}).items()
            if int(religion_id) in used_religions
        }
        self.religion_last_spread_turns = {
            religion_id: max(
                self.religion_foundation_turns.get(religion_id, 1),
                int(getattr(self, "religion_last_spread_turns", {}).get(
                    religion_id,
                    self.religion_foundation_turns.get(religion_id, self.turn),
                )),
            )
            for religion_id in used_religions
        }
        self.religion_holy_sites = {
            int(religion_id): int(tid)
            for religion_id, tid in getattr(self, "religion_holy_sites", {}).items()
            if int(religion_id) in used_religions and int(tid) in valid_ids
        }
        self.religious_influence = {
            int(tid): int(religion_id)
            for tid, religion_id in getattr(self, "religious_influence", {}).items()
            if int(tid) in valid_ids
            and int(religion_id) in used_religions
            and not self.is_territory_tax_haven_immune_to_religion(int(tid))
        }

    def found_religion_if_possible(self, player: int, territory_id: int) -> Optional[str]:
        return moteur_regles.found_religion_if_possible(self, player, territory_id)

    def apply_initial_religious_influence(self, religion_id: int, holy_site_id: int) -> None:
        candidates = [holy_site_id]
        if 0 <= holy_site_id < len(self.territories):
            candidates.extend(self.territories[holy_site_id].neighbors)
        for tid in candidates:
            if not (0 <= tid < len(self.territories)):
                continue
            if self.is_territory_tax_haven_immune_to_religion(tid):
                continue
            if religion_id != self.WONDER_RELIGION_ID and tid != holy_site_id and tid in self.religious_influence:
                continue
            self.religious_influence[tid] = religion_id

    def get_player_temple_count(self, player: int) -> int:
        if player < 0 or self.is_onu_player(player):
            return 0
        return sum(
            1
            for territory_id in getattr(self, "temple_territory_ids", set())
            if 0 <= territory_id < len(self.territories)
            and self.territories[territory_id].owner == player
        )

    def get_religion_founder(self, religion_id: int) -> Optional[int]:
        if religion_id == self.WONDER_RELIGION_ID:
            return self.get_wonder_controller("elyrion_sanctuary")
        for player, founded_religion_id in getattr(self, "religion_founders", {}).items():
            if founded_religion_id == religion_id:
                return player
        return None

    def get_religion_spread_interval(self, religion_id: int) -> Optional[int]:
        founder = self.get_religion_founder(religion_id)
        if founder is None:
            return None
        temple_count = self.get_player_temple_count(founder)
        if temple_count <= 0:
            return None
        capped_count = min(7, temple_count)
        return self.RELIGION_SPREAD_INTERVAL_BY_TEMPLE_COUNT[capped_count]

    def get_national_religion_influenced_territory_count(self, player: int) -> int:
        religion_ids: set[int] = set()
        founded_religion_id = getattr(self, "religion_founders", {}).get(player)
        if founded_religion_id is not None:
            religion_ids.add(founded_religion_id)
        if self.player_controls_wonder(player, "elyrion_sanctuary"):
            religion_ids.add(self.WONDER_RELIGION_ID)
        if not religion_ids:
            return 0
        return sum(
            1
            for territory in self.territories
            if territory.owner == player
            and getattr(self, "religious_influence", {}).get(territory.id) in religion_ids
        )

    def get_religious_income_bonus(self, player: int) -> int:
        influenced_count = self.get_national_religion_influenced_territory_count(player)
        return influenced_count * self.RELIGIOUS_INCOME_BONUS_PER_TERRITORY

    def get_religious_reinforcement_bonus(self, player: int) -> int:
        influenced_count = self.get_national_religion_influenced_territory_count(player)
        if influenced_count <= 0:
            return 0
        return math.ceil(influenced_count / self.RELIGIOUS_REINFORCEMENT_TERRITORIES_PER_BONUS)

    def expand_religious_influences_if_due(self) -> List[str]:
        return moteur_regles.expand_religious_influences_if_due(self)

    def remove_religious_influence_from_tax_haven(self, territory_id: int) -> None:
        self.religious_influence.pop(territory_id, None)

    def get_controlled_holy_site_count(self, player: int) -> int:
        return sum(
            1
            for tid in getattr(self, "religion_holy_sites", {}).values()
            if 0 <= tid < len(self.territories) and self.territories[tid].owner == player
        )

    def get_required_holy_site_count_for_victory(self) -> int:
        if "elyrion_sanctuary" in getattr(self, "wonder_territories", {}):
            return 6
        return 5

    def is_holy_site_victory_active(self) -> bool:
        required = self.get_required_holy_site_count_for_victory()
        return len(getattr(self, "religion_holy_sites", {})) >= required

    def get_university_science_output(self, territory_id: int) -> int:
        age = max(0, int(getattr(self, "university_ages", {}).get(territory_id, 0)))
        if age >= 100:
            return 10
        if age >= 40:
            return 4
        if age >= 10:
            return 2
        return 1

    def calculate_territory_science(self, territory: Territory) -> int:
        if territory.owner == self.onu_player_id or territory.id not in self.university_territory_ids:
            return 0
        return self.get_university_science_output(territory.id)

    def calculate_player_science_income(self, player: int) -> int:
        if player < 0 or self.is_onu_player(player):
            return 0
        return sum(self.calculate_territory_science(terr) for terr in self.territories if terr.owner == player)

    def get_player_science(self, player: Optional[int] = None) -> int:
        player = self.current_player if player is None else player
        if player < 0 or self.is_onu_player(player):
            return 0
        self.player_science.setdefault(player, 0)
        science = self.player_science.get(player, 0)
        if self.player_controls_wonder(player, "atlas_observatory"):
            science *= 2
        return science

    def get_base_player_science(self, player: int) -> int:
        if player < 0 or self.is_onu_player(player):
            return 0
        self.player_science.setdefault(player, 0)
        return self.player_science.get(player, 0)

    def add_science_for_player(self, player: int) -> int:
        return moteur_regles.add_science_for_player(self, player)

    def has_science_level(self, player: int, threshold: int) -> bool:
        return self.get_player_science(player) >= threshold

    def can_player_manipulate_onu(self, player: int) -> bool:
        return player in self.last_stand_bonus_players or self.has_science_level(player, self.SCIENCE_ONU_MANIPULATION_THRESHOLD)

    def can_player_integrate_tax_haven_by_science(self, player: int) -> bool:
        return self.has_science_level(player, self.SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD)

    def can_player_attack_with_four_dice(self, player: int) -> bool:
        return self.has_science_level(player, self.SCIENCE_ATTACK_4_DICE_THRESHOLD)

    def get_cultural_center_multiplier(self, age: int) -> int:
        if age >= 100:
            return 10
        if age >= 40:
            return 5
        if age >= 10:
            return 2
        return 1

    def calculate_territory_culture(self, territory: Territory) -> int:
        ages = self.cultural_center_ages.get(territory.id, [])
        if territory.owner == self.onu_player_id or not ages:
            return 0
        base = max(1, len(territory.neighbors))
        return sum(base * self.get_cultural_center_multiplier(age) for age in ages)

    def calculate_player_culture(self, player: int) -> int:
        return moteur_regles.calculate_player_culture(self, player)

    def get_next_culture_expansion_milestone(self, player: int) -> int:
        reached = max(0, int(getattr(self, "culture_expansion_milestones", {}).get(player, 0)))
        return ((reached // 50) + 1) * 50

    def get_culture_expansion_target_ids(self, player: int) -> set[int]:
        owned_ids = {territory.id for territory in self.territories if territory.owner == player}
        targets: set[int] = set()
        for territory_id in owned_ids:
            if not (0 <= territory_id < len(self.territories)):
                continue
            for neighbor_id in self.territories[territory_id].neighbors:
                if 0 <= neighbor_id < len(self.territories) and neighbor_id not in owned_ids:
                    target_owner = self.territories[neighbor_id].owner
                    if target_owner in getattr(self, "commercial_city_players", set()):
                        continue
                    if self.can_commercial_city_gain_territory(player, neighbor_id):
                        targets.add(neighbor_id)
        return targets

    def annex_territory_by_culture(self, territory_id: int, player: int) -> Optional[int]:
        if not (0 <= territory_id < len(self.territories)):
            return None
        if self.territories[territory_id].owner in getattr(self, "commercial_city_players", set()):
            return None
        if not self.can_commercial_city_gain_territory(player, territory_id):
            return None
        territory = self.territories[territory_id]
        previous_owner = territory.owner
        if previous_owner == player:
            return None
        territory.owner = player

        # L'expansion culturelle est une annexion directe, pas une capture militaire :
        # la garnison et les constructions restent, mais les statuts ONU/vassal disparaissent.
        self.sanctuary_territory_ids.discard(territory_id)
        self.submitted_territory_ids.discard(territory_id)
        self.submitted_territory_overlords.pop(territory_id, None)
        self.submitted_territory_created_turns.pop(territory_id, None)
        self.vassal_territory_overlords.pop(territory_id, None)
        self.vassal_territory_created_turns.pop(territory_id, None)
        self.vassal_players.pop(territory_id, None)
        for territory_ids in getattr(self, "integrated_vassal_territories", {}).values():
            territory_ids.discard(territory_id)
        for territory_ids in getattr(self, "integrated_submitted_territories", {}).values():
            territory_ids.discard(territory_id)
        return previous_owner

    def trigger_culture_expansions_if_due(self, player: int) -> tuple[list[str], int]:
        notes, culture = moteur_regles.trigger_culture_expansions_if_due(self, player)
        if notes:
            self.selected_source = None
            self.selected_target = None
        return notes, culture

    def get_culture_protection_level(self, player: int) -> int:
        culture = self.calculate_player_culture(player)
        if culture >= 150:
            return 150
        if culture >= 125:
            return 125
        if culture >= 100:
            return 100
        if culture >= 75:
            return 75
        if culture >= 50:
            return 50
        if culture >= 25:
            return 25
        return 0

    def has_culture_immunity(self, player: int) -> bool:
        return self.get_culture_protection_level(player) >= 150

    def calculate_cultural_revolt_or_betrayal_loss_count(self, player: int, default_loss_count: int) -> int:
        protection_level = self.get_culture_protection_level(player)
        capped_losses = {
            25: 4,
            50: 3,
            75: 2,
            100: 1,
            125: 0,
            150: 0,
        }
        if protection_level in capped_losses:
            return min(default_loss_count, capped_losses[protection_level])
        return default_loss_count

    def calculate_cultural_revolution_loss_count(self, player: int, territory_count: int) -> int:
        protection_level = self.get_culture_protection_level(player)
        if protection_level >= 150:
            return 0
        denominator_by_level = {
            25: 4,
            50: 5,
            75: 6,
            100: 7,
            125: 10,
        }
        denominator = denominator_by_level.get(protection_level, 3)
        return territory_count // denominator

    def get_culture_protection_label(self, player: int) -> str:
        culture = self.calculate_player_culture(player)
        level = self.get_culture_protection_level(player)
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

    def has_culture_advantage(self, player: int, target_player: int, threshold: Optional[int] = None) -> bool:
        return moteur_regles.has_culture_advantage(self, player, target_player, threshold)

    def player_has_force_attack_culture_exception(self, player: int) -> bool:
        return any(
            terr.owner == player and terr.regiments >= self.AI_CULTURE_FORCE_ATTACK_REGIMENTS
            for terr in self.territories
        )

    def is_ai_attack_blocked_by_culture(self, attacker: int, defender: int) -> bool:
        # Ancienne immunite culturelle IA desactivee : la culture agit maintenant
        # sur la probabilite de nouer des alliances IA, pas sur l'interdiction d'attaquer.
        return False

    def age_cultural_centers_one_turn(self) -> None:
        for tid in list(self.cultural_center_ages):
            self.cultural_center_ages[tid] = [age + 1 for age in self.cultural_center_ages.get(tid, [])]

    def age_universities_one_turn(self) -> None:
        for tid in list(getattr(self, "university_ages", {})):
            if tid in self.university_territory_ids:
                self.university_ages[tid] = max(0, int(self.university_ages.get(tid, 0))) + 1
            else:
                self.university_ages.pop(tid, None)

    def ensure_player_economy(self, player: int) -> None:
        if player >= 0 and player not in self.player_money:
            self.player_money[player] = 0

    def get_player_money(self, player: Optional[int] = None) -> int:
        player = self.current_player if player is None else player
        self.ensure_player_economy(player)
        return self.player_money.get(player, 0)

    def spend_player_money(self, player: int, amount: int) -> bool:
        self.ensure_player_economy(player)
        if amount < 0 or self.player_money[player] < amount:
            return False
        self.player_money[player] -= amount
        return True

    def choose_weighted_territory_ids_from_pool(self, pool: List[int], count: int, weight_func) -> List[int]:
        available = list(pool)
        selected: List[int] = []
        while available and len(selected) < count:
            weights = [max(1, int(weight_func(tid))) for tid in available]
            total = sum(weights)
            pick = random.uniform(0, total)
            running = 0.0
            chosen_index = 0
            for idx, weight in enumerate(weights):
                running += weight
                if pick <= running:
                    chosen_index = idx
                    break
            selected.append(available.pop(chosen_index))
        return selected

    def choose_weighted_territory_ids(self, count: int, weight_func) -> List[int]:
        available = list(range(len(self.territories)))
        selected: List[int] = []
        while available and len(selected) < count:
            weights = [max(1, int(weight_func(tid))) for tid in available]
            total = sum(weights)
            pick = random.uniform(0, total)
            running = 0.0
            chosen_index = 0
            for idx, weight in enumerate(weights):
                running += weight
                if pick <= running:
                    chosen_index = idx
                    break
            selected.append(available.pop(chosen_index))
        return selected

    def assign_initial_economic_structures(self) -> None:
        self.fortress_territory_ids = set()
        self.fortress_capture_counts = {}
        self.industry_territory_ids = set()
        self.industry_capture_counts = {}
        self.factory_territory_ids = set()
        self.airport_territory_ids = set()
        self.port_territory_ids = set()
        self.industrial_capture_counts = {}
        self.cultural_center_ages = {}
        self.cultural_capture_counts = {}
        self.university_territory_ids = set()
        self.university_capture_counts = {}
        if not self.territories:
            return

        non_commercial_ids = [tid for tid in range(len(self.territories)) if not self.is_commercial_city_territory(tid)]
        fortress_pool = non_commercial_ids or list(range(len(self.territories)))
        fortress_ids = self.choose_weighted_territory_ids_from_pool(
            fortress_pool,
            min(self.INITIAL_FORTRESS_COUNT, len(fortress_pool)),
            lambda tid: max(1, len(self.territories[tid].neighbors)) ** 2,
        )
        self.fortress_territory_ids = set(fortress_ids)
        self.fortress_capture_counts = {tid: 0 for tid in self.fortress_territory_ids}

        ids = list(non_commercial_ids)
        random.shuffle(ids)
        for tid in ids[:min(self.INITIAL_INDUSTRY_COUNT, len(ids))]:
            options = ["factory", "airport", "port"]
            self.add_industrial_structure(tid, random.choice(options))

        cultural_pool = non_commercial_ids or list(range(len(self.territories)))
        cultural_count = min(self.INITIAL_CULTURAL_CENTER_COUNT, len(cultural_pool))
        for tid in random.sample(cultural_pool, cultural_count):
            self.add_cultural_center(tid, age=0)

    def normalize_tax_haven_capital_payload(self, raw_payload) -> dict[int, set[int]]:
        """Restaure les capitales paradis fiscal depuis une sauvegarde ancienne ou nouvelle."""
        normalized: dict[int, set[int]] = {}
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
            capital_ids: set[int] = set()
            for raw_tid in values:
                try:
                    capital_ids.add(int(raw_tid))
                except (TypeError, ValueError):
                    continue
            if capital_ids:
                normalized[player] = capital_ids
        return normalized

    def get_player_tax_haven_capital_ids(self, player: int) -> set[int]:
        if self.is_potential_commercial_city_player(player):
            if not self.is_commercial_city_player(player):
                return set()
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

    def get_all_tax_haven_capital_ids(self) -> set[int]:
        capital_ids: set[int] = set()
        for player in set(self.last_stand_bonus_players) | set(self.last_stand_bonus_territory) | set(self.commercial_city_players):
            capital_ids.update(self.get_player_tax_haven_capital_ids(player))
        return capital_ids

    def add_tax_haven_capital(self, player: int, territory_id: int) -> None:
        self.last_stand_bonus_players.add(player)
        capital_ids = self.get_player_tax_haven_capital_ids(player)
        capital_ids.add(territory_id)
        self.last_stand_bonus_territory[player] = capital_ids
        self.remove_religious_influence_from_tax_haven(territory_id)

    def remove_tax_haven_player(self, player: int) -> bool:
        if self.is_commercial_city_player(player):
            return False
        if player not in self.last_stand_bonus_players and player not in self.last_stand_bonus_territory:
            return False
        self.last_stand_bonus_players.discard(player)
        self.last_stand_bonus_territory.pop(player, None)
        return True

    def remove_tax_haven_capital(self, player: int, territory_id: int) -> None:
        capital_ids = self.get_player_tax_haven_capital_ids(player)
        capital_ids.discard(territory_id)
        if capital_ids:
            self.last_stand_bonus_players.add(player)
            self.last_stand_bonus_territory[player] = capital_ids
        else:
            self.remove_tax_haven_player(player)

    def refresh_last_stand_bonus_state(self) -> None:
        """Nettoie les avantages de paradis fiscal devenus incoherents."""
        valid_ids = set(range(len(self.territories)))
        normalized_players: set[int] = set()
        normalized_territories: dict[int, set[int]] = {}
        for player in set(self.last_stand_bonus_players) | set(self.last_stand_bonus_territory) | set(self.commercial_city_players):
            if self.is_potential_commercial_city_player(player):
                if self.is_commercial_city_player(player):
                    capital_id = self.get_commercial_city_capital_id(player)
                    if capital_id is not None:
                        normalized_players.add(player)
                        normalized_territories[player] = {capital_id}
                continue
            valid_capitals = {
                tid for tid in self.get_player_tax_haven_capital_ids(player)
                if tid in valid_ids and self.territories[tid].owner == player
            }
            if not valid_capitals:
                continue
            normalized_players.add(player)
            normalized_territories[player] = valid_capitals
        self.last_stand_bonus_players = normalized_players
        self.last_stand_bonus_territory = normalized_territories

    def activate_last_stand_bonus_if_needed(self, player: int) -> Optional[str]:
        return moteur_regles.activate_last_stand_bonus_if_needed(self, player)

    def deactivate_last_stand_bonus_after_conquest(self, player: int) -> bool:
        """Retire le statut paradis fiscal apres une conquete militaire.

        Cette fonction n'est appelee que lors d'une capture par la force. Les autres
        acquisitions de territoire (corruption, don, vente, association, evenements)
        ne doivent pas la declencher.
        """
        if player < 0 or self.is_onu_player(player) or self.is_commercial_city_player(player):
            return False
        return self.remove_tax_haven_player(player)

    def is_last_stand_bonus_territory(self, territory_id: int) -> bool:
        return territory_id in self.get_all_tax_haven_capital_ids()

    def calculate_territory_income(self, territory: Territory) -> int:
        return moteur_regles.calculate_territory_income(self, territory)

    def is_tax_haven_income_bonus_active(self, player: int) -> bool:
        return (
            player in self.last_stand_bonus_players
            and bool(self.get_player_tax_haven_capital_ids(player))
            and self.player_has_complete_industrial_set(player)
        )

    def calculate_player_income(self, player: int) -> int:
        return moteur_regles.calculate_player_income(self, player)

    def collect_income_for_player(self, player: int) -> int:
        if player < 0 or self.is_onu_player(player):
            return 0
        self.ensure_player_economy(player)
        income = self.calculate_player_income(player)
        self.player_money[player] += income
        return income

    def begin_player_turn(self, player: int) -> None:
        report = moteur_actions.begin_player_turn(self, player)
        if report.skipped:
            self.reset_ai_turn_state()
            return
        if report.turn_notes:
            self.show_message(
                " ".join(report.turn_notes)
                + f" Revenu encaisse: +{report.income} ecu(s). Culture: {report.culture}. Science: +{report.science_income} (total {report.science}).",
                4600,
            )
        self.shop_action = None
        self.shop_mercenary_quantity = 1
        self.shop_gift_amount = 10
        # La situation geopolitique ne s'ouvre plus automatiquement en debut de tour.
        # Elle reste disponible a la demande via le bouton de l'en-tete.
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0
        # Partie interface de reset_ai_turn_state : le tirage du comportement
        # des IA "variable" a deja ete fait par le moteur dans begin_player_turn.
        if self.phase == "playing" and self.is_ai_player(self.current_player):
            self.ai_state = "announce"
            self.ai_next_action_time = pygame.time.get_ticks() + self.get_ai_initial_delay_ms()
        else:
            self.ai_state = "idle"

    def register_special_capture(self, territory_id: int) -> List[str]:
        return moteur_regles.register_special_capture(self, territory_id)

    def transfer_eliminated_player_money(self, eliminated_player: int, winner: int) -> str:
        if eliminated_player < 0 or winner < 0 or eliminated_player == winner:
            return ""
        self.ensure_player_economy(eliminated_player)
        self.ensure_player_economy(winner)
        amount = self.player_money.get(eliminated_player, 0)
        if amount <= 0:
            return ""
        self.player_money[winner] += amount
        self.player_money[eliminated_player] = 0
        return f" J{winner + 1} recupere {amount} ecu(s) de J{eliminated_player + 1}."

    def maybe_trigger_market_event(self, display: bool = True) -> Optional[str]:
        message = moteur_regles.maybe_trigger_market_event(self)
        if message and display:
            self.show_message(message, 5200)
        return message

    def begin_shopping_phase(self) -> None:
        self.phase = "shopping"
        self.shop_action = None
        self.pending_wonder_type = None
        self.pending_offensive_alliance_ai = None
        self.pending_gift_territory_id = None
        self.pending_bridge_territory_id = None
        self.shop_panel_collapsed = False
        self.shop_mercenary_quantity = max(1, min(1, max(1, self.get_player_money() // self.MERCENARY_COST)))
        self.update_shop_gift_amount()
        self.selected_source = None
        self.selected_target = None
        self.show_message("Phase d'achats : mercenaires, vente/don de territoire, don d'argent ou autre achat.", 3200)

    def finish_shopping_phase(self) -> None:
        self.phase = "playing"
        self.shop_action = None
        self.pending_wonder_type = None
        self.pending_offensive_alliance_ai = None
        self.pending_gift_territory_id = None
        self.pending_bridge_territory_id = None
        self.shop_panel_collapsed = False
        self.shop_mercenary_quantity = 1
        self.shop_gift_amount = 10
        self.start_move_phase()

    def get_shop_action_label(self, action: Optional[str]) -> str:
        labels = {
            "mercenaries": "recruter des mercenaires",
            "sell_territory": "vendre un territoire",
            "give_territory": "donner un territoire",
            "gift_money": "donner de l'argent",
            "build_fortress": "construire une forteresse",
            "destroy_fortress": "detruire une forteresse",
            "corrupt": "corrompre un territoire ennemi",
            "revolt": "declencher une revolte",
            "build_factory": "construire une usine",
            "build_airport": "construire un aeroport",
            "build_port": "construire un port",
            "build_temple": "construire un temple",
            "build_cultural_center": "construire un centre culturel",
            "build_university": "construire une universite",
            "destroy_university": "detruire une universite",
            "alliance": "acheter une alliance defensive",
            "offensive_alliance": "acheter une alliance offensive",
            "tax_haven_association": "association / integration paradis fiscal",
            "freeze_territory": "figer un territoire en territoire ONU",
            "release_sanctuary": "liberer un territoire ONU vers une IA",
            "change_capital": "changer de capitale",
            "build_wonder": (
                f"construire {self.get_wonder_name(self.pending_wonder_type)}"
                if self.pending_wonder_type else "construire une merveille"
            ),
            "build_bridge": "creer un pont",
            "destroy_bridge": "detruire un pont",
        }
        return labels.get(action or "", "aucun achat selectionne")

    def calculate_revolt_cost_for_target_player(self, target_player: int) -> int:
        territory_count = sum(1 for terr in self.territories if terr.owner == target_player)
        if territory_count < 10:
            return self.REVOLT_COST_LOW
        if territory_count <= 18:
            return self.REVOLT_COST_MEDIUM
        return self.REVOLT_COST_HIGH

    def calculate_revolt_loss_count(self, territory_count: int) -> int:
        return max(1, territory_count // 4)

    def normalize_nation_pair(self, player_a: int, player_b: int) -> tuple[int, int]:
        return tuple(sorted((int(player_a), int(player_b))))

    def get_owned_components(self, player: int) -> list[list[int]]:
        owned_ids = {terr.id for terr in self.territories if terr.owner == player}
        components: list[list[int]] = []
        seen: set[int] = set()
        for territory_id in sorted(owned_ids):
            if territory_id in seen:
                continue
            stack = [territory_id]
            seen.add(territory_id)
            component: list[int] = []
            while stack:
                current = stack.pop()
                component.append(current)
                for neighbor_id in self.territories[current].neighbors:
                    if neighbor_id in owned_ids and neighbor_id not in seen:
                        seen.add(neighbor_id)
                        stack.append(neighbor_id)
            components.append(sorted(component))
        return components

    def component_has_all_nation_structures(self, territory_ids: list[int]) -> bool:
        territory_set = set(territory_ids)
        return (
            bool(self.fortress_territory_ids & territory_set)
            and bool(self.factory_territory_ids & territory_set)
            and bool(self.port_territory_ids & territory_set)
            and bool(self.airport_territory_ids & territory_set)
            and bool(getattr(self, "temple_territory_ids", set()) & territory_set)
            and any(self.get_cultural_center_count(tid) > 0 for tid in territory_set)
            and bool(self.university_territory_ids & territory_set)
        )

    def component_has_active_regular_capital(self, player: int, territory_ids: list[int]) -> bool:
        territory_set = set(territory_ids)
        if self.is_commercial_city_player(player):
            capital_id = self.get_commercial_city_capital_id(player)
            return capital_id is not None and capital_id in territory_set
        capital_id = self.get_active_regular_capital_id_for_player(player)
        return capital_id is not None and capital_id in territory_set

    def count_component_nation_structure_kinds(self, territory_ids: list[int]) -> int:
        territory_set = set(territory_ids)
        score = 0
        if self.fortress_territory_ids & territory_set:
            score += 1
        if self.factory_territory_ids & territory_set:
            score += 1
        if self.port_territory_ids & territory_set:
            score += 1
        if self.airport_territory_ids & territory_set:
            score += 1
        if getattr(self, "temple_territory_ids", set()) & territory_set:
            score += 1
        if any(self.get_cultural_center_count(tid) > 0 for tid in territory_set):
            score += 1
        if self.university_territory_ids & territory_set:
            score += 1
        return score

    def get_component_industrial_types(self, territory_ids: list[int]) -> set[str]:
        territory_set = set(territory_ids)
        types: set[str] = set()
        for structure_type, structure_ids in self.get_industrial_structure_sets().items():
            if structure_ids & territory_set:
                types.add(structure_type)
        return types

    def get_missing_component_industrial_types(self, territory_ids: list[int]) -> list[str]:
        existing = self.get_component_industrial_types(territory_ids)
        missing = [structure_type for structure_type in ("factory", "airport", "port") if structure_type not in existing]
        random.shuffle(missing)
        return missing

    def component_has_temple(self, territory_ids: list[int]) -> bool:
        territory_set = set(territory_ids)
        return bool(getattr(self, "temple_territory_ids", set()) & territory_set)

    def component_has_cultural_center(self, territory_ids: list[int]) -> bool:
        return any(self.get_cultural_center_count(tid) > 0 for tid in territory_ids)

    def component_has_university(self, territory_ids: list[int]) -> bool:
        territory_set = set(territory_ids)
        return bool(self.university_territory_ids & territory_set)

    def find_player_nation_component(self, player: int, require_capital: bool = True) -> Optional[list[int]]:
        if player < 0 or self.is_onu_player(player):
            return None
        for component in self.get_owned_components(player):
            if len(component) < self.NATION_MIN_TERRITORIES:
                continue
            if not self.component_has_all_nation_structures(component):
                continue
            if require_capital and not self.component_has_active_regular_capital(player, component):
                continue
            return component
        return None

    def find_player_nation_development_component(self, player: int) -> Optional[list[int]]:
        if player < 0 or self.is_onu_player(player):
            return None
        candidates = [component for component in self.get_owned_components(player) if len(component) >= self.NATION_MIN_TERRITORIES]
        if not candidates:
            return None
        capital_id = (
            self.get_commercial_city_capital_id(player)
            if self.is_commercial_city_player(player)
            else self.get_active_regular_capital_id_for_player(player)
        )
        return max(
            candidates,
            key=lambda component: (
                self.count_component_nation_structure_kinds(component),
                1 if capital_id in component else 0,
                len(component),
                random.random(),
            ),
        )

    def player_has_nation_structures_but_needs_capital(self, player: int) -> bool:
        return (
            self.find_player_nation_component(player, require_capital=False) is not None
            and self.find_player_nation_component(player, require_capital=True) is None
        )

    def player_qualifies_as_nation(self, player: int) -> bool:
        return self.find_player_nation_component(player, require_capital=True) is not None

    def is_nation_player(self, player: int) -> bool:
        return player in getattr(self, "nation_players", set())

    def is_cold_war_active(self) -> bool:
        return False

    def get_cold_war_camp(self, player: int) -> Optional[int]:
        return None

    def assign_player_to_cold_war_camp(self, player: int) -> Optional[int]:
        return None

    def assign_all_ai_to_cold_war_camps(self) -> None:
        self.cold_war_active = False
        self.cold_war_nations = None
        self.cold_war_alliances = {}

    def trigger_cold_war_if_ready(self) -> Optional[str]:
        self.assign_all_ai_to_cold_war_camps()
        return None

    def sanitize_nation_diplomacy(self) -> None:
        active_players = set(self.get_active_players())
        self.assign_all_ai_to_cold_war_camps()
        self.nation_players = {
            player for player in getattr(self, "nation_players", set())
            if player in active_players
        }
        if hasattr(self, "nation_qualification_start_turns"):
            self.nation_qualification_start_turns = {
                player: start_turn
                for player, start_turn in self.nation_qualification_start_turns.items()
                if player in active_players and player not in self.nation_players
            }
        if hasattr(self, "nation_capital_loss_start_turns"):
            self.nation_capital_loss_start_turns = {
                player: start_turn
                for player, start_turn in self.nation_capital_loss_start_turns.items()
                if player in self.nation_players
            }
        self.nation_alliances = set()
        self.nation_wars = set()

    def convert_commercial_city_to_nation(self, player: int) -> Optional[str]:
        if player not in self.commercial_city_players:
            return None
        former_capital_id = self.get_commercial_city_capital_id(player)
        self.commercial_city_players.discard(player)
        self.commercial_city_capital_ids.pop(player, None)
        self.last_stand_bonus_players.discard(player)
        self.last_stand_bonus_territory.pop(player, None)
        if former_capital_id is not None and 0 <= former_capital_id < len(self.territories) and self.territories[former_capital_id].owner == player:
            self.player_capital_ids[player] = former_capital_id
        self.assign_ai_personality_to_player(player, "standard")
        self.pending_commercial_city_spawns = max(
            0,
            getattr(self, "pending_commercial_city_spawns", 0),
        ) + 1
        self.sanitize_player_capitals()
        return (
            f"J{player + 1} perd definitivement son statut de Cite commercante et devient une nation IA standard. "
            "Une nouvelle Cite commercante apparaitra au debut du prochain cycle de tours."
        )

    def reset_nation_qualification_progress(self, player: int) -> None:
        if hasattr(self, "nation_qualification_start_turns"):
            self.nation_qualification_start_turns.pop(player, None)

    def get_nation_qualification_remaining_turns(self, player: int) -> int:
        start_turn = getattr(self, "nation_qualification_start_turns", {}).get(player)
        if start_turn is None:
            return self.NATION_QUALIFICATION_DELAY_TURNS
        elapsed = max(0, self.turn - start_turn)
        return max(0, self.NATION_QUALIFICATION_DELAY_TURNS - elapsed)

    def update_nation_qualification_progress(self, player: int) -> Optional[str]:
        if player in getattr(self, "nation_players", set()):
            self.reset_nation_qualification_progress(player)
            return None
        component = self.find_player_nation_component(player)
        if component is None:
            self.reset_nation_qualification_progress(player)
            return None
        if not hasattr(self, "nation_qualification_start_turns"):
            self.nation_qualification_start_turns = {}
        if player not in self.nation_qualification_start_turns:
            self.nation_qualification_start_turns[player] = self.turn
            return (
                f"Tour {self.turn}: J{player + 1} remplit les criteres nationaux. "
                f"Il devra les conserver pendant {self.NATION_QUALIFICATION_DELAY_TURNS} tours."
            )
        if self.turn - self.nation_qualification_start_turns[player] < self.NATION_QUALIFICATION_DELAY_TURNS:
            return None
        return self.form_nation_for_player(player)

    def form_nation_for_player(self, player: int) -> Optional[str]:
        if player in self.nation_players:
            return None
        component = self.find_player_nation_component(player)
        if component is None:
            return None
        cc_note = self.convert_commercial_city_to_nation(player)
        self.nation_players.add(player)
        self.reset_nation_qualification_progress(player)
        if not hasattr(self, "nation_capital_loss_start_turns"):
            self.nation_capital_loss_start_turns = {}
        self.nation_capital_loss_start_turns.pop(player, None)
        self.nation_alliances = set()
        message = (
            f"Tour {self.turn}: J{player + 1} devient une nation "
            f"({len(component)} territoires contigus avec tous les amenagements requis). "
            f"Ses revenus sont desormais divises par {self.NATION_INCOME_DIVISOR}."
        )
        if cc_note:
            message += " " + cc_note
        self.record_major_event(message)
        return message

    def lose_nation_status_if_needed(self, player: int) -> Optional[str]:
        if player not in self.nation_players:
            if hasattr(self, "nation_capital_loss_start_turns"):
                self.nation_capital_loss_start_turns.pop(player, None)
            return None

        territory_count = self.count_player_territories(player)
        loss_reason: Optional[str] = None
        if territory_count <= 1:
            loss_reason = "il ne controle plus qu'un territoire"
        else:
            capital_id = self.get_active_regular_capital_id_for_player(player)
            if capital_id is not None:
                if hasattr(self, "nation_capital_loss_start_turns"):
                    self.nation_capital_loss_start_turns.pop(player, None)
                return None
            if not hasattr(self, "nation_capital_loss_start_turns"):
                self.nation_capital_loss_start_turns = {}
            if player not in self.nation_capital_loss_start_turns:
                self.nation_capital_loss_start_turns[player] = self.turn
                return (
                    f"Tour {self.turn}: J{player + 1} n'a plus de capitale. "
                    f"Le statut de nation sera perdu si la situation dure {self.NATION_CAPITAL_LOSS_DELAY_TURNS} tours."
                )
            if self.turn - self.nation_capital_loss_start_turns[player] < self.NATION_CAPITAL_LOSS_DELAY_TURNS:
                return None
            loss_reason = "il est reste dix tours sans capitale"

        self.nation_players.discard(player)
        self.reset_nation_qualification_progress(player)
        if hasattr(self, "nation_capital_loss_start_turns"):
            self.nation_capital_loss_start_turns.pop(player, None)
        self.nation_alliances = set()
        self.nation_wars = set()
        territory = next((terr for terr in self.territories if terr.owner == player), None)
        if territory is not None and territory_count <= 1:
            self.add_tax_haven_capital(player, territory.id)
            if territory.id not in self.fortress_territory_ids:
                self.fortress_territory_ids.add(territory.id)
                self.fortress_capture_counts[territory.id] = 0
            message = f"Tour {self.turn}: J{player + 1} perd son statut de nation ({loss_reason}) et bascule en paradis fiscal sur {territory.name}."
        else:
            message = f"Tour {self.turn}: J{player + 1} perd son statut de nation ({loss_reason})."
        self.record_major_event(message)
        return message

    def break_nation_alliance(self, player_a: int, player_b: int, reason: str) -> Optional[str]:
        return None

    def sign_nation_peace(self, player_a: int, player_b: int, paid_cost: Optional[int] = None) -> Optional[str]:
        return None

    def maybe_break_ai_nation_alliances(self, player: int) -> list[str]:
        return []

    def maybe_ai_nation_peace(self, player: int) -> list[str]:
        return []

    def refresh_nation_states(self, trigger_player: Optional[int] = None) -> list[str]:
        self.nation_alliances = set()
        self.nation_wars = set()
        self.assign_all_ai_to_cold_war_camps()
        return moteur_regles.refresh_nation_states(self, trigger_player)

    def is_nation_alliance_active(self, player_a: int, player_b: int) -> bool:
        return player_a == player_b

    def are_nations_at_war(self, player_a: int, player_b: int) -> bool:
        return False

    def calculate_nation_peace_cost(self, human_player: int, opponent: int) -> int:
        return 0

    def ai_needs_new_capital_as_nation(self, player: int) -> bool:
        if not self.is_ai_player(player):
            return False
        if self.is_commercial_city_player(player) or self.is_onu_player(player):
            return False
        if self.get_active_regular_capital_id_for_player(player) is not None:
            return False
        return (
            player in getattr(self, "nation_players", set())
            or self.player_has_nation_structures_but_needs_capital(player)
        )

    def choose_ai_new_capital_target(self, player: int) -> Optional[Territory]:
        owned = [terr for terr in self.territories if terr.owner == player and not self.is_sanctuary_territory(terr.id)]
        if not owned:
            return None
        qualifying_component = self.find_player_nation_component(player, require_capital=False)
        if qualifying_component is not None:
            preferred = [terr for terr in owned if terr.id in qualifying_component]
            if preferred:
                owned = preferred
        return max(owned, key=lambda terr: (self.calculate_territory_income(terr), len(terr.neighbors), terr.regiments, random.random()))

    def change_ai_capital_without_ui(self, player: int, territory_id: int) -> None:
        if not (0 <= territory_id < len(self.territories)):
            return
        if not hasattr(self, "player_capital_ids"):
            self.player_capital_ids = {}
        self.player_capital_ids[player] = territory_id
        self.sanctuary_territory_ids.discard(territory_id)
        self.sanitize_player_capitals()

    def count_player_territories(self, player: int) -> int:
        return sum(1 for terr in self.territories if terr.owner == player)

    def normalize_alliance_key(self, human_player: int, ai_player: int) -> tuple[int, int]:
        return (human_player, ai_player)

    def normalize_ai_alliance_key(self, ai_a: int, ai_b: int) -> tuple[int, int]:
        return tuple(sorted((ai_a, ai_b)))

    def get_commercial_city_wonder_ally(self) -> Optional[int]:
        ally = self.get_wonder_controller("golden_pact_palace")
        if ally is None or self.is_commercial_city_player(ally):
            return None
        return ally

    def enforce_commercial_city_wonder_exclusivity(self) -> None:
        if "golden_pact_palace" not in getattr(self, "wonder_territories", {}):
            return
        commercial_players = set(getattr(self, "commercial_city_players", set()))
        self.active_alliances = {
            key: expires_turn
            for key, expires_turn in self.active_alliances.items()
            if key[0] not in commercial_players and key[1] not in commercial_players
        }
        self.alliance_start_turns = {
            key: start_turn for key, start_turn in self.alliance_start_turns.items()
            if key in self.active_alliances
        }
        self.active_offensive_alliances = {
            key: data
            for key, data in self.active_offensive_alliances.items()
            if key[0] not in commercial_players and key[1] not in commercial_players and data[0] not in commercial_players
        }
        self.offensive_alliance_start_turns = {
            key: start_turn for key, start_turn in self.offensive_alliance_start_turns.items()
            if key in self.active_offensive_alliances
        }
        self.active_ai_alliances = {
            key: expires_turn
            for key, expires_turn in self.active_ai_alliances.items()
            if not (set(key) & commercial_players)
        }
        self.ai_alliance_start_turns = {
            key: start_turn for key, start_turn in self.ai_alliance_start_turns.items()
            if key in self.active_ai_alliances
        }

    def is_ai_alliance_active(self, ai_a: int, ai_b: int) -> bool:
        if ai_a == ai_b:
            return False
        self.cleanup_expired_alliances()
        key = self.normalize_ai_alliance_key(ai_a, ai_b)
        return self.turn < self.active_ai_alliances.get(key, -1)

    def break_ai_alliance_due_to_offensive_contract(self, ai_player: int, target_player: int) -> Optional[str]:
        if not (self.is_ai_player(ai_player) and self.is_ai_player(target_player)):
            return None
        self.cleanup_expired_alliances()
        key = self.normalize_ai_alliance_key(ai_player, target_player)
        expires_turn = self.active_ai_alliances.get(key)
        if expires_turn is None or self.turn >= expires_turn:
            return None
        self.active_ai_alliances.pop(key, None)
        self.ai_alliance_start_turns.pop(key, None)
        return (
            f"L'alliance IA entre J{ai_player + 1} et J{target_player + 1} est rompue "
            f"par le contrat offensif."
        )

    def get_ai_random_alliance_denominator(self, player: int) -> int:
        if player in self.last_stand_bonus_players:
            return self.AI_TAX_HAVEN_ALLIANCE_DENOMINATOR
        culture = self.calculate_player_culture(player)
        if culture >= 40:
            return self.AI_HIGH_CULTURE_ALLIANCE_DENOMINATOR
        if culture >= 20:
            return self.AI_CULTURE_ALLIANCE_DENOMINATOR
        return self.AI_ALLIANCE_DENOMINATOR

    def maybe_trigger_random_ai_alliance(self, player: int) -> Optional[str]:
        return moteur_regles.maybe_trigger_random_ai_alliance(self, player)

    def cleanup_expired_alliances(self) -> None:
        # La branche guerre froide de l'ancienne version est morte
        # (is_cold_war_active renvoie False) : le moteur ne la reprend pas.
        moteur_regles.cleanup_expired_alliances(self)

    def is_alliance_active(self, human_player: int, ai_player: int) -> bool:
        self.cleanup_expired_alliances()
        return self.turn < self.active_alliances.get((human_player, ai_player), -1)

    def is_offensive_alliance_active(self, human_player: int, ai_player: int) -> bool:
        self.cleanup_expired_alliances()
        data = self.active_offensive_alliances.get((human_player, ai_player))
        return data is not None and self.turn < data[1]

    def get_alliance_cost(self, ai_player: int) -> int:
        return self.count_player_territories(ai_player) * self.ALLIANCE_COST_PER_TERRITORY

    def get_offensive_alliance_cost(self, ai_player: int) -> int:
        return self.count_player_territories(ai_player) * self.OFFENSIVE_ALLIANCE_COST_PER_TERRITORY

    def calculate_onu_manipulation_cost(self, territory: Territory) -> int:
        return max(1, territory.regiments) * self.ONU_MANIPULATION_COST_PER_REGIMENT

    def get_random_ai_recipient_for_released_sanctuary(self, excluded_players: Optional[set[int]] = None) -> int:
        excluded_players = excluded_players or set()
        candidates = [
            player for player in self.get_active_players()
            if player not in excluded_players and self.is_ai_player(player) and not self.is_commercial_city_player(player)
        ]
        if candidates:
            return random.choice(candidates)

        new_player = self.num_players
        self.num_players += 1
        self.base_ai_players.add(new_player)
        self.assign_ai_personality_to_player(new_player)
        self.ensure_player_economy(new_player)
        self.assign_player_to_cold_war_camp(new_player)
        return new_player

    def get_random_ai_recipient_for_sedition(self, previous_owner: int) -> int:
        candidates = [
            player for player in self.get_active_players()
            if player != previous_owner and self.is_ai_player(player) and not self.is_commercial_city_player(player)
        ]
        if candidates:
            return random.choice(candidates)

        new_player = self.num_players
        self.num_players += 1
        self.base_ai_players.add(new_player)
        self.assign_ai_personality_to_player(new_player)
        self.ensure_player_economy(new_player)
        self.assign_player_to_cold_war_camp(new_player)
        return new_player

    def calculate_sedition_chance_points(self, territory: Territory) -> int:
        if territory.owner in getattr(self, "nation_players", set()) or self.is_commercial_city_player(territory.owner):
            return 0
        if self.is_active_regular_capital(territory.id) or self.has_university(territory.id):
            return 0
        regiments = max(0, int(territory.regiments))
        return min(self.SEDITION_DENOMINATOR, regiments * regiments)

    def maybe_trigger_sedition_at_end_of_turn(self) -> Optional[str]:
        message = moteur_regles.maybe_trigger_sedition_at_end_of_turn(self)
        if message:
            self.selected_source = None
            self.selected_target = None
            self.show_message(message, 6200)
        return message

    def get_allied_humans_for_ai(self, ai_player: int) -> set[int]:
        self.cleanup_expired_alliances()
        allied = {human for (human, ai), expires_turn in self.active_alliances.items() if ai == ai_player and self.turn < expires_turn}
        allied.update(
            overlord for tid, overlord in getattr(self, "vassal_territory_overlords", {}).items()
            if getattr(self, "vassal_players", {}).get(tid) == ai_player
        )
        return allied

    def get_offensive_alliance_target_for_ai(self, ai_player: int) -> Optional[int]:
        self.cleanup_expired_alliances()
        candidates: List[Tuple[int, int]] = []
        for (_human, ai), (target, expires_turn) in self.active_offensive_alliances.items():
            if ai == ai_player and self.turn < expires_turn and any(terr.owner == target for terr in self.territories):
                candidates.append((expires_turn, target))
        if not candidates:
            return None
        return max(candidates)[1]

    def is_attack_blocked_by_alliance(self, attacker: int, defender: int) -> bool:
        # Guerre froide et vassaux : blocs morts non repris par le moteur.
        return moteur_regles.is_attack_blocked_by_alliance(self, attacker, defender)

    def break_alliance_due_to_human_attack(self, attacker: int, defender: int) -> Optional[str]:
        message = moteur_regles.break_alliance_due_to_human_attack(self, attacker, defender)
        if message:
            self.last_alliance_break_message = message
        return message

    def count_player_universities(self, player: int) -> int:
        return sum(
            1
            for territory_id in self.university_territory_ids
            if 0 <= territory_id < len(self.territories)
            and self.territories[territory_id].owner == player
        )

    def get_tax_haven_territory_limit(self, player: int) -> Optional[int]:
        if self.is_human_player_id(player):
            return None
        return self.TAX_HAVEN_LOSS_TERRITORY_THRESHOLD

    def snapshot_tax_haven_turn_start_territory_counts(self) -> None:
        """Memorise les possessions PF au tout debut du tour global.

        Les evenements de debut de tour, notamment les trahisons, peuvent donner
        des territoires a un joueur deja en paradis fiscal. Ces gains ne doivent
        pas casser le statut PF pendant le tour en cours : le controle se fait
        sur cette photo de debut de tour. La facture arrive au tour suivant,
        comme toute bureaucratie absurde mais ici volontaire.
        """
        self.tax_haven_turn_start_territory_counts = {
            player: self.count_player_territories(player)
            for player in self.last_stand_bonus_players
        }

    def enforce_last_stand_bonus_limits(self, begin_of_turn: bool = False) -> Optional[str]:
        """Retire le paradis fiscal uniquement au debut du tour du joueur concerne.

        Les joueurs humains en paradis fiscal n'ont plus de plafond territorial lie
        au nombre d'universites. Les anciens paliers d'universites restent appliques
        seulement aux joueurs IA ordinaires, tant qu'une future regle ne vient pas
        civiliser ce zoo fiscal. Les autres appels historiques restent inoffensifs
        pour eviter une perte immediate apres une conquete, une corruption ou une association.
        """
        if not begin_of_turn:
            return None
        player = self.current_player
        if self.is_potential_commercial_city_player(player):
            self.refresh_last_stand_bonus_state()
            return None
        if player not in self.last_stand_bonus_players:
            return None
        territory_count = self.tax_haven_turn_start_territory_counts.get(
            player,
            self.count_player_territories(player),
        )
        territory_limit = self.get_tax_haven_territory_limit(player)
        if territory_limit is None or territory_count <= territory_limit:
            return None
        self.remove_tax_haven_player(player)
        university_count = self.count_player_universities(player)
        message = (
            f"J{player + 1} controle {territory_count} territoires en debut de tour "
            f"avec {university_count} universite(s), au-dessus du plafond PF de {territory_limit} "
            f": paradis fiscal termine."
        )
        self.show_message(message, 3400)
        return message

    def get_shop_action_base_cost(self, action: str) -> int:
        costs = {
            "mercenaries": self.MERCENARY_COST,
            "sell_territory": 0,
            "give_territory": 0,
            "gift_money": 0,
            "build_fortress": self.FORTRESS_COST,
            "destroy_fortress": self.DESTROY_FORTRESS_COST,
            "corrupt": 0,
            "revolt": self.REVOLT_COST_LOW,
            "build_factory": self.FACTORY_COST,
            "build_airport": self.AIRPORT_COST,
            "build_port": self.PORT_COST,
            "build_temple": self.TEMPLE_COST,
            "build_cultural_center": self.CULTURAL_CENTER_COST,
            "build_university": self.UNIVERSITY_COST,
            "destroy_university": self.UNIVERSITY_COST,
            "alliance": 0,
            "offensive_alliance": 0,
            "tax_haven_association": 0,
            "freeze_territory": 0,
            "release_sanctuary": 0,
            "change_capital": self.CHANGE_CAPITAL_COST,
            "build_wonder": self.WONDER_COST,
            "build_bridge": self.BUILD_BRIDGE_COST,
            "destroy_bridge": self.DESTROY_BRIDGE_COST,
        }
        return costs.get(action, 0)

    def update_shop_mercenary_quantity(self) -> None:
        max_quantity = self.get_player_money() // self.MERCENARY_COST
        if max_quantity <= 0:
            self.shop_mercenary_quantity = 1
            return
        self.shop_mercenary_quantity = max(1, min(self.shop_mercenary_quantity, max_quantity))

    def change_shop_mercenary_quantity(self, delta: int) -> None:
        max_quantity = self.get_player_money() // self.MERCENARY_COST
        if max_quantity <= 0:
            self.shop_mercenary_quantity = 1
            self.show_message("Pas assez d'ecus pour recruter des mercenaires.", 1600)
            return
        self.shop_mercenary_quantity = max(1, min(max_quantity, self.shop_mercenary_quantity + delta))

    def update_shop_gift_amount(self) -> None:
        max_amount = self.get_player_money()
        if max_amount <= 0:
            self.shop_gift_amount = 0
            return
        if self.shop_gift_amount <= 0:
            self.shop_gift_amount = min(10, max_amount)
        self.shop_gift_amount = max(1, min(self.shop_gift_amount, max_amount))

    def change_shop_gift_amount(self, delta: int) -> None:
        max_amount = self.get_player_money()
        if max_amount <= 0:
            self.shop_gift_amount = 0
            self.show_message("Impossible de donner de l'argent : aucun ecu disponible.", 1800)
            return
        step = 10
        current = self.shop_gift_amount if self.shop_gift_amount > 0 else min(step, max_amount)
        self.shop_gift_amount = max(1, min(max_amount, current + delta * step))

    def handle_shop_click(self, pos: Tuple[int, int]) -> None:
        if self.shop_panel_collapsed:
            if self.shop_finish_compact_rect.collidepoint(pos):
                self.finish_shopping_phase()
                return
            if self.shop_reopen_rect.collidepoint(pos):
                self.shop_panel_collapsed = False
                self.show_message("Menu des achats rouvert.", 1200)
                return
            terr = self.get_territory_at_pos(pos)
            if terr is not None:
                self.handle_shop_territory_click(terr)
            return

        if self.finish_shopping_rect.collidepoint(pos):
            self.finish_shopping_phase()
            return

        # Les boutons +/- sont disponibles directement a cote de "Mercenaires xN".
        # Ils changent seulement la quantite, sans lancer l'achat ni replier le menu.
        if self.shop_minus_rect.collidepoint(pos):
            self.shop_action = "mercenaries"
            self.change_shop_mercenary_quantity(-1)
            self.show_message(f"Mercenaires selectionnes : {self.shop_mercenary_quantity}.", 1200)
            return
        if self.shop_plus_rect.collidepoint(pos):
            self.shop_action = "mercenaries"
            self.change_shop_mercenary_quantity(1)
            self.show_message(f"Mercenaires selectionnes : {self.shop_mercenary_quantity}.", 1200)
            return
        if self.shop_gift_minus_rect.collidepoint(pos):
            self.shop_action = "gift_money"
            self.change_shop_gift_amount(-1)
            self.show_message(f"Don selectionne : {self.shop_gift_amount} ecu(s).", 1200)
            return
        if self.shop_gift_plus_rect.collidepoint(pos):
            self.shop_action = "gift_money"
            self.change_shop_gift_amount(1)
            self.show_message(f"Don selectionne : {self.shop_gift_amount} ecu(s).", 1200)
            return

        for action, rect in self.shop_buttons.items():
            if action in ("build_bridge", "destroy_bridge") and self.get_player_science(self.current_player) < self.SCIENCE_BRIDGE_THRESHOLD:
                continue
            if rect.collidepoint(pos):
                self.shop_action = action
                if action != "give_territory":
                    self.pending_gift_territory_id = None
                if action not in ("build_bridge", "destroy_bridge"):
                    self.pending_bridge_territory_id = None
                if action == "mercenaries":
                    self.update_shop_mercenary_quantity()
                    max_quantity = self.get_player_money() // self.MERCENARY_COST
                    if max_quantity <= 0:
                        self.show_message("Pas assez d'ecus pour recruter des mercenaires.", 1800)
                        return
                    self.shop_panel_collapsed = True
                    self.show_message(
                        f"Achat selectionne : {self.shop_mercenary_quantity} mercenaire(s). Cliquez maintenant sur le territoire ou les placer.",
                        2400,
                    )
                elif action == "sell_territory":
                    self.shop_panel_collapsed = True
                    self.show_message(
                        "Vente selectionnee : cliquez sur un territoire que vous controlez. Prix = 10 ecu(s) par regiment + 50 par amenagement ou bonus +3/+5.",
                        3000,
                    )
                elif action == "give_territory":
                    self.shop_panel_collapsed = True
                    self.pending_gift_territory_id = None
                    self.show_message(
                        "Don de territoire selectionne : cliquez d'abord sur un territoire que vous controlez, puis sur un territoire du joueur beneficiaire.",
                        3600,
                    )
                elif action == "gift_money":
                    self.update_shop_gift_amount()
                    if self.shop_gift_amount <= 0:
                        self.show_message("Impossible de donner de l'argent : aucun ecu disponible.", 1800)
                        return
                    self.shop_panel_collapsed = True
                    self.show_message(
                        f"Don selectionne : {self.shop_gift_amount} ecu(s). Cliquez sur un territoire du joueur beneficiaire.",
                        3000,
                    )
                elif action == "freeze_territory":
                    self.shop_panel_collapsed = True
                    self.show_message(
                        f"Figement ONU selectionne : cliquez un territoire. Prix = {self.ONU_MANIPULATION_COST_PER_REGIMENT} ecu(s) par regiment.",
                        3200,
                    )
                elif action == "release_sanctuary":
                    self.shop_panel_collapsed = True
                    self.show_message(
                        f"Liberation ONU selectionnee : cliquez un territoire ONU. Prix = {self.ONU_MANIPULATION_COST_PER_REGIMENT} ecu(s) par regiment.",
                        3200,
                    )
                elif action == "change_capital":
                    self.shop_panel_collapsed = True
                    self.show_message(
                        f"Changement de capitale selectionne : cliquez sur le territoire qui deviendra votre capitale. Prix = {self.CHANGE_CAPITAL_COST} ecu(s).",
                        3200,
                    )
                elif action == "build_wonder":
                    required_science = self.get_wonder_science_threshold(self.current_player)
                    if not self.can_player_build_wonder(self.current_player):
                        self.shop_action = None
                        self.pending_wonder_type = None
                        self.show_message(
                            f"Merveilles verrouillees : {required_science} points de science requis.",
                            2600,
                        )
                        return
                    if self.get_player_money(self.current_player) < self.WONDER_COST:
                        self.shop_action = None
                        self.pending_wonder_type = None
                        self.show_message(
                            f"Merveille trop chere : {self.WONDER_COST} ecus requis.",
                            2200,
                        )
                        return
                    available = self.get_available_wonder_types()
                    if not available:
                        self.shop_action = None
                        self.pending_wonder_type = None
                        self.show_message("Les quatre merveilles ont deja ete construites.", 2400)
                        return
                    prompt_lines = ["Choisissez la merveille a construire :"]
                    for index, wonder_type in enumerate(available, start=1):
                        definition = self.WONDER_DEFINITIONS[wonder_type]
                        prompt_lines.append(f"{index} - {definition['name']} : {definition['effect']}")
                    selection = self.ask_int("\n".join(prompt_lines), 1, len(available))
                    self.pending_wonder_type = available[selection - 1]
                    self.shop_panel_collapsed = True
                    self.show_message(
                        f"{self.get_wonder_name(self.pending_wonder_type)} selectionnee. Cliquez un territoire que vous controlez. Prix : {self.WONDER_COST} ecus.",
                        3600,
                    )
                elif action in ("build_bridge", "destroy_bridge"):
                    cost = self.BUILD_BRIDGE_COST if action == "build_bridge" else self.DESTROY_BRIDGE_COST
                    if self.get_player_money(self.current_player) < cost:
                        self.shop_action = None
                        self.pending_bridge_territory_id = None
                        self.show_message(f"Operation trop chere : {cost} ecus requis.", 2200)
                        return
                    if action == "destroy_bridge" and not self.bridge_links:
                        self.shop_action = None
                        self.pending_bridge_territory_id = None
                        self.show_message("Aucun pont ne peut etre detruit sur cette carte.", 2200)
                        return
                    self.pending_bridge_territory_id = None
                    self.shop_panel_collapsed = True
                    verb = "relier" if action == "build_bridge" else "identifier le pont a detruire"
                    self.show_message(
                        f"Cliquez sur le premier territoire pour {verb}, puis sur le second. Prix : {cost} ecus.",
                        3400,
                    )
                else:
                    self.shop_panel_collapsed = True
                    self.show_message(
                        f"Achat selectionne : {self.get_shop_action_label(action)}. Cliquez maintenant sur le territoire concerne.",
                        2200,
                    )
                return

        if self.shop_panel_rect.collidepoint(pos):
            return

        terr = self.get_territory_at_pos(pos)
        if terr is None:
            return
        self.handle_shop_territory_click(terr)

    def handle_shop_territory_click(self, terr: Territory) -> None:
        if self.shop_action is None:
            self.show_message("Choisissez d'abord une option d'achat. Oui, le capitalisme exige un menu.", 1800)
            return
        action_handlers = {
            "mercenaries": self.execute_shop_mercenary_purchase,
            "sell_territory": self.execute_shop_sell_territory,
            "give_territory": self.execute_shop_give_territory,
            "gift_money": self.execute_shop_gift_money,
            "build_fortress": self.execute_shop_build_fortress,
            "destroy_fortress": self.execute_shop_destroy_fortress,
            "corrupt": self.execute_shop_corrupt_territory,
            "revolt": self.execute_shop_revolt,
            "build_factory": self.execute_shop_build_factory,
            "build_airport": self.execute_shop_build_airport,
            "build_port": self.execute_shop_build_port,
            "build_temple": self.execute_shop_build_temple,
            "build_cultural_center": self.execute_shop_build_cultural_center,
            "build_university": self.execute_shop_build_university,
            "destroy_university": self.execute_shop_destroy_university,
            "alliance": self.execute_shop_buy_alliance,
            "offensive_alliance": self.execute_shop_buy_offensive_alliance,
            "tax_haven_association": self.execute_shop_tax_haven_association,
            "freeze_territory": self.execute_shop_freeze_territory,
            "release_sanctuary": self.execute_shop_release_sanctuary,
            "change_capital": self.execute_shop_change_capital,
            "build_wonder": self.execute_shop_build_wonder,
            "build_bridge": self.execute_shop_build_bridge,
            "destroy_bridge": self.execute_shop_destroy_bridge,
        }
        handler = action_handlers.get(self.shop_action)
        if handler is None:
            return
        handler(terr)
        if self.phase == "shopping":
            self.refresh_nation_states(trigger_player=self.current_player)
        if self.phase == "shopping" and not (
            (self.shop_action == "offensive_alliance" and self.pending_offensive_alliance_ai is not None)
            or (self.shop_action == "give_territory" and self.pending_gift_territory_id is not None)
            or (self.shop_action in ("build_bridge", "destroy_bridge") and self.pending_bridge_territory_id is not None)
        ):
            self.shop_panel_collapsed = False
        winner = self.check_winner()
        if winner is not None:
            self.declare_victory(winner)

    def execute_shop_mercenary_purchase(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Les mercenaires doivent etre places sur un territoire controle.", 2200)
            return
        self.update_shop_mercenary_quantity()
        quantity = self.shop_mercenary_quantity
        cost = quantity * self.MERCENARY_COST
        if not self.spend_player_money(self.current_player, cost):
            self.show_message("Pas assez d'ecus pour ces mercenaires.", 1800)
            return
        terr.regiments += quantity
        self.shop_mercenary_quantity = 1
        self.update_shop_mercenary_quantity()
        self.show_message(f"{quantity} mercenaire(s) places sur {terr.name} pour {cost} ecu(s).", 2000)

    def execute_shop_sell_territory(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Vous ne pouvez vendre qu'un territoire que vous controlez.", 2200)
            return
        candidates = [
            player for player in self.get_active_players()
            if player != self.current_player and not self.is_commercial_city_player(player)
        ]
        if not candidates:
            self.show_message("Vente impossible : aucun autre joueur actif non cite commercante ne peut recevoir ce territoire.", 2600)
            return
        sale_price = self.calculate_territory_sale_price(terr)
        buyer = random.choice(candidates)
        terr.owner = buyer
        self.ensure_player_economy(self.current_player)
        self.player_money[self.current_player] += sale_price
        self.refresh_last_stand_bonus_state()
        self.enforce_last_stand_bonus_limits()
        elimination_note = ""
        if not any(t.owner == self.current_player for t in self.territories):
            self.mark_eliminated_player_if_human(self.current_player)
            self.refresh_eliminated_human_players()
            elimination_note = f" J{self.current_player + 1} n'a plus de territoire."
        self.show_message(
            f"{terr.name} vendu a J{buyer + 1} pour {sale_price} ecu(s) "
            f"({terr.regiments} regiment(s) x 10 + {self.calculate_sale_structure_bonus(terr)} ecu(s) de bonus)."
            + elimination_note,
            3600,
        )

    def execute_shop_give_territory(self, terr: Territory) -> None:
        if self.pending_gift_territory_id is None:
            if terr.owner != self.current_player:
                self.show_message("Vous devez d'abord choisir un territoire que vous controlez.", 2400)
                return
            candidates = [player for player in self.get_active_players() if player != self.current_player]
            if not candidates:
                self.show_message("Don impossible : aucun autre joueur actif ne peut recevoir ce territoire.", 2600)
                return
            self.pending_gift_territory_id = terr.id
            self.show_message(
                f"Territoire a donner : {terr.name}. Cliquez maintenant sur un territoire du joueur beneficiaire.",
                3400,
            )
            return

        source_id = self.pending_gift_territory_id
        if not (0 <= source_id < len(self.territories)):
            self.pending_gift_territory_id = None
            self.show_message("Don impossible : territoire source invalide.", 2200)
            return
        source = self.territories[source_id]
        if source.owner != self.current_player:
            self.pending_gift_territory_id = None
            self.show_message("Don impossible : ce territoire n'est plus controle par vous.", 2600)
            return

        target_player = terr.owner
        if target_player < 0 or self.is_sanctuary_territory(terr.id):
            self.show_message("Impossible de donner un territoire a l'ONU.", 2200)
            return
        if target_player == self.current_player:
            self.show_message("Choisissez un autre joueur comme beneficiaire. Se donner sa propre terre, c'est juste rester proprietaire avec des etapes.", 3000)
            return
        if not self.can_commercial_city_gain_territory(target_player, source.id):
            self.show_message("Don impossible : une Cite commercante ne peut jamais prendre le controle d'une capitale.", 3000)
            return

        source.owner = target_player
        self.pending_gift_territory_id = None
        self.refresh_last_stand_bonus_state()
        self.enforce_last_stand_bonus_limits()
        elimination_note = ""
        if not any(t.owner == self.current_player for t in self.territories):
            self.mark_eliminated_player_if_human(self.current_player)
            self.refresh_eliminated_human_players()
            elimination_note = f" J{self.current_player + 1} n'a plus de territoire."
        self.show_message(
            f"{source.name} donne a J{target_player + 1}. Aucun ecu gagne, juste de la geopolitique charitable." + elimination_note,
            3600,
        )

    def execute_shop_gift_money(self, terr: Territory) -> None:
        target_player = terr.owner
        if target_player < 0 or self.is_sanctuary_territory(terr.id):
            self.show_message("Impossible de donner de l'argent a l'ONU.", 2200)
            return
        if target_player == self.current_player:
            self.show_message("Impossible de se donner de l'argent a soi-meme. Meme la comptabilite refuserait.", 2400)
            return
        self.update_shop_gift_amount()
        amount = self.shop_gift_amount
        if amount <= 0:
            self.show_message("Impossible de donner de l'argent : aucun ecu disponible.", 1800)
            return
        if not self.spend_player_money(self.current_player, amount):
            self.show_message(f"Don impossible : {amount} ecu(s) non disponibles.", 2200)
            return
        self.ensure_player_economy(target_player)
        self.player_money[target_player] += amount
        self.update_shop_gift_amount()
        self.show_message(f"J{self.current_player + 1} donne {amount} ecu(s) a J{target_player + 1}.", 2600)

    def execute_shop_build_fortress(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Une forteresse doit etre construite sur un territoire controle.", 2200)
            return
        if terr.id in self.fortress_territory_ids:
            self.show_message("Ce territoire possede deja une forteresse.", 1800)
            return
        if not self.spend_player_money(self.current_player, self.FORTRESS_COST):
            self.show_message("Pas assez d'ecus pour construire une forteresse.", 1800)
            return
        self.fortress_territory_ids.add(terr.id)
        self.fortress_capture_counts[terr.id] = 0
        self.show_message(f"Forteresse construite sur {terr.name} pour {self.FORTRESS_COST} ecu(s).", 2200)

    def execute_shop_destroy_fortress(self, terr: Territory) -> None:
        if terr.id not in self.fortress_territory_ids:
            self.show_message("Aucune forteresse a detruire sur ce territoire.", 1800)
            return
        if not self.spend_player_money(self.current_player, self.DESTROY_FORTRESS_COST):
            self.show_message("Pas assez d'ecus pour detruire cette forteresse.", 1800)
            return
        self.fortress_territory_ids.discard(terr.id)
        self.fortress_capture_counts.pop(terr.id, None)
        self.show_message(f"Forteresse de {terr.name} detruite pour {self.DESTROY_FORTRESS_COST} ecu(s).", 2200)

    def calculate_corruption_surcharge(self, territory_id: int) -> int:
        surcharge = 0
        if territory_id in self.fortress_territory_ids:
            surcharge += self.CORRUPTION_FORTRESS_SURCHARGE
        surcharge += self.get_industrial_structure_count(territory_id) * self.CORRUPTION_INDUSTRIAL_SURCHARGE
        surcharge += self.get_cultural_center_count(territory_id) * self.CORRUPTION_CULTURAL_CENTER_SURCHARGE
        if territory_id in self.ultra_super_territory_ids or self.territories[territory_id].reinforcement_bonus >= 3:
            surcharge += self.CORRUPTION_BONUS_TERRITORY_SURCHARGE
        return surcharge

    def calculate_corruption_cost(self, terr: Territory, attacker: Optional[int] = None) -> Tuple[int, int, int]:
        attacker = self.current_player if attacker is None else attacker
        cost_per_regiment = (
            self.REDUCED_CORRUPTION_COST_PER_REGIMENT
            if self.has_culture_advantage(attacker, terr.owner)
            else self.CORRUPTION_COST_PER_REGIMENT
        )
        base_cost = max(1, terr.regiments) * cost_per_regiment
        surcharge = self.calculate_corruption_surcharge(terr.id)
        return base_cost + surcharge, base_cost, surcharge

    def execute_shop_corrupt_territory(self, terr: Territory) -> None:
        current_is_commercial_city = self.is_commercial_city_player(self.current_player)
        if terr.owner == self.current_player:
            self.show_message("Ce territoire est deja a vous. La corruption interne, gardons ca pour plus tard.", 2200)
            return
        if terr.id in self.golden_territory_ids:
            self.show_message("Impossible de corrompre un territoire dore : incorruptible.", 2200)
            return
        if (terr.owner < 0 or self.is_sanctuary_territory(terr.id)) and not current_is_commercial_city:
            self.show_message("Impossible de corrompre un territoire ONU.", 2200)
            return
        if self.is_commercial_city_territory(terr.id):
            self.show_message("Impossible de corrompre une cite commercante.", 2200)
            return
        if self.is_last_stand_bonus_territory(terr.id) and not current_is_commercial_city:
            self.show_message("Impossible de corrompre une capitale en paradis fiscal.", 2400)
            return
        if current_is_commercial_city and not self.is_territory_adjacent_to_player(terr.id, self.current_player):
            self.show_message("Corruption CC impossible : le territoire doit etre adjacent a une cite deja controlee.", 2600)
            return
        cost, base_cost, surcharge = self.calculate_corruption_cost(terr)
        if not self.spend_player_money(self.current_player, cost):
            surcharge_note = f" dont {surcharge} de surcout amenagement/+3" if surcharge > 0 else ""
            self.show_message(f"Corruption trop chere : {cost} ecu(s) necessaires{surcharge_note}.", 2600)
            return
        previous_owner = terr.owner
        if self.can_player_create_vassal_from_corruption(self.current_player):
            vassal_player = self.create_vassal_from_corruption(terr.id, self.current_player)
            self.refresh_last_stand_bonus_state()
            self.enforce_last_stand_bonus_limits()
            elimination_note = ""
            if previous_owner >= 0 and not any(t.owner == previous_owner for t in self.territories):
                self.mark_eliminated_player_if_human(previous_owner)
                self.refresh_eliminated_human_players()
                elimination_note = f" J{previous_owner + 1} est elimine." + self.transfer_eliminated_player_money(previous_owner, self.current_player)
            surcharge_note = f" Base {base_cost} + surcout {surcharge}." if surcharge > 0 else ""
            vassal_label = f"J{vassal_player + 1}" if vassal_player is not None else "un nouveau vassal"
            self.show_message(
                f"{terr.name} corrompu pour {cost} ecu(s).{surcharge_note} Le territoire devient vassal ({vassal_label}), Cite commercante alliee a J{self.current_player + 1}; integration dans {self.VASSAL_INTEGRATION_DELAY_TURNS} tours." + elimination_note,
                5200,
            )
            return

        self.sanctuary_territory_ids.discard(terr.id)
        self.submitted_territory_ids.discard(terr.id)
        self.submitted_territory_overlords.pop(terr.id, None)
        self.submitted_territory_created_turns.pop(terr.id, None)
        self.vassal_territory_overlords.pop(terr.id, None)
        self.vassal_territory_created_turns.pop(terr.id, None)
        self.vassal_players.pop(terr.id, None)
        terr.owner = self.current_player
        if current_is_commercial_city:
            self.enforce_commercial_city_cultural_center_limit()
        self.refresh_last_stand_bonus_state()
        self.enforce_last_stand_bonus_limits()
        elimination_note = ""
        if previous_owner >= 0 and not any(t.owner == previous_owner for t in self.territories):
            self.mark_eliminated_player_if_human(previous_owner)
            self.refresh_eliminated_human_players()
            elimination_note = f" J{previous_owner + 1} est elimine." + self.transfer_eliminated_player_money(previous_owner, self.current_player)
        surcharge_note = f" Base {base_cost} + surcout {surcharge}." if surcharge > 0 else ""
        self.show_message(f"{terr.name} corrompu pour {cost} ecu(s).{surcharge_note} Les amenagements restent intacts." + elimination_note, 4200)

    def execute_shop_revolt(self, terr: Territory) -> None:
        if terr.owner == self.current_player:
            self.show_message("Choisissez un territoire ennemi pour designer la cible de la revolte.", 2200)
            return
        if terr.owner < 0:
            self.show_message("Impossible de declencher une revolte chez l'ONU.", 2200)
            return
        target_player = terr.owner
        if self.is_commercial_city_player(target_player):
            self.show_message(
                "Revolte impossible : les Cites Commercantes sont immunisees contre les revoltes.",
                2800,
            )
            return
        if target_player in getattr(self, "nation_players", set()):
            self.show_message("Revolte impossible : les nations sont immunisees contre les revoltes.", 2600)
            return
        owned = [t for t in self.territories if t.owner == target_player]
        if not owned:
            self.show_message("Cet ennemi n'a plus de territoire a perdre.", 1800)
            return

        revolt_cost = self.calculate_revolt_cost_for_target_player(target_player)
        if not self.spend_player_money(self.current_player, revolt_cost):
            self.show_message(f"Pas assez d'ecus pour declencher cette revolte : {revolt_cost} ecu(s) necessaires.", 2200)
            return

        lost_count = self.calculate_revolt_loss_count(len(owned))
        territories_to_transfer = self.choose_owned_contiguous_block(target_player, lost_count)
        if not territories_to_transfer:
            self.player_money[self.current_player] += revolt_cost
            self.show_message("Revolte impossible : aucune cible valide hors capitale.", 2600)
            return
        lost_count = len(territories_to_transfer)
        rebel_player, returning_human = self.allocate_rebel_player()
        for territory in territories_to_transfer:
            territory.owner = rebel_player
        self.refresh_last_stand_bonus_state()
        self.refresh_eliminated_human_players()
        elimination_note = ""
        if not any(t.owner == target_player for t in self.territories):
            self.mark_eliminated_player_if_human(target_player)
            elimination_note = f" J{target_player + 1} est elimine." + self.transfer_eliminated_player_money(target_player, self.current_player)
        comeback = "nouveau joueur IA"
        self.show_message(
            f"Revolte financee chez J{target_player + 1} pour {revolt_cost} ecu(s): "
            f"{lost_count}/{len(owned)} territoire(s) passent a J{rebel_player + 1} ({comeback})." + elimination_note,
            4400,
        )

    def execute_shop_build_industrial_structure(self, terr: Territory, structure_type: str, label: str, cost: int) -> None:
        if terr.owner != self.current_player:
            self.show_message(f"Un {label} doit etre construit sur un territoire controle.", 2200)
            return
        existing_structure_type = self.get_industrial_structure_type(terr.id)
        if terr.id in self.get_industrial_structure_sets().get(structure_type, set()):
            labels = {"factory": "usine", "airport": "aeroport", "port": "port"}
            self.show_message(f"Ce territoire possede deja cet amenagement industriel ({labels.get(structure_type, 'industrie')}).", 2200)
            return
        if existing_structure_type is not None:
            labels = {"factory": "usine", "airport": "aeroport", "port": "port"}
            self.show_message(f"Ce territoire possede deja un amenagement industriel ({labels.get(existing_structure_type, 'industrie')}).", 2200)
            return
        if not self.spend_player_money(self.current_player, cost):
            self.show_message(f"Pas assez d'ecus pour construire un {label}.", 1800)
            return
        if not self.add_industrial_structure(terr.id, structure_type):
            self.show_message(f"Construction impossible pour ce {label}.", 1800)
            return
        bonus_note = " Bonus PF trio industriel actif : revenus +50%." if self.is_tax_haven_income_bonus_active(self.current_player) else ""
        self.show_message(f"{label.capitalize()} construit sur {terr.name} pour {cost} ecu(s)." + bonus_note, 2600)

    def execute_shop_build_factory(self, terr: Territory) -> None:
        self.execute_shop_build_industrial_structure(terr, "factory", "usine", self.FACTORY_COST)

    def execute_shop_build_airport(self, terr: Territory) -> None:
        self.execute_shop_build_industrial_structure(terr, "airport", "aeroport", self.AIRPORT_COST)

    def execute_shop_build_port(self, terr: Territory) -> None:
        self.execute_shop_build_industrial_structure(terr, "port", "port", self.PORT_COST)

    def execute_shop_build_temple(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Un temple doit etre construit sur un territoire controle.", 2200)
            return
        if self.has_temple(terr.id):
            self.show_message(f"Maximum atteint : un seul temple sur {terr.name}.", 2200)
            return
        if not self.spend_player_money(self.current_player, self.TEMPLE_COST):
            self.show_message(f"Pas assez d'ecus pour construire un temple : {self.TEMPLE_COST} requis.", 2200)
            return
        self.add_temple(terr.id)
        religion_note = getattr(self, "last_religion_foundation_message", None)
        if religion_note:
            self.show_message(f"Temple construit sur {terr.name}. {religion_note}", 5200)
        else:
            self.show_message(f"Temple construit sur {terr.name} pour {self.TEMPLE_COST} ecu(s).", 2600)

    def execute_shop_build_cultural_center(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Un centre culturel doit etre construit sur un territoire controle.", 2200)
            return
        if not self.can_add_cultural_center(terr.id):
            self.show_message(f"Maximum atteint : un seul centre culturel sur {terr.name}.", 2200)
            return
        if not self.spend_player_money(self.current_player, self.CULTURAL_CENTER_COST):
            self.show_message(f"Pas assez d'ecus pour construire un centre culturel : {self.CULTURAL_CENTER_COST} requis.", 2200)
            return
        self.add_cultural_center(terr.id, age=0)
        count = self.get_cultural_center_count(terr.id)
        self.show_message(f"Centre culturel construit sur {terr.name} pour {self.CULTURAL_CENTER_COST} ecu(s).", 2600)

    def execute_shop_build_university(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Une universite doit etre construite sur un territoire controle.", 2200)
            return
        if self.has_university(terr.id):
            self.show_message(f"Maximum atteint : une seule universite sur {terr.name}.", 2200)
            return
        if not self.spend_player_money(self.current_player, self.UNIVERSITY_COST):
            self.show_message(f"Pas assez d'ecus pour construire une universite : {self.UNIVERSITY_COST} requis.", 2200)
            return
        self.add_university(terr.id)
        self.show_message(f"Universite construite sur {terr.name} pour {self.UNIVERSITY_COST} ecu(s). Elle produit de la science a chaque tour.", 3400)

    def execute_shop_build_wonder(self, terr: Territory) -> None:
        wonder_type = self.pending_wonder_type
        if wonder_type not in self.WONDER_DEFINITIONS:
            self.show_message("Choisissez d'abord une merveille dans le menu des achats.", 2200)
            return
        required_science = self.get_wonder_science_threshold(self.current_player)
        if not self.can_player_build_wonder(self.current_player):
            self.show_message(
                f"Science insuffisante : {required_science} points requis pour une merveille.",
                2400,
            )
            return
        if terr.owner != self.current_player:
            self.show_message("Une merveille doit etre construite sur un territoire controle.", 2200)
            return
        if self.get_wonder_type_at_territory(terr.id) is not None:
            self.show_message(f"{terr.name} accueille deja une merveille.", 2200)
            return
        if wonder_type not in self.get_available_wonder_types():
            self.show_message(f"{self.get_wonder_name(wonder_type)} a deja ete construite.", 2400)
            self.pending_wonder_type = None
            return
        if not self.spend_player_money(self.current_player, self.WONDER_COST):
            self.show_message(f"Pas assez d'ecus : {self.WONDER_COST} requis pour cette merveille.", 2200)
            return
        if not self.build_wonder(terr.id, wonder_type):
            self.player_money[self.current_player] += self.WONDER_COST
            self.show_message("Construction de la merveille impossible.", 2200)
            return
        wonder_name = self.get_wonder_name(wonder_type)
        wonder_effect = self.get_wonder_effect(wonder_type)
        self.pending_wonder_type = None
        self.shop_action = None
        self.show_message(
            f"{wonder_name} construite sur {terr.name} pour {self.WONDER_COST} ecus. {wonder_effect}.",
            5200,
        )

    def execute_shop_build_bridge(self, terr: Territory) -> None:
        if self.get_player_science(self.current_player) < self.SCIENCE_BRIDGE_THRESHOLD:
            self.pending_bridge_territory_id = None
            self.show_message(
                f"Ponts verrouilles : {self.SCIENCE_BRIDGE_THRESHOLD} points de science requis.", 2400
            )
            return
        if self.pending_bridge_territory_id is None:
            self.pending_bridge_territory_id = terr.id
            self.show_message(
                f"Premier territoire : {terr.name}. Cliquez maintenant sur le territoire a relier.", 2800
            )
            return
        territory_a = self.pending_bridge_territory_id
        territory_b = terr.id
        if territory_a == territory_b:
            self.show_message("Choisissez deux territoires differents.", 2000)
            return
        key = tuple(sorted((territory_a, territory_b)))
        if key in self.bridge_links or territory_b in self.territories[territory_a].neighbors:
            self.show_message("Ces deux territoires sont deja directement relies.", 2400)
            return
        points = self.find_bridge_connection_points(*key)
        if points is None:
            self.show_message(
                "Pont impossible : distance superieure a 2 cm, absence d'eau ou passage au-dessus d'un territoire.",
                3400,
            )
            return
        if not self.spend_player_money(self.current_player, self.BUILD_BRIDGE_COST):
            self.pending_bridge_territory_id = None
            self.show_message(f"Pont trop cher : {self.BUILD_BRIDGE_COST} ecus requis.", 2200)
            return
        self.add_bridge(key, points)
        self.pending_bridge_territory_id = None
        message = (
            f"J{self.current_player + 1} construit un pont entre {self.territories[key[0]].name} "
            f"et {self.territories[key[1]].name} pour {self.BUILD_BRIDGE_COST} ecus."
        )
        self.record_major_event(message)
        self.record_replay_snapshot(message, force=True)
        self.show_message(message, 4200)

    def execute_shop_destroy_bridge(self, terr: Territory) -> None:
        if self.get_player_science(self.current_player) < self.SCIENCE_BRIDGE_THRESHOLD:
            self.pending_bridge_territory_id = None
            self.show_message(
                f"Ponts verrouilles : {self.SCIENCE_BRIDGE_THRESHOLD} points de science requis.", 2400
            )
            return
        if self.pending_bridge_territory_id is None:
            self.pending_bridge_territory_id = terr.id
            self.show_message(
                f"Premier territoire : {terr.name}. Cliquez sur l'autre extremite du pont.", 2800
            )
            return
        key = tuple(sorted((self.pending_bridge_territory_id, terr.id)))
        if key not in self.bridge_links:
            self.show_message("Aucun pont ne relie ces deux territoires.", 2400)
            return
        if not self.spend_player_money(self.current_player, self.DESTROY_BRIDGE_COST):
            self.pending_bridge_territory_id = None
            self.show_message(f"Destruction trop chere : {self.DESTROY_BRIDGE_COST} ecus requis.", 2200)
            return
        territory_a, territory_b = key
        self.remove_bridge(key)
        self.pending_bridge_territory_id = None
        message = (
            f"J{self.current_player + 1} detruit le pont entre {self.territories[territory_a].name} "
            f"et {self.territories[territory_b].name} pour {self.DESTROY_BRIDGE_COST} ecus."
        )
        self.record_major_event(message)
        self.record_replay_snapshot(message, force=True)
        self.show_message(message, 4200)

    def execute_shop_destroy_university(self, terr: Territory) -> None:
        if not self.has_university(terr.id):
            self.show_message("Aucune universite a detruire sur ce territoire.", 1800)
            return
        if not self.spend_player_money(self.current_player, self.UNIVERSITY_COST):
            self.show_message(f"Pas assez d'ecus pour detruire cette universite : {self.UNIVERSITY_COST} requis.", 2200)
            return
        self.remove_university(terr.id)
        self.show_message(f"Universite de {terr.name} detruite pour {self.UNIVERSITY_COST} ecu(s).", 2400)

    def execute_shop_change_capital(self, terr: Territory) -> None:
        if self.current_player in self.commercial_city_players:
            self.show_message("Changement impossible : les Cites commercantes gardent leur capitale CC propre.", 2600)
            return
        if terr.owner != self.current_player:
            self.show_message("La nouvelle capitale doit etre un territoire que vous controlez.", 2400)
            return
        if self.is_sanctuary_territory(terr.id) or terr.owner == self.onu_player_id:
            self.show_message("Changement impossible : un territoire ONU ne peut pas devenir capitale.", 2400)
            return
        previous_capital_id = getattr(self, "player_capital_ids", {}).get(self.current_player)
        if previous_capital_id == terr.id and self.is_active_regular_capital(terr.id):
            self.show_message(f"{terr.name} est deja votre capitale. Meme l'administration peut eviter un formulaire inutile.", 2600)
            return
        if not self.spend_player_money(self.current_player, self.CHANGE_CAPITAL_COST):
            self.show_message(f"Pas assez d'ecus pour changer de capitale : {self.CHANGE_CAPITAL_COST} requis.", 2200)
            return
        if not hasattr(self, "player_capital_ids"):
            self.player_capital_ids = {}
        old_name = None
        if previous_capital_id is not None and 0 <= previous_capital_id < len(self.territories):
            old_name = self.territories[previous_capital_id].name
        self.player_capital_ids[self.current_player] = terr.id
        self.sanctuary_territory_ids.discard(terr.id)
        self.sanitize_player_capitals()
        old_note = f" Ancienne capitale : {old_name}." if old_name and old_name != terr.name else ""
        self.show_message(
            f"{terr.name} devient la capitale de J{self.current_player + 1} pour {self.CHANGE_CAPITAL_COST} ecu(s)."
            f" Revenu x{self.CAPITAL_INCOME_MULTIPLIER} et symbole C actifs." + old_note,
            3600,
        )

    def calculate_union_cost(self, target_player: int) -> int:
        return 0

    def execute_shop_union_nations(self, terr: Territory) -> None:
        self.show_message("Union des nations supprimee : les nations ne peuvent plus s'unir.", 2600)

    def execute_shop_peace_treaty(self, terr: Territory) -> None:
        self.show_message("Traite national supprime : les nations n'ont plus de diplomatie permanente particuliere.", 2600)

    def execute_shop_buy_alliance(self, terr: Territory) -> None:
        if self.is_cold_war_active():
            self.show_message("Alliance impossible : la guerre froide a fige les blocs. Plus aucun contrat d'alliance n'est disponible.", 3200)
            return
        target_player = terr.owner
        exclusive_ally = self.get_commercial_city_wonder_ally()
        if self.is_commercial_city_player(target_player) and exclusive_ally is not None:
            self.show_message(
                f"Alliance impossible : la Cite commercante est exclusivement alliee a J{exclusive_ally + 1} grace au Palais du Pacte d'Or.",
                3200,
            )
            return
        if target_player == self.current_player:
            self.show_message("Choisissez un territoire du joueur IA avec qui conclure l'alliance defensive.", 2200)
            return
        if target_player < 0 or self.is_sanctuary_territory(terr.id):
            self.show_message("Impossible d'acheter une alliance avec l'ONU. Meme la fiction a des limites.", 2200)
            return
        if not self.is_ai_player(target_player):
            self.show_message("Alliance impossible : la cible doit etre un joueur IA, pas un joueur humain.", 2400)
            return
        if not self.is_human_player_id(self.current_player):
            self.show_message("Seul un joueur humain peut acheter une alliance.", 2200)
            return
        cost = self.get_alliance_cost(target_player)
        if cost <= 0:
            self.show_message("Alliance impossible : ce joueur IA ne controle plus aucun territoire.", 2200)
            return
        if not self.spend_player_money(self.current_player, cost):
            self.show_message(f"Alliance defensive trop chere : {cost} ecu(s) necessaires.", 2200)
            return
        expires_turn = self.turn + self.ALLIANCE_DURATION_TURNS
        self.active_alliances[(self.current_player, target_player)] = expires_turn
        self.alliance_start_turns[(self.current_player, target_player)] = self.turn
        event_message = f"Alliance defensive conclue avec J{target_player + 1} pour {cost} ecu(s). J{target_player + 1} n'attaquera plus J{self.current_player + 1} jusqu'au tour {expires_turn}."
        self.record_major_event(event_message)
        self.show_message(event_message, 4200)

    def execute_shop_buy_offensive_alliance(self, terr: Territory) -> None:
        if self.is_cold_war_active():
            self.pending_offensive_alliance_ai = None
            self.show_message("Alliance offensive impossible : la guerre froide a remplace la diplomatie par deux blocs definitifs.", 3200)
            return
        clicked_player = terr.owner
        if not self.is_human_player_id(self.current_player):
            self.pending_offensive_alliance_ai = None
            self.show_message("Seul un joueur humain peut acheter une alliance offensive.", 2200)
            return

        if self.pending_offensive_alliance_ai is None:
            if clicked_player == self.current_player:
                self.show_message("Choisissez d'abord un territoire du joueur IA a recruter offensivement.", 2400)
                return
            if clicked_player < 0 or self.is_sanctuary_territory(terr.id):
                self.show_message("Impossible de recruter offensivement l'ONU. Il reste donc un fond de dignite institutionnelle.", 2400)
                return
            if not self.is_ai_player(clicked_player):
                self.show_message("Alliance offensive impossible : l'allie doit etre un joueur IA.", 2400)
                return
            exclusive_ally = self.get_commercial_city_wonder_ally()
            if self.is_commercial_city_player(clicked_player) and exclusive_ally is not None:
                self.show_message(
                    f"Alliance offensive impossible : la Cite commercante est exclusivement alliee a J{exclusive_ally + 1}.",
                    3000,
                )
                return
            cost = self.get_offensive_alliance_cost(clicked_player)
            if cost <= 0:
                self.show_message("Alliance offensive impossible : ce joueur IA ne controle plus aucun territoire.", 2200)
                return
            if self.get_player_money(self.current_player) < cost:
                self.show_message(f"Alliance offensive trop chere : {cost} ecu(s) necessaires.", 2400)
                return
            self.pending_offensive_alliance_ai = clicked_player
            self.shop_panel_collapsed = True
            self.show_message(
                f"Allie offensif selectionne : J{clicked_player + 1}. Cliquez maintenant sur un territoire du joueur a cibler.",
                3600,
            )
            return

        ai_player = self.pending_offensive_alliance_ai
        target_player = clicked_player
        if target_player < 0 or self.is_sanctuary_territory(terr.id):
            self.show_message("Cible invalide : l'ONU ne compte pas comme joueur cible pour cette alliance.", 2400)
            return
        if target_player == self.current_player:
            self.show_message("Cible invalide : payer une IA pour vous attaquer serait audacieux, mais non.", 2600)
            return
        if target_player == ai_player:
            self.show_message("Cible invalide : l'allie offensif ne va pas s'attaquer lui-meme.", 2400)
            return
        if not any(t.owner == ai_player for t in self.territories):
            self.pending_offensive_alliance_ai = None
            self.show_message("Alliance offensive impossible : l'allie IA n'a plus de territoire.", 2400)
            return
        if not any(t.owner == target_player for t in self.territories):
            self.show_message("Alliance offensive impossible : la cible n'a plus de territoire.", 2400)
            return

        cost = self.get_offensive_alliance_cost(ai_player)
        if not self.spend_player_money(self.current_player, cost):
            self.pending_offensive_alliance_ai = None
            self.show_message(f"Alliance offensive trop chere : {cost} ecu(s) necessaires.", 2400)
            return

        expires_turn = self.turn + self.ALLIANCE_DURATION_TURNS
        self.active_offensive_alliances[(self.current_player, ai_player)] = (target_player, expires_turn)
        self.offensive_alliance_start_turns[(self.current_player, ai_player)] = self.turn
        broken_ai_alliance_note = self.break_ai_alliance_due_to_offensive_contract(ai_player, target_player)
        self.pending_offensive_alliance_ai = None
        event_message = f"Alliance offensive conclue avec J{ai_player + 1} pour {cost} ecu(s). J{ai_player + 1} cible J{target_player + 1} jusqu'au tour {expires_turn}."
        if broken_ai_alliance_note:
            event_message += " " + broken_ai_alliance_note
        self.record_major_event(event_message)
        self.show_message(event_message, 5200 if broken_ai_alliance_note else 4600)

    def cleanup_removed_ai_player(self, ai_player: int) -> None:
        self.schedule_commercial_city_replacement_if_destroyed(ai_player)
        self.base_ai_players.discard(ai_player)
        self.auto_controlled_players.discard(ai_player)
        self.commercial_city_players.discard(ai_player)
        self.commercial_city_capital_ids.pop(ai_player, None)
        self.ai_personalities.pop(ai_player, None)
        self.ai_current_behavior.pop(ai_player, None)
        self.player_science.pop(ai_player, None)
        self.culture_expansion_milestones.pop(ai_player, None)
        self.active_alliances = {
            key: expires_turn
            for key, expires_turn in self.active_alliances.items()
            if key[1] != ai_player
        }
        self.alliance_start_turns = {key: start for key, start in self.alliance_start_turns.items() if key in self.active_alliances}
        self.active_ai_alliances = {
            key: expires_turn
            for key, expires_turn in self.active_ai_alliances.items()
            if ai_player not in key
        }
        self.ai_alliance_start_turns = {key: start for key, start in self.ai_alliance_start_turns.items() if key in self.active_ai_alliances}
        self.active_offensive_alliances = {
            key: data
            for key, data in self.active_offensive_alliances.items()
            if key[1] != ai_player and data[0] != ai_player
        }
        self.offensive_alliance_start_turns = {key: start for key, start in self.offensive_alliance_start_turns.items() if key in self.active_offensive_alliances}
        self.nation_players.discard(ai_player)
        self.nation_alliances = {key for key in self.nation_alliances if ai_player not in key}
        self.nation_wars = {key for key in self.nation_wars if ai_player not in key}

    def execute_shop_freeze_territory(self, terr: Territory) -> None:
        if not self.can_player_manipulate_onu(self.current_player):
            self.show_message(f"Figement impossible : il faut etre en paradis fiscal ou avoir {self.SCIENCE_ONU_MANIPULATION_THRESHOLD} points de science.", 2800)
            return
        if self.is_sanctuary_territory(terr.id) or terr.owner == self.onu_player_id:
            self.show_message("Ce territoire est deja un territoire ONU. Meme l'ONU ne peut pas etre plus ONU.", 2600)
            return
        if self.is_last_stand_bonus_territory(terr.id):
            self.show_message("Figement impossible : une capitale en paradis fiscal ne peut pas devenir territoire ONU.", 3000)
            return
        if self.is_regular_capital_territory(terr.id):
            self.show_message("Figement impossible : une capitale de joueur ne peut pas devenir territoire ONU.", 3000)
            return
        if self.is_golden_territory(terr.id):
            self.show_message("Figement impossible : un territoire dore ne peut jamais devenir territoire ONU.", 3000)
            return
        cost = self.calculate_onu_manipulation_cost(terr)
        if not self.spend_player_money(self.current_player, cost):
            self.show_message(f"Figement trop cher : {cost} ecu(s) necessaires.", 2400)
            return
        previous_owner = terr.owner
        previous_regiments = terr.regiments
        self.convert_territory_to_sanctuary(terr.id, regiments=previous_regiments)
        self.refresh_last_stand_bonus_state()
        self.refresh_eliminated_human_players()
        elimination_note = ""
        if previous_owner >= 0 and not any(t.owner == previous_owner for t in self.territories):
            self.mark_eliminated_player_if_human(previous_owner)
            self.refresh_eliminated_human_players()
            elimination_note = f" J{previous_owner + 1} n'a plus de territoire."
        self.show_message(
            f"{terr.name} fige en territoire ONU pour {cost} ecu(s) ({max(1, previous_regiments)} regiment(s) x {self.ONU_MANIPULATION_COST_PER_REGIMENT})."
            + elimination_note,
            4200,
        )

    def execute_shop_release_sanctuary(self, terr: Territory) -> None:
        if not self.can_player_manipulate_onu(self.current_player):
            self.show_message(f"Liberation impossible : il faut etre en paradis fiscal ou avoir {self.SCIENCE_ONU_MANIPULATION_THRESHOLD} points de science.", 2800)
            return
        if not self.is_sanctuary_territory(terr.id) and terr.owner != self.onu_player_id:
            self.show_message("Liberation impossible : ce territoire n'est pas un territoire ONU.", 2400)
            return
        cost = self.calculate_onu_manipulation_cost(terr)
        if not self.spend_player_money(self.current_player, cost):
            self.show_message(f"Liberation trop chere : {cost} ecu(s) necessaires.", 2400)
            return
        new_owner = self.get_random_ai_recipient_for_released_sanctuary(excluded_players={self.current_player})
        self.sanctuary_territory_ids.discard(terr.id)
        self.submitted_territory_ids.discard(terr.id)
        self.submitted_territory_overlords.pop(terr.id, None)
        self.submitted_territory_created_turns.pop(terr.id, None)
        terr.owner = new_owner
        terr.reinforcement_bonus = 1
        terr.regiments = max(1, terr.regiments)
        if self.selected_source == terr.id:
            self.selected_source = None
        if self.selected_target == terr.id:
            self.selected_target = None
        self.refresh_last_stand_bonus_state()
        self.refresh_eliminated_human_players()
        self.show_message(
            f"{terr.name} libere de l'ONU pour {cost} ecu(s) et attribue a l'IA J{new_owner + 1}.",
            4200,
        )

    def execute_shop_tax_haven_association(self, terr: Territory) -> None:
        human_player = self.current_player
        ai_player = terr.owner
        if not self.is_human_player_id(human_player):
            self.show_message("Seul un joueur humain peut utiliser cette option de paradis fiscal.", 2400)
            return
        if ai_player == human_player:
            self.show_message("Choisissez une capitale IA en paradis fiscal, pas votre propre territoire.", 2400)
            return
        if ai_player < 0 or self.is_sanctuary_territory(terr.id):
            self.show_message("Operation impossible avec l'ONU. La bureaucratie gagne encore.", 2400)
            return
        if not self.is_ai_player(ai_player):
            self.show_message("Operation impossible : la capitale cible doit appartenir a un joueur IA.", 2600)
            return
        if ai_player not in self.last_stand_bonus_players or terr.id not in self.get_player_tax_haven_capital_ids(ai_player):
            self.show_message("Operation impossible : ce territoire n'est pas la capitale IA en paradis fiscal.", 2800)
            return

        if self.can_player_integrate_tax_haven_by_science(human_player):
            self.execute_shop_science_tax_haven_integration(terr, ai_player)
            return

        if human_player in self.last_stand_bonus_players:
            self.execute_shop_tax_haven_integration(terr, ai_player)
            return

        absorbed_territories = [territory for territory in self.territories if territory.owner == ai_player]
        if not absorbed_territories:
            self.show_message("Association impossible : ce joueur IA n'a plus de territoire actif.", 2200)
            return

        previous_ai_money = self.player_money.get(ai_player, 0)
        self.ensure_player_economy(human_player)
        self.player_money[human_player] += previous_ai_money
        self.player_money[ai_player] = 0

        for territory in absorbed_territories:
            territory.owner = human_player

        self.remove_tax_haven_player(ai_player)
        self.cleanup_removed_ai_player(ai_player)

        self.add_tax_haven_capital(human_player, terr.id)

        owned_after_association = [territory for territory in self.territories if territory.owner == human_player]
        loss_count = min(max(0, len(owned_after_association) // 4), max(0, len(owned_after_association) - 1))
        lost_territories: List[Territory] = []
        returning_human = False
        loss_receiver: Optional[int] = None
        if loss_count > 0:
            loss_candidates = [territory.id for territory in owned_after_association if territory.id != terr.id]
            # On privilegie un bloc contigu sans jamais sacrifier la nouvelle capitale, parce que perdre
            # son paradis fiscal au moment precis ou on le cree serait une blague fiscale de trop.
            picked = [territory for territory in self.choose_owned_contiguous_block(human_player, loss_count) if territory.id != terr.id]
            if len(picked) < loss_count:
                picked_ids = {territory.id for territory in picked}
                remaining = [tid for tid in loss_candidates if tid not in picked_ids]
                random.shuffle(remaining)
                picked.extend(self.territories[tid] for tid in remaining[: loss_count - len(picked)])
            lost_territories = picked[:loss_count]
            loss_receiver, returning_human = self.allocate_rebel_player()
            for territory in lost_territories:
                territory.owner = loss_receiver

        self.refresh_last_stand_bonus_state()
        self.refresh_eliminated_human_players()
        comeback = "nouveau joueur IA"
        loss_note = (
            f" J{human_player + 1} perd {len(lost_territories)} territoire(s) sur {len(owned_after_association)} au profit de J{loss_receiver + 1} ({comeback})."
            if loss_receiver is not None
            else " Aucun territoire perdu : empire trop petit pour prelever un quart sans detruire la capitale."
        )
        money_note = f" Tresor IA recupere : {previous_ai_money} ecu(s)." if previous_ai_money > 0 else ""
        self.show_message(
            f"Association conclue : J{human_player + 1} absorbe J{ai_player + 1}, {terr.name} devient sa capitale x10."
            + loss_note
            + money_note,
            5600,
        )

    def execute_shop_science_tax_haven_integration(self, terr: Territory, ai_player: int) -> None:
        human_player = self.current_player
        if not self.can_player_integrate_tax_haven_by_science(human_player):
            self.show_message(f"Integration scientifique impossible : {self.SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD} points de science requis.", 2600)
            return
        terr.owner = human_player
        self.remove_tax_haven_capital(ai_player, terr.id)
        if not any(territory.owner == ai_player for territory in self.territories):
            self.cleanup_removed_ai_player(ai_player)
        self.refresh_last_stand_bonus_state()
        self.refresh_eliminated_human_players()
        self.show_message(
            f"Integration technologique : J{human_player + 1} integre {terr.name} sans cout ni penalite. Le territoire perd son statut de paradis fiscal.",
            4600,
        )

    def execute_shop_tax_haven_integration(self, terr: Territory, ai_player: int) -> None:
        human_player = self.current_player
        cost = self.TAX_HAVEN_INTEGRATION_COST
        if not self.spend_player_money(human_player, cost):
            self.show_message(f"Integration trop chere : {cost} ecu(s) necessaires.", 2400)
            return

        terr.owner = human_player
        self.remove_tax_haven_capital(ai_player, terr.id)
        self.add_tax_haven_capital(human_player, terr.id)
        if not any(territory.owner == ai_player for territory in self.territories):
            self.cleanup_removed_ai_player(ai_player)
        self.refresh_last_stand_bonus_state()
        self.refresh_eliminated_human_players()

        self.show_message(
            f"Integration conclue : J{human_player + 1} paie {cost} ecu(s) et prend le controle de la capitale x10 {terr.name} de J{ai_player + 1}.",
            4600,
        )

    def execute_ai_economic_actions(self, player: int) -> int:
        return moteur_regles.execute_ai_economic_actions(self, player)

    def find_ai_wonder_purchase(self, player: int):
        if not self.is_ai_player(player) or not self.can_player_build_wonder(player):
            return None
        available_wonders = self.get_available_wonder_types()
        if not available_wonders:
            return None
        candidates = [
            territory for territory in self.territories
            if territory.owner == player
            and not self.is_sanctuary_territory(territory.id)
            and self.get_wonder_type_at_territory(territory.id) is None
        ]
        if not candidates:
            return None
        wonder_type = available_wonders[0]
        target = max(
            candidates,
            key=lambda territory: (
                self.calculate_territory_income(territory),
                len(territory.neighbors),
                territory.regiments,
                -territory.id,
            ),
        )
        return self.WONDER_COST, lambda terr=target, kind=wonder_type: self.build_wonder(terr.id, kind)

    def find_next_regular_ai_purchase(self, player: int):
        owned = [terr for terr in self.territories if terr.owner == player]
        if not owned:
            return None
        owned.sort(key=lambda terr: terr.id)

        # Les achats IA visent d'abord le bloc contigu qui peut devenir nation.
        # Acheter le bon batiment au mauvais endroit, c'est tres humain, mais ici on evite.
        nation_component = self.find_player_nation_development_component(player)
        development_ids = set(nation_component) if nation_component is not None else {terr.id for terr in owned}
        development_owned = [terr for terr in owned if terr.id in development_ids]
        if not development_owned:
            development_owned = owned

        fortress_action = self.find_regular_ai_fortress_purchase(player, development_owned)
        if fortress_action is not None:
            return fortress_action

        industrial_types = self.get_component_industrial_types([terr.id for terr in development_owned])
        if not industrial_types:
            return self.find_regular_ai_industrial_purchase(player, development_owned, preferred_missing_types=None)

        development_tid_list = [terr.id for terr in development_owned]
        if not self.component_has_temple(development_tid_list):
            temple_candidates = [terr for terr in development_owned if self.can_add_temple(terr.id)]
            if temple_candidates:
                target = self.choose_regular_ai_development_target(temple_candidates, player)
                return self.TEMPLE_COST, lambda terr=target: self.add_temple(terr.id)

        if not self.component_has_cultural_center(development_tid_list):
            cultural_candidates = [terr for terr in development_owned if self.can_add_cultural_center(terr.id)]
            if cultural_candidates:
                target = self.choose_regular_ai_development_target(cultural_candidates, player)
                return self.CULTURAL_CENTER_COST, lambda terr=target: self.add_cultural_center(terr.id, age=0)

        if not self.component_has_university(development_tid_list):
            university_candidates = [terr for terr in development_owned if self.can_add_university(terr.id)]
            if university_candidates:
                target = self.choose_regular_ai_university_target(university_candidates, player)
                return self.UNIVERSITY_COST, lambda terr=target: self.add_university(terr.id)

        if len(industrial_types) < 2:
            action = self.find_regular_ai_industrial_purchase(
                player,
                development_owned,
                preferred_missing_types=self.get_missing_component_industrial_types(development_tid_list),
            )
            if action is not None:
                return action
            return self.find_regular_ai_mercenary_purchase(player, owned)

        if len(industrial_types) < 3:
            action = self.find_regular_ai_industrial_purchase(
                player,
                development_owned,
                preferred_missing_types=self.get_missing_component_industrial_types(development_tid_list),
            )
            if action is not None:
                return action
            return self.find_regular_ai_mercenary_purchase(player, owned)

        return self.find_regular_ai_mercenary_purchase(player, owned)

    def find_regular_ai_fortress_purchase(self, player: int, owned: List[Territory]):
        if any(terr.id in self.fortress_territory_ids for terr in owned):
            return None
        candidates = [terr for terr in owned if terr.id not in self.fortress_territory_ids]
        if not candidates:
            return None
        capital_id = self.get_active_regular_capital_id_for_player(player)
        if capital_id is not None:
            capital = self.territories[capital_id]
            if capital.owner == player and capital.id not in self.fortress_territory_ids:
                return self.FORTRESS_COST, lambda terr=capital: self.add_regular_ai_fortress(terr.id)
        target = self.choose_regular_ai_development_target(candidates, player)
        return self.FORTRESS_COST, lambda terr=target: self.add_regular_ai_fortress(terr.id)

    def add_regular_ai_fortress(self, territory_id: int) -> None:
        if not (0 <= territory_id < len(self.territories)):
            return
        self.fortress_territory_ids.add(territory_id)
        self.fortress_capture_counts[territory_id] = 0

    def get_active_regular_capital_id_for_player(self, player: int) -> Optional[int]:
        capital_id = getattr(self, "player_capital_ids", {}).get(player)
        if capital_id is None or not (0 <= capital_id < len(self.territories)):
            return None
        if self.territories[capital_id].owner != player:
            return None
        if self.is_onu_player(player) or self.is_potential_commercial_city_player(player):
            return None
        return capital_id

    def get_player_industrial_types(self, player: int) -> set[str]:
        owned_ids = {terr.id for terr in self.territories if terr.owner == player}
        types: set[str] = set()
        for structure_type, territory_ids in self.get_industrial_structure_sets().items():
            if territory_ids & owned_ids:
                types.add(structure_type)
        return types

    def get_missing_player_industrial_types(self, player: int) -> list[str]:
        existing = self.get_player_industrial_types(player)
        missing = [structure_type for structure_type in ("factory", "airport", "port") if structure_type not in existing]
        random.shuffle(missing)
        return missing

    def player_has_temple(self, player: int) -> bool:
        return self.get_player_temple_count(player) > 0

    def player_has_cultural_center(self, player: int) -> bool:
        return any(
            terr.owner == player and self.get_cultural_center_count(terr.id) > 0
            for terr in self.territories
        )

    def player_has_university(self, player: int) -> bool:
        return any(terr.owner == player and terr.id in self.university_territory_ids for terr in self.territories)

    def find_regular_ai_industrial_purchase(
        self,
        player: int,
        owned: List[Territory],
        preferred_missing_types: Optional[List[str]],
    ):
        candidates = [terr for terr in owned if self.get_industrial_structure_count(terr.id) == 0]
        if not candidates:
            return None
        structure_types = list(preferred_missing_types) if preferred_missing_types else ["factory", "airport", "port"]
        if not structure_types:
            return None
        structure_type = random.choice(structure_types)
        cost = {
            "factory": self.FACTORY_COST,
            "airport": self.AIRPORT_COST,
            "port": self.PORT_COST,
        }[structure_type]
        target = self.choose_regular_ai_development_target(candidates, player)
        return cost, lambda terr=target, structure_type=structure_type: self.add_industrial_structure(terr.id, structure_type)

    def choose_regular_ai_development_target(self, candidates: List[Territory], player: int) -> Territory:
        candidate_ids = {terr.id for terr in candidates}
        nation_component = self.find_player_nation_development_component(player)
        if nation_component is not None:
            nation_pool = [terr for terr in candidates if terr.id in nation_component]
            if nation_pool:
                candidates = nation_pool
                candidate_ids = {terr.id for terr in candidates}
        capital_id = self.get_active_regular_capital_id_for_player(player)
        if capital_id is not None and capital_id in candidate_ids:
            for terr in candidates:
                if terr.id == capital_id:
                    return terr
        return max(candidates, key=lambda terr: (len(terr.neighbors), terr.regiments, random.random()))

    def choose_regular_ai_university_target(self, candidates: List[Territory], player: int) -> Territory:
        nation_component = self.find_player_nation_development_component(player)
        if nation_component is not None:
            nation_pool = [terr for terr in candidates if terr.id in nation_component]
            if nation_pool:
                candidates = nation_pool
        capital_id = self.get_active_regular_capital_id_for_player(player)
        non_capital_candidates = [terr for terr in candidates if terr.id != capital_id]
        pool = non_capital_candidates or candidates
        return max(pool, key=lambda terr: (len(terr.neighbors), terr.regiments, random.random()))

    def find_regular_ai_mercenary_purchase(self, player: int, owned: List[Territory]):
        quantity = self.player_money[player] // self.MERCENARY_COST
        if quantity <= 0:
            return None
        return quantity * self.MERCENARY_COST, lambda quantity=quantity, owned=list(owned): self.add_regular_ai_mercenaries(owned, quantity)

    def add_regular_ai_mercenaries(self, owned: List[Territory], quantity: int) -> None:
        active_owned = [terr for terr in owned if 0 <= terr.id < len(self.territories) and self.territories[terr.id].owner == terr.owner]
        pool = active_owned or owned
        if not pool:
            return
        for _ in range(max(0, quantity)):
            random.choice(pool).regiments += 1

    def execute_commercial_city_economic_actions(self, player: int) -> int:
        return moteur_regles.execute_commercial_city_economic_actions(self, player)

    def find_next_commercial_city_purchase(self, player: int):
        if not self.is_commercial_city_player(player):
            return None
        owned = [terr for terr in self.territories if terr.owner == player]
        if not owned:
            return None
        owned.sort(key=lambda terr: terr.id)
        capital_id = self.get_commercial_city_capital_id(player)
        if capital_id is None:
            return None
        capital = self.territories[capital_id]

        # Ordre d'achat CC : capitale d'abord, puis diversification industrielle
        # sur les territoires acquis avant de continuer l'expansion. Le tout pour
        # satisfaire la future definition de nation, car le droit constitutionnel
        # adore apparaitre au milieu d'une partie.
        if capital.id not in self.fortress_territory_ids:
            return self.FORTRESS_COST, lambda terr=capital: self.add_commercial_city_fortress(terr.id)

        if self.get_industrial_structure_count(capital.id) == 0:
            structure_type = random.choice(["factory", "airport", "port"])
            cost = {
                "factory": self.FACTORY_COST,
                "airport": self.AIRPORT_COST,
                "port": self.PORT_COST,
            }[structure_type]
            return cost, lambda terr=capital, structure_type=structure_type: self.add_industrial_structure(terr.id, structure_type)

        if not self.has_temple(capital.id):
            return self.TEMPLE_COST, lambda terr=capital: self.add_temple(terr.id)

        if self.get_cultural_center_count(capital.id) < 1 and self.can_add_cultural_center(capital.id):
            return self.CULTURAL_CENTER_COST, lambda terr=capital: self.add_cultural_center(terr.id, age=0)

        if self.can_add_university(capital.id):
            return self.UNIVERSITY_COST, lambda terr=capital: self.add_university(terr.id)

        missing_industries = self.get_missing_player_industrial_types(player)
        if missing_industries:
            industrial_candidates = [terr for terr in owned if self.get_industrial_structure_count(terr.id) == 0]
            if industrial_candidates:
                structure_type = random.choice(missing_industries)
                cost = {
                    "factory": self.FACTORY_COST,
                    "airport": self.AIRPORT_COST,
                    "port": self.PORT_COST,
                }[structure_type]
                target = self.choose_regular_ai_development_target(industrial_candidates, player)
                return cost, lambda terr=target, structure_type=structure_type: self.add_industrial_structure(terr.id, structure_type)

        candidates = [
            terr for terr in self.territories
            if terr.owner != player
            and terr.id not in self.golden_territory_ids
            and not self.is_commercial_city_capital(terr.id)
            and not self.is_any_capital_territory(terr.id)
            and self.can_commercial_city_gain_territory(player, terr.id)
        ]
        if not candidates:
            return None
        terr = random.choice(candidates)
        cost = max(1, self.calculate_corruption_cost(terr, attacker=player)[0])
        return cost, lambda terr=terr: self.transfer_territory_to_commercial_city(terr.id, player)

    def find_next_commercial_city_industrial_purchase(self, owned: List[Territory]):
        # Ancienne diversification multi-territoires des CC : conservee comme no-op pour
        # compatibilite interne, mais la nouvelle regle limite l'achat industriel a la capitale.
        return None

    def add_commercial_city_fortress(self, territory_id: int) -> None:
        self.fortress_territory_ids.add(territory_id)
        self.fortress_capture_counts[territory_id] = 0

    def transfer_territory_to_commercial_city(self, territory_id: int, player: int) -> None:
        if not (0 <= territory_id < len(self.territories)):
            return
        if not self.can_commercial_city_gain_territory(player, territory_id):
            return
        previous_owner = self.territories[territory_id].owner
        self.sanctuary_territory_ids.discard(territory_id)
        self.submitted_territory_ids.discard(territory_id)
        self.submitted_territory_overlords.pop(territory_id, None)
        self.submitted_territory_created_turns.pop(territory_id, None)
        self.vassal_territory_overlords.pop(territory_id, None)
        self.vassal_territory_created_turns.pop(territory_id, None)
        self.vassal_players.pop(territory_id, None)
        self.territories[territory_id].owner = player
        self.enforce_commercial_city_cultural_center_limit(player)
        if previous_owner >= 0 and not any(t.owner == previous_owner for t in self.territories):
            self.mark_eliminated_player_if_human(previous_owner)
            self.refresh_eliminated_human_players()
        self.refresh_last_stand_bonus_state()


    def is_colonized_player(self, player: int) -> bool:
        return False

    def calculate_colonization_cost(self, target_player: int) -> int:
        return 0

    def remove_player_economic_structures(self, player: int) -> int:
        return 0

    def get_colonized_development_component(self, player: int) -> list[int]:
        return []

    def choose_colonized_development_target(self, player: int, predicate) -> Optional[Territory]:
        return None

    def player_has_colonization_completion_structures(self, player: int) -> bool:
        return False

    def find_next_colonized_purchase(self, player: int):
        return None

    def execute_colonized_economic_actions(self, player: int) -> list[str]:
        return []

    def choose_decolonization_capital(self, player: int) -> Optional[Territory]:
        return None

    def is_valid_decolonization_transfer_target(self, territory_id: int, player: int) -> bool:
        return False

    def grant_decolonization_territories(self, player: int, target_total: int = 10) -> int:
        return 0

    def decolonize_player(self, player: int) -> Optional[str]:
        return None

    def apply_colonization(self, colonizer: int, target_player: int) -> str:
        return "Colonisation supprimee."

    def execute_shop_colonize_player(self, terr: Territory) -> None:
        self.show_message("Colonisation supprimee : plus aucun joueur ne peut coloniser un autre joueur.", 2600)


    def build_replay_snapshot(self, label: str = "") -> dict:
        return {
            "turn": int(self.turn),
            "player": int(self.current_player),
            "label": str(label),
            "owners": [int(territory.owner) for territory in self.territories],
            "regiments": [int(territory.regiments) for territory in self.territories],
            "reinforcement_bonuses": [int(territory.reinforcement_bonus) for territory in self.territories],
            "precious_mines": sorted(int(tid) for tid in self.precious_mineral_mine_ids),
            "wonders": {str(kind): int(tid) for kind, tid in self.wonder_territories.items()},
            "fortresses": sorted(int(tid) for tid in self.fortress_territory_ids),
            "factories": sorted(int(tid) for tid in self.factory_territory_ids),
            "airports": sorted(int(tid) for tid in self.airport_territory_ids),
            "ports": sorted(int(tid) for tid in self.port_territory_ids),
            "cultural_centers": sorted(int(tid) for tid in self.cultural_center_ages),
            "universities": sorted(int(tid) for tid in self.university_territory_ids),
            "temples": sorted(int(tid) for tid in getattr(self, "temple_territory_ids", set())),
            "sanctuaries": sorted(int(tid) for tid in self.sanctuary_territory_ids),
            "submitted": sorted(int(tid) for tid in getattr(self, "submitted_territory_ids", set())),
            "capitals": {str(player): int(tid) for player, tid in self.player_capital_ids.items()},
            "commercial_capitals": {str(player): int(tid) for player, tid in self.commercial_city_capital_ids.items()},
            "commercial_players": sorted(int(player) for player in self.commercial_city_players),
            "nation_players": sorted(int(player) for player in self.nation_players),
            "religious_influence": {str(tid): int(religion_id) for tid, religion_id in self.religious_influence.items()},
            "religion_holy_sites": {str(religion_id): int(tid) for religion_id, tid in self.religion_holy_sites.items()},
            "religion_foundation_turns": {str(religion_id): int(turn) for religion_id, turn in self.religion_foundation_turns.items()},
            "religion_last_spread_turns": {str(religion_id): int(turn) for religion_id, turn in self.religion_last_spread_turns.items()},
            "money": {str(player): int(value) for player, value in self.player_money.items()},
            "science": {str(player): int(value) for player, value in self.player_science.items()},
            "bridges": [
                {
                    "a": int(a),
                    "b": int(b),
                    "start": list(self.bridge_link_points[(a, b)][0]),
                    "end": list(self.bridge_link_points[(a, b)][1]),
                    "fragile": (a, b) in self.fragile_bridge_links,
                }
                for a, b in sorted(self.bridge_links)
                if (a, b) in self.bridge_link_points
            ],
        }

    def replay_snapshot_signature(self, snapshot: dict) -> tuple:
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

    def record_replay_snapshot(self, label: str = "", force: bool = False) -> None:
        if not self.territories:
            return
        snapshot = self.build_replay_snapshot(label)
        if self.replay_history and not force:
            previous = self.replay_history[-1]
            if self.replay_snapshot_signature(previous) == self.replay_snapshot_signature(snapshot):
                if label:
                    previous["label"] = label
                    previous["turn"] = int(self.turn)
                    previous["player"] = int(self.current_player)
                return
        self.replay_history.append(snapshot)
        if len(self.replay_history) > self.MAX_REPLAY_SNAPSHOTS:
            first = self.replay_history[0]
            self.replay_history = [first] + self.replay_history[-(self.MAX_REPLAY_SNAPSHOTS - 1):]

    def apply_replay_snapshot(self, snapshot: dict) -> None:
        owners = snapshot.get("owners", [])
        regiments = snapshot.get("regiments", [])
        if len(owners) != len(self.territories) or len(regiments) != len(self.territories):
            return
        for index, territory in enumerate(self.territories):
            territory.owner = int(owners[index])
            territory.regiments = max(0, int(regiments[index]))
        reinforcement_bonuses = snapshot.get("reinforcement_bonuses", [])
        if len(reinforcement_bonuses) == len(self.territories):
            for index, territory in enumerate(self.territories):
                territory.reinforcement_bonus = max(1, int(reinforcement_bonuses[index]))
        self.precious_mineral_mine_ids = set(int(tid) for tid in snapshot.get("precious_mines", []))
        self.wonder_territories = {str(kind): int(tid) for kind, tid in snapshot.get("wonders", {}).items()}
        self.current_player = int(snapshot.get("player", self.current_player))
        self.turn = max(1, int(snapshot.get("turn", self.turn)))
        self.fortress_territory_ids = set(int(tid) for tid in snapshot.get("fortresses", []))
        self.factory_territory_ids = set(int(tid) for tid in snapshot.get("factories", []))
        self.industry_territory_ids = set(self.factory_territory_ids)
        self.airport_territory_ids = set(int(tid) for tid in snapshot.get("airports", []))
        self.port_territory_ids = set(int(tid) for tid in snapshot.get("ports", []))
        cultural_ids = set(int(tid) for tid in snapshot.get("cultural_centers", []))
        self.cultural_center_ages = {tid: self.cultural_center_ages.get(tid, [0]) or [0] for tid in cultural_ids}
        self.university_territory_ids = set(int(tid) for tid in snapshot.get("universities", []))
        self.temple_territory_ids = set(int(tid) for tid in snapshot.get("temples", []))
        self.sanctuary_territory_ids = set(int(tid) for tid in snapshot.get("sanctuaries", []))
        self.submitted_territory_ids = set(int(tid) for tid in snapshot.get("submitted", []))
        self.player_capital_ids = {int(player): int(tid) for player, tid in snapshot.get("capitals", {}).items()}
        self.commercial_city_capital_ids = {
            int(player): int(tid) for player, tid in snapshot.get("commercial_capitals", {}).items()
        }
        self.commercial_city_players = set(int(player) for player in snapshot.get("commercial_players", []))
        self.nation_players = set(int(player) for player in snapshot.get("nation_players", []))
        self.bridge_links = set()
        self.fragile_bridge_links = set()
        self.bridge_link_points = {}
        for item in snapshot.get("bridges", []):
            try:
                key = tuple(sorted((int(item["a"]), int(item["b"]))))
                start = (int(item["start"][0]), int(item["start"][1]))
                end = (int(item["end"][0]), int(item["end"][1]))
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            self.bridge_links.add(key)
            self.bridge_link_points[key] = (start, end)
            if bool(item.get("fragile", False)):
                self.fragile_bridge_links.add(key)
        self.recompute_neighbors_from_grid()
        self.religious_influence = {
            int(tid): int(religion_id) for tid, religion_id in snapshot.get("religious_influence", {}).items()
        }
        self.religion_holy_sites = {
            int(religion_id): int(tid) for religion_id, tid in snapshot.get("religion_holy_sites", {}).items()
        }
        self.religion_foundation_turns = {
            int(religion_id): int(turn) for religion_id, turn in snapshot.get("religion_foundation_turns", {}).items()
        }
        self.religion_last_spread_turns = {
            int(religion_id): int(turn) for religion_id, turn in snapshot.get("religion_last_spread_turns", {}).items()
        }
        self.player_money = {int(player): int(value) for player, value in snapshot.get("money", {}).items()}
        self.player_science = {int(player): int(value) for player, value in snapshot.get("science", {}).items()}
        self.selected_source = None
        self.selected_target = None

    def get_winner_statistics(self, winner: int) -> dict:
        owned = [territory for territory in self.territories if territory.owner == winner]
        owned_ids = {territory.id for territory in owned}
        religion_id = self.religion_founders.get(winner)
        religion_name = self.get_religion_name(religion_id) if religion_id is not None else "Aucune"
        religion_influence = (
            sum(1 for value in self.religious_influence.values() if value == religion_id)
            if religion_id is not None else 0
        )
        structures = {
            "forteresses": len(owned_ids & self.fortress_territory_ids),
            "industries": sum(self.get_industrial_structure_count(tid) for tid in owned_ids),
            "centres culturels": sum(len(self.cultural_center_ages.get(tid, [])) for tid in owned_ids),
            "universites": len(owned_ids & self.university_territory_ids),
            "temples": len(owned_ids & self.temple_territory_ids),
        }
        ranking = []
        players = sorted({territory.owner for territory in self.territories if territory.owner >= 0} | set(range(self.num_players)))
        for player in players:
            territories = [territory for territory in self.territories if territory.owner == player]
            ranking.append({
                "player": player,
                "territories": len(territories),
                "regiments": sum(max(0, territory.regiments) for territory in territories),
                "money": self.get_player_money(player),
            })
        ranking.sort(key=lambda item: (item["territories"], item["regiments"], item["money"]), reverse=True)
        return {
            "winner": winner,
            "reason": self.last_victory_reason or "condition de victoire atteinte",
            "turn": int(self.turn),
            "kind": self.get_player_kind_label(winner),
            "territories": len(owned),
            "territory_total": len(self.territories),
            "regiments": sum(max(0, territory.regiments) for territory in owned),
            "money": self.get_player_money(winner),
            "culture": self.calculate_player_culture(winner),
            "science": self.get_player_science(winner),
            "structures": structures,
            "religion": religion_name,
            "religion_influence": religion_influence,
            "holy_sites": self.get_controlled_holy_site_count(winner),
            "ranking": ranking[:6],
            "events": list(self.recent_major_events[-5:]),
        }

    def initialize_confetti(self) -> None:
        colors = [
            (244, 208, 63), (236, 112, 99), (88, 214, 141),
            (84, 153, 199), (165, 105, 189), (245, 245, 245),
        ]
        self.confetti_particles = []
        for _ in range(150):
            self.confetti_particles.append({
                "x": random.uniform(0, self.WIDTH),
                "y": random.uniform(-self.HEIGHT, 0),
                "vx": random.uniform(-0.8, 0.8),
                "vy": random.uniform(1.8, 4.8),
                "size": random.randint(3, 8),
                "angle": random.uniform(0.0, math.tau),
                "spin": random.uniform(-0.12, 0.12),
                "color": random.choice(colors),
            })

    def update_confetti(self) -> None:
        for particle in self.confetti_particles:
            particle["x"] += particle["vx"]
            particle["y"] += particle["vy"]
            particle["angle"] += particle["spin"]
            if particle["y"] > self.HEIGHT + 12:
                particle["x"] = random.uniform(0, self.WIDTH)
                particle["y"] = random.uniform(-180, -10)

    def draw_confetti(self) -> None:
        for particle in self.confetti_particles:
            x = int(particle["x"])
            y = int(particle["y"])
            size = int(particle["size"])
            angle = particle["angle"]
            dx = int(math.cos(angle) * size)
            dy = int(math.sin(angle) * size)
            pygame.draw.line(self.screen, particle["color"], (x - dx, y - dy), (x + dx, y + dy), 3)

    def declare_victory(self, winner: int) -> None:
        self.current_player = winner
        self.victory_winner = winner
        self.record_replay_snapshot(f"Victoire de J{winner + 1}", force=True)
        self.victory_summary = self.get_winner_statistics(winner)
        self.replay_restore_state = None
        self.replay_paused = False
        self.replay_finished = False
        self.initialize_confetti()
        self.phase = "game_over"
        self.ai_state = "idle"
        self.show_message(f"Victoire du joueur {winner + 1} !", 8000)

    def start_replay(self) -> None:
        if len(self.replay_history) < 2:
            self.show_message("Replay indisponible : pas assez d'instantanes enregistres.", 2600)
            return
        self.replay_restore_state = self.build_replay_snapshot("Etat final")
        self.replay_index = 0
        self.replay_paused = False
        self.replay_finished = False
        self.phase = "replay"
        self.apply_replay_snapshot(self.replay_history[0])
        self.replay_next_frame_time = pygame.time.get_ticks() + self.REPLAY_FRAME_DELAY_MS

    def update_replay(self) -> None:
        if self.replay_paused or self.replay_finished or not self.replay_history:
            return
        now = pygame.time.get_ticks()
        if now < self.replay_next_frame_time:
            return
        self.replay_index = min(self.replay_index + 1, len(self.replay_history) - 1)
        self.apply_replay_snapshot(self.replay_history[self.replay_index])
        self.replay_next_frame_time = now + self.REPLAY_FRAME_DELAY_MS
        if self.replay_index >= len(self.replay_history) - 1:
            self.replay_finished = True
            self.replay_paused = True

    def toggle_replay_pause(self) -> None:
        if self.replay_finished:
            self.replay_index = 0
            self.apply_replay_snapshot(self.replay_history[0])
            self.replay_finished = False
        self.replay_paused = not self.replay_paused
        self.replay_next_frame_time = pygame.time.get_ticks() + self.REPLAY_FRAME_DELAY_MS

    def stop_replay(self) -> None:
        if self.replay_restore_state is not None:
            self.apply_replay_snapshot(self.replay_restore_state)
        if self.victory_winner is not None:
            self.current_player = self.victory_winner
        self.phase = "game_over"
        self.replay_paused = False
        self.replay_finished = False
        self.replay_restore_state = None

    def record_major_event(self, message: str) -> None:
        if not message:
            return
        clean = " ".join(str(message).split())
        if not clean:
            return
        if self.recent_major_events and self.recent_major_events[-1] == clean:
            return
        self.recent_major_events.append(clean)
        self.recent_major_events = self.recent_major_events[-8:]

        if self.phase not in ("playing", "shopping"):
            return
        human_players = [
            player
            for player in self.get_active_players()
            if self.is_human_player_id(player)
        ]
        immediate_player = (
            self.current_player
            if not self.collecting_between_turn_events
            and self.current_player in human_players
            else None
        )
        if immediate_player is not None:
            self.queue_major_event_modal("Evenement important", [clean])
        for player in human_players:
            if player == immediate_player:
                continue
            pending = self.pending_major_events_for_humans.setdefault(player, [])
            if not pending or pending[-1] != clean:
                pending.append(clean)
                self.pending_major_events_for_humans[player] = pending[-20:]

    def sanitize_major_event_modal(self, modal: object) -> Optional[dict]:
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

    def queue_major_event_modal(self, title: str, events: list[str]) -> None:
        modal = self.sanitize_major_event_modal({"title": title, "events": events})
        if modal is None:
            return
        if self.major_event_modal is None:
            self.major_event_modal = modal
        else:
            self.major_event_modal_queue.append(modal)

    def close_major_event_modal(self) -> None:
        if self.major_event_modal_queue:
            self.major_event_modal = self.major_event_modal_queue.pop(0)
        else:
            self.major_event_modal = None

    def draw_major_event_modal(self) -> None:
        modal = self.major_event_modal
        if modal is None:
            return
        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((5, 8, 12, 185))
        self.screen.blit(overlay, (0, 0))

        panel_width = min(900, self.WIDTH - 100)
        panel_height = min(520, self.HEIGHT - 100)
        panel = pygame.Rect(
            (self.WIDTH - panel_width) // 2,
            (self.HEIGHT - panel_height) // 2,
            panel_width,
            panel_height,
        )
        pygame.draw.rect(self.screen, (27, 35, 45), panel, border_radius=14)
        pygame.draw.rect(self.screen, (244, 208, 63), panel, width=3, border_radius=14)

        title = self.font_large.render(modal["title"], True, (244, 208, 63))
        self.screen.blit(title, title.get_rect(centerx=panel.centerx, top=panel.top + 24))
        pygame.draw.line(
            self.screen,
            (125, 135, 145),
            (panel.left + 30, panel.top + 76),
            (panel.right - 30, panel.top + 76),
            1,
        )

        y = panel.top + 96
        content_bottom = panel.bottom - 72
        events = modal.get("events", [])
        for index, event_text in enumerate(events):
            prefix = "- " if len(events) > 1 else ""
            for wrapped_line in self.wrap_text(prefix + event_text, self.font_medium, panel.width - 76):
                if y + 28 > content_bottom:
                    ellipsis = self.font_medium.render("...", True, (236, 240, 241))
                    self.screen.blit(ellipsis, (panel.left + 38, y))
                    y = content_bottom
                    break
                rendered = self.font_medium.render(wrapped_line, True, (236, 240, 241))
                self.screen.blit(rendered, (panel.left + 38, y))
                y += 30
            if y >= content_bottom:
                break
            if index < len(events) - 1:
                y += 8

        footer_text = "Appuyez sur Echap pour afficher l'evenement suivant" if self.major_event_modal_queue else "Appuyez sur Echap pour fermer"
        footer = self.font_small.render(footer_text, True, (180, 190, 200))
        self.screen.blit(footer, footer.get_rect(centerx=panel.centerx, bottom=panel.bottom - 22))

    def wrap_text(self, text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        words = str(text).split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = current + " " + word
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def get_player_kind_label(self, player: int) -> str:
        if self.is_colonized_player(player):
            return "colonise"
        cold_war_camp = self.get_cold_war_camp(player)
        if cold_war_camp is not None and player != cold_war_camp:
            return f"IA bloc J{cold_war_camp + 1}"
        if self.is_nation_player(player):
            base = "nation IA" if self.is_ai_player(player) else "nation humaine"
            if self.is_commercial_city_player(player):
                base += " (ancienne cite commercante en transition)"
            return base
        if self.is_commercial_city_player(player):
            return "IA cite commercante agressive"
        if self.is_ai_player(player):
            return "IA " + self.get_ai_profile_label(player, include_current=True)
        return "humain"

    def get_next_fixed_geopolitical_events(self) -> list[str]:
        events: list[str] = []
        next_empire_turn = ((self.turn // 10) + 1) * 10
        if next_empire_turn % 40 == 0:
            events.append(f"Tour {next_empire_turn}: revolution generale programmee")
            next_after_revolution = next_empire_turn + 10
            empire_index = next_after_revolution // 10 - next_after_revolution // 40
            label = "trahison" if empire_index % 2 == 0 else "revolte"
            events.append(f"Tour {next_after_revolution}: evenement d'empire programme ({label})")
        else:
            empire_index = next_empire_turn // 10 - next_empire_turn // 40
            label = "trahison" if empire_index % 2 == 0 else "revolte"
            events.append(f"Tour {next_empire_turn}: evenement d'empire programme ({label})")
            next_revolution_turn = ((self.turn // 40) + 1) * 40
            events.append(f"Tour {next_revolution_turn}: prochaine revolution generale")
        return events[:3]

    def get_geopolitical_alliance_lines(self) -> list[str]:
        self.cleanup_expired_alliances()
        lines: list[str] = []
        for (human, ai), expires_turn in sorted(self.active_alliances.items()):
            start_turn = self.alliance_start_turns.get((human, ai), max(1, expires_turn - self.ALLIANCE_DURATION_TURNS))
            remaining = max(0, expires_turn - self.turn)
            soon = " - expire bientot" if remaining <= 2 else ""
            lines.append(
                f"J{human + 1} <-> J{ai + 1}: alliance defensive, tour {start_turn} a {expires_turn}, reste {remaining}{soon}"
            )
        for (human, ai), (target, expires_turn) in sorted(self.active_offensive_alliances.items()):
            start_turn = self.offensive_alliance_start_turns.get((human, ai), max(1, expires_turn - self.ALLIANCE_DURATION_TURNS))
            remaining = max(0, expires_turn - self.turn)
            soon = " - expire bientot" if remaining <= 2 else ""
            lines.append(
                f"J{human + 1} + J{ai + 1} contre J{target + 1}: alliance offensive, tour {start_turn} a {expires_turn}, reste {remaining}{soon}"
            )
        for (ai_a, ai_b), expires_turn in sorted(self.active_ai_alliances.items()):
            start_turn = self.ai_alliance_start_turns.get(
                (ai_a, ai_b), max(1, expires_turn - self.ALLIANCE_DURATION_TURNS)
            )
            remaining = max(0, expires_turn - self.turn)
            soon = " - expire bientot" if remaining <= 2 else ""
            lines.append(
                f"J{ai_a + 1} <-> J{ai_b + 1}: alliance IA, tour {start_turn} a {expires_turn}, reste {remaining}{soon}"
            )
        if self.is_cold_war_active() and getattr(self, "cold_war_nations", None):
            blocs = []
            for nation in self.cold_war_nations or ():
                allies = sorted(
                    player for player, camp in getattr(self, "cold_war_alliances", {}).items()
                    if camp == nation and any(terr.owner == player for terr in self.territories)
                )
                ally_label = ", allies IA " + ", ".join(f"J{player + 1}" for player in allies) if allies else ""
                blocs.append(f"bloc J{nation + 1}{ally_label}")
            lines.append("Guerre froide: " + " contre ".join(blocs))
        if getattr(self, "final_duel_active", False) and getattr(self, "final_duel_champions", None):
            champions = list(self.final_duel_champions or [])
            blocs = []
            for champion in champions:
                allies = sorted(
                    player for player, bloc in getattr(self, "final_duel_alliances", {}).items()
                    if bloc == champion and player != champion
                )
                ally_label = ", allies " + ", ".join(f"J{player + 1}" for player in allies) if allies else ""
                blocs.append(f"bloc J{champion + 1}{ally_label}")
            lines.append("Finale entre champions: " + " contre ".join(blocs))
        for a, b in sorted(getattr(self, "nation_wars", set())):
            lines.append(f"J{a + 1} x J{b + 1}: guerre entre nations")
        return lines or ["Aucune alliance active"]

    def get_geopolitical_status_lines(self) -> list[str]:
        active_players = self.get_active_players()
        human_active = [player for player in active_players if self.is_human_player_id(player) and not self.is_ai_player(player)]
        human_eliminated = sorted(
            player for player in self.eliminated_human_players
            if self.is_human_player_id(player) and not any(terr.owner == player for terr in self.territories)
        )
        new_ai = sorted(player for player in active_players if player >= self.initial_num_players and self.is_ai_player(player))
        onu_count = sum(1 for terr in self.territories if terr.owner == self.onu_player_id or self.is_sanctuary_territory(terr.id))
        golden_summary: dict[int, int] = {}
        for tid in self.golden_territory_ids:
            if 0 <= tid < len(self.territories):
                owner = self.territories[tid].owner
                if owner >= 0:
                    golden_summary[owner] = golden_summary.get(owner, 0) + 1
        golden_text = ", ".join(f"J{player + 1}={count}" for player, count in sorted(golden_summary.items())) or "aucun joueur"
        cold_war_line = "Guerre froide: inactive"
        if self.is_cold_war_active() and getattr(self, "cold_war_nations", None):
            cold_war_line = "Guerre froide: " + " contre ".join(f"J{p + 1}" for p in self.cold_war_nations or ())
        return [
            f"Joueurs actifs: {len(active_players)} ({len(human_active)} humain(s), {sum(1 for p in active_players if self.is_ai_player(p))} IA)",
            cold_war_line,
            "Humains actifs: " + (", ".join(f"J{p + 1}" for p in human_active) or "aucun"),
            "Humains eliminés mais presents au depart: " + (", ".join(f"J{p + 1}" for p in human_eliminated) or "aucun"),
            "Nouvelles IA apparues: " + (", ".join(f"J{p + 1}" for p in new_ai) or "aucune"),
            f"ONU: {onu_count} territoire(s) | Territoires dores controles: {golden_text}",
            "Cites Commercantes: immunisees contre sedition, revolte, revolution et trahison",
        ]

    def get_geopolitical_player_color(self, player: int) -> tuple[int, int, int]:
        base = self.PLAYER_COLORS[player % len(self.PLAYER_COLORS)]
        # Les couleurs de carte trop sombres deviennent illisibles sur le panneau.
        # On les eclaircit juste assez pour que le tableau ne se transforme pas en test de vue.
        luminance = 0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2]
        if luminance >= 125:
            return base
        factor = 0.35
        return tuple(min(255, int(channel + (255 - channel) * factor)) for channel in base)

    def get_geopolitical_power_rows(self) -> list[tuple[int, list[str]]]:
        rows: list[tuple[int, list[str]]] = []
        for player in self.get_active_players():
            territories = self.count_player_territories(player)
            money = self.get_player_money(player)
            income = self.calculate_player_income(player)
            culture = self.calculate_player_culture(player)
            science = self.get_player_science(player)
            science_income = self.calculate_player_science_income(player)
            reinforcement = self.get_empire_reinforcement_preview(player)
            structures = self.get_empire_structure_counts(player)
            pf = "oui" if player in self.last_stand_bonus_players or self.is_commercial_city_player(player) else "non"
            golden_count = sum(
                1
                for tid in self.golden_territory_ids
                if 0 <= tid < len(self.territories) and self.territories[tid].owner == player
            )
            religion_ids: list[int] = []
            founded_religion_id = getattr(self, "religion_founders", {}).get(player)
            if founded_religion_id is not None:
                religion_ids.append(founded_religion_id)
            if self.player_controls_wonder(player, "elyrion_sanctuary"):
                religion_ids.append(self.WONDER_RELIGION_ID)
            religion_names = "/".join(self.get_religion_name(religion_id) for religion_id in religion_ids)
            religion_summary = (
                f"{religion_names} ({self.get_national_religion_influenced_territory_count(player)})"
                if religion_names else "aucune"
            )
            wonder_names = [
                self.get_wonder_name(wonder_type)
                for wonder_type in self.WONDER_DEFINITIONS
                if self.player_controls_wonder(player, wonder_type)
            ]
            wonder_summary = ", ".join(wonder_names) if wonder_names else "aucune"
            asset_summary = (
                f"PF:{pf} D:{golden_count} +3:{structures['ultra']} "
                f"+5:{structures['bonus_5']} M:{structures['precious_mines']}"
            )
            rows.append((player, [
                f"J{player + 1}",
                self.get_player_kind_label(player),
                str(territories),
                str(money),
                f"+{income}",
                str(culture),
                f"{science} (+{science_income})",
                f"{reinforcement['regiments']}/{reinforcement['regiment_limit']}",
                f"+{reinforcement['total']}",
                religion_summary,
                str(self.get_controlled_holy_site_count(player)),
                asset_summary,
                wonder_summary,
            ]))
        return rows

    def get_geopolitical_power_page_capacity(self) -> int:
        rect = self.geopolitical_panel_rect
        row_h = 26
        table_top = rect.y + 96
        reserved_bottom = 60
        available = max(0, rect.bottom - reserved_bottom - table_top)
        table_gap = 14
        # La situation detaillee utilise deux tableaux superposes, chacun avec son en-tete.
        # Le nombre de joueurs par page doit donc reserver deux lignes par joueur.
        return max(1, ((available - table_gap) // (row_h * 2)) - 1)

    def get_geopolitical_power_page_count(self) -> int:
        row_count = len(self.get_geopolitical_power_rows())
        capacity = self.get_geopolitical_power_page_capacity()
        return max(1, math.ceil(row_count / capacity))

    def get_geopolitical_info_sections(self) -> list[tuple[str, list[str], bool]]:
        recent = self.recent_major_events[-8:] if self.recent_major_events else ["Aucun evenement majeur enregistre"]
        return [
            ("Synthese", self.get_geopolitical_status_lines(), False),
            ("Alliances", self.get_geopolitical_alliance_lines(), False),
            ("Evenements a venir", self.get_next_fixed_geopolitical_events(), False),
            ("Evenements recents", recent, True),
        ]

    def get_geopolitical_info_pages(self) -> list[list[tuple[str, str, bool]]]:
        rect = self.geopolitical_panel_rect
        max_width = rect.width - 48
        top_y = rect.y + 62
        reserved_bottom = 54
        available_height = max(72, rect.bottom - reserved_bottom - top_y)
        pages: list[list[tuple[str, str, bool]]] = []
        current: list[tuple[str, str, bool]] = []
        used_height = 0

        def item_height(kind: str, text: str) -> int:
            if kind == "section":
                return 34
            return max(1, len(self.wrap_text(text, self.font_small, max_width))) * 18

        def add_item(kind: str, text: str, muted: bool = False) -> None:
            nonlocal current, used_height
            height = item_height(kind, text)
            if current and used_height + height > available_height:
                pages.append(current)
                current = []
                used_height = 0
            current.append((kind, text, muted))
            used_height += height

        for section_title, lines, muted in self.get_geopolitical_info_sections():
            if current and used_height + item_height("section", section_title) > available_height:
                pages.append(current)
                current = []
                used_height = 0
            add_item("section", section_title, False)
            for line in lines:
                add_item("line", "- " + line, muted)

        if current:
            pages.append(current)
        return pages or [[("line", "Aucune information geopolitique disponible", True)]]

    def get_geopolitical_panel_page_count(self) -> int:
        return self.get_geopolitical_power_page_count() + len(self.get_geopolitical_info_pages())

    def close_geopolitical_panel(self) -> None:
        page_count = self.get_geopolitical_panel_page_count()
        if self.geopolitical_panel_page + 1 < page_count:
            self.geopolitical_panel_page += 1
            return
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0

    def can_show_geopolitical_button(self) -> bool:
        return self.phase in ("playing", "shopping") and self.is_human_player_id(self.current_player) and not self.is_ai_player(self.current_player)

    def open_geopolitical_panel(self) -> None:
        if not self.can_show_geopolitical_button():
            return
        self.empire_panel_visible = False
        self.empire_panel_page = 0
        self.geopolitical_panel_visible = True
        self.geopolitical_panel_page = 0

    def can_show_empire_panel(self) -> bool:
        return self.can_show_geopolitical_button()

    def open_empire_panel(self) -> None:
        if not self.can_show_empire_panel():
            return
        self.pending_details_click_time = None
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0
        self.empire_panel_visible = True
        self.empire_panel_page = 0

    def close_empire_panel(self) -> None:
        page_count = len(self.get_empire_panel_pages(self.current_player))
        if self.empire_panel_page + 1 < page_count:
            self.empire_panel_page += 1
            return
        self.empire_panel_visible = False
        self.empire_panel_page = 0

    def toggle_hover_details(self) -> None:
        if not self.can_show_geopolitical_button():
            return
        self.hover_details_enabled = not self.hover_details_enabled
        state = "actives" if self.hover_details_enabled else "desactives"
        self.show_message(f"Details au survol {state}.", 1400)

    def handle_details_button_left_click(self) -> None:
        """Clic simple : details des territoires. Double-clic : tableau de bord."""
        if not self.can_show_empire_panel():
            self.pending_details_click_time = None
            return
        now = pygame.time.get_ticks()
        previous_click = self.pending_details_click_time
        if previous_click is not None and now - previous_click <= self.DETAILS_DOUBLE_CLICK_DELAY_MS:
            self.pending_details_click_time = None
            self.open_empire_panel()
            return
        self.pending_details_click_time = now

    def process_pending_details_button_click(self) -> None:
        """Execute le clic simple seulement quand le delai du double-clic est ecoule."""
        click_time = self.pending_details_click_time
        if click_time is None:
            return
        if pygame.time.get_ticks() - click_time <= self.DETAILS_DOUBLE_CLICK_DELAY_MS:
            return
        self.pending_details_click_time = None
        if self.can_show_geopolitical_button() and not self.empire_panel_visible:
            self.toggle_hover_details()

    def toggle_all_map_icons(self) -> None:
        current = getattr(self, "map_icon_view", "all" if getattr(self, "show_all_map_icons", False) else "fortress")
        order = ["fortress", "all", "religion"]
        try:
            next_mode = order[(order.index(current) + 1) % len(order)]
        except ValueError:
            next_mode = "fortress"
        self.map_icon_view = next_mode
        self.show_all_map_icons = next_mode == "all"
        labels = {
            "fortress": "forteresses seules",
            "all": "toutes les icones",
            "religion": "vue religion",
        }
        self.show_message(f"Vue carte : {labels[next_mode]}.", 1400)

    def get_empire_structure_counts(self, player: int) -> dict[str, int]:
        owned_ids = {terr.id for terr in self.territories if terr.owner == player}
        counts = {
            "fortresses": len(self.fortress_territory_ids & owned_ids),
            "factories": len(self.factory_territory_ids & owned_ids),
            "airports": len(self.airport_territory_ids & owned_ids),
            "ports": len(self.port_territory_ids & owned_ids),
            "cultural_centers": sum(self.get_cultural_center_count(tid) for tid in owned_ids),
            "universities": len(self.university_territory_ids & owned_ids),
            "temples": len(getattr(self, "temple_territory_ids", set()) & owned_ids),
            "ultra": sum(1 for tid in owned_ids if self.territories[tid].reinforcement_bonus == 3),
            "bonus_5": sum(1 for tid in owned_ids if self.territories[tid].reinforcement_bonus == 5),
            "precious_mines": len(self.precious_mineral_mine_ids & owned_ids),
            "golden": len(self.golden_territory_ids & owned_ids),
        }
        counts["total"] = sum(
            counts[key]
            for key in ("fortresses", "factories", "airports", "ports", "cultural_centers", "universities", "temples")
        )
        return counts

    def player_controls_bonus_5(self, player: int) -> bool:
        return any(
            terr.owner == player and terr.reinforcement_bonus == 5
            for terr in self.territories
        )

    def get_reinforcement_regiment_limit(self, player: int) -> int:
        if self.player_controls_bonus_5(player):
            return self.MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS_WITH_BONUS_5
        return self.MAX_REINFORCEMENT_ELIGIBLE_REGIMENTS

    def get_ai_reinforcement_bonus(self, player: int) -> int:
        if not self.is_ai_player(player):
            return 0
        bonus = 0
        for start_turn, stage_bonus in self.AI_REINFORCEMENT_BONUS_STAGES:
            if self.turn < start_turn:
                break
            bonus = stage_bonus
        return bonus

    def get_empire_reinforcement_preview(self, player: int) -> dict[str, int | bool]:
        owned = [terr for terr in self.territories if terr.owner == player]
        total_regiments = sum(max(0, terr.regiments) for terr in owned)
        regiment_limit = self.get_reinforcement_regiment_limit(player)
        eligible = total_regiments < regiment_limit
        controlled = len(owned)
        base = min(self.MAX_REINFORCEMENTS_PER_TURN, math.ceil(controlled / 3)) if controlled else 0
        ultra = sum(1 for terr in owned if terr.reinforcement_bonus == 3)
        ultra_bonus = ultra * 3
        bonus_5 = sum(1 for terr in owned if terr.reinforcement_bonus == 5)
        bonus_5_reinforcements = bonus_5 * 5
        religious_bonus = self.get_religious_reinforcement_bonus(player)
        ai_bonus = self.get_ai_reinforcement_bonus(player)
        total = base + ultra_bonus + bonus_5_reinforcements + religious_bonus + ai_bonus if eligible else 0
        return {
            "eligible": eligible,
            "regiments": total_regiments,
            "base": base,
            "ultra_bonus": ultra_bonus,
            "bonus_5": bonus_5,
            "bonus_5_reinforcements": bonus_5_reinforcements,
            "regiment_limit": regiment_limit,
            "religious_bonus": religious_bonus,
            "ai_bonus": ai_bonus,
            "total": total,
        }

    def get_empire_capital_lines(self, player: int) -> list[str]:
        lines: list[str] = []
        active_capital = self.get_active_regular_capital_id_for_player(player)
        original_capital = getattr(self, "player_capital_ids", {}).get(player)
        if active_capital is not None:
            territory = self.territories[active_capital]
            lines.append(f"Capitale: {territory.name} ({territory.regiments} regiments, revenu x{self.CAPITAL_INCOME_MULTIPLIER})")
        elif original_capital is not None and 0 <= original_capital < len(self.territories):
            territory = self.territories[original_capital]
            owner_label = "ONU" if territory.owner == self.onu_player_id else (f"J{territory.owner + 1}" if territory.owner >= 0 else "sans proprietaire")
            lines.append(f"Capitale perdue: {territory.name}, controlee par {owner_label}")
        else:
            lines.append("Capitale: aucune")

        tax_haven_ids = sorted(self.get_player_tax_haven_capital_ids(player))
        if tax_haven_ids:
            names = ", ".join(self.territories[tid].name for tid in tax_haven_ids if 0 <= tid < len(self.territories))
            lines.append(f"Paradis fiscal: actif sur {names or 'territoire inconnu'}")
        return lines

    def get_empire_nation_lines(self, player: int) -> list[str]:
        if player in getattr(self, "nation_players", set()):
            lines = [f"Nation active: revenus divises par {self.NATION_INCOME_DIVISOR}"]
            capital_id = self.get_active_regular_capital_id_for_player(player)
            if capital_id is None:
                start_turn = getattr(self, "nation_capital_loss_start_turns", {}).get(player)
                if start_turn is None:
                    remaining = self.NATION_CAPITAL_LOSS_DELAY_TURNS
                else:
                    remaining = max(0, self.NATION_CAPITAL_LOSS_DELAY_TURNS - (self.turn - start_turn))
                lines.append(f"ALERTE: aucune capitale active; perte du statut dans {remaining} tour(s) si rien ne change")
            else:
                lines.append("Capitale active: statut national securise")
            lines.append("Immunites nationales: revoltes, revolutions, seditions et corruption")
            return lines

        components = self.get_owned_components(player)
        if not components:
            return ["Aucun territoire: acces au statut de nation impossible"]

        capital_id = self.get_active_regular_capital_id_for_player(player)
        candidate = max(
            components,
            key=lambda component: (
                1 if len(component) >= self.NATION_MIN_TERRITORIES else 0,
                self.count_component_nation_structure_kinds(component),
                1 if capital_id in component else 0,
                len(component),
                -min(component),
            ),
        )
        candidate_set = set(candidate)
        requirements = [
            (len(candidate) >= self.NATION_MIN_TERRITORIES, f"{len(candidate)}/{self.NATION_MIN_TERRITORIES} territoires contigus"),
            (bool(self.fortress_territory_ids & candidate_set), "forteresse"),
            (bool(self.factory_territory_ids & candidate_set), "usine"),
            (bool(self.airport_territory_ids & candidate_set), "aeroport"),
            (bool(self.port_territory_ids & candidate_set), "port"),
            (bool(getattr(self, "temple_territory_ids", set()) & candidate_set), "temple"),
            (any(self.get_cultural_center_count(tid) > 0 for tid in candidate), "centre culturel"),
            (bool(self.university_territory_ids & candidate_set), "universite"),
            (capital_id is not None and capital_id in candidate_set, "capitale active dans ce bloc"),
        ]
        complete = all(ok for ok, _label in requirements)
        lines = [f"Bloc candidat: {len(candidate)} territoire(s) contigu(s)"]
        if complete:
            remaining = self.get_nation_qualification_remaining_turns(player)
            if player in getattr(self, "nation_qualification_start_turns", {}):
                lines.append(f"Conditions remplies et maintenues: encore {remaining} tour(s) avant de devenir une nation")
            else:
                lines.append(f"Conditions remplies: encore {remaining} tour(s) a maintenir a partir du prochain controle")
        else:
            missing = [label for ok, label in requirements if not ok]
            lines.append("Conditions manquantes dans le meme bloc: " + ", ".join(missing))
        achieved = [label for ok, label in requirements if ok]
        lines.append("Deja acquis dans ce bloc: " + ", ".join(achieved))
        return lines

    def get_empire_science_lines(self, player: int) -> list[str]:
        science = self.get_player_science(player)
        income = self.calculate_player_science_income(player)
        wonder_threshold = self.get_wonder_science_threshold(player)
        unlocked: list[str] = []
        if science >= self.SCIENCE_ONU_MANIPULATION_THRESHOLD:
            unlocked.append("manipulation ONU")
        if science >= wonder_threshold:
            unlocked.append("construction de merveilles")
        if science >= self.SCIENCE_BRIDGE_THRESHOLD:
            unlocked.append("construction et destruction de ponts")
        if science >= self.SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD:
            unlocked.append("integration paradis fiscal")
        if science >= self.SCIENCE_ATTACK_4_DICE_THRESHOLD:
            unlocked.append("attaque a 4 des")
        thresholds = [
            (self.SCIENCE_ONU_MANIPULATION_THRESHOLD, "manipulation ONU"),
            (wonder_threshold, "construction de merveilles"),
            (self.SCIENCE_BRIDGE_THRESHOLD, "construction et destruction de ponts"),
            (self.SCIENCE_TAX_HAVEN_INTEGRATION_THRESHOLD, "integration paradis fiscal"),
            (self.SCIENCE_ATTACK_4_DICE_THRESHOLD, "attaque a 4 des"),
        ]
        next_unlock = next(((threshold, label) for threshold, label in thresholds if science < threshold), None)
        lines = [f"Science: {science} point(s), +{income} par tour"]
        if self.player_controls_wonder(player, "atlas_observatory"):
            lines.append(f"Observatoire d'Atlas controle: science de base {self.get_base_player_science(player)}, science effective x2")
        lines.append("Pouvoirs acquis: " + (", ".join(unlocked) if unlocked else "aucun"))
        if next_unlock is not None:
            threshold, label = next_unlock
            lines.append(f"Prochain palier: {label} a {threshold} points (manque {threshold - science})")
        else:
            lines.append("Tous les pouvoirs scientifiques sont debloques")
        return lines

    def get_empire_religion_lines(self, player: int) -> list[str]:
        religion_ids: list[int] = []
        founded_religion_id = getattr(self, "religion_founders", {}).get(player)
        if founded_religion_id is not None:
            religion_ids.append(founded_religion_id)
        if self.player_controls_wonder(player, "elyrion_sanctuary"):
            religion_ids.append(self.WONDER_RELIGION_ID)
        temple_count = self.get_player_temple_count(player)
        if not religion_ids:
            used_regular_religions = {
                religion_id for religion_id in getattr(self, "religion_founders", {}).values()
                if religion_id < self.WONDER_RELIGION_ID
            }
            available = max(0, self.WONDER_RELIGION_ID - len(used_regular_religions))
            return [
                f"Religion nationale: aucune; temples controles: {temple_count}",
                f"Religions encore fondables: {available}",
            ]

        religion_id = religion_ids[-1]
        religion_labels = ", ".join(
            f"{self.get_religion_name(active_religion_id)} ({self.get_religion_symbol(active_religion_id)})"
            for active_religion_id in religion_ids
        )
        national_influence = self.get_national_religion_influenced_territory_count(player)
        world_influence = sum(1 for rid in getattr(self, "religious_influence", {}).values() if rid in religion_ids)
        income_bonus = self.get_religious_income_bonus(player)
        reinforcement_bonus = self.get_religious_reinforcement_bonus(player)
        holy_site_id = getattr(self, "religion_holy_sites", {}).get(religion_id)
        holy_site_line = "Lieu sacre: inconnu"
        if holy_site_id is not None and 0 <= holy_site_id < len(self.territories):
            territory = self.territories[holy_site_id]
            owner_label = "vous" if territory.owner == player else ("ONU" if territory.owner == self.onu_player_id else f"J{territory.owner + 1}")
            holy_site_line = f"Lieu sacre: {territory.name}, controle par {owner_label}"
        interval = self.get_religion_spread_interval(religion_id)
        if interval is None:
            spread_line = "Expansion: arretee tant qu'aucun temple n'est controle"
        else:
            last_spread = int(getattr(self, "religion_last_spread_turns", {}).get(religion_id, self.turn))
            remaining = max(0, interval - (self.turn - last_spread))
            spread_line = f"Expansion: tous les {interval} tours; prochaine dans {remaining} tour(s)"
        return [
            f"Religions actives: {religion_labels}; temples: {temple_count}",
            f"Influence: {world_influence} territoire(s) dans le monde, dont {national_influence} sous votre controle",
            f"Bonus actuels: +{income_bonus} ecus et +{reinforcement_bonus} renfort(s) par tour",
            holy_site_line,
            spread_line,
        ]

    def get_empire_submitted_lines(self, player: int) -> list[str]:
        submitted: list[tuple[int, str]] = []
        for tid, overlord in getattr(self, "submitted_territory_overlords", {}).items():
            if overlord != player or not (0 <= tid < len(self.territories)):
                continue
            created = int(getattr(self, "submitted_territory_created_turns", {}).get(tid, self.turn))
            remaining = max(0, self.SUBMITTED_TERRITORY_INTEGRATION_DELAY_TURNS - (self.turn - created))
            submitted.append((remaining, f"{self.territories[tid].name}: integration dans {remaining} tour(s)"))
        submitted.sort(key=lambda item: (item[0], item[1]))
        if not submitted:
            return ["Aucun territoire actuellement soumis a votre nation"]
        lines = [line for _remaining, line in submitted[:5]]
        if len(submitted) > 5:
            lines.append(f"... et {len(submitted) - 5} autre(s) territoire(s) soumis")
        tribute = self.calculate_submitted_territory_tribute(player)
        lines.append(f"Tribut total actuel: +{tribute} ecus par tour")
        return lines

    def get_empire_alliance_lines(self, player: int) -> list[str]:
        self.cleanup_expired_alliances()
        lines: list[str] = []
        for (human, ai), expires_turn in sorted(self.active_alliances.items()):
            if human != player or self.turn >= expires_turn:
                continue
            lines.append(f"Alliance defensive avec J{ai + 1}: encore {max(0, expires_turn - self.turn)} tour(s)")
        for (human, ai), (target, expires_turn) in sorted(self.active_offensive_alliances.items()):
            if human != player or self.turn >= expires_turn:
                continue
            lines.append(f"Alliance offensive avec J{ai + 1} contre J{target + 1}: encore {max(0, expires_turn - self.turn)} tour(s)")
        return lines or ["Aucune alliance active"]

    def get_empire_internal_risk_lines(self, player: int) -> list[str]:
        owned = [terr for terr in self.territories if terr.owner == player]
        risky = []
        tax_haven_ids = self.get_player_tax_haven_capital_ids(player)
        for territory in owned:
            if territory.id in tax_haven_ids or self.is_sanctuary_territory(territory.id):
                continue
            points = self.calculate_sedition_chance_points(territory)
            if points > 0:
                risky.append((points, territory))
        if not risky:
            return ["Sedition: aucun territoire expose actuellement"]
        points, territory = max(risky, key=lambda item: (item[0], item[1].regiments, -item[1].id))
        chance = 100.0 * points / self.SEDITION_DENOMINATOR
        lines = [f"Risque de sedition le plus eleve: {territory.name}, {chance:.1f}% ({territory.regiments} regiments)"]
        if player in getattr(self, "nation_players", set()):
            lines.append("Le statut de nation annule toutefois toute sedition")
        else:
            lines.append("Une capitale active, une universite ou le statut de nation annule ce risque sur le territoire concerne")
        return lines

    def get_empire_victory_lines(self, player: int) -> list[str]:
        total = len(self.territories)
        threshold = math.ceil(total * 0.75) if total else 0
        territories = self.count_player_territories(player)
        golden = sum(1 for tid in self.golden_territory_ids if 0 <= tid < total and self.territories[tid].owner == player)
        holy = self.get_controlled_holy_site_count(player)
        required_holy_sites = self.get_required_holy_site_count_for_victory()
        lines = [
            f"Controle territorial: {territories}/{threshold} requis pour les 3/4 (manque {max(0, threshold - territories)})",
            f"Territoires dores: {golden}/4 (manque {max(0, 4 - golden)})",
        ]
        if self.is_holy_site_victory_active():
            lines.append(f"Lieux sacres: {holy}/{required_holy_sites} (manque {max(0, required_holy_sites - holy)})")
        else:
            lines.append(
                f"Lieux sacres: {holy}/{required_holy_sites}; victoire inactive tant que les {required_holy_sites} religions requises ne sont pas fondees"
            )
        return lines

    def get_empire_victory_threat_lines(self, player: int) -> list[str]:
        total = len(self.territories)
        if total <= 0:
            return ["Aucun adversaire actif"]
        threshold = math.ceil(total * 0.75)
        required_holy_sites = self.get_required_holy_site_count_for_victory()
        holy_victory_active = self.is_holy_site_victory_active()
        threats = []
        for opponent in self.get_active_players():
            if opponent == player or self.is_onu_player(opponent):
                continue
            territories = self.count_player_territories(opponent)
            golden = sum(1 for tid in self.golden_territory_ids if 0 <= tid < total and self.territories[tid].owner == opponent)
            holy = self.get_controlled_holy_site_count(opponent)
            danger = territories >= max(1, threshold - 3) or golden >= 3 or (holy_victory_active and holy >= required_holy_sites - 1)
            close = territories >= math.ceil(threshold * 0.65) or golden >= 2 or (holy_victory_active and holy >= required_holy_sites - 2)
            score = max(
                territories / max(1, threshold),
                golden / 4,
                (holy / required_holy_sites) if holy_victory_active else 0,
            )
            threats.append((2 if danger else 1 if close else 0, score, territories, golden, holy, opponent))
        threats.sort(reverse=True)
        close_threats = [item for item in threats if item[0] > 0]
        if not close_threats:
            if not threats:
                return ["Aucun adversaire actif"]
            _level, _score, territories, golden, holy, opponent = threats[0]
            return [
                "Aucun adversaire n'est actuellement proche d'une victoire.",
                f"Principal rival: J{opponent + 1} ({territories}/{threshold} territoires, {golden}/4 dores, {holy}/{required_holy_sites} lieux sacres)",
            ]
        lines = []
        for level, _score, territories, golden, holy, opponent in close_threats[:5]:
            label = "DANGER IMMEDIAT" if level >= 2 else "a surveiller"
            details = f"{territories}/{threshold} territoires, {golden}/4 dores"
            if holy_victory_active:
                details += f", {holy}/{required_holy_sites} lieux sacres"
            lines.append(f"J{opponent + 1} - {label}: {details}")
        return lines

    def get_empire_special_status_lines(self, player: int) -> list[str]:
        lines = []
        culture = self.calculate_player_culture(player)
        last_culture_milestone = max(0, int(getattr(self, "culture_expansion_milestones", {}).get(player, 0)))
        next_culture_milestone = self.get_next_culture_expansion_milestone(player)
        lines.append(
            f"Expansion culturelle: culture {culture}, dernier palier {last_culture_milestone or 'aucun'}, prochain palier {next_culture_milestone}"
        )
        if self.player_has_complete_industrial_set(player):
            lines.append("Ensemble industriel complet: usine + aeroport + port")
        else:
            labels = {"factory": "usine", "airport": "aeroport", "port": "port"}
            missing = [labels[item] for item in self.get_missing_player_industrial_types(player)]
            lines.append("Ensemble industriel incomplet; manque: " + ", ".join(missing))
        if self.is_tax_haven_income_bonus_active(player):
            lines.append("Bonus paradis fiscal complet: revenu global augmente de 50%")
        if player in getattr(self, "last_stand_bonus_players", set()):
            lines.append("Statut paradis fiscal actif")
        if player in getattr(self, "nation_players", set()):
            lines.append("Statut nation actif")
        if self.is_commercial_city_player(player):
            lines.append("Statut Cite commercante actif")
        controlled_wonders = [
            self.get_wonder_name(wonder_type)
            for wonder_type in self.WONDER_DEFINITIONS
            if self.player_controls_wonder(player, wonder_type)
        ]
        if controlled_wonders:
            lines.append("Merveilles controlees: " + ", ".join(controlled_wonders))
        return lines or ["Aucun statut special"]

    def get_empire_panel_pages(self, player: int) -> list:
        structures = self.get_empire_structure_counts(player)
        reinforcement = self.get_empire_reinforcement_preview(player)
        owned = self.count_player_territories(player)
        total = len(self.territories)
        phase_labels = {"attack": "attaque", "move": "deplacement"}
        overview = [
            f"Statut: {self.get_player_kind_label(player)}",
            f"Tour {self.turn}; phase: {phase_labels.get(self.turn_phase, self.turn_phase)}",
            f"Territoires: {owned}/{total}; regiments: {reinforcement['regiments']}",
            f"Tresorerie: {self.get_player_money(player)} ecus; revenu prochain tour: +{self.calculate_player_income(player)}",
        ]
        if reinforcement["eligible"]:
            overview.append(
                f"Renforts prevus: {reinforcement['total']} = base {reinforcement['base']} + bonus +3 {reinforcement['ultra_bonus']} + bonus +5 {reinforcement['bonus_5_reinforcements']} + religion {reinforcement['religious_bonus']} + progression IA {reinforcement['ai_bonus']}"
            )
            overview.append(
                f"Plafond militaire: {reinforcement['regiments']}/{reinforcement['regiment_limit']} regiments avant suspension des renforts"
            )
        else:
            overview.append(
                f"Renforts suspendus: {reinforcement['regiments']} regiments, plafond atteint ({reinforcement['regiment_limit']})"
            )
        overview.extend(self.get_empire_capital_lines(player))

        amenities = [
            f"Total des amenagements: {structures['total']}",
            f"Forteresses: {structures['fortresses']}",
            f"Usines: {structures['factories']}; aeroports: {structures['airports']}; ports: {structures['ports']}",
            f"Centres culturels: {structures['cultural_centers']}",
            f"Universites: {structures['universities']}; temples: {structures['temples']}",
            f"Territoires bonus +3: {structures['ultra']}; bonus +5: {structures['bonus_5']}; mines precieuses: {structures['precious_mines']}; territoires dores: {structures['golden']}/4",
        ]

        culture_science = [self.get_culture_protection_label(player)] + self.get_empire_science_lines(player)
        page_one_left = [
            ("Vue d'ensemble", overview),
            ("Amenagements", amenities),
        ]
        page_one_right = [
            ("Acces au statut de nation", self.get_empire_nation_lines(player)),
            ("Culture et science", culture_science),
        ]

        page_two_left = [
            ("Vos conditions de victoire", self.get_empire_victory_lines(player)),
            ("Adversaires proches de la victoire", self.get_empire_victory_threat_lines(player)),
            ("Diplomatie", self.get_empire_alliance_lines(player)),
        ]
        page_two_right = [
            ("Religion", self.get_empire_religion_lines(player)),
            ("Territoires soumis", self.get_empire_submitted_lines(player)),
            ("Risques et statuts utiles", self.get_empire_internal_risk_lines(player) + self.get_empire_special_status_lines(player)),
        ]
        return [(page_one_left, page_one_right), (page_two_left, page_two_right)]

    def draw_empire_panel(self) -> None:
        if not self.empire_panel_visible or not self.can_show_empire_panel():
            return

        pages = self.get_empire_panel_pages(self.current_player)
        self.empire_panel_page = max(0, min(self.empire_panel_page, len(pages) - 1))
        left_sections, right_sections = pages[self.empire_panel_page]

        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        rect = self.empire_panel_rect
        pygame.draw.rect(self.screen, (18, 32, 52), rect, border_radius=16)
        pygame.draw.rect(self.screen, (236, 240, 241), rect, width=1, border_radius=16)

        title = self.font_large.render(
            f"Empire de J{self.current_player + 1} - tour {self.turn} ({self.empire_panel_page + 1}/{len(pages)})",
            True,
            (236, 240, 241),
        )
        self.screen.blit(title, (rect.x + 24, rect.y + 18))

        column_gap = 34
        column_width = (rect.width - 48 - column_gap) // 2
        start_y = rect.y + 64
        bottom_limit = self.empire_panel_close_rect.top - 40
        section_color = (244, 208, 63)
        body_color = (225, 230, 235)
        warning_color = (255, 190, 120)
        danger_color = (255, 135, 125)

        def draw_sections(sections: list[tuple[str, list[str]]], x: int) -> None:
            y = start_y
            for title_text, lines in sections:
                if y + 28 > bottom_limit:
                    break
                rendered_title = self.font_medium.render(title_text, True, section_color)
                self.screen.blit(rendered_title, (x, y))
                y += 27
                for text_line in lines:
                    color = danger_color if "DANGER" in text_line or "ALERTE" in text_line else warning_color if "suspendus" in text_line or "perdue" in text_line else body_color
                    wrapped = self.wrap_text("- " + text_line, self.font_small, column_width)
                    for wrapped_line in wrapped:
                        if y + 18 > bottom_limit:
                            ellipsis = self.font_small.render("...", True, body_color)
                            self.screen.blit(ellipsis, (x, y))
                            return
                        rendered = self.font_small.render(wrapped_line, True, color)
                        self.screen.blit(rendered, (x, y))
                        y += 18
                y += 9

        left_x = rect.x + 24
        right_x = left_x + column_width + column_gap
        pygame.draw.line(self.screen, (85, 103, 122), (right_x - column_gap // 2, start_y), (right_x - column_gap // 2, bottom_limit), 1)
        draw_sections(left_sections, left_x)
        draw_sections(right_sections, right_x)

        footer = self.font_small.render("Clic droit sur Details : activer/desactiver les informations au survol", True, (160, 170, 180))
        self.screen.blit(footer, (rect.x + 24, rect.bottom - 58))

        close_label = "Suite" if self.empire_panel_page + 1 < len(pages) else "Fermer"
        close_color = (64, 89, 120) if self.empire_panel_close_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
        pygame.draw.rect(self.screen, close_color, self.empire_panel_close_rect, border_radius=8)
        pygame.draw.rect(self.screen, (236, 240, 241), self.empire_panel_close_rect, width=1, border_radius=8)
        close_text = self.font_medium.render(close_label, True, (236, 240, 241))
        self.screen.blit(close_text, close_text.get_rect(center=self.empire_panel_close_rect.center))

    def draw_geopolitical_panel(self) -> None:
        if not self.geopolitical_panel_visible or self.phase not in ("playing", "shopping") or self.is_ai_player(self.current_player):
            return

        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 135))
        self.screen.blit(overlay, (0, 0))

        rect = self.geopolitical_panel_rect
        pygame.draw.rect(self.screen, (18, 32, 52), rect, border_radius=16)
        pygame.draw.rect(self.screen, (236, 240, 241), rect, width=1, border_radius=16)

        power_rows = self.get_geopolitical_power_rows()
        page_capacity = self.get_geopolitical_power_page_capacity()
        power_page_count = self.get_geopolitical_power_page_count()
        info_pages = self.get_geopolitical_info_pages()
        page_count = power_page_count + len(info_pages)
        self.geopolitical_panel_page = max(0, min(self.geopolitical_panel_page, page_count - 1))
        page = self.geopolitical_panel_page
        is_power_page = page < power_page_count
        power_page = min(page, power_page_count - 1)
        start_index = power_page * page_capacity
        end_index = start_index + page_capacity
        visible_power_rows = power_rows[start_index:end_index] if is_power_page else []

        title_suffix = f" ({page + 1}/{page_count})" if page_count > 1 else ""
        title_prefix = "Situation geopolitique" if page == 0 else "Situation geopolitique, suite"
        title = self.font_large.render(
            f"{title_prefix} - tour {self.turn} - J{self.current_player + 1}{title_suffix}",
            True,
            (236, 240, 241),
        )
        self.screen.blit(title, (rect.x + 24, rect.y + 18))

        y = rect.y + 62
        x = rect.x + 24
        max_width = rect.width - 48
        section_color = (244, 208, 63)
        body_color = (225, 230, 235)
        muted_color = (189, 195, 199)

        def draw_section(label: str) -> None:
            nonlocal y
            rendered = self.font_medium.render(label, True, section_color)
            self.screen.blit(rendered, (x, y))
            y += 28

        def draw_line(text: str, color=body_color, indent: int = 0) -> None:
            nonlocal y
            for line in self.wrap_text(text, self.font_small, max_width - indent):
                rendered = self.font_small.render(line, True, color)
                self.screen.blit(rendered, (x + indent, y))
                y += 18

        if is_power_page:
            draw_section("Puissances")

            table_x = x
            table_y = y
            row_h = 26
            full_columns = [
                ("Joueur", 55, "center", 0),
                ("Nature / attitude", 160, "left", 1),
                ("Terr.", 48, "right", 2),
                ("Tresor", 80, "right", 3),
                ("Rev./tour", 75, "right", 4),
                ("Culture", 70, "right", 5),
                ("Science", 105, "right", 6),
                ("Armee/plaf.", 75, "right", 7),
                ("Renf.", 60, "right", 8),
                ("Religion (infl.)", 140, "left", 9),
                ("Sites", 48, "right", 10),
                ("Atouts", 150, "left", 11),
                ("Merveilles", 190, "left", 12),
            ]
            split_tables = [
                [
                    ("Joueur", 55, "center", 0),
                    ("Nature / attitude", 150, "left", 1),
                    ("Terr.", 48, "right", 2),
                    ("Tresor", 75, "right", 3),
                    ("Rev./tour", 72, "right", 4),
                    ("Culture", 65, "right", 5),
                    ("Science", 100, "right", 6),
                ],
                [
                    ("Joueur", 55, "center", 0),
                    ("Armee/plaf.", 75, "right", 7),
                    ("Renf.", 58, "right", 8),
                    ("Religion (infl.)", 135, "left", 9),
                    ("Sites", 48, "right", 10),
                    ("Atouts", 145, "left", 11),
                    ("Merveilles", 190, "left", 12),
                ],
            ]
            header_bg = (46, 68, 98)
            header_border = (236, 240, 241)
            row_bg = (22, 38, 61)
            alt_row_bg = (29, 48, 74)
            grid_color = (170, 184, 198)

            def cell_overflows(text: str, font: pygame.font.Font, width: int) -> bool:
                return font.size(str(text))[0] > width - 14

            def needs_split_tables(rows: list[tuple[int, list[str]]], columns: list[tuple[str, int, str, int]]) -> bool:
                if sum(width for _label, width, _align, _idx in columns) > max_width:
                    return True
                for _player, values in rows:
                    for _label, width, _align, index in columns:
                        if cell_overflows(values[index], self.font_small, width):
                            return True
                return False

            use_split_tables = needs_split_tables(visible_power_rows, full_columns)
            table_groups = split_tables if use_split_tables else [full_columns]
            table_gap = 14
            table_group_xs = [table_x]
            if use_split_tables:
                table_group_xs.append(table_x)

            def fit_cell_text(text: str, font: pygame.font.Font, width: int) -> str:
                text = str(text)
                if font.size(text)[0] <= width - 14:
                    return text
                ellipsis = "..."
                while text and font.size(text + ellipsis)[0] > width - 14:
                    text = text[:-1]
                return (text + ellipsis) if text else ellipsis

            def draw_table_cell(text: str, cell_rect: pygame.Rect, color=body_color, align: str = "left", bold: bool = False) -> None:
                font = self.font_medium if bold else self.font_small
                clipped = fit_cell_text(text, font, cell_rect.width)
                rendered = font.render(clipped, True, color)
                if align == "right":
                    text_x = cell_rect.right - rendered.get_width() - 8
                elif align == "center":
                    text_x = cell_rect.x + (cell_rect.width - rendered.get_width()) // 2
                else:
                    text_x = cell_rect.x + 8
                text_y = cell_rect.y + (cell_rect.height - rendered.get_height()) // 2
                self.screen.blit(rendered, (text_x, text_y))

            def draw_table_row(
                row_y: int,
                values: list[str],
                columns: list[tuple[str, int, str, int]],
                table_w: int,
                table_origin_x: int,
                background: tuple[int, int, int],
                header: bool = False,
                player: Optional[int] = None,
            ) -> None:
                border_color = header_border if header else grid_color
                col_x = table_origin_x
                for label, width, default_align, index in columns:
                    cell_rect = pygame.Rect(col_x, row_y, width, row_h)
                    pygame.draw.rect(self.screen, background, cell_rect)
                    pygame.draw.rect(self.screen, border_color, cell_rect, width=2 if header else 1)
                    value = label if header else values[index]
                    if header:
                        draw_table_cell(value, cell_rect, (255, 255, 255), "center", bold=False)
                    else:
                        color = self.get_geopolitical_player_color(player or 0)
                        draw_table_cell(value, cell_rect, color, default_align)
                    col_x += width
                pygame.draw.rect(self.screen, border_color, (table_origin_x, row_y, table_w, row_h), width=2 if header else 1)

            table_start_y = y
            max_table_bottom = table_start_y
            for group_index, columns in enumerate(table_groups):
                table_y = table_start_y if group_index == 0 else max_table_bottom + table_gap
                table_w = sum(width for _label, width, _align, _idx in columns)
                table_origin_x = table_group_xs[group_index]
                draw_table_row(table_y, [], columns, table_w, table_origin_x, header_bg, header=True)
                row_y = table_y + row_h
                for offset, (player, values) in enumerate(visible_power_rows):
                    background = alt_row_bg if (start_index + offset) % 2 else row_bg
                    draw_table_row(row_y, values, columns, table_w, table_origin_x, background, player=player)
                    row_y += row_h
                max_table_bottom = max(max_table_bottom, row_y)
            y = max_table_bottom

            if use_split_tables:
                draw_line("Tableau scinde pour eviter les cellules tronquees.", muted_color)

            remaining_power_rows = max(0, len(power_rows) - end_index)
            if remaining_power_rows > 0:
                draw_line(f"... {remaining_power_rows} joueur(s) dans l'encart suivant", muted_color)
            elif len(info_pages) > 0:
                draw_line("Suite automatique: synthese, alliances et evenements.", muted_color)
        else:
            info_page_index = page - power_page_count
            info_items = info_pages[info_page_index] if 0 <= info_page_index < len(info_pages) else []
            for kind, text, muted in info_items:
                if kind == "section":
                    draw_section(text)
                else:
                    draw_line(text, muted_color if muted else body_color)

        close_label = "Suite" if page + 1 < page_count else "Fermer"
        close_color = (64, 89, 120) if self.geopolitical_panel_close_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
        pygame.draw.rect(self.screen, close_color, self.geopolitical_panel_close_rect, border_radius=8)
        pygame.draw.rect(self.screen, (236, 240, 241), self.geopolitical_panel_close_rect, width=1, border_radius=8)
        close_text = self.font_medium.render(close_label, True, (236, 240, 241))
        self.screen.blit(close_text, close_text.get_rect(center=self.geopolitical_panel_close_rect.center))

    def draw_shop_overlay(self) -> None:
        if self.shop_panel_collapsed:
            compact_rect = pygame.Rect(self.WIDTH - 610, 48, 590, 34)
            pygame.draw.rect(self.screen, (21, 36, 58), compact_rect, border_radius=10)
            pygame.draw.rect(self.screen, (236, 240, 241), compact_rect, width=1, border_radius=10)
            action_label = self.get_shop_action_label(self.shop_action)
            if self.shop_action == "mercenaries":
                quantity_label = f" | mercenaires: {self.shop_mercenary_quantity}"
            elif self.shop_action == "gift_money":
                quantity_label = f" | don: {self.shop_gift_amount} ecu(s)"
            elif self.shop_action == "give_territory" and self.pending_gift_territory_id is not None:
                source = self.territories[self.pending_gift_territory_id] if 0 <= self.pending_gift_territory_id < len(self.territories) else None
                quantity_label = f" | territoire: {source.name}" if source is not None else ""
            elif self.shop_action in ("build_bridge", "destroy_bridge") and self.pending_bridge_territory_id is not None:
                source = self.territories[self.pending_bridge_territory_id] if 0 <= self.pending_bridge_territory_id < len(self.territories) else None
                quantity_label = f" | extremite: {source.name}" if source is not None else ""
            else:
                quantity_label = ""
            status = self.font_small.render(f"Achat: {action_label}{quantity_label} | ecus: {self.get_player_money()}", True, (244, 208, 63))
            self.screen.blit(status, (compact_rect.x + 12, compact_rect.y + 9))
            for rect, label, base_color in [
                (self.shop_reopen_rect, "Menu achats", (52, 73, 94)),
                (self.shop_finish_compact_rect, "Fin achats", (42, 94, 68)),
            ]:
                color = tuple(min(255, c + 20) for c in base_color) if rect.collidepoint(pygame.mouse.get_pos()) else base_color
                pygame.draw.rect(self.screen, color, rect, border_radius=8)
                pygame.draw.rect(self.screen, (236, 240, 241), rect, width=1, border_radius=8)
                rendered = self.font_small.render(label, True, (236, 240, 241))
                self.screen.blit(rendered, rendered.get_rect(center=rect.center))
            return

        shadow_rect = self.shop_panel_rect.move(5, 5)
        pygame.draw.rect(self.screen, (0, 0, 0, 70), shadow_rect, border_radius=14)
        pygame.draw.rect(self.screen, (21, 36, 58), self.shop_panel_rect, border_radius=14)
        pygame.draw.rect(self.screen, (236, 240, 241), self.shop_panel_rect, width=1, border_radius=14)

        title = self.font_medium.render("Marche des achats", True, (236, 240, 241))
        self.screen.blit(title, (self.shop_panel_rect.x + 20, self.shop_panel_rect.y + 14))
        subtitle = self.font_small.render("PARADIS FISCAL : FIGER ONU et LIBERER ONU apparaissent en bas du menu.", True, (244, 208, 63))
        self.screen.blit(subtitle, (self.shop_panel_rect.x + 20, self.shop_panel_rect.y + 42))
        money = self.get_player_money()
        income = self.calculate_player_income(self.current_player)
        culture = self.calculate_player_culture(self.current_player)
        science = self.get_player_science(self.current_player)
        science_income = self.calculate_player_science_income(self.current_player)
        money_text = self.font_small.render(f"J{self.current_player + 1} : {money} ecu(s) | revenu +{income}/tour | culture {culture} | science {science} (+{science_income})", True, (244, 208, 63))
        self.screen.blit(money_text, (self.shop_panel_rect.x + 20, self.shop_panel_rect.y + 66))

        self.update_shop_gift_amount()
        button_specs = [
            ("mercenaries", f"Mercenaires x{self.shop_mercenary_quantity} - {self.MERCENARY_COST}/reg."),
            ("sell_territory", "VENDRE TERR. +10/reg +bonus"),
            ("give_territory", "DONNER TERRITOIRE"),
            ("gift_money", f"DONNER ARGENT x{self.shop_gift_amount}"),
            ("build_fortress", f"Construire forteresse - {self.FORTRESS_COST}"),
            ("destroy_fortress", f"Detruire forteresse - {self.DESTROY_FORTRESS_COST}"),
            ("corrupt", f"Corrompre - {self.REDUCED_CORRUPTION_COST_PER_REGIMENT}/{self.CORRUPTION_COST_PER_REGIMENT}/reg. + bonus"),
            ("revolt", f"Declencher revolte - {self.REVOLT_COST_LOW}-{self.REVOLT_COST_HIGH}"),
            ("build_factory", f"Usine - {self.FACTORY_COST}"),
            ("build_airport", f"Aeroport - {self.AIRPORT_COST}"),
            ("build_port", f"Port - {self.PORT_COST}"),
            ("build_temple", f"Temple - {self.TEMPLE_COST}"),
            ("build_cultural_center", f"Centre culturel - {self.CULTURAL_CENTER_COST}"),
            ("build_university", f"Universite - {self.UNIVERSITY_COST}"),
            ("alliance", f"Alliance def. - {self.ALLIANCE_COST_PER_TERRITORY}/terr."),
            ("offensive_alliance", f"Alliance off. - {self.OFFENSIVE_ALLIANCE_COST_PER_TERRITORY}/terr."),
            ("tax_haven_association", "Association / integration PF"),
            ("freeze_territory", f"Figer ONU - {self.ONU_MANIPULATION_COST_PER_REGIMENT}/reg."),
            ("release_sanctuary", f"Liberer ONU - {self.ONU_MANIPULATION_COST_PER_REGIMENT}/reg."),
            ("change_capital", f"Changer capitale - {self.CHANGE_CAPITAL_COST}"),
            ("destroy_university", f"Detruire universite - {self.UNIVERSITY_COST}"),
            ("build_wonder", f"Merveille - {self.WONDER_COST}"),
        ]
        if science >= self.SCIENCE_BRIDGE_THRESHOLD:
            button_specs.extend([
                ("build_bridge", f"Creer pont - {self.BUILD_BRIDGE_COST}"),
                ("destroy_bridge", f"Detruire pont - {self.DESTROY_BRIDGE_COST}"),
            ])
        for action, label in button_specs:
            rect = self.shop_buttons[action]
            base_cost = self.get_shop_action_base_cost(action)
            tax_haven_only = action in ("freeze_territory", "release_sanctuary")
            affordable = (
                action in ("corrupt", "alliance", "offensive_alliance", "tax_haven_association", "sell_territory", "give_territory")
                or (action == "gift_money" and self.get_player_money() > 0)
                or (tax_haven_only and self.can_player_manipulate_onu(self.current_player) and self.get_player_money() >= self.ONU_MANIPULATION_COST_PER_REGIMENT)
                or (not tax_haven_only and self.get_player_money() >= base_cost)
            )
            if action == "build_wonder":
                affordable = (
                    affordable
                    and self.can_player_build_wonder(self.current_player)
                    and bool(self.get_available_wonder_types())
                )
            elif action == "destroy_bridge":
                affordable = affordable and bool(self.bridge_links)
            active = self.shop_action == action
            if not affordable:
                color = (44, 52, 60)
                text_color = (135, 140, 145)
            elif active:
                color = (84, 153, 199)
                text_color = (236, 240, 241)
            elif action == "sell_territory":
                color = (116, 86, 32)
                text_color = (255, 245, 210)
            elif action == "give_territory":
                color = (102, 76, 36)
                text_color = (255, 245, 210)
            elif action == "gift_money":
                color = (38, 96, 74)
                text_color = (220, 255, 235)
            elif action in ("freeze_territory", "release_sanctuary"):
                color = (62, 82, 110)
                text_color = (225, 240, 255)
            else:
                color = (52, 73, 94)
                text_color = (236, 240, 241)
            if rect.collidepoint(pygame.mouse.get_pos()) and affordable:
                color = tuple(min(255, c + 20) for c in color)
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), rect, width=1, border_radius=8)
            if action in ("mercenaries", "gift_money"):
                text_rect = pygame.Rect(rect.x + 8, rect.y, rect.width - 70, rect.height)
                rendered = self.font_small.render(label, True, text_color)
                self.screen.blit(rendered, rendered.get_rect(midleft=(text_rect.x, text_rect.centery)))
                controls = (
                    [(self.shop_minus_rect, "-"), (self.shop_plus_rect, "+")]
                    if action == "mercenaries"
                    else [(self.shop_gift_minus_rect, "-"), (self.shop_gift_plus_rect, "+")]
                )
                for control_rect, symbol in controls:
                    control_color = (64, 89, 120) if control_rect.collidepoint(pygame.mouse.get_pos()) and affordable else (38, 56, 78)
                    pygame.draw.rect(self.screen, control_color, control_rect, border_radius=6)
                    pygame.draw.rect(self.screen, (236, 240, 241), control_rect, width=1, border_radius=6)
                    symbol_text = self.font_small.render(symbol, True, (236, 240, 241))
                    self.screen.blit(symbol_text, symbol_text.get_rect(center=control_rect.center))
            else:
                rendered = self.font_small.render(label, True, text_color)
                self.screen.blit(rendered, rendered.get_rect(center=rect.center))

        selected_text = self.font_small.render(f"Selection actuelle : {self.get_shop_action_label(self.shop_action)}", True, (189, 195, 199))
        self.screen.blit(selected_text, (self.shop_panel_rect.x + 20, self.shop_panel_rect.y + 524))

        quantity_center_x = self.shop_panel_rect.centerx
        quantity_y = self.shop_panel_rect.y + 548
        if self.shop_action == "mercenaries":
            self.update_shop_mercenary_quantity()
            qty_hint = self.font_small.render(
                f"Mercenaires : {self.shop_mercenary_quantity} selectionne(s). Cliquez + ou -, puis le bouton Mercenaires.",
                True,
                (236, 240, 241),
            )
        elif self.shop_action == "gift_money":
            qty_hint = self.font_small.render(
                f"Don : {self.shop_gift_amount} ecu(s). Ajustez avec + / -, puis cliquez un joueur beneficiaire.",
                True,
                (236, 240, 241),
            )
        elif self.shop_action == "give_territory":
            if self.pending_gift_territory_id is None:
                hint_text = "Don de territoire : cliquez un de vos territoires."
            else:
                source = self.territories[self.pending_gift_territory_id] if 0 <= self.pending_gift_territory_id < len(self.territories) else None
                source_name = source.name if source is not None else "?"
                hint_text = f"Don de territoire : {source_name} selectionne. Cliquez le joueur beneficiaire."
            qty_hint = self.font_small.render(hint_text, True, (236, 240, 241))
        elif self.shop_action == "change_capital":
            qty_hint = self.font_small.render("Changement de capitale : cliquez un territoire que vous controlez.", True, (236, 240, 241))
        elif self.shop_action == "build_wonder" and self.pending_wonder_type:
            qty_hint = self.font_small.render(
                f"Merveille : {self.get_wonder_name(self.pending_wonder_type)}. Cliquez un de vos territoires.",
                True,
                (236, 240, 241),
            )
        elif self.shop_action in ("build_bridge", "destroy_bridge"):
            operation = "Construction" if self.shop_action == "build_bridge" else "Destruction"
            if self.pending_bridge_territory_id is None:
                hint_text = f"{operation} de pont : cliquez la premiere extremite."
            else:
                source = self.territories[self.pending_bridge_territory_id]
                hint_text = f"{operation} de pont : {source.name} selectionne, cliquez la seconde extremite."
            qty_hint = self.font_small.render(hint_text, True, (236, 240, 241))
        else:
            qty_hint = self.font_small.render("Paradis fiscal : figer/liberer ONU coutent 50 ecu(s) par regiment.", True, (189, 195, 199))
        self.screen.blit(qty_hint, qty_hint.get_rect(center=(quantity_center_x, quantity_y)))

        help_lines = ["Actions en deux clics : don de territoire, alliance offensive et ponts."]
        for idx, line in enumerate(help_lines):
            rendered = self.font_small.render(line, True, (189, 195, 199))
            self.screen.blit(rendered, (self.shop_panel_rect.x + 20, self.shop_panel_rect.y + 564 + idx * 16))

        finish_color = (64, 120, 89) if self.finish_shopping_rect.collidepoint(pygame.mouse.get_pos()) else (42, 94, 68)
        pygame.draw.rect(self.screen, finish_color, self.finish_shopping_rect, border_radius=8)
        pygame.draw.rect(self.screen, (236, 240, 241), self.finish_shopping_rect, width=1, border_radius=8)
        finish_text = self.font_medium.render("Fin des achats", True, (236, 240, 241))
        self.screen.blit(finish_text, finish_text.get_rect(center=self.finish_shopping_rect.center))

    def trigger_sanctuary_annexation_event(self, human_player: int) -> str:
        """Sanction appliquee quand un humain annexe un territoire ONU."""
        owned = [terr for terr in self.territories if terr.owner == human_player]
        if len(owned) < 2:
            return "ONU annexee par un humain : sanction impossible, empire trop petit."

        event_type = random.choice(["revolt_new", "revolt_transfer", "chaos"])

        if event_type == "chaos":
            message = self.build_global_chaos_event_message(
                f"Sanctuaire ONU annexe par J{human_player + 1}: chaos mondial."
            )
            if message is not None:
                return message
            return "Sanctuaire ONU annexe : chaos mondial impossible, trop peu de territoires a bouleverser."

        default_lost_count = min(5, len(owned))
        lost_count = self.calculate_cultural_revolt_or_betrayal_loss_count(human_player, default_lost_count)
        if lost_count <= 0:
            return f"Sanctuaire ONU annexe : sanction de revolte/trahison sans perte pour J{human_player + 1} ({self.get_culture_protection_label(human_player)})."
        territories_to_transfer = self.choose_owned_contiguous_block(human_player, lost_count)
        if not territories_to_transfer:
            return f"Sanctuaire ONU annexe : sanction de revolte/trahison impossible, aucune cible valide hors capitale pour J{human_player + 1}."
        lost_count = len(territories_to_transfer)

        if event_type == "revolt_transfer":
            active_players = [
                player for player in self.get_active_players()
                if player != human_player and not self.is_commercial_city_player(player)
            ]
            if active_players:
                territory_counts = {player: sum(1 for terr in self.territories if terr.owner == player) for player in active_players}
                min_count = min(territory_counts.values())
                receivers = [player for player, count in territory_counts.items() if count == min_count]
                beneficiary_player = random.choice(receivers)
                for terr in territories_to_transfer:
                    terr.owner = beneficiary_player
                self.refresh_eliminated_human_players()
                return f"Sanctuaire ONU annexe : trahison punitive. {lost_count} territoire(s) de J{human_player + 1} passent a J{beneficiary_player + 1}."

        new_player, returning_human = self.allocate_rebel_player()
        for terr in territories_to_transfer:
            terr.owner = new_player
        self.refresh_eliminated_human_players()
        comeback = "nouveau joueur IA"
        return f"Sanctuaire ONU annexe : revolte punitive. {lost_count} territoire(s) de J{human_player + 1} passent a J{new_player + 1} ({comeback})."

    def run(self) -> None:
        self.phase = "start_menu"
        self.turn_phase = "attack"
        self.turn_move_count = 0
        self.show_message("Choisissez : creer une carte ou commencer une partie.", 2600)

        while self.running:
            self.clock.tick(self.FPS)
            self.handle_events()
            self.update()
            self.draw()

        pygame.quit()

    def place_end_turn_reinforcement(self, terr: Territory, player: int) -> bool:
        """Place un renfort de fin de tour, ou le convertit en ecus si le territoire a une universite."""
        if terr.id in self.university_territory_ids:
            self.ensure_player_economy(player)
            self.player_money[player] += 10
            return True
        terr.regiments += 1
        return False

    def grant_reinforcements(self, player: int) -> None:
        report = moteur_regles.grant_reinforcements(self, player)
        if report is None:
            return
        durations = {"colonisation": 2200, "plafond": 2600, "renforts": 2200}
        self.show_message(report.message, durations[report.kind])

    def maybe_spawn_random_ai_economic_structure(self, display: bool = True) -> Optional[str]:
        """Regle des apparitions economiques IA aleatoires supprimee."""
        return None

    def maybe_spawn_random_ai_cultural_center(self, display: bool = True) -> Optional[str]:
        """Regle des apparitions culturelles IA aleatoires supprimee."""
        return None

    def get_active_players(self) -> List[int]:
        return sorted({t.owner for t in self.territories if t.owner >= 0})

    def is_human_player_id(self, player: int) -> bool:
        return 0 <= player < self.num_players and not self.is_ai_player(player)

    def mark_eliminated_player_if_human(self, player: int) -> None:
        if self.is_human_player_id(player):
            self.eliminated_human_players.add(player)

    def refresh_eliminated_human_players(self) -> None:
        self.eliminated_human_players = {
            player for player in self.eliminated_human_players
            if 0 <= player < self.num_players
            and self.is_human_player_id(player)
            and not any(terr.owner == player for terr in self.territories)
        }

    def allocate_rebel_player(self) -> tuple[int, bool]:
        """Cree toujours un nouveau joueur IA pour revolte, revolution ou chaos.

        L'ancien retour prioritaire d'un joueur humain elimine est supprime.
        Un joueur pourra ensuite etre bascule manuellement en mode humain via le bouton de controle.
        """
        new_player = self.num_players
        self.num_players += 1
        self.base_ai_players.add(new_player)
        self.human_controlled_players.discard(new_player)
        self.auto_controlled_players.discard(new_player)
        self.assign_ai_personality_to_player(new_player)
        self.ensure_player_economy(new_player)
        self.assign_player_to_cold_war_camp(new_player)
        return new_player, False

    def build_global_chaos_event_message(self, prefix: Optional[str] = None) -> Optional[str]:
        message = moteur_regles.build_global_chaos_event_message(self, prefix=prefix)
        if message is not None:
            self.selected_source = None
            self.selected_target = None
        return message

    def maybe_trigger_chaos_event(self) -> bool:
        message = moteur_regles.maybe_trigger_chaos_event(self)
        if message is None:
            return False
        self.show_message(message, 6200)
        return True

    def maybe_trigger_empire_event(self) -> None:
        self.selected_source = None
        self.selected_target = None
        messages = moteur_regles.maybe_trigger_empire_event(self)
        for message in messages:
            self.show_message(message, 4600)

    def get_end_turn_move_limit(self, player: Optional[int] = None) -> int:
        return moteur_regles.get_end_turn_move_limit(self, player)

    def get_ai_mobilization_frontier_territories(self, player: int) -> List[Territory]:
        return [
            terr for terr in self.territories
            if terr.owner == player
            and any(
                self.territories[neighbor_id].owner != player
                for neighbor_id in terr.neighbors
            )
        ]

    def maybe_trigger_ai_mobilization(self, player: int) -> Optional[str]:
        return moteur_regles.maybe_trigger_ai_mobilization(self, player)

    def start_move_phase(self) -> None:
        self.turn_phase = "move"
        self.turn_move_count = 0
        self.selected_source = None
        self.selected_target = None
        move_limit = self.get_end_turn_move_limit()
        self.show_message(
            f"Phase de deplacement : clic gauche = source, clic droit = destination ; double-clic = concentration aleatoire (max {move_limit}).",
            3600,
        )

    def complete_turn(self) -> None:
        report = moteur_actions.advance_turn(
            self, self.cell_width, self.cell_height, begin_next_turn=False,
        )
        if report.reinforcement_report is not None:
            durations = {"colonisation": 2200, "plafond": 2600, "renforts": 2200}
            self.show_message(report.reinforcement_report.message, durations[report.reinforcement_report.kind])
        if report.sedition_message:
            self.show_message(report.sedition_message, 6200)
        if report.winner is not None:
            self.last_victory_reason = report.winner_reason
            self.declare_victory(report.winner)
            return
        if report.new_global_turn:
            if report.resource_messages:
                self.show_message(" | ".join(report.resource_messages), 6200)
            if report.religion_messages:
                self.show_message(" ".join(report.religion_messages), 5200)
            if report.market_message:
                self.show_message(report.market_message, 5200)
            for message in report.empire_messages:
                self.show_message(message, 4600)
        self.selected_source = None
        self.selected_target = None
        if report.has_active_players:
            self.begin_player_turn(self.current_player)
        else:
            self.reset_ai_turn_state()

    def handle_end_turn_action(self) -> None:
        if self.turn_phase == "attack":
            if self.is_ai_player(self.current_player) or self.is_colonized_player(self.current_player):
                self.start_move_phase()
            else:
                self.begin_shopping_phase()
        else:
            self.complete_turn()

    def get_human_union_champions(self, player: int) -> list[int]:
        if getattr(self, "final_duel_active", False) or not self.is_human_player_id(player):
            return []
        members = self.get_union_members(player)
        champions = sorted(member for member in members if self.is_human_player_id(member))
        return champions if len(champions) >= 2 else []

    def ensure_final_duel_auxiliary_players(self, minimum_count: int) -> list[int]:
        auxiliary_players = [
            player for player in range(self.num_players)
            if player >= 0
            and player not in set(getattr(self, "final_duel_champions", ()) or ())
            and not self.is_onu_player(player)
        ]
        while len(auxiliary_players) < minimum_count:
            new_player = self.num_players
            self.num_players += 1
            self.base_ai_players.add(new_player)
            self.auto_controlled_players.discard(new_player)
            self.human_controlled_players.discard(new_player)
            self.commercial_city_players.discard(new_player)
            self.assign_ai_personality_to_player(new_player, "standard")
            self.ensure_player_economy(new_player)
            auxiliary_players.append(new_player)
        return auxiliary_players

    def maybe_start_final_duel(self, winner: int) -> bool:
        champions = self.get_human_union_champions(winner)
        if len(champions) < 2:
            return False

        valid_ids = set(range(len(self.territories)))
        champion_originals: dict[int, set[int]] = {}
        already_reserved: set[int] = set()
        for champion in champions:
            self.ensure_union_origin_snapshot(champion)
            original_ids = [
                tid for tid in sorted(self.union_original_territories.get(champion, set()))
                if tid in valid_ids and tid not in already_reserved
            ][:self.NATION_MIN_TERRITORIES]
            champion_originals[champion] = set(original_ids)
            already_reserved.update(original_ids)

        self.final_duel_active = True
        self.final_duel_champions = tuple(champions)
        self.final_duel_alliances = {champion: champion for champion in champions}
        self.final_duel_pending_winner = None
        self.nation_players = set()
        self.nation_qualification_start_turns = {}
        self.nation_capital_loss_start_turns = {}
        self.nation_alliances = set()
        self.nation_wars = set()
        self.submitted_territory_ids = set()
        self.submitted_territory_overlords = {}
        self.submitted_territory_created_turns = {}
        self.sanctuary_territory_ids = set()

        auxiliary_players = self.ensure_final_duel_auxiliary_players(len(champions))
        random.shuffle(auxiliary_players)
        allies_by_champion = {champion: [] for champion in champions}
        for index, player in enumerate(auxiliary_players):
            champion = champions[index % len(champions)]
            self.final_duel_alliances[player] = champion
            allies_by_champion[champion].append(player)

        for champion, original_ids in champion_originals.items():
            for tid in original_ids:
                self.territories[tid].owner = champion
                self.territories[tid].regiments = max(1, self.territories[tid].regiments)

        remaining = [tid for tid in range(len(self.territories)) if tid not in already_reserved]
        random.shuffle(remaining)
        territory_counts = {player: 0 for player in auxiliary_players}
        block_counts = {champion: 0 for champion in champions}
        for tid in remaining:
            champion = min(champions, key=lambda item: (block_counts[item], random.random()))
            candidates = allies_by_champion.get(champion) or auxiliary_players
            owner = min(candidates, key=lambda player: (territory_counts.get(player, 0), random.random()))
            self.territories[tid].owner = owner
            self.territories[tid].regiments = max(1, self.territories[tid].regiments)
            territory_counts[owner] = territory_counts.get(owner, 0) + 1
            block_counts[champion] += 1

        self.nation_players = set()
        self.nation_qualification_start_turns = {}
        self.nation_capital_loss_start_turns = {}
        self.nation_alliances = set()
        self.nation_wars = set()
        self.selected_source = None
        self.selected_target = None
        self.phase = "playing"
        champion_labels = ", ".join(f"J{champion + 1}" for champion in champions)
        self.last_victory_reason = (
            f"victoire intermediaire : union humaine dissoute, finale entre champions {champion_labels}"
        )
        message = (
            f"Victoire intermediaire de J{winner + 1}. Union humaine dissoute : champions {champion_labels}. "
            f"Chaque champion recupere au plus {self.NATION_MIN_TERRITORIES} territoires d'origine; "
            f"le reste du monde est confie a des allies definitifs repartis en {len(champions)} blocs."
        )
        self.record_major_event(message)
        self.show_message(message, 9000)
        return True

    def check_winner(self) -> Optional[int]:
        winner, reason = moteur_regles.evaluate_winner(self)
        self.last_victory_reason = reason
        return winner

    def handle_start_menu_click(self, pos: Tuple[int, int]) -> None:
        if self.start_create_map_rect.collidepoint(pos):
            self.start_custom_map_editor()
            return
        if self.start_edit_map_rect.collidepoint(pos):
            self.start_existing_map_editor()
            return
        if self.start_game_rect.collidepoint(pos):
            self.start_game_session()
            return
        if self.start_load_game_rect.collidepoint(pos):
            self.start_load_saved_game()

    def handle_events(self) -> None:
        for event in pygame.event.get():
            ai_turn = self.phase == "playing" and self.is_ai_player(self.current_player)
            if event.type == pygame.QUIT:
                self.running = False
                continue
            if self.major_event_modal is not None:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.close_major_event_modal()
                continue
            if event.type == pygame.MOUSEBUTTONDOWN:
                if self.phase in ("playing", "shopping") and self.empire_panel_visible and not ai_turn:
                    if event.button == 1 and self.empire_panel_close_rect.collidepoint(event.pos):
                        self.close_empire_panel()
                    continue
                if self.phase in ("playing", "shopping") and self.geopolitical_panel_visible and not ai_turn:
                    if event.button == 1 and self.geopolitical_panel_close_rect.collidepoint(event.pos):
                        self.close_geopolitical_panel()
                    continue
                if self.phase in ("playing", "shopping") and event.button == 1 and self.geopolitical_button_rect.collidepoint(event.pos):
                    self.open_geopolitical_panel()
                    return
                if self.phase in ("playing", "shopping") and self.details_button_rect.collidepoint(event.pos):
                    if event.button == 1:
                        self.handle_details_button_left_click()
                        return
                    if event.button == 3:
                        self.pending_details_click_time = None
                        self.toggle_hover_details()
                        return
                if self.phase in ("playing", "shopping") and event.button == 1 and self.all_icons_button_rect.collidepoint(event.pos):
                    self.toggle_all_map_icons()
                    return
                if self.phase == "start_menu" and event.button == 1:
                    self.handle_start_menu_click(event.pos)
                    continue
                if self.phase == "map_editor" and event.button == 1:
                    self.handle_custom_editor_click(event.pos)
                    continue
                if self.phase == "map_editor" and event.button == 3:
                    continue
                if self.phase == "shopping" and event.button == 1:
                    self.handle_shop_click(event.pos)
                    continue
                if self.phase == "playing" and event.button in (1, 3):
                    if event.button == 1 and self.save_map_rect.collidepoint(event.pos):
                        save_name = self.save_current_map_to_file()
                        self.show_message(f"Carte sauvegardee : {save_name}", 2200)
                        return
                    if event.button == 1 and self.save_game_rect.collidepoint(event.pos):
                        save_name = self.save_current_game_to_file()
                        self.show_message(f"Partie sauvegardee : {save_name}", 2200)
                        return
                    if event.button == 1 and self.auto_mode_rect.collidepoint(event.pos) and self.can_toggle_auto_mode(self.current_player):
                        self.toggle_current_player_auto_mode()
                        return
                    if self.fast_ai_rect.collidepoint(event.pos):
                        if event.button == 3:
                            self.toggle_instant_ai_movements()
                        else:
                            self.toggle_fast_ai_movements()
                        return
                if self.phase == "playing" and not ai_turn:
                    if event.button == 1:
                        if self.end_turn_rect.collidepoint(event.pos):
                            self.handle_end_turn_action()
                            return
                        if self.turn_phase == "move" and getattr(event, "clicks", 1) >= 2:
                            destination = self.get_territory_at_pos(event.pos)
                            if destination is not None:
                                self.move_random_regiments_to_territory(destination)
                            return
                        self.handle_left_click(event.pos)
                    elif event.button == 3:
                        self.handle_right_click(event.pos)
                elif self.phase == "game_over" and event.button == 1:
                    if self.replay_rect.collidepoint(event.pos):
                        self.start_replay()
                        return
                    if self.restart_rect.collidepoint(event.pos):
                        self.restart_game()
                        return
                elif self.phase == "replay" and event.button == 1:
                    if self.replay_pause_rect.collidepoint(event.pos):
                        self.toggle_replay_pause()
                        return
                    if self.replay_return_rect.collidepoint(event.pos):
                        self.stop_replay()
                        return
            elif event.type == pygame.MOUSEMOTION:
                self.update_hovered_territory(event.pos)
                if self.phase == "map_editor" and self.custom_dragging_territory_id is not None:
                    self.update_custom_drag(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP:
                if self.phase == "map_editor" and event.button == 1 and self.custom_dragging_territory_id is not None:
                    self.stop_custom_drag()
            elif event.type == pygame.KEYDOWN:
                ctrl_pressed = bool(event.mod & (pygame.KMOD_CTRL | pygame.KMOD_META))
                if event.key == pygame.K_F11 or (event.key == pygame.K_p and ctrl_pressed):
                    self.toggle_fullscreen()
                    continue
                if self.phase in ("playing", "shopping") and self.empire_panel_visible and not ai_turn and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self.close_empire_panel()
                    continue
                if self.phase == "playing" and self.geopolitical_panel_visible and not ai_turn and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self.close_geopolitical_panel()
                    continue
                if self.phase == "map_editor" and event.key == pygame.K_DELETE and self.custom_selected_territory_id is not None:
                    self.remove_custom_territory(self.custom_selected_territory_id)
                    continue
                if self.phase == "shopping" and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self.finish_shopping_phase()
                    continue
                if self.phase == "playing" and not ai_turn and event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    self.handle_end_turn_action()
                    continue
                if self.phase == "game_over" and event.key == pygame.K_r:
                    self.start_replay()
                    continue
                if self.phase == "replay" and event.key == pygame.K_SPACE:
                    self.toggle_replay_pause()
                    continue
                if self.phase == "replay" and event.key == pygame.K_ESCAPE:
                    self.stop_replay()

    def get_territory_at_pos(self, pos: Tuple[int, int]) -> Optional[Territory]:
        x, y = pos
        if y < self.map_top:
            return None
        col = int(x // self.cell_width)
        row = int((y - self.map_top) // self.cell_height)
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return None
        tid = self.grid_territory[row][col]
        if tid < 0 or tid >= len(self.territories):
            return None
        return self.territories[tid]

    def update_hovered_territory(self, pos: Tuple[int, int]) -> None:
        territory = self.get_territory_at_pos(pos)
        self.hovered_territory_id = territory.id if territory is not None else None
        self.hovered_territory_pos = pos

    def get_owner_label(self, owner: int) -> str:
        if self.is_onu_player(owner):
            return "ONU"
        if owner < 0:
            return "aucun"
        label = f"J{owner + 1}"
        for tid, player in getattr(self, "vassal_players", {}).items():
            if player == owner:
                overlord = self.get_vassal_overlord(tid)
                suffix = f" de J{overlord + 1}" if overlord is not None else ""
                return f"{label} - Vassal{suffix}"
        if self.is_commercial_city_player(owner):
            return f"{label} - Cite commercante"
        if self.is_ai_player(owner):
            return f"{label} - IA"
        return f"{label} - humain"

    def build_territory_tooltip_lines(self, territory: Territory) -> List[Tuple[str, Tuple[int, int, int]]]:
        muted = (190, 198, 205)
        normal = (236, 240, 241)
        accent = (255, 232, 150)
        warning = (255, 190, 150)
        good = (185, 230, 190)
        lines: List[Tuple[str, Tuple[int, int, int]]] = []

        lines.append((f"{territory.name}  |  {self.get_owner_label(territory.owner)}", accent))
        lines.append((f"Troupes : {territory.regiments} regiment(s)", normal))
        if self.is_vassal_territory(territory.id):
            overlord = self.get_vassal_overlord(territory.id)
            created_turn = self.vassal_territory_created_turns.get(territory.id, self.turn)
            remaining = max(0, self.VASSAL_INTEGRATION_DELAY_TURNS - (self.turn - created_turn))
            if overlord is not None:
                lines.append((f"Vassal de J{overlord + 1} : integration dans {remaining} tour(s)", good))
        elif self.is_submitted_territory(territory.id):
            overlord = self.get_submitted_territory_overlord(territory.id)
            if overlord is not None:
                lines.append((f"Tribut verse a J{overlord + 1} : {self.calculate_submitted_territory_income(territory)} ecu(s)/tour", good))
        elif territory.owner >= 0 and not self.is_onu_player(territory.owner):
            lines.append((f"Revenu du territoire : {self.calculate_territory_income(territory)} ecu(s)/tour", good))
        if territory.reinforcement_bonus > 1:
            lines.append((f"Renfort : +{territory.reinforcement_bonus} par tour", good))
        else:
            lines.append(("Renfort : +1 par tour", muted))
        if territory.id in self.precious_mineral_mine_ids:
            lines.append((f"Mine de minerais precieux : +{self.PRECIOUS_MINERAL_MINE_INCOME} ecus par tour", good))

        statuses: List[str] = []
        if territory.id in self.golden_territory_ids:
            statuses.append("territoire dore")
        if self.is_vassal_territory(territory.id):
            overlord = self.get_vassal_overlord(territory.id)
            if overlord is not None:
                statuses.append(f"vassal de J{overlord + 1}")
            else:
                statuses.append("vassal")
        elif self.is_submitted_territory(territory.id):
            overlord = self.get_submitted_territory_overlord(territory.id)
            if overlord is not None:
                statuses.append(f"territoire soumis a J{overlord + 1}")
            else:
                statuses.append("territoire soumis")
        elif self.is_sanctuary_territory(territory.id):
            statuses.append("sanctuaire ONU")
        if self.is_active_regular_capital(territory.id):
            statuses.append("capitale active, revenu x10")
        elif self.is_regular_capital_territory(territory.id):
            original_owner = self.get_regular_capital_owner(territory.id)
            if original_owner is not None:
                statuses.append(f"ancienne capitale de J{original_owner + 1}")
        if self.is_commercial_city_territory(territory.id):
            statuses.append("capitale de Cite commercante")
        if self.is_last_stand_bonus_territory(territory.id):
            statuses.append("paradis fiscal, revenu x10")
        if statuses:
            lines.append(("Statut : " + ", ".join(statuses), warning))

        structures: List[str] = []
        if territory.id in self.fortress_territory_ids:
            count = self.fortress_capture_counts.get(territory.id, 0)
            structures.append(f"forteresse ({count}/3 captures)")
        if territory.id in self.precious_mineral_mine_ids:
            structures.append("mine de minerais precieux")
        industrial_labels = {
            "factory": "usine",
            "airport": "aeroport",
            "port": "port",
        }
        industrial_type = self.get_industrial_structure_type(territory.id)
        if industrial_type:
            count = self.industrial_capture_counts.get(territory.id, 0)
            structures.append(f"{industrial_labels.get(industrial_type, industrial_type)} ({count}/3 captures)")
        if territory.id in getattr(self, "temple_territory_ids", set()):
            count = self.temple_capture_counts.get(territory.id, 0)
            structures.append(f"temple ({count}/3 captures, aucun effet pour le moment)")
        cultural_count = self.get_cultural_center_count(territory.id)
        if cultural_count:
            ages = self.cultural_center_ages.get(territory.id, [])
            age_label = ", ".join(str(age) for age in ages)
            count = self.cultural_capture_counts.get(territory.id, 0)
            plural = "s" if cultural_count > 1 else ""
            structures.append(f"centre{plural} culturel{plural} x{cultural_count}, age {age_label} ({count}/3 captures)")
        if territory.id in self.university_territory_ids:
            count = self.university_capture_counts.get(territory.id, 0)
            age = self.university_ages.get(territory.id, 0)
            science_output = self.get_university_science_output(territory.id)
            structures.append(f"universite, age {age}, science +{science_output}/tour ({count}/3 captures)")
        if structures:
            lines.append(("Amenagements :", normal))
            for item in structures:
                lines.append((f"- {item}", muted))
        else:
            lines.append(("Amenagements : aucun", muted))

        wonder_type = self.get_wonder_type_at_territory(territory.id)
        if wonder_type is not None:
            lines.append((f"Merveille : {self.get_wonder_name(wonder_type)}", accent))
            lines.append((self.get_wonder_effect(wonder_type), good))

        culture = self.calculate_territory_culture(territory)
        if culture:
            lines.append((f"Culture produite : {culture}", good))
        science = self.calculate_territory_science(territory)
        if science:
            lines.append((f"Science produite : {science}", good))
        lines.append((f"Voisins : {len(territory.neighbors)}", muted))
        return lines

    def draw_wrapped_tooltip_line(
        self,
        text: str,
        color: Tuple[int, int, int],
        x: int,
        y: int,
        max_width: int,
    ) -> int:
        words = text.split(" ")
        current = ""
        line_height = self.font_small.get_height() + 3
        for word in words:
            candidate = word if not current else current + " " + word
            if self.font_small.size(candidate)[0] <= max_width:
                current = candidate
                continue
            if current:
                rendered = self.font_small.render(current, True, color)
                self.screen.blit(rendered, (x, y))
                y += line_height
            current = word
        if current:
            rendered = self.font_small.render(current, True, color)
            self.screen.blit(rendered, (x, y))
            y += line_height
        return y

    def draw_territory_tooltip(self) -> None:
        if not self.hover_details_enabled:
            return
        if self.phase not in ("playing", "shopping"):
            return
        if self.geopolitical_panel_visible or self.empire_panel_visible:
            return
        mouse_pos = pygame.mouse.get_pos()
        if self.phase == "shopping" and not self.shop_panel_collapsed and self.shop_panel_rect.collidepoint(mouse_pos):
            return
        territory = self.get_territory_at_pos(mouse_pos)
        if territory is None:
            return

        lines = self.build_territory_tooltip_lines(territory)
        max_text_width = min(360, max(260, self.WIDTH // 3))
        line_height = self.font_small.get_height() + 3
        wrapped_line_count = 0
        for text, _color in lines:
            words = text.split(" ")
            current = ""
            count_for_line = 0
            for word in words:
                candidate = word if not current else current + " " + word
                if self.font_small.size(candidate)[0] <= max_text_width:
                    current = candidate
                else:
                    count_for_line += 1
                    current = word
            wrapped_line_count += max(1, count_for_line + (1 if current else 0))

        tooltip_width = max_text_width + 24
        tooltip_height = 18 + wrapped_line_count * line_height
        x = mouse_pos[0] + 18
        y = mouse_pos[1] + 18
        if x + tooltip_width > self.WIDTH - 8:
            x = mouse_pos[0] - tooltip_width - 18
        if y + tooltip_height > self.HEIGHT - 8:
            y = mouse_pos[1] - tooltip_height - 18
        x = max(8, min(self.WIDTH - tooltip_width - 8, x))
        y = max(self.map_top + 8, min(self.HEIGHT - tooltip_height - 8, y))

        tooltip_rect = pygame.Rect(x, y, tooltip_width, tooltip_height)
        shadow_rect = tooltip_rect.move(3, 3)
        shadow = pygame.Surface((shadow_rect.width, shadow_rect.height), pygame.SRCALPHA)
        shadow.fill((0, 0, 0, 115))
        self.screen.blit(shadow, shadow_rect.topleft)
        pygame.draw.rect(self.screen, (20, 31, 46), tooltip_rect, border_radius=8)
        pygame.draw.rect(self.screen, (230, 235, 240), tooltip_rect, width=1, border_radius=8)

        cursor_y = y + 9
        text_x = x + 12
        for text, color in lines:
            cursor_y = self.draw_wrapped_tooltip_line(text, color, text_x, cursor_y, max_text_width)

    def select_attack_source(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Vous devez choisir un de vos territoires.")
            return
        if terr.regiments < 2:
            self.show_message("Il faut au moins 2 regiments pour attaquer.")
            return
        if not any(self.territories[n].owner != self.current_player for n in terr.neighbors):
            self.show_message("Pas d'ennemis adjacents sur ce territoire.")
            return
        self.selected_source = terr.id
        self.selected_target = None
        self.show_message(f"Source {terr.name} selectionnee. Clic gauche = une attaque, clic droit = attaque jusqu'au bout.")

    def can_move_between(self, src: Territory, dst: Territory) -> bool:
        return moteur_regles.can_move_between(self, src, dst)

    def select_move_source(self, terr: Territory) -> None:
        if terr.owner != self.current_player:
            self.show_message("Vous devez choisir un de vos territoires.")
            return
        if terr.regiments < 2:
            self.show_message("Il faut laisser au moins 1 regiment sur le territoire d'origine.")
            return
        self.selected_source = terr.id
        self.selected_target = None
        self.show_message(f"Source de deplacement : {terr.name}. Clic droit sur un territoire allie connecte = 1 regiment deplace.")

    def move_random_regiments_to_territory(self, dst: Territory) -> bool:
        """Concentre au hasard le maximum de regiments autorise sur un territoire.

        Chaque regiment excedentaire disponible sur un territoire source constitue
        une chance de tirage. Les territoires les plus garnis contribuent donc au
        deplacement au prorata de leurs effectifs, tout en conservant une garnison
        minimale d'un regiment et la continuite territoriale habituelle.
        """
        move_limit = self.get_end_turn_move_limit()
        remaining = move_limit - self.turn_move_count
        if remaining <= 0:
            self.show_message(f"Limite atteinte : maximum {move_limit} regiments deplaces en fin de tour.")
            return False
        if dst.owner != self.current_player:
            self.show_message("Le territoire de destination doit vous appartenir.")
            return False

        moved_by_source: dict[int, int] = {}
        moved = 0
        while moved < remaining:
            weighted_sources: list[Territory] = []
            for src in self.territories:
                if (
                    src.owner == self.current_player
                    and src.id != dst.id
                    and src.regiments > 1
                    and self.can_move_between(src, dst)
                ):
                    weighted_sources.extend([src] * (src.regiments - 1))
            if not weighted_sources:
                break
            src = random.choice(weighted_sources)
            src.regiments -= 1
            dst.regiments += 1
            moved += 1
            self.turn_move_count += 1
            moved_by_source[src.id] = moved_by_source.get(src.id, 0) + 1

        if moved <= 0:
            self.show_message("Aucun regiment disponible sur un autre territoire allie relie.", 2200)
            return False

        self.selected_source = None
        self.selected_target = dst.id
        sources = ", ".join(
            f"{self.territories[tid].name} ({count})"
            for tid, count in sorted(moved_by_source.items())
        )
        if self.turn_move_count >= move_limit and self.phase == "playing" and self.turn_phase == "move" and not self.is_ai_player(self.current_player):
            self.complete_turn()
            self.show_message(
                f"{moved} regiment(s) concentre(s) sur {dst.name} depuis {sources}. Fin de tour automatique.",
                3000,
            )
        else:
            restant = move_limit - self.turn_move_count
            self.show_message(
                f"{moved} regiment(s) concentre(s) sur {dst.name} depuis {sources}. Reste {restant} deplacement(s).",
                2800,
            )
        return True

    def move_one_regiment(self, src: Territory, dst: Territory) -> bool:
        move_limit = self.get_end_turn_move_limit()
        ok, code = moteur_regles.move_one_regiment(self, src, dst)
        if not ok:
            refusal_messages = {
                "limite": f"Limite atteinte : maximum {move_limit} regiments deplaces en fin de tour.",
                "proprietaire": "Le deplacement ne peut se faire qu'entre deux territoires allies.",
                "meme_territoire": "Choisissez un territoire de destination different.",
                "garnison": "Impossible : il doit rester au moins 1 regiment sur le territoire d'origine.",
                "continuite": "Deplacement impossible : les deux territoires doivent etre relies par une continuite de territoires allies.",
            }
            self.show_message(refusal_messages[code])
            return False
        self.selected_target = dst.id
        restant = move_limit - self.turn_move_count
        self.show_message(f"1 regiment deplace de {src.name} vers {dst.name}. Reste {restant} deplacement(s).", 1200)
        if self.turn_move_count >= move_limit and self.phase == "playing" and self.turn_phase == "move" and not self.is_ai_player(self.current_player):
            self.complete_turn()
            self.show_message(f"{move_limit} deplacements effectues : fin de tour automatique.", 2200)
        return True

    def shortest_owned_path(self, start_id: int, target_id: int, owner: int) -> Optional[List[int]]:
        if start_id == target_id:
            return [start_id]
        from collections import deque

        queue = deque([start_id])
        previous: dict[int, Optional[int]] = {start_id: None}
        while queue:
            current = queue.popleft()
            for neighbor_id in self.territories[current].neighbors:
                neighbor = self.territories[neighbor_id]
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

    def compute_ai_move_target(self) -> Optional[Tuple[Territory, Territory]]:
        behavior = self.get_ai_behavior(self.current_player)
        current_is_commercial = self.current_player in getattr(self, "commercial_city_players", set())
        frontline_enemies = [
            enemy for enemy in self.territories
            if enemy.owner != self.current_player
            and not (current_is_commercial and self.is_any_capital_territory(enemy.id))
            and not self.is_attack_blocked_by_alliance(self.current_player, enemy.owner)
            and any(self.territories[n].owner == self.current_player for n in enemy.neighbors)
        ]
        offensive_target = self.get_offensive_alliance_target_for_ai(self.current_player)
        if offensive_target is not None:
            targeted_frontline = [enemy for enemy in frontline_enemies if enemy.owner == offensive_target]
            if targeted_frontline:
                frontline_enemies = targeted_frontline
                behavior = "aggressive"

        if not frontline_enemies:
            return None

        if behavior == "aggressive":
            target_enemy = max(frontline_enemies, key=lambda terr: (terr.owner == offensive_target, terr.regiments, len(terr.neighbors), -terr.id))
        elif behavior == "defensive":
            owned_borders = [
                terr for terr in self.territories
                if terr.owner == self.current_player
                and any(self.territories[n].owner != self.current_player for n in terr.neighbors)
            ]
            if not owned_borders:
                return None
            weakest_border = min(owned_borders, key=lambda terr: (terr.regiments, terr.id))
            enemy_neighbors = [
                self.territories[n]
                for n in weakest_border.neighbors
                if self.territories[n].owner != self.current_player
                and not (current_is_commercial and self.is_any_capital_territory(n))
                and not self.is_attack_blocked_by_alliance(self.current_player, self.territories[n].owner)
            ]
            if not enemy_neighbors:
                return None
            target_enemy = max(enemy_neighbors, key=lambda terr: (terr.regiments, -terr.id))
        else:
            target_enemy = max(frontline_enemies, key=lambda terr: (terr.regiments, -terr.id))

        border_candidates = [
            self.territories[nid]
            for nid in target_enemy.neighbors
            if self.territories[nid].owner == self.current_player
        ]
        if not border_candidates:
            return None

        best_border: Optional[Tuple[Tuple[int, int, int, int], Territory]] = None
        for border in border_candidates:
            reachable_sources = [
                src for src in self.territories
                if src.owner == self.current_player
                and src.regiments > 1
                and src.id != border.id
                and self.can_move_between(src, border)
            ]
            movable_total = sum(src.regiments - 1 for src in reachable_sources)
            if behavior == "aggressive":
                score = (movable_total, target_enemy.regiments, -border.regiments, -border.id)
            elif behavior == "defensive":
                pressure = sum(self.territories[n].regiments for n in border.neighbors if self.territories[n].owner != self.current_player and not self.is_attack_blocked_by_alliance(self.current_player, self.territories[n].owner))
                score = (pressure, -border.regiments, movable_total, -border.id)
            else:
                score = (movable_total, -border.regiments, target_enemy.regiments, -border.id)
            if best_border is None or score > best_border[0]:
                best_border = (score, border)

        if best_border is None or best_border[0][0] <= 0:
            return None
        return target_enemy, best_border[1]

    def compute_ai_move_sources(self, border_id: int) -> List[Tuple[Territory, int]]:
        border = self.territories[border_id]
        candidates: List[Tuple[Tuple[int, int, int], Territory, int]] = []
        for src in self.territories:
            if src.owner != self.current_player or src.regiments <= 1 or src.id == border_id:
                continue
            path = self.shortest_owned_path(src.id, border_id, self.current_player)
            if path is None:
                continue
            movable = src.regiments - 1
            distance = len(path) - 1
            score = (movable, -distance, -src.id)
            candidates.append((score, src, movable))

        candidates.sort(reverse=True, key=lambda item: item[0])
        return [(src, movable) for _, src, movable in candidates]

    def execute_ai_move_phase(self) -> bool:
        move_limit = self.get_end_turn_move_limit()
        if self.turn_move_count >= move_limit:
            return False
        move_target = self.compute_ai_move_target()
        if move_target is None:
            return False

        target_enemy, border = move_target
        sources = self.compute_ai_move_sources(border.id)
        if not sources:
            return False

        moved = 0
        used_sources: List[str] = []
        remaining = move_limit - self.turn_move_count
        for src, movable in sources:
            if remaining <= 0:
                break
            to_move = min(remaining, movable)
            moved_from_source = 0
            while moved_from_source < to_move and self.turn_move_count < move_limit and src.regiments > 1:
                if not self.move_one_regiment(src, border):
                    break
                moved_from_source += 1
                moved += 1
                remaining -= 1
            if moved_from_source > 0:
                used_sources.append(f"{src.name} ({moved_from_source})")

        if moved <= 0:
            return False

        self.selected_source = None
        self.selected_target = border.id
        sources_text = ", ".join(used_sources[:3])
        if len(used_sources) > 3:
            sources_text += ", ..."
        self.show_message(
            f"Ordinateur J{self.current_player + 1} ({self.get_ai_profile_label(self.current_player)}): {moved} regiment(s) deplaces vers {border.name}, au contact de {target_enemy.name} ({target_enemy.regiments} regiments). Sources: {sources_text}.",
            max(1, self.get_ai_action_delay_ms() - 100),
        )
        return True

    def handle_left_click(self, pos: Tuple[int, int]) -> None:
        terr = self.get_territory_at_pos(pos)
        if terr is None:
            self.selected_target = None
            return
        if self.turn_phase == "move":
            self.select_move_source(terr)
            return
        if self.is_colonized_player(self.current_player):
            self.show_message("Joueur colonise : aucune attaque possible jusqu'a la decolonisation.", 2400)
            return
        if terr.owner == self.current_player:
            self.select_attack_source(terr)
            return
        if self.selected_source is None:
            self.show_message("Choisissez d'abord votre territoire attaquant.")
            return
        src = self.territories[self.selected_source]
        if terr.id not in src.neighbors or terr.owner == self.current_player:
            self.show_message("Choisissez une cible ennemie adjacente.")
            return
        self.selected_target = terr.id
        self.resolve_attack_once_and_refresh(src, terr)

    def handle_right_click(self, pos: Tuple[int, int]) -> None:
        terr = self.get_territory_at_pos(pos)
        if terr is None:
            return
        if self.selected_source is None:
            if self.turn_phase == "move":
                self.show_message("Choisissez d'abord le territoire source avec un clic gauche.")
            else:
                self.show_message("Choisissez d'abord votre territoire attaquant avec un clic gauche.")
            return
        src = self.territories[self.selected_source]
        if self.turn_phase == "move":
            self.move_one_regiment(src, terr)
            return
        if self.is_colonized_player(self.current_player):
            self.show_message("Joueur colonise : aucune attaque possible jusqu'a la decolonisation.", 2400)
            return
        if terr.id not in src.neighbors:
            self.show_message("La cible doit etre voisine du territoire source.")
            return
        if terr.owner == self.current_player:
            self.show_message("La cible doit appartenir a un ennemi.")
            return
        self.selected_target = terr.id
        self.resolve_attack_until_end(src, terr)

    def restart_game(self) -> None:
        # Recommence sur la carte actuelle. Regenerer ici cassait les cartes personnalisees
        # et pouvait rendre le bouton inoperant selon le mode de carte utilise.
        # On revient en revanche au nombre de joueurs choisi au debut : les joueurs
        # apparus en cours de partie ne deviennent pas des fondateurs par magie.
        if not self.territories:
            self.generate_grid_map()

        self.num_players = self.initial_num_players or self.num_players
        self.ai_player_count = self.initial_ai_player_count or self.ai_player_count
        self.base_ai_players = set(range(self.ai_player_count))
        self.auto_controlled_players = set()
        self.commercial_city_players = set()
        self.commercial_city_capital_ids = {}
        self.player_capital_ids = {}
        self.pending_commercial_city_spawns = 0
        self.nation_players = set()
        self.nation_qualification_start_turns = {}
        self.nation_capital_loss_start_turns = {}
        self.nation_alliances = set()
        self.nation_wars = set()
        self.cold_war_active = False
        self.cold_war_nations = None
        self.cold_war_alliances = {}
        self.colonized_players = set()
        self.submitted_territory_ids = set()
        self.submitted_territory_overlords = {}
        self.submitted_territory_created_turns = {}
        self.vassal_territory_overlords = {}
        self.vassal_territory_created_turns = {}
        self.vassal_players = {}
        self.integrated_vassal_territories = {}
        self.integrated_submitted_territories = {}
        self.union_members = {}
        self.union_original_territories = {}
        self.final_duel_active = False
        self.final_duel_champions = None
        self.final_duel_alliances = {}
        self.final_duel_pending_winner = None
        self.assign_ai_personalities()

        for terr in self.territories:
            terr.owner = -1
            terr.regiments = 0
        self.eliminated_human_players = set()
        self.human_controlled_players = set()
        self.prepare_initial_commercial_cities()
        self.assign_initial_ownership_and_armies()
        self.assign_random_bonus_territories()
        self.assign_golden_territories()
        self.assign_sanctuary_territories()
        self.reset_economy_state()
        self.assign_initial_economic_structures()
        self.last_victory_reason = ""
        self.victory_winner = None
        self.victory_summary = {}
        self.replay_history = []
        self.replay_restore_state = None
        self.confetti_particles = []
        self.current_player = 0
        self.turn = 1
        self.selected_source = None
        self.selected_target = None
        self.phase = "playing"
        self.turn_phase = "attack"
        self.turn_move_count = 0
        self.geopolitical_panel_visible = False
        self.geopolitical_panel_page = 0
        self.empire_panel_visible = False
        self.empire_panel_page = 0
        self.last_empire_event_turn = 0
        self.snapshot_tax_haven_turn_start_territory_counts()
        self.record_replay_snapshot("Debut de la partie", force=True)
        self.show_message("Nouvelle partie", 2000)
        self.begin_player_turn(self.current_player)

    def can_attack_specific_target(self, src: Territory, dst: Territory) -> bool:
        return moteur_regles.can_attack_specific_target(self, src, dst)

    def resolve_attack_once_and_refresh(self, src: Territory, dst: Territory) -> None:
        if not self.can_attack_specific_target(src, dst):
            self.show_message("Attaque impossible.")
            return
        att_text, def_text, conquered = self.resolve_attack_once(src, dst)
        self.selected_target = dst.id if self.can_attack_specific_target(src, dst) else None
        self.selected_source = src.id if (not conquered and self.can_attack_specific_target(src, dst)) else None

        winner = self.check_winner()
        if winner is not None:
            self.declare_victory(winner)
            return
        if conquered:
            if self.last_special_conquest_message:
                self.show_message(self.last_special_conquest_message, 5200)
            else:
                prefix = (self.last_alliance_break_message + " ") if self.last_alliance_break_message else ""
                self.show_message(prefix + f"{src.name} conquiert {dst.name}.", 2600)
        else:
            prefix = (self.last_alliance_break_message + " ") if self.last_alliance_break_message else ""
            self.show_message(prefix + f"Attaque simple sur {dst.name} : {att_text} contre {def_text}.", 2200)

    def resolve_attack_until_end(self, src: Territory, dst: Territory) -> None:
        last_att = None
        last_def = None
        conquered = False
        while self.phase == "playing" and self.can_attack_specific_target(src, dst):
            last_att, last_def, conquered = self.resolve_attack_once(src, dst)
            if conquered or not self.can_attack_specific_target(src, dst):
                break
        self.selected_source = None
        self.selected_target = None

        winner = self.check_winner()
        if winner is not None:
            self.declare_victory(winner)
            return
        if conquered:
            if self.last_special_conquest_message:
                self.show_message(self.last_special_conquest_message, 5200)
            else:
                prefix = (self.last_alliance_break_message + " ") if self.last_alliance_break_message else ""
                self.show_message(prefix + f"{src.name} conquiert {dst.name}.", 2800)
        elif last_att is not None and last_def is not None:
            prefix = (self.last_alliance_break_message + " ") if self.last_alliance_break_message else ""
            self.show_message(prefix + f"Fin de l'assaut sur {dst.name}. Dernier duel : {last_att} contre {last_def}.", 2800)

    def resolve_attack_once(self, src: Territory, dst: Territory) -> Tuple[str, str, bool]:
        result = moteur_regles.resolve_attack_once(
            self, src, dst,
            submit_decider=self.ask_human_submission_choice,
        )
        self.last_special_conquest_message = result.special_conquest_message
        self.last_alliance_break_message = result.alliance_break_message
        if result.conquered and dst.owner == self.onu_player_id:
            # Territoire soumis a l'ONU : meme nettoyage de selection que
            # l'ancien submit_conquered_territory.
            if self.selected_source == dst.id:
                self.selected_source = None
            if self.selected_target == dst.id:
                self.selected_target = None
        if result.elimination_message:
            self.show_message(result.elimination_message, 3500)
        return result.att_text, result.def_text, result.conquered

    def ai_attack_score(self, src: Territory, dst: Territory, behavior: str) -> Optional[Tuple[Tuple[int, int, int, int, int], bool]]:
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
            total_attack = diff >= 6 or (src.regiments >= 8 and random.random() < 0.18)
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
            enemy_pressure = sum(self.territories[n].regiments for n in src.neighbors if self.territories[n].owner != self.current_player and not self.is_attack_blocked_by_alliance(self.current_player, self.territories[n].owner))
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

    def find_ai_attack(self) -> Optional[Tuple[Territory, Territory, bool]]:
        if self.is_colonized_player(self.current_player):
            return None
        current_is_commercial = self.is_commercial_city_player(self.current_player)
        exclusive_wonder_ally = (
            self.get_commercial_city_wonder_ally()
            if current_is_commercial
            else None
        )
        if (
            current_is_commercial
            and exclusive_wonder_ally is None
            and self.count_player_territories(self.current_player) >= self.COMMERCIAL_CITY_TERRITORY_LIMIT
        ):
            return None
        behavior = self.get_ai_behavior(self.current_player)
        if exclusive_wonder_ally is not None:
            # Sans cela, le profil simplement "agressif" lance souvent un seul duel,
            # perd un regiment puis ne trouve plus d'attaque admissible. Avec le Palais,
            # la CC doit agir comme une puissance offensive contre tous sauf son unique allie.
            behavior = "very_aggressive"
        offensive_target = self.get_offensive_alliance_target_for_ai(self.current_player)
        if offensive_target is not None:
            behavior = "very_aggressive"
        candidates: List[Tuple[Tuple[int, int, int, int, int], Territory, Territory, bool]] = []

        for src in self.territories:
            if src.owner != self.current_player:
                continue

            for neighbor_id in src.neighbors:
                dst = self.territories[neighbor_id]
                if dst.owner == self.current_player:
                    continue
                if current_is_commercial and self.is_any_capital_territory(dst.id):
                    continue
                if offensive_target is not None and dst.owner != offensive_target:
                    continue
                if self.is_attack_blocked_by_alliance(self.current_player, dst.owner):
                    continue
                if self.is_ai_attack_blocked_by_culture(self.current_player, dst.owner):
                    continue
                if self.is_submitted_territory(dst.id):
                    continue
                if self.is_sanctuary_territory(dst.id) and src.regiments < 40:
                    # Les IA ignorent les sanctuaires ONU, sauf si le territoire attaquant
                    # adjacent concentre au moins 40 regiments. A ce stade, visiblement,
                    # la diplomatie est remplacee par un gros tas de soldats.
                    continue
                scored = self.ai_attack_score(src, dst, behavior)
                if scored is None:
                    continue
                score, total_attack = scored
                candidates.append((score, src, dst, total_attack))

        if not candidates:
            return None
        best_move = max(candidates, key=lambda item: item[0])
        return best_move[1], best_move[2], best_move[3]

    def normalize_ai_speed_mode(self) -> None:
        if getattr(self, "ai_speed_mode", "normal") not in ("normal", "fast", "instant"):
            self.ai_speed_mode = "instant" if getattr(self, "fast_ai_movements", False) else "normal"
        self.fast_ai_movements = self.ai_speed_mode == "instant"

    def get_ai_initial_delay_ms(self) -> int:
        self.normalize_ai_speed_mode()
        if self.ai_speed_mode == "instant":
            return 0
        if self.ai_speed_mode == "fast":
            return 120
        return 350

    def get_ai_action_delay_ms(self) -> int:
        self.normalize_ai_speed_mode()
        if self.ai_speed_mode == "instant":
            return 0
        if self.ai_speed_mode == "fast":
            return self.AI_FAST_ACTION_DELAY_MS
        return self.AI_ACTION_DELAY_MS

    def get_ai_message_duration_ms(self, extra_ms: int = 0) -> int:
        self.normalize_ai_speed_mode()
        if self.ai_speed_mode == "instant":
            return max(1, extra_ms)
        return max(1, self.get_ai_action_delay_ms() + extra_ms)

    def get_ai_speed_label(self) -> str:
        self.normalize_ai_speed_mode()
        labels = {
            "normal": "IA normale",
            "fast": "IA rapide",
            "instant": "IA acceleree",
        }
        return labels.get(self.ai_speed_mode, "IA normale")

    def set_ai_speed_mode(self, mode: str) -> None:
        if mode not in ("normal", "fast", "instant"):
            mode = "normal"
        self.ai_speed_mode = mode
        self.fast_ai_movements = self.ai_speed_mode == "instant"
        if self.phase == "playing" and self.is_ai_player(self.current_player):
            self.ai_next_action_time = pygame.time.get_ticks() + self.get_ai_initial_delay_ms()
        descriptions = {
            "normal": "vitesse normale",
            "fast": "mode rapide visible",
            "instant": "mode accelere maximal",
        }
        self.show_message(f"Mouvements IA : {descriptions[self.ai_speed_mode]}.", 1800)

    def toggle_fast_ai_movements(self) -> None:
        self.normalize_ai_speed_mode()
        # Clic gauche : bascule lisible et reversible entre normal et rapide.
        # Avant, le clic sur "IA rapide" envoyait vers "IA acceleree", ce qui est
        # exactement le genre de piege UX qui fait croire que les boutons ont une opinion.
        next_mode = "normal" if self.ai_speed_mode == "fast" else "fast"
        self.set_ai_speed_mode(next_mode)

    def toggle_instant_ai_movements(self) -> None:
        self.normalize_ai_speed_mode()
        # Clic droit : conserve l'ancien mode accelere maximal, sans bloquer le retour.
        next_mode = "normal" if self.ai_speed_mode == "instant" else "instant"
        self.set_ai_speed_mode(next_mode)

    def process_ai_turn(self) -> None:
        if self.phase != "playing" or not self.is_ai_player(self.current_player):
            return
        now = pygame.time.get_ticks()
        if now < self.ai_next_action_time:
            return

        if self.ai_state == "announce":
            offensive_target = self.get_offensive_alliance_target_for_ai(self.current_player)
            offensive_note = f" -> cible J{offensive_target + 1}" if offensive_target is not None else ""
            self.show_message(f"Tour du joueur ordinateur {self.current_player + 1} ({self.get_ai_profile_label(self.current_player)}{offensive_note})...", max(1, self.get_ai_action_delay_ms() - 100))
            self.ai_state = "acting"
            self.ai_next_action_time = now + self.get_ai_action_delay_ms()
            return

        if self.ai_state == "acting":
            move = self.find_ai_attack()
            if move is None:
                self.start_move_phase()
                self.ai_state = "moving"
                self.ai_next_action_time = now + self.get_ai_action_delay_ms()
                return

            src, dst, total_attack = move
            self.selected_source = src.id
            self.selected_target = dst.id

            if total_attack:
                self.resolve_attack_until_end(src, dst)
            else:
                att_text, def_text, conquered = self.resolve_attack_once(src, dst)

                winner = self.check_winner()
                if winner is not None:
                    self.declare_victory(winner)
                    return

                if conquered:
                    if self.last_special_conquest_message:
                        self.show_message(self.last_special_conquest_message, self.get_ai_message_duration_ms(1200))
                    else:
                        self.show_message(
                            f"Ordinateur J{self.current_player + 1} ({self.get_ai_profile_label(self.current_player)}): {src.name} ({att_text}) conquiert {dst.name} ({def_text}).",
                            max(1, self.get_ai_action_delay_ms() - 100),
                        )
                    self.selected_source = None
                    self.selected_target = None
                else:
                    self.show_message(
                        f"Ordinateur J{self.current_player + 1} ({self.get_ai_profile_label(self.current_player)}): {src.name} attaque {dst.name} - {att_text} contre {def_text}.",
                        max(1, self.get_ai_action_delay_ms() - 100),
                    )

            self.ai_next_action_time = now + self.get_ai_action_delay_ms()
            return

        if self.ai_state == "moving":
            if not self.execute_ai_move_phase():
                self.show_message(f"Joueur ordinateur {self.current_player + 1} : fin du tour automatique.", max(1, self.get_ai_action_delay_ms() - 100))
            self.ai_state = "ending"
            self.ai_next_action_time = now + self.get_ai_action_delay_ms()
            return

        if self.ai_state == "ending":
            self.complete_turn()

    def update(self) -> None:
        self.process_pending_details_button_click()
        if self.message and pygame.time.get_ticks() > self.message_timer:
            self.message = ""
        if self.major_event_modal is not None:
            return
        if self.phase == "game_over":
            self.update_confetti()
        elif self.phase == "replay":
            self.update_replay()
        self.normalize_ai_speed_mode()
        if self.ai_speed_mode == "instant":
            for _ in range(250):
                if self.phase != "playing" or not self.is_ai_player(self.current_player):
                    break
                previous_player = self.current_player
                previous_state = self.ai_state
                self.process_ai_turn()
                if self.phase != "playing" or not self.is_ai_player(self.current_player):
                    break
                if self.current_player == previous_player and self.ai_state == previous_state and pygame.time.get_ticks() < self.ai_next_action_time:
                    break
        else:
            self.process_ai_turn()

    def get_territory_amenagement_count(self, territory_id: int) -> int:
        """Compte les amenagements construits sur un territoire.

        Les statuts (capitale, cite commercante, paradis fiscal, ONU, soumis, dore)
        ne comptent pas ici : le cercle remplace uniquement le petit bonhomme et
        indique la densite d'amenagements reels du territoire.
        """
        if not (0 <= territory_id < len(self.territories)):
            return 0
        count = 0
        if territory_id in self.fortress_territory_ids:
            count += 1
        # Usine, aeroport et port constituent une seule categorie : un territoire
        # ne peut accueillir qu'un seul amenagement industriel.
        industrial_ids = (
            self.factory_territory_ids
            | self.airport_territory_ids
            | self.port_territory_ids
        )
        if territory_id in industrial_ids:
            count += 1
        if territory_id in getattr(self, "temple_territory_ids", set()):
            count += 1
        if territory_id in self.cultural_center_ages:
            count += 1
        if territory_id in self.university_territory_ids:
            count += 1
        return count

    def get_max_territory_amenagement_count(self) -> int:
        # Forteresse + industrie + temple + centre culturel + universite.
        return 5

    def draw_amenagement_progress_circle(
        self,
        x: int,
        y: int,
        count: int,
        max_count: Optional[int] = None,
        color: Tuple[int, int, int] = (220, 220, 220),
    ) -> None:
        max_count = max(1, max_count or self.get_max_territory_amenagement_count())
        count = max(0, min(int(count), max_count))
        radius = 8
        border_color = (235, 235, 235)
        empty_color = (18, 32, 52)
        pygame.draw.circle(self.screen, empty_color, (x, y), radius)
        if count >= max_count:
            pygame.draw.circle(self.screen, color, (x, y), radius - 2)
        elif count > 0:
            fraction = count / max_count
            start_angle = -math.pi / 2
            end_angle = start_angle + math.tau * fraction
            steps = max(4, int(28 * fraction))
            points = [(x, y)]
            for index in range(steps + 1):
                angle = start_angle + (end_angle - start_angle) * index / steps
                points.append((
                    int(round(x + math.cos(angle) * (radius - 2))),
                    int(round(y + math.sin(angle) * (radius - 2))),
                ))
            pygame.draw.polygon(self.screen, color, points)
        pygame.draw.circle(self.screen, border_color, (x, y), radius, 2)

    def draw_bonus_badge(self, x: int, y: int, bonus: int) -> None:
        if bonus <= 1:
            return
        radius = 9 if bonus == 2 else 11
        bg_color = (241, 196, 15) if bonus == 2 else (230, 126, 34)
        border_color = (44, 62, 80)
        pygame.draw.circle(self.screen, bg_color, (x, y), radius)
        pygame.draw.circle(self.screen, border_color, (x, y), radius, 2)
        label = self.font_small.render(f"+{bonus}", True, (20, 20, 20))
        self.screen.blit(label, label.get_rect(center=(x, y)))

    def draw_letter_badge(self, x: int, y: int, label_text: str, bg_color: Tuple[int, int, int], border_color: Tuple[int, int, int]) -> None:
        pygame.draw.circle(self.screen, bg_color, (x, y), 11)
        pygame.draw.circle(self.screen, border_color, (x, y), 11, 2)
        label = self.font_small.render(label_text, True, (20, 20, 20))
        self.screen.blit(label, label.get_rect(center=(x, y)))

    def draw_capital_badge(self, x: int, y: int, highlighted: bool = False) -> None:
        # Capitale ordinaire active : sigle C visible sur la carte.
        # Pour les nations, le C est volontairement criard : apparemment il faut
        # maintenant du neon constitutionnel pour que la diplomatie soit lisible.
        if highlighted:
            pygame.draw.circle(self.screen, (255, 255, 210), (x, y), 16)
            pygame.draw.circle(self.screen, (255, 210, 40), (x, y), 15, 3)
            self.draw_letter_badge(x, y, "C", (255, 245, 90), (120, 70, 0))
        else:
            self.draw_letter_badge(x, y, "C", (255, 245, 170), (90, 55, 10))

    def draw_factory_badge(self, x: int, y: int) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (133, 193, 233), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (44, 62, 80), badge_rect, width=2, border_radius=6)

        body_color = (28, 42, 56)
        roof_points = [
            (badge_rect.x + 5, badge_rect.y + 12),
            (badge_rect.x + 8, badge_rect.y + 8),
            (badge_rect.x + 11, badge_rect.y + 12),
            (badge_rect.x + 14, badge_rect.y + 8),
            (badge_rect.x + 17, badge_rect.y + 12),
            (badge_rect.x + 20, badge_rect.y + 8),
            (badge_rect.x + 23, badge_rect.y + 12),
        ]
        pygame.draw.polygon(self.screen, body_color, roof_points)
        pygame.draw.rect(self.screen, body_color, (badge_rect.x + 5, badge_rect.y + 12, 18, 6), border_radius=1)
        pygame.draw.rect(self.screen, body_color, (badge_rect.x + 18, badge_rect.y + 5, 3, 8), border_radius=1)
        smoke_color = (236, 240, 241)
        pygame.draw.circle(self.screen, smoke_color, (badge_rect.x + 20, badge_rect.y + 4), 2)
        pygame.draw.circle(self.screen, smoke_color, (badge_rect.x + 22, badge_rect.y + 2), 2)


    def draw_airport_badge(self, x: int, y: int) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (174, 214, 241), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (44, 62, 80), badge_rect, width=2, border_radius=6)
        plane_color = (28, 42, 56)
        pygame.draw.polygon(self.screen, plane_color, [
            (badge_rect.centerx, badge_rect.y + 4),
            (badge_rect.centerx + 3, badge_rect.y + 15),
            (badge_rect.centerx, badge_rect.y + 20),
            (badge_rect.centerx - 3, badge_rect.y + 15),
        ])
        pygame.draw.polygon(self.screen, plane_color, [
            (badge_rect.x + 4, badge_rect.y + 12),
            (badge_rect.x + 24, badge_rect.y + 12),
            (badge_rect.x + 18, badge_rect.y + 15),
            (badge_rect.x + 10, badge_rect.y + 15),
        ])

    def draw_port_badge(self, x: int, y: int) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (118, 215, 196), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (44, 62, 80), badge_rect, width=2, border_radius=6)
        hull = [(badge_rect.x + 5, badge_rect.y + 14), (badge_rect.x + 23, badge_rect.y + 14), (badge_rect.x + 19, badge_rect.y + 19), (badge_rect.x + 8, badge_rect.y + 19)]
        pygame.draw.polygon(self.screen, (28, 42, 56), hull)
        pygame.draw.rect(self.screen, (28, 42, 56), (badge_rect.x + 10, badge_rect.y + 8, 8, 6), border_radius=1)
        pygame.draw.line(self.screen, (236, 240, 241), (badge_rect.x + 5, badge_rect.y + 20), (badge_rect.x + 23, badge_rect.y + 20), 1)

    def draw_temple_badge(self, x: int, y: int) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (245, 203, 167), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (112, 66, 20), badge_rect, width=2, border_radius=6)
        pillar_color = (112, 66, 20)
        pygame.draw.polygon(self.screen, pillar_color, [
            (badge_rect.x + 4, badge_rect.y + 10),
            (badge_rect.centerx, badge_rect.y + 4),
            (badge_rect.x + 24, badge_rect.y + 10),
        ])
        pygame.draw.rect(self.screen, pillar_color, (badge_rect.x + 5, badge_rect.y + 18, 18, 2))
        for px in (badge_rect.x + 7, badge_rect.x + 12, badge_rect.x + 17):
            pygame.draw.rect(self.screen, pillar_color, (px, badge_rect.y + 11, 3, 7), border_radius=1)

    def draw_culture_badge(self, x: int, y: int, count: int = 1) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (215, 189, 226), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (84, 52, 94), badge_rect, width=2, border_radius=6)
        pygame.draw.polygon(self.screen, (84, 52, 94), [
            (badge_rect.x + 6, badge_rect.y + 18),
            (badge_rect.x + 14, badge_rect.y + 6),
            (badge_rect.x + 22, badge_rect.y + 18),
        ], 2)
        pygame.draw.line(self.screen, (84, 52, 94), (badge_rect.x + 8, badge_rect.y + 18), (badge_rect.x + 20, badge_rect.y + 18), 2)
        if count > 1:
            glyph = self.font_small.render(str(count), True, (84, 52, 94))
            self.screen.blit(glyph, glyph.get_rect(center=(badge_rect.right - 5, badge_rect.y + 7)))

    def draw_university_badge(self, x: int, y: int) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (214, 234, 248), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (36, 76, 112), badge_rect, width=2, border_radius=6)
        pillar_color = (36, 76, 112)
        pygame.draw.polygon(self.screen, pillar_color, [
            (badge_rect.x + 5, badge_rect.y + 10),
            (badge_rect.centerx, badge_rect.y + 4),
            (badge_rect.x + 23, badge_rect.y + 10),
        ])
        pygame.draw.rect(self.screen, pillar_color, (badge_rect.x + 6, badge_rect.y + 18, 16, 2))
        for px in (badge_rect.x + 8, badge_rect.x + 13, badge_rect.x + 18):
            pygame.draw.rect(self.screen, pillar_color, (px, badge_rect.y + 11, 3, 7), border_radius=1)

    def draw_fortress_badge(self, x: int, y: int) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (196, 198, 201), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (44, 62, 80), badge_rect, width=2, border_radius=6)

        body_color = (52, 73, 94)
        wall_rect = pygame.Rect(badge_rect.x + 4, badge_rect.y + 10, 20, 9)
        pygame.draw.rect(self.screen, body_color, wall_rect, border_radius=2)
        tower_w = 4
        tower_h = 11
        for tower_x in (badge_rect.x + 4, badge_rect.x + 12, badge_rect.x + 20):
            pygame.draw.rect(self.screen, body_color, (tower_x, badge_rect.y + 7, tower_w, tower_h), border_radius=1)
            pygame.draw.rect(self.screen, body_color, (tower_x, badge_rect.y + 5, tower_w, 2))
        gate_color = (236, 240, 241)
        pygame.draw.rect(self.screen, gate_color, (badge_rect.x + 12, badge_rect.y + 13, 4, 6), border_radius=1)

    def draw_precious_mineral_mine_badge(self, x: int, y: int) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        pygame.draw.rect(self.screen, (72, 62, 92), badge_rect, border_radius=6)
        pygame.draw.rect(self.screen, (225, 215, 245), badge_rect, width=2, border_radius=6)
        crystal = [
            (badge_rect.centerx, badge_rect.y + 3),
            (badge_rect.x + 21, badge_rect.y + 10),
            (badge_rect.x + 17, badge_rect.y + 21),
            (badge_rect.x + 10, badge_rect.y + 21),
            (badge_rect.x + 6, badge_rect.y + 10),
        ]
        pygame.draw.polygon(self.screen, (174, 235, 255), crystal)
        pygame.draw.polygon(self.screen, (48, 95, 125), crystal, width=2)
        pygame.draw.line(self.screen, (255, 255, 255), (badge_rect.centerx, badge_rect.y + 4), (badge_rect.centerx, badge_rect.y + 19), 1)

    def draw_wonder_badge(self, x: int, y: int, wonder_type: str) -> None:
        badge_rect = pygame.Rect(0, 0, 30, 26)
        badge_rect.center = (x, y)
        colors = {
            "elyrion_sanctuary": ((52, 88, 116), (174, 235, 255)),
            "thousand_voices_theatre": ((92, 50, 112), (235, 188, 255)),
            "atlas_observatory": ((32, 68, 108), (150, 215, 255)),
            "golden_pact_palace": ((105, 77, 20), (255, 220, 92)),
        }
        background, symbol_color = colors.get(wonder_type, ((70, 70, 70), (235, 235, 235)))
        pygame.draw.rect(self.screen, background, badge_rect, border_radius=7)
        pygame.draw.rect(self.screen, symbol_color, badge_rect, width=2, border_radius=7)

        cx, cy = badge_rect.center
        if wonder_type == "elyrion_sanctuary":
            pygame.draw.circle(self.screen, symbol_color, (cx, cy - 3), 7, 2)
            pygame.draw.line(self.screen, symbol_color, (cx, cy - 10), (cx, cy + 9), 2)
            pygame.draw.line(self.screen, symbol_color, (cx - 5, cy + 7), (cx + 5, cy + 7), 2)
        elif wonder_type == "thousand_voices_theatre":
            pygame.draw.circle(self.screen, symbol_color, (cx - 5, cy), 6, 2)
            pygame.draw.circle(self.screen, symbol_color, (cx + 5, cy), 6, 2)
            pygame.draw.arc(self.screen, symbol_color, (cx - 8, cy - 1, 6, 7), 0, math.pi, 1)
            pygame.draw.arc(self.screen, symbol_color, (cx + 2, cy + 1, 6, 7), math.pi, math.tau, 1)
        elif wonder_type == "atlas_observatory":
            pygame.draw.line(self.screen, symbol_color, (cx - 8, cy + 6), (cx + 6, cy - 6), 4)
            pygame.draw.line(self.screen, symbol_color, (cx - 3, cy + 3), (cx + 2, cy + 9), 2)
            pygame.draw.circle(self.screen, (255, 245, 170), (cx + 8, cy - 8), 2)
        elif wonder_type == "golden_pact_palace":
            pygame.draw.circle(self.screen, symbol_color, (cx - 4, cy), 6, 2)
            pygame.draw.circle(self.screen, symbol_color, (cx + 4, cy), 6, 2)

    def draw_money_bonus_badge(self, x: int, y: int, commercial_city: bool = False, vassal: bool = False) -> None:
        badge_rect = pygame.Rect(0, 0, 28, 24)
        badge_rect.center = (x, y)
        if vassal:
            pygame.draw.rect(self.screen, (186, 85, 211), badge_rect, border_radius=6)
            pygame.draw.rect(self.screen, (74, 22, 96), badge_rect, width=2, border_radius=6)
            coin_color = (235, 196, 245)
            glyph_text = "x10"
            glyph_color = (48, 12, 61)
        elif commercial_city:
            pygame.draw.rect(self.screen, (42, 197, 210), badge_rect, border_radius=6)
            pygame.draw.rect(self.screen, (12, 73, 84), badge_rect, width=2, border_radius=6)
            coin_color = (188, 245, 250)
            glyph_text = "CC"
            glyph_color = (6, 48, 55)
        else:
            pygame.draw.rect(self.screen, (248, 218, 92), badge_rect, border_radius=6)
            pygame.draw.rect(self.screen, (99, 73, 18), badge_rect, width=2, border_radius=6)
            coin_color = (255, 245, 170)
            glyph_text = "x10"
            glyph_color = (71, 48, 11)
        pygame.draw.circle(self.screen, coin_color, (badge_rect.x + 10, badge_rect.y + 12), 5)
        pygame.draw.circle(self.screen, glyph_color, (badge_rect.x + 10, badge_rect.y + 12), 5, 1)
        glyph = self.font_small.render(glyph_text, True, glyph_color)
        self.screen.blit(glyph, glyph.get_rect(midleft=(badge_rect.x + 14, badge_rect.centery)))

    def draw_religion_symbol_badge(self, x: int, y: int, religion_id: int, holy: bool = False) -> None:
        color = self.get_religion_color(religion_id)
        border = (255, 255, 255) if holy else (35, 35, 35)
        radius = 14 if holy else 10
        pygame.draw.circle(self.screen, color, (x, y), radius)
        pygame.draw.circle(self.screen, border, (x, y), radius, 2)
        label = self.font_small.render(self.get_religion_symbol(religion_id), True, (18, 24, 30))
        self.screen.blit(label, label.get_rect(center=(x, y)))

    def draw_religion_view_symbols(self) -> None:
        for territory in self.territories:
            if not territory.cells:
                continue
            center_row, center_col = self.get_territory_center(territory.id)
            cx = int((center_col + 0.5) * self.cell_width)
            cy = int(self.map_top + (center_row + 0.5) * self.cell_height)
            label = self.font_small.render(territory.name, True, (245, 247, 250))
            label_rect = label.get_rect(center=(cx, cy + 22))
            label_rect.x = max(3, min(self.WIDTH - label_rect.width - 3, label_rect.x))
            label_rect.y = max(self.map_top + 3, min(self.HEIGHT - label_rect.height - 3, label_rect.y))
            background_rect = label_rect.inflate(8, 4)
            pygame.draw.rect(self.screen, (22, 28, 34), background_rect, border_radius=4)
            pygame.draw.rect(self.screen, (210, 216, 222), background_rect, width=1, border_radius=4)
            self.screen.blit(label, label_rect)

        for religion_id, territory_id in sorted(getattr(self, "religion_holy_sites", {}).items()):
            if not (0 <= territory_id < len(self.territories)):
                continue
            territory = self.territories[territory_id]
            if not territory.cells:
                continue
            center_row, center_col = self.get_territory_center(territory_id)
            cx = int((center_col + 0.5) * self.cell_width)
            cy = int(self.map_top + (center_row + 0.5) * self.cell_height)
            self.draw_religion_symbol_badge(cx, cy, religion_id, holy=True)
        legend_x = 18
        legend_y = self.map_top + 12
        for religion_id in sorted(set(getattr(self, "religion_founders", {}).values())):
            self.draw_religion_symbol_badge(legend_x + 12, legend_y + 10, religion_id, holy=False)
            text = self.font_small.render(self.get_religion_name(religion_id), True, (236, 240, 241))
            self.screen.blit(text, (legend_x + 32, legend_y + 2))
            legend_y += 24

    def draw_territories(self) -> None:
        territory_colors: List[Tuple[int, int, int]] = []
        religion_view = self.is_religion_view_active()
        for terr in self.territories:
            if religion_view:
                religion_id = getattr(self, "religious_influence", {}).get(terr.id)
                if religion_id is None:
                    base = (58, 65, 72)
                else:
                    base = self.get_religion_color(religion_id)
                color = tuple(max(28, int(c * 0.78)) for c in base)
            else:
                base = self.PLAYER_COLORS[terr.owner % len(self.PLAYER_COLORS)] if terr.owner >= 0 else (90, 100, 110)
                # Joueur courant boost leger. Ennemis : 72% au lieu de 55% pour rester lisibles.
                color = tuple(min(255, int(c * 1.12) + 10) for c in base) if terr.owner == self.current_player else tuple(int(c * 0.72) for c in base)
            if terr.id == self.selected_source or (self.phase == "map_editor" and terr.id == self.custom_selected_territory_id):
                # Sélection source : flash blanc fort
                color = tuple(min(255, c + 70) for c in color)
            elif self.turn_phase == "attack" and self.selected_source is not None and terr.id in self.territories[self.selected_source].neighbors and terr.owner != self.current_player:
                # Cibles attaquables : teinte rouge
                color = (min(255, color[0] + 50), max(0, color[1] - 10), max(0, color[2] - 10))
            elif self.turn_phase == "move" and terr.id == self.selected_target:
                color = tuple(min(255, c + 40) for c in color)
            territory_colors.append(color)

        for r in range(self.rows):
            for c in range(self.cols):
                tid = self.grid_territory[r][c]
                x = int(c * self.cell_width)
                y = int(self.map_top + r * self.cell_height)
                rect = pygame.Rect(x, y, int(self.cell_width) + 1, int(self.cell_height) + 1)
                if tid < 0:
                    water_color = (38, 110, 168) if self.phase == "map_editor" else (42, 118, 175)
                    pygame.draw.rect(self.screen, water_color, rect)
                else:
                    pygame.draw.rect(self.screen, territory_colors[tid], rect)

        for r in range(self.rows):
            for c in range(self.cols):
                tid = self.grid_territory[r][c]
                if tid < 0:
                    continue
                terr = self.territories[tid]
                border_width = 3 if terr.owner == self.current_player else 1
                border_color = (255, 220, 50) if terr.owner == self.current_player else self.BORDER_COLOR
                border_styles = [(border_color, border_width)]
                if self.is_submitted_territory(tid):
                    border_styles = [((185, 90, 255), max(border_width, 5))]
                elif self.is_sanctuary_territory(tid):
                    border_styles = [((230, 245, 255), max(border_width, 5))]
                x0 = int(c * self.cell_width)
                y0 = int(self.map_top + r * self.cell_height)
                x1 = int((c + 1) * self.cell_width)
                y1 = int(self.map_top + (r + 1) * self.cell_height)
                top_tid = self.grid_territory[(r - 1) % self.rows][c] if self.map_mode == "custom" else (self.grid_territory[r - 1][c] if r > 0 else None)
                bottom_tid = self.grid_territory[(r + 1) % self.rows][c] if self.map_mode == "custom" else (self.grid_territory[r + 1][c] if r < self.rows - 1 else None)
                left_tid = self.grid_territory[r][(c - 1) % self.cols] if self.map_mode == "custom" else (self.grid_territory[r][c - 1] if c > 0 else None)
                right_tid = self.grid_territory[r][(c + 1) % self.cols] if self.map_mode == "custom" else (self.grid_territory[r][c + 1] if c < self.cols - 1 else None)
                if top_tid != tid:
                    for line_color, line_width in border_styles:
                        pygame.draw.line(self.screen, line_color, (x0, y0), (x1, y0), line_width)
                if bottom_tid != tid:
                    for line_color, line_width in border_styles:
                        pygame.draw.line(self.screen, line_color, (x0, y1), (x1, y1), line_width)
                if left_tid != tid:
                    for line_color, line_width in border_styles:
                        pygame.draw.line(self.screen, line_color, (x0, y0), (x0, y1), line_width)
                if right_tid != tid:
                    for line_color, line_width in border_styles:
                        pygame.draw.line(self.screen, line_color, (x1, y0), (x1, y1), line_width)

        if self.phase != "map_editor" and religion_view:
            self.draw_religion_view_symbols()
            return

        if self.phase != "map_editor":
            for terr in self.territories:
                if not terr.cells:
                    continue
                center_row, center_col = self.get_territory_center(terr.id)
                cx = int((center_col + 0.5) * self.cell_width)
                cy = int(self.map_top + (center_row + 0.5) * self.cell_height)
                # Fond de la boîte : couleur du propriétaire assombrie pour contraste
                base_color = self.PLAYER_COLORS[terr.owner % len(self.PLAYER_COLORS)] if terr.owner >= 0 else (90, 100, 110)
                box_bg = tuple(max(0, int(c * 0.30) + 8) for c in base_color)
                box_border = tuple(min(255, int(c * 0.85)) for c in base_color)
                text_color = (235, 235, 235)
                icon_color = tuple(min(255, int(c * 1.6) + 40) for c in base_color)
                count_label = self.font_small.render(str(terr.regiments), True, text_color)
                box_width = 22 + count_label.get_width() + 10
                box_height = max(20, count_label.get_height() + 8)
                box_rect = pygame.Rect(0, 0, box_width, box_height)
                box_rect.center = (cx, cy)
                if terr.reinforcement_bonus > 1:
                    box_rect.x -= 10
                box_rect.x = max(4, min(self.WIDTH - box_rect.width - 4, box_rect.x))
                box_rect.y = max(self.map_top + 2, min(self.HEIGHT - box_rect.height - 4, box_rect.y))
                pygame.draw.rect(self.screen, box_bg, box_rect, border_radius=4)
                pygame.draw.rect(self.screen, box_border, box_rect, width=1, border_radius=4)
                amenagement_count = self.get_territory_amenagement_count(terr.id)
                circle_x = box_rect.x + 12
                circle_y = box_rect.centery
                self.draw_amenagement_progress_circle(
                    circle_x,
                    circle_y,
                    amenagement_count,
                    self.get_max_territory_amenagement_count(),
                    icon_color,
                )
                self.screen.blit(count_label, count_label.get_rect(midleft=(circle_x + 14, box_rect.centery)))
                if terr.reinforcement_bonus > 1:
                    badge_x = min(self.WIDTH - 14, box_rect.right + 12)
                    badge_y = max(self.map_top + 12, box_rect.centery)
                    self.draw_bonus_badge(badge_x, badge_y, terr.reinforcement_bonus)
                if terr.id in self.golden_territory_ids:
                    golden_x = max(16, min(self.WIDTH - 16, box_rect.left - 16))
                    golden_y = max(self.map_top + 16, box_rect.centery)
                    pygame.draw.circle(self.screen, (255, 215, 0), (golden_x, golden_y), 14)
                    pygame.draw.circle(self.screen, (120, 90, 0), (golden_x, golden_y), 14, 2)
                    pygame.draw.circle(self.screen, (255, 235, 120), (golden_x, golden_y), 9)
                    pygame.draw.circle(self.screen, (255, 250, 210), (golden_x, golden_y), 5)
                special_icon_types = []
                if terr.id in self.fortress_territory_ids:
                    special_icon_types.append("fortress")
                if terr.id in self.precious_mineral_mine_ids:
                    special_icon_types.append("precious_mine")
                wonder_type = self.get_wonder_type_at_territory(terr.id)
                if wonder_type is not None:
                    special_icon_types.append(f"wonder:{wonder_type}")

                # Les lieux sacres restent visibles dans la vue par defaut
                # (forteresses), ainsi que dans la vue affichant toutes les icones.
                holy_site_religion_id = next(
                    (
                        religion_id
                        for religion_id, holy_site_id in getattr(self, "religion_holy_sites", {}).items()
                        if holy_site_id == terr.id
                    ),
                    None,
                )
                if holy_site_religion_id is not None and holy_site_religion_id != self.WONDER_RELIGION_ID:
                    special_icon_types.append(f"holy_site:{holy_site_religion_id}")

                # Le mode "icones : forteresses" ne masque que les amenagements
                # secondaires. Les statuts restent visibles, sinon on confond une
                # capitale, un PF ou une CC avec un simple territoire ordinaire.
                if self.show_all_map_icons:
                    if terr.id in self.factory_territory_ids:
                        special_icon_types.append("factory")
                    if terr.id in self.airport_territory_ids:
                        special_icon_types.append("airport")
                    if terr.id in self.port_territory_ids:
                        special_icon_types.append("port")
                    if terr.id in getattr(self, "temple_territory_ids", set()):
                        special_icon_types.append("temple")
                    if terr.id in self.cultural_center_ages:
                        special_icon_types.append("culture")
                    if terr.id in self.university_territory_ids:
                        special_icon_types.append("university")

                if self.is_active_regular_capital(terr.id):
                    special_icon_types.append("capital")
                if self.is_vassal_territory(terr.id):
                    special_icon_types.append("vassal_money")
                elif self.is_last_stand_bonus_territory(terr.id):
                    special_icon_types.append("commercial_money" if self.is_commercial_city_territory(terr.id) else "money")
                if special_icon_types:
                    spacing = 32
                    start_x = box_rect.centerx - (len(special_icon_types) - 1) * (spacing // 2)
                    badge_y = max(self.map_top + 14, box_rect.top - 14)
                    for index, icon_type in enumerate(special_icon_types):
                        badge_x = max(16, min(self.WIDTH - 16, start_x + index * spacing))
                        if icon_type == "fortress":
                            self.draw_fortress_badge(badge_x, badge_y)
                        elif icon_type == "precious_mine":
                            self.draw_precious_mineral_mine_badge(badge_x, badge_y)
                        elif icon_type.startswith("wonder:"):
                            self.draw_wonder_badge(badge_x, badge_y, icon_type.split(":", 1)[1])
                        elif icon_type == "factory":
                            self.draw_factory_badge(badge_x, badge_y)
                        elif icon_type == "airport":
                            self.draw_airport_badge(badge_x, badge_y)
                        elif icon_type == "port":
                            self.draw_port_badge(badge_x, badge_y)
                        elif icon_type == "temple":
                            self.draw_temple_badge(badge_x, badge_y)
                        elif icon_type == "culture":
                            self.draw_culture_badge(badge_x, badge_y, len(self.cultural_center_ages.get(terr.id, [])))
                        elif icon_type == "university":
                            self.draw_university_badge(badge_x, badge_y)
                        elif icon_type.startswith("holy_site:"):
                            religion_id = int(icon_type.split(":", 1)[1])
                            self.draw_religion_symbol_badge(badge_x, badge_y, religion_id, holy=True)
                        elif icon_type == "capital":
                            self.draw_capital_badge(badge_x, badge_y, highlighted=self.is_nation_player(terr.owner))
                        elif icon_type == "commercial_money":
                            self.draw_money_bonus_badge(badge_x, badge_y, commercial_city=True)
                        elif icon_type == "vassal_money":
                            self.draw_money_bonus_badge(badge_x, badge_y, vassal=True)
                        else:
                            self.draw_money_bonus_badge(badge_x, badge_y)


    def shorten_segment(self, start: Tuple[int, int], end: Tuple[int, int], inset_px: float = 20.0) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        sx, sy = start
        ex, ey = end
        dx = ex - sx
        dy = ey - sy
        dist = math.hypot(dx, dy)
        if dist <= inset_px * 2:
            return start, end
        ux = dx / dist
        uy = dy / dist
        ns = (int(round(sx + ux * inset_px)), int(round(sy + uy * inset_px)))
        ne = (int(round(ex - ux * inset_px)), int(round(ey - uy * inset_px)))
        return ns, ne

    def draw_terre_links(self) -> None:
        if self.map_mode != "terre" or not self.terre_links:
            return
        for link in self.terre_links:
            a, b = link
            if not (0 <= a < len(self.territories) and 0 <= b < len(self.territories)):
                continue
            if link in self.terre_link_points:
                start, end = self.terre_link_points[link]
            else:
                start = self.get_territory_center_cell(a)
                end = self.get_territory_center_cell(b)
            sx = int((start[1] + 0.5) * self.cell_width)
            sy = int(self.map_top + (start[0] + 0.5) * self.cell_height)
            ex = int((end[1] + 0.5) * self.cell_width)
            ey = int(self.map_top + (end[0] + 0.5) * self.cell_height)
            (sx, sy), (ex, ey) = self.shorten_segment((sx, sy), (ex, ey), 22.0)
            pygame.draw.line(self.screen, (18, 32, 52), (sx, sy), (ex, ey), 8)
            pygame.draw.line(self.screen, (236, 240, 241), (sx, sy), (ex, ey), 3)
            pygame.draw.circle(self.screen, (236, 240, 241), (sx, sy), 4)
            pygame.draw.circle(self.screen, (236, 240, 241), (ex, ey), 4)

    def draw_bridges(self) -> None:
        for key in sorted(getattr(self, "bridge_links", set())):
            points = self.bridge_link_points.get(key)
            if points is None:
                continue
            start, end = points
            sx = int((start[1] + 0.5) * self.cell_width)
            sy = int(self.map_top + (start[0] + 0.5) * self.cell_height)
            ex = int((end[1] + 0.5) * self.cell_width)
            ey = int(self.map_top + (end[0] + 0.5) * self.cell_height)
            pygame.draw.line(self.screen, (18, 32, 52), (sx, sy), (ex, ey), 10)
            pygame.draw.line(self.screen, (224, 170, 72), (sx, sy), (ex, ey), 5)
            pygame.draw.circle(self.screen, (255, 224, 145), (sx, sy), 5)
            pygame.draw.circle(self.screen, (255, 224, 145), (ex, ey), 5)

    def draw_ui(self) -> None:
        ui_rect = pygame.Rect(0, 0, self.WIDTH, 82)
        pygame.draw.rect(self.screen, (18, 32, 52), ui_rect)
        pygame.draw.line(self.screen, (44, 62, 80), (0, 82), (self.WIDTH, 82), 2)

        if self.map_mode == "continents":
            map_label = "Continents 20-35%"
        elif self.map_mode == "continents_45":
            map_label = "Continents 40-50%"
        elif self.map_mode == "terre":
            map_label = "Terre"
        elif self.map_mode == "custom":
            map_label = "Personnalisee"
        else:
            map_label = "Standard"

        if self.phase == "map_editor":
            editor_title = "Modification de carte" if self.editing_map_path is not None else "Creation manuelle de carte"
            title_text = self.font_medium.render(editor_title, True, (236, 240, 241))
            self.screen.blit(title_text, (20, 10))
            counter_text = self.font_medium.render(f"Territoires crees : {len(self.territories)}", True, (244, 208, 63))
            self.screen.blit(counter_text, (20, 36))
            size_labels = {"medium": "Moyen", "large": "Grand", "immense": "Immense"}
            for key, rect in self.custom_size_buttons.items():
                active = key == self.custom_map_size
                color = (84, 153, 199) if active else (52, 73, 94)
                pygame.draw.rect(self.screen, color, rect, border_radius=8)
                pygame.draw.rect(self.screen, (236, 240, 241), rect, width=1, border_radius=8)
                label = self.font_small.render(size_labels[key], True, (236, 240, 241))
                self.screen.blit(label, label.get_rect(center=rect.center))
            shape_labels = {"block": "Bloc", "star": "Etoile"}
            for key, rect in self.custom_shape_buttons.items():
                active = key == self.custom_shape
                color = (88, 214, 141) if active else (52, 73, 94)
                pygame.draw.rect(self.screen, color, rect, border_radius=8)
                pygame.draw.rect(self.screen, (236, 240, 241), rect, width=1, border_radius=8)
                label = self.font_small.render(shape_labels[key], True, (236, 240, 241))
                self.screen.blit(label, label.get_rect(center=rect.center))
            fill_color = (64, 89, 120) if self.fill_custom_map_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
            pygame.draw.rect(self.screen, fill_color, self.fill_custom_map_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.fill_custom_map_rect, width=1, border_radius=8)
            fill_text = self.font_small.render("Remplir toute la carte", True, (236, 240, 241))
            self.screen.blit(fill_text, fill_text.get_rect(center=self.fill_custom_map_rect.center))
            finish_color = (64, 89, 120) if self.finish_custom_map_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
            pygame.draw.rect(self.screen, finish_color, self.finish_custom_map_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.finish_custom_map_rect, width=1, border_radius=8)
            finish_text = self.font_small.render("Sauvegarder la carte", True, (236, 240, 241))
            self.screen.blit(finish_text, finish_text.get_rect(center=self.finish_custom_map_rect.center))
            back_color = (64, 89, 120) if self.editor_return_menu_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
            pygame.draw.rect(self.screen, back_color, self.editor_return_menu_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.editor_return_menu_rect, width=1, border_radius=8)
            back_text = self.font_small.render("Retour au menu", True, (236, 240, 241))
            self.screen.blit(back_text, back_text.get_rect(center=self.editor_return_menu_rect.center))
            info_lines = [
                "Clic gauche sur la mer : ajoute un territoire genere aleatoirement a l'endroit choisi.",
                "Clic gauche maintenu sur un territoire existant : deplacement par glisser-deposer avec rebouclage aux bords.",
                "Touche Delete sur un territoire selectionne : suppression immediate.",
                "Remplir toute la carte : ajoute automatiquement des territoires jusqu'a disparition totale des oceans.",
                "Tailles : moyen, grand, immense. Formes : bloc ou etoile.",
                "Sauvegarder la carte : enregistre la carte actuelle puis revient au menu si vous modifiez une carte existante.",
            ]
            for i, line in enumerate(info_lines):
                self.screen.blit(self.font_small.render(line, True, (189, 195, 199)), (340, 12 + i * 17))
        else:
            self.screen.blit(self.font_medium.render(f"Tour {self.turn}", True, (236, 240, 241)), (20, 18))
            tribes_suffix = " | Tribus" if self.tribes_mode else ""
            difficulty_label = f"Mode: {self.get_difficulty_label()}{tribes_suffix}"
            self.screen.blit(self.font_small.render(f"Carte: {map_label}", True, (189, 195, 199)), (22, 42))
            self.screen.blit(self.font_small.render(difficulty_label, True, (189, 195, 199)), (22, 60))
            if self.turn_phase == "move" and not self.is_ai_player(self.current_player):
                phase_text = f"Deplacements restants: {self.get_end_turn_move_limit() - self.turn_move_count}"
            else:
                phase_text = "Phase: attaque" if self.turn_phase == "attack" else "Phase: deplacement"
            self.screen.blit(self.font_small.render(phase_text, True, (189, 195, 199)), (180, 60))
            if self.current_player >= 0:
                economy_text = f"E:{self.get_player_money(self.current_player)}(+{self.calculate_player_income(self.current_player)}) | C:{self.calculate_player_culture(self.current_player)} | S:{self.get_player_science(self.current_player)}(+{self.calculate_player_science_income(self.current_player)})"
                self.screen.blit(self.font_small.render(economy_text, True, (244, 208, 63)), (360, 60))
            player_color = self.PLAYER_COLORS[self.current_player % len(self.PLAYER_COLORS)]
            player_kind = f"Ordinateur - {self.get_ai_profile_label(self.current_player)}" if self.is_ai_player(self.current_player) else "Humain"
            self.screen.blit(self.font_medium.render(f"Joueur {self.current_player + 1} ({player_kind})", True, player_color), (180, 18))

            counts = [0 for _ in range(self.num_players)]
            for terr in self.territories:
                if 0 <= terr.owner < self.num_players:
                    counts[terr.owner] += 1
            counts_str = " | ".join(
                f"J{idx + 1}{'O-' + self.get_ai_profile_label(idx, include_current=False)[:3] if self.is_ai_player(idx) else 'H'}: {count}"
                for idx, count in enumerate(counts)
            )
            self.screen.blit(self.font_small.render(f"Territoires - {counts_str}", True, (189, 195, 199)), (180, 40))

            save_btn_color = (64, 89, 120) if self.save_map_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
            pygame.draw.rect(self.screen, save_btn_color, self.save_map_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.save_map_rect, width=1, border_radius=8)
            save_text = self.font_small.render("Sauvegarder la carte", True, (236, 240, 241))
            self.screen.blit(save_text, save_text.get_rect(center=self.save_map_rect.center))

            save_game_btn_color = (64, 120, 89) if self.save_game_rect.collidepoint(pygame.mouse.get_pos()) else (42, 94, 68)
            pygame.draw.rect(self.screen, save_game_btn_color, self.save_game_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.save_game_rect, width=1, border_radius=8)
            save_game_text = self.font_small.render("Sauvegarder la partie", True, (236, 240, 241))
            self.screen.blit(save_game_text, save_game_text.get_rect(center=self.save_game_rect.center))

            btn_enabled = not self.is_ai_player(self.current_player)
            if btn_enabled:
                btn_color = (64, 89, 120) if self.end_turn_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
            else:
                btn_color = (45, 52, 60)
            pygame.draw.rect(self.screen, btn_color, self.end_turn_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.end_turn_rect, width=1, border_radius=8)
            end_turn_label = "Deplacements termines" if self.turn_phase == "move" else "Fin de tour"
            btn_text = self.font_small.render(end_turn_label, True, (236, 240, 241))
            self.screen.blit(btn_text, btn_text.get_rect(center=self.end_turn_rect.center))

            geo_enabled = self.can_show_geopolitical_button()
            if geo_enabled:
                geo_color = (64, 89, 120) if self.geopolitical_button_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
            else:
                geo_color = (45, 52, 60)
            pygame.draw.rect(self.screen, geo_color, self.geopolitical_button_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.geopolitical_button_rect, width=1, border_radius=8)
            geo_text = self.font_small.render("Situation", True, (236, 240, 241) if geo_enabled else (140, 146, 153))
            self.screen.blit(geo_text, geo_text.get_rect(center=self.geopolitical_button_rect.center))

            if geo_enabled:
                details_base = (76, 118, 86) if self.empire_panel_visible else ((70, 101, 78) if self.hover_details_enabled else (52, 73, 94))
                details_color = tuple(min(255, c + 20) for c in details_base) if self.details_button_rect.collidepoint(pygame.mouse.get_pos()) else details_base
            else:
                details_color = (45, 52, 60)
            pygame.draw.rect(self.screen, details_color, self.details_button_rect, border_radius=8)
            pygame.draw.rect(self.screen, (236, 240, 241), self.details_button_rect, width=1, border_radius=8)
            details_text = self.font_small.render("Details", True, (236, 240, 241) if geo_enabled else (140, 146, 153))
            self.screen.blit(details_text, details_text.get_rect(center=self.details_button_rect.center))

            view_mode = getattr(self, "map_icon_view", "all" if self.show_all_map_icons else "fortress")
            if view_mode == "religion":
                all_icons_base = (90, 70, 120)
                all_icons_label = "Vue: religion"
            elif view_mode == "all":
                all_icons_base = (60, 86, 66)
                all_icons_label = "Icones: tout"
            else:
                all_icons_base = (45, 58, 72)
                all_icons_label = "Icones: fort."
            all_icons_color = tuple(min(255, c + 14) for c in all_icons_base) if self.all_icons_button_rect.collidepoint(pygame.mouse.get_pos()) else all_icons_base
            pygame.draw.rect(self.screen, all_icons_color, self.all_icons_button_rect, border_radius=6)
            pygame.draw.rect(self.screen, (180, 190, 198), self.all_icons_button_rect, width=1, border_radius=6)
            all_icons_text = self.font_small.render(all_icons_label, True, (236, 240, 241))
            self.screen.blit(all_icons_text, all_icons_text.get_rect(center=self.all_icons_button_rect.center))

            checkbox_rect = pygame.Rect(self.auto_mode_rect.x, self.auto_mode_rect.y + 4, 18, 18)
            can_toggle = self.can_toggle_auto_mode(self.current_player)
            checked = self.is_auto_mode_enabled_for_player(self.current_player)
            outline_color = (236, 240, 241) if can_toggle else (110, 118, 125)
            label_color = (236, 240, 241) if can_toggle else (140, 146, 153)
            pygame.draw.rect(self.screen, (24, 38, 58), checkbox_rect, border_radius=4)
            pygame.draw.rect(self.screen, outline_color, checkbox_rect, width=2, border_radius=4)
            if checked:
                pygame.draw.line(self.screen, outline_color, (checkbox_rect.x + 4, checkbox_rect.y + 10), (checkbox_rect.x + 8, checkbox_rect.y + 14), 2)
                pygame.draw.line(self.screen, outline_color, (checkbox_rect.x + 8, checkbox_rect.y + 14), (checkbox_rect.x + 14, checkbox_rect.y + 5), 2)
            auto_label = "Mode IA" if checked else "Mode humain"
            self.screen.blit(self.font_small.render(auto_label, True, label_color), (checkbox_rect.right + 8, self.auto_mode_rect.y + 4))

            fast_checkbox_rect = pygame.Rect(self.fast_ai_rect.x, self.fast_ai_rect.y + 4, 18, 18)
            fast_outline = (236, 240, 241)
            pygame.draw.rect(self.screen, (24, 38, 58), fast_checkbox_rect, border_radius=4)
            pygame.draw.rect(self.screen, fast_outline, fast_checkbox_rect, width=2, border_radius=4)
            self.normalize_ai_speed_mode()
            if self.ai_speed_mode != "normal":
                pygame.draw.line(self.screen, fast_outline, (fast_checkbox_rect.x + 4, fast_checkbox_rect.y + 10), (fast_checkbox_rect.x + 8, fast_checkbox_rect.y + 14), 2)
                pygame.draw.line(self.screen, fast_outline, (fast_checkbox_rect.x + 8, fast_checkbox_rect.y + 14), (fast_checkbox_rect.x + 14, fast_checkbox_rect.y + 5), 2)
            fast_label = self.get_ai_speed_label()
            self.screen.blit(self.font_small.render(fast_label, True, fast_outline), (fast_checkbox_rect.right + 8, self.fast_ai_rect.y + 4))
            hint_label = "G: normal/rapide | D: accel."
            self.screen.blit(self.font_small.render(hint_label, True, (170, 178, 186)), (fast_checkbox_rect.right + 8, self.fast_ai_rect.y + 20))

            # Encart volontairement allege : le jeu garde seulement l'etat utile.

        if self.message:
            msg = self.font_medium.render(self.message, True, (236, 240, 241))
            self.screen.blit(msg, (self.WIDTH // 2 - msg.get_width() // 2, 36))

    def draw_start_menu(self) -> None:
        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 70))
        self.screen.blit(overlay, (0, 0))
        title = self.font_large.render("Jeu de strategie", True, (236, 240, 241))
        self.screen.blit(title, (self.WIDTH // 2 - title.get_width() // 2, self.HEIGHT // 2 - 120))
        subtitle = self.font_medium.render("Choisissez l'action de depart", True, (189, 195, 199))
        self.screen.blit(subtitle, (self.WIDTH // 2 - subtitle.get_width() // 2, self.HEIGHT // 2 - 88))

        create_color = (64, 89, 120) if self.start_create_map_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
        pygame.draw.rect(self.screen, create_color, self.start_create_map_rect, border_radius=10)
        pygame.draw.rect(self.screen, (236, 240, 241), self.start_create_map_rect, width=1, border_radius=10)
        create_text = self.font_medium.render("Creer une carte", True, (236, 240, 241))
        self.screen.blit(create_text, create_text.get_rect(center=self.start_create_map_rect.center))

        edit_color = (64, 89, 120) if self.start_edit_map_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
        pygame.draw.rect(self.screen, edit_color, self.start_edit_map_rect, border_radius=10)
        pygame.draw.rect(self.screen, (236, 240, 241), self.start_edit_map_rect, width=1, border_radius=10)
        edit_text = self.font_medium.render("Modifier une carte existante", True, (236, 240, 241))
        self.screen.blit(edit_text, edit_text.get_rect(center=self.start_edit_map_rect.center))

        game_color = (64, 89, 120) if self.start_game_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
        pygame.draw.rect(self.screen, game_color, self.start_game_rect, border_radius=10)
        pygame.draw.rect(self.screen, (236, 240, 241), self.start_game_rect, width=1, border_radius=10)
        game_text = self.font_medium.render("Commencer une partie", True, (236, 240, 241))
        self.screen.blit(game_text, game_text.get_rect(center=self.start_game_rect.center))

        saved_games = sorted(self.saved_games_dir.glob("*.json"))
        load_game_available = len(saved_games) > 0
        load_game_base = (42, 94, 68) if load_game_available else (35, 50, 40)
        load_game_hover = (64, 120, 89) if load_game_available else (35, 50, 40)
        load_game_color = load_game_hover if (load_game_available and self.start_load_game_rect.collidepoint(pygame.mouse.get_pos())) else load_game_base
        pygame.draw.rect(self.screen, load_game_color, self.start_load_game_rect, border_radius=10)
        pygame.draw.rect(self.screen, (236, 240, 241) if load_game_available else (100, 110, 105), self.start_load_game_rect, width=1, border_radius=10)
        load_game_label = f"Reprendre une partie ({len(saved_games)})" if load_game_available else "Reprendre une partie (aucune)"
        load_game_text = self.font_medium.render(load_game_label, True, (236, 240, 241) if load_game_available else (120, 130, 125))
        self.screen.blit(load_game_text, load_game_text.get_rect(center=self.start_load_game_rect.center))

        info = [
            "Creer une carte : ouvre l'editeur manuel et sauvegarde autant de cartes que voulu.",
            "Modifier une carte existante : choisit une carte sauvegardee, l'ouvre dans l'editeur, puis l'ecrase a la sauvegarde.",
            "Commencer une partie : permet ensuite de choisir une carte sauvegardee ou d'en generer une nouvelle.",
            "Reprendre une partie : charge une partie sauvegardee depuis 'parties_en_cours' et la reprend exactement.",
        ]
        for i, line in enumerate(info):
            rendered = self.font_small.render(line, True, (189, 195, 199))
            self.screen.blit(rendered, (self.WIDTH // 2 - rendered.get_width() // 2, self.HEIGHT // 2 + 168 + i * 20))

    def draw_trophy(self, center_x: int, top_y: int) -> None:
        gold = (244, 208, 63)
        dark_gold = (180, 135, 28)
        cup = pygame.Rect(center_x - 34, top_y, 68, 48)
        pygame.draw.rect(self.screen, gold, cup, border_radius=10)
        pygame.draw.rect(self.screen, dark_gold, cup, width=3, border_radius=10)
        pygame.draw.arc(self.screen, gold, pygame.Rect(center_x - 58, top_y + 5, 34, 38), math.pi / 2, math.pi * 1.5, 6)
        pygame.draw.arc(self.screen, gold, pygame.Rect(center_x + 24, top_y + 5, 34, 38), -math.pi / 2, math.pi / 2, 6)
        pygame.draw.rect(self.screen, gold, pygame.Rect(center_x - 6, top_y + 46, 12, 25), border_radius=3)
        pygame.draw.rect(self.screen, gold, pygame.Rect(center_x - 28, top_y + 68, 56, 10), border_radius=4)

    def draw_game_over(self) -> None:
        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 145))
        self.screen.blit(overlay, (0, 0))
        self.draw_confetti()

        panel_width = min(980, self.WIDTH - 80)
        panel_height = min(610, self.HEIGHT - 80)
        panel = pygame.Rect((self.WIDTH - panel_width) // 2, (self.HEIGHT - panel_height) // 2, panel_width, panel_height)
        pygame.draw.rect(self.screen, (24, 38, 58), panel, border_radius=18)
        pygame.draw.rect(self.screen, (244, 208, 63), panel, width=4, border_radius=18)
        pygame.draw.rect(self.screen, (236, 240, 241), panel.inflate(-16, -16), width=1, border_radius=14)

        summary = self.victory_summary or self.get_winner_statistics(self.current_player)
        winner = int(summary.get("winner", self.current_player))
        self.draw_trophy(panel.centerx, panel.y + 18)
        pulse = 12 + int(6 * (1 + math.sin(pygame.time.get_ticks() / 260.0)))
        glow = pygame.Surface((panel_width, 80), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (244, 208, 63, pulse), pygame.Rect(80, 0, panel_width - 160, 78))
        self.screen.blit(glow, (panel.x, panel.y + 74))

        title = self.font_large.render(f"VICTOIRE DU JOUEUR {winner + 1}", True, (255, 245, 170))
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 120)))
        reason_lines = self.wrap_text(str(summary.get("reason", "condition de victoire atteinte")), self.font_medium, panel_width - 120)
        for index, line in enumerate(reason_lines[:2]):
            rendered = self.font_medium.render(line, True, (236, 240, 241))
            self.screen.blit(rendered, rendered.get_rect(center=(panel.centerx, panel.y + 154 + index * 24)))

        total = max(1, int(summary.get("territory_total", len(self.territories))))
        territories = int(summary.get("territories", 0))
        percentage = round(100 * territories / total)
        left_x = panel.x + 42
        right_x = panel.centerx + 18
        top = panel.y + 216
        stats_left = [
            f"Duree : {summary.get('turn', self.turn)} tours",
            f"Statut : {summary.get('kind', '')}",
            f"Territoires : {territories}/{total} ({percentage} %)",
            f"Regiments : {summary.get('regiments', 0)}",
            f"Tresor : {summary.get('money', 0)} ecus",
            f"Culture : {summary.get('culture', 0)} | Science : {summary.get('science', 0)}",
        ]
        structures = summary.get("structures", {})
        stats_right = [
            f"Forteresses : {structures.get('forteresses', 0)}",
            f"Industries : {structures.get('industries', 0)}",
            f"Centres culturels : {structures.get('centres culturels', 0)}",
            f"Universites : {structures.get('universites', 0)}",
            f"Temples : {structures.get('temples', 0)}",
            f"Religion : {summary.get('religion', 'Aucune')} ({summary.get('religion_influence', 0)} territoires)",
            f"Lieux sacres controles : {summary.get('holy_sites', 0)}",
        ]
        for index, line in enumerate(stats_left):
            self.screen.blit(self.font_small.render(line, True, (224, 230, 236)), (left_x, top + index * 23))
        for index, line in enumerate(stats_right):
            self.screen.blit(self.font_small.render(line, True, (224, 230, 236)), (right_x, top + index * 23))

        ranking_y = panel.y + 372
        rank_title = self.font_medium.render("Classement final", True, (244, 208, 63))
        self.screen.blit(rank_title, (left_x, ranking_y))
        ranking = summary.get("ranking", [])
        for index, item in enumerate(ranking[:6]):
            player = int(item.get("player", 0))
            marker = "  VAINQUEUR" if player == winner else ""
            line = (
                f"{index + 1}. J{player + 1} - {item.get('territories', 0)} terr. - "
                f"{item.get('regiments', 0)} reg. - {item.get('money', 0)} ecus{marker}"
            )
            color = (255, 245, 170) if player == winner else (205, 213, 220)
            self.screen.blit(self.font_small.render(line, True, color), (left_x, ranking_y + 30 + index * 20))

        events_x = panel.centerx + 18
        event_title = self.font_medium.render("Derniers faits marquants", True, (244, 208, 63))
        self.screen.blit(event_title, (events_x, ranking_y))
        event_y = ranking_y + 30
        for event in summary.get("events", [])[-4:]:
            lines = self.wrap_text(str(event), self.font_small, panel.right - events_x - 32)
            for line in lines[:2]:
                self.screen.blit(self.font_small.render("- " + line, True, (205, 213, 220)), (events_x, event_y))
                event_y += 18
            event_y += 3
            if event_y > panel.bottom - 110:
                break

        replay_enabled = len(self.replay_history) >= 2
        replay_color = (170, 118, 24) if self.replay_rect.collidepoint(pygame.mouse.get_pos()) else (134, 91, 18)
        if not replay_enabled:
            replay_color = (65, 65, 65)
        pygame.draw.rect(self.screen, replay_color, self.replay_rect, border_radius=10)
        pygame.draw.rect(self.screen, (255, 245, 170) if replay_enabled else (120, 120, 120), self.replay_rect, width=2, border_radius=10)
        replay_label = f"REPLAY RAPIDE ({len(self.replay_history)} etapes)" if replay_enabled else "REPLAY INDISPONIBLE"
        replay_text = self.font_medium.render(replay_label, True, (255, 245, 170) if replay_enabled else (140, 140, 140))
        self.screen.blit(replay_text, replay_text.get_rect(center=self.replay_rect.center))

        btn_color = (64, 89, 120) if self.restart_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
        pygame.draw.rect(self.screen, btn_color, self.restart_rect, border_radius=10)
        pygame.draw.rect(self.screen, (236, 240, 241), self.restart_rect, width=2, border_radius=10)
        btn_text = self.font_medium.render("RECOMMENCER", True, (236, 240, 241))
        self.screen.blit(btn_text, btn_text.get_rect(center=self.restart_rect.center))

    def draw_replay_overlay(self) -> None:
        # Les commandes du replay occupent exclusivement le bandeau de menu.
        # La carte commence a self.map_top (90 px) et reste donc entierement visible.
        menu_bar = pygame.Rect(0, 0, self.WIDTH, 82)
        pygame.draw.rect(self.screen, (18, 28, 44), menu_bar)
        pygame.draw.line(self.screen, (244, 208, 63), (0, 82), (self.WIDTH, 82), 2)

        snapshot = self.replay_history[self.replay_index] if self.replay_history else {}
        title = self.font_medium.render("REPLAY ACCELERE", True, (255, 245, 170))
        self.screen.blit(title, (18, 8))

        progress = (
            f"Etape {self.replay_index + 1}/{max(1, len(self.replay_history))} - "
            f"Tour {snapshot.get('turn', self.turn)} - "
            f"J{int(snapshot.get('player', self.current_player)) + 1}"
        )
        self.screen.blit(self.font_small.render(progress, True, (236, 240, 241)), (18, 45))

        label = str(snapshot.get("label", "Evolution de la partie"))
        label_x = 355
        label_width = max(120, self.replay_pause_rect.left - label_x - 18)
        wrapped = self.wrap_text(label, self.font_small, label_width)
        if wrapped:
            replay_event = wrapped[0]
            if len(wrapped) > 1:
                replay_event += "..."
            self.screen.blit(
                self.font_small.render(replay_event, True, (189, 195, 199)),
                (label_x, 45),
            )

        pause_label = "REJOUER" if self.replay_finished else ("REPRENDRE" if self.replay_paused else "PAUSE")
        pause_color = (170, 118, 24) if self.replay_pause_rect.collidepoint(pygame.mouse.get_pos()) else (134, 91, 18)
        pygame.draw.rect(self.screen, pause_color, self.replay_pause_rect, border_radius=8)
        pygame.draw.rect(self.screen, (255, 245, 170), self.replay_pause_rect, width=1, border_radius=8)
        pause_text = self.font_medium.render(pause_label, True, (255, 245, 170))
        self.screen.blit(pause_text, pause_text.get_rect(center=self.replay_pause_rect.center))

        return_color = (64, 89, 120) if self.replay_return_rect.collidepoint(pygame.mouse.get_pos()) else (52, 73, 94)
        pygame.draw.rect(self.screen, return_color, self.replay_return_rect, border_radius=8)
        pygame.draw.rect(self.screen, (236, 240, 241), self.replay_return_rect, width=1, border_radius=8)
        return_text = self.font_medium.render("RETOUR AU RESULTAT", True, (236, 240, 241))
        self.screen.blit(return_text, return_text.get_rect(center=self.replay_return_rect.center))

    def draw(self) -> None:
        self.screen.fill(self.BACKGROUND_COLOR)
        self.draw_territories()
        self.draw_terre_links()
        self.draw_bridges()
        if self.phase != "replay":
            self.draw_ui()
        if self.phase == "start_menu":
            self.draw_start_menu()
        elif self.phase == "shopping":
            self.draw_shop_overlay()
            self.draw_geopolitical_panel()
            self.draw_empire_panel()
        elif self.phase == "playing":
            self.draw_geopolitical_panel()
            self.draw_empire_panel()
        elif self.phase == "game_over":
            self.draw_game_over()
        elif self.phase == "replay":
            self.draw_replay_overlay()
        if self.phase not in ("game_over", "replay"):
            self.draw_territory_tooltip()
        self.draw_major_event_modal()
        pygame.display.flip()


def main() -> None:
    game = GraphicalGame()
    game.run()


if __name__ == "__main__":
    main()
