"""Parite moteur <-> x45 ORIGINAL des actions d'achat (etape 1c.2).

Pour chaque sauvegarde, l'etat est charge dans la copie d'origine
(``x45-original.py``) et dans le moteur, le joueur courant recoit le meme
tresor et la meme science des deux cotes, puis une sequence d'achats
deterministe est rejouee en parallele : mercenaires, constructions,
destructions, vente, don, corruption, revolte, merveille, capitale, ponts,
alliances, manipulation ONU, association PF.

Apres chaque achat, le message (succes ou refus, textes de x45) et l'etat
serialise complet doivent etre identiques.

Lancement, depuis le dossier "Jeux Strat" :
    python -m unittest discover -s tests -v
"""

import json
import os
import random
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moteur import GameState
from moteur import achats
from moteur import regles

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_parite_original import import_original_module, ORIGINAL_PATH
from test_parite_x45 import (
    ALLIANCE_LIST_KEYS, SET_LIKE_KEYS, retirer_cles_hors_original,
)

SAVES_DIR = Path(__file__).resolve().parents[1] / "parties_en_cours"
RANDOM_SEED = 20260722
MONEY_BOOST = 100000
SCIENCE_BOOST = 250


def iter_save_files():
    """Les sauvegardes comparables a l'original.

    Les sauvegardes creees depuis les nouvelles regles de juillet 2026
    peuvent contenir des merveilles culturelles, inconnues de
    ``x45-original.py`` (qui les supprime au chargement) : la parite des
    achats n'a de sens que pour les sauvegardes anterieures.
    """
    fichiers = []
    for chemin in sorted(SAVES_DIR.glob("*.json")):
        try:
            payload = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if any(
            regles.is_cultural_wonder_type(wonder_type)
            for wonder_type in payload.get("wonder_territories", {})
        ):
            continue
        fichiers.append(chemin)
    return fichiers


class TestPariteAchats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
        if not ORIGINAL_PATH.exists():
            raise unittest.SkipTest("x45-original.py absent.")
        try:
            if "x45_original" in sys.modules:
                original = sys.modules["x45_original"]
            else:
                original = import_original_module()
        except Exception as exc:
            raise unittest.SkipTest(f"x45-original non importable ici : {exc}")
        original.tk = None
        original.messagebox = None
        cls.original = original
        cls.game = original.GraphicalGame()

    def load_both(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        random.seed(RANDOM_SEED)
        self.game.phase = "setup"
        self.game.apply_saved_game_state(json.loads(json.dumps(payload)))
        random.seed(RANDOM_SEED)
        state = GameState.from_payload(payload)
        regles.sanitize_after_load(state)

        # Meme tresor et meme science des deux cotes pour exercer les achats.
        for holder in (self.game, state):
            player = holder.current_player
            holder.player_money[player] = holder.player_money.get(player, 0) + MONEY_BOOST
            holder.player_science[player] = SCIENCE_BOOST
        return self.game, state

    def as_json(self, payload):
        payload = json.loads(json.dumps(payload))
        for key in SET_LIKE_KEYS:
            if isinstance(payload.get(key), list):
                payload[key] = sorted(payload[key])
        for key, sort_fields in ALLIANCE_LIST_KEYS.items():
            if isinstance(payload.get(key), list):
                payload[key] = sorted(
                    payload[key],
                    key=lambda item: tuple(item.get(field) for field in sort_fields),
                )
        return payload

    def compare_states(self, game, state, label):
        self.assertEqual(
            self.as_json(game.build_game_payload()),
            retirer_cles_hors_original(self, self.as_json(state.to_payload())),
            f"etat divergent apres l'achat '{label}'",
        )

    def first_owned(self, state, predicate=lambda terr: True):
        for terr in state.territories:
            if terr.owner == state.current_player and predicate(terr):
                return terr.id
        return None

    def first_enemy(self, state, predicate=lambda terr: True):
        for terr in state.territories:
            if terr.owner != state.current_player and terr.owner >= 0 and predicate(terr):
                return terr.id
        return None

    def run_pair(self, game, state, label, original_call, engine_call, seed_offset=0):
        """Execute l'achat des deux cotes avec le meme germe et compare."""
        game.message = ""
        random.seed(RANDOM_SEED + seed_offset)
        original_call()
        original_message = game.message

        random.seed(RANDOM_SEED + seed_offset)
        result = engine_call()

        self.assertEqual(
            original_message, result.message,
            f"message divergent pour l'achat '{label}'",
        )
        self.compare_states(game, state, label)

    def test_parite_des_achats(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                game, state = self.load_both(path)

                # --- Mercenaires (quantite fixee) ---
                tid = self.first_owned(state)
                if tid is not None:
                    def orig_mercenaires(tid=tid):
                        game.shop_mercenary_quantity = 5
                        game.execute_shop_mercenary_purchase(game.territories[tid])
                    self.run_pair(
                        game, state, "mercenaires",
                        orig_mercenaires,
                        lambda tid=tid: achats.acheter_mercenaires(state, state.territories[tid], 5),
                    )

                # --- Constructions sur territoire possede ---
                simple_builds = [
                    ("forteresse", "execute_shop_build_fortress", achats.construire_forteresse),
                    ("temple", "execute_shop_build_temple", achats.construire_temple),
                    ("centre_culturel", "execute_shop_build_cultural_center", achats.construire_centre_culturel),
                    ("universite", "execute_shop_build_university", achats.construire_universite),
                ]
                for index, (label, method_name, engine_func) in enumerate(simple_builds):
                    tid = self.first_owned(state)
                    if tid is None:
                        continue
                    self.run_pair(
                        game, state, label,
                        lambda tid=tid, m=method_name: getattr(game, m)(game.territories[tid]),
                        lambda tid=tid, f=engine_func: f(state, state.territories[tid]),
                        seed_offset=index + 1,
                    )

                # --- Industrie (usine) sur un territoire encore vierge ---
                tid = self.first_owned(
                    state, lambda terr: regles.get_industrial_structure_count(state, terr.id) == 0)
                if tid is not None:
                    self.run_pair(
                        game, state, "usine",
                        lambda tid=tid: game.execute_shop_build_factory(game.territories[tid]),
                        lambda tid=tid: achats.construire_industrie(state, state.territories[tid], "factory"),
                    )

                # --- Merveille ---
                tid = self.first_owned(
                    state, lambda terr: regles.get_wonder_type_at_territory(state, terr.id) is None)
                if tid is not None:
                    def orig_merveille(tid=tid):
                        game.pending_wonder_type = "thousand_voices_theatre"
                        game.execute_shop_build_wonder(game.territories[tid])
                    self.run_pair(
                        game, state, "merveille",
                        orig_merveille,
                        lambda tid=tid: achats.construire_merveille(
                            state, state.territories[tid], "thousand_voices_theatre"),
                    )

                # --- Changement de capitale ---
                tid = self.first_owned(
                    state, lambda terr: not regles.is_sanctuary_territory(state, terr.id))
                if tid is not None:
                    self.run_pair(
                        game, state, "capitale",
                        lambda tid=tid: game.execute_shop_change_capital(game.territories[tid]),
                        lambda tid=tid: achats.changer_capitale(state, state.territories[tid]),
                    )

                # --- Destructions ---
                fortress_ids = sorted(state.fortress_territory_ids)
                if fortress_ids:
                    tid = fortress_ids[0]
                    self.run_pair(
                        game, state, "detruire_forteresse",
                        lambda tid=tid: game.execute_shop_destroy_fortress(game.territories[tid]),
                        lambda tid=tid: achats.detruire_forteresse(state, state.territories[tid]),
                    )
                university_ids = sorted(state.university_territory_ids)
                if university_ids:
                    tid = university_ids[0]
                    self.run_pair(
                        game, state, "detruire_universite",
                        lambda tid=tid: game.execute_shop_destroy_university(game.territories[tid]),
                        lambda tid=tid: achats.detruire_universite(state, state.territories[tid]),
                    )

                # --- Corruption d'un territoire ennemi ---
                tid = self.first_enemy(state)
                if tid is not None:
                    self.run_pair(
                        game, state, "corruption",
                        lambda tid=tid: game.execute_shop_corrupt_territory(game.territories[tid]),
                        lambda tid=tid: achats.corrompre_territoire(state, state.territories[tid]),
                        seed_offset=7,
                    )

                # --- Revolte chez un ennemi ---
                tid = self.first_enemy(state)
                if tid is not None:
                    self.run_pair(
                        game, state, "revolte",
                        lambda tid=tid: game.execute_shop_revolt(game.territories[tid]),
                        lambda tid=tid: achats.financer_revolte(state, state.territories[tid]),
                        seed_offset=8,
                    )

                # --- Vente d'un territoire possede ---
                tid = self.first_owned(state)
                if tid is not None:
                    self.run_pair(
                        game, state, "vendre_territoire",
                        lambda tid=tid: game.execute_shop_sell_territory(game.territories[tid]),
                        lambda tid=tid: achats.vendre_territoire(state, state.territories[tid]),
                        seed_offset=9,
                    )

                # --- Don de territoire (flux en deux clics cote original) ---
                source_id = self.first_owned(state)
                target_id = self.first_enemy(state)
                if source_id is not None and target_id is not None:
                    target_player = state.territories[target_id].owner
                    def orig_don(source_id=source_id, target_id=target_id):
                        game.pending_gift_territory_id = None
                        game.execute_shop_give_territory(game.territories[source_id])
                        game.message = ""
                        game.execute_shop_give_territory(game.territories[target_id])
                    self.run_pair(
                        game, state, "donner_territoire",
                        orig_don,
                        lambda source_id=source_id, target_player=target_player:
                            achats.donner_territoire(state, state.territories[source_id], target_player),
                    )

                # --- Don d'argent ---
                target_id = self.first_enemy(state)
                if target_id is not None:
                    target_player = state.territories[target_id].owner
                    def orig_argent(target_id=target_id):
                        game.shop_gift_amount = 10
                        game.execute_shop_gift_money(game.territories[target_id])
                    self.run_pair(
                        game, state, "donner_argent",
                        orig_argent,
                        lambda target_player=target_player:
                            achats.donner_argent(state, target_player, 10),
                    )

                # --- Alliances (defensive puis offensive) ---
                ai_tid = self.first_enemy(
                    state, lambda terr: regles.is_ai_player(state, terr.owner)
                    and not regles.is_sanctuary_territory(state, terr.id))
                if ai_tid is not None:
                    self.run_pair(
                        game, state, "alliance",
                        lambda tid=ai_tid: game.execute_shop_buy_alliance(game.territories[tid]),
                        lambda tid=ai_tid: achats.acheter_alliance(state, state.territories[tid]),
                    )
                ai_tid = self.first_enemy(
                    state, lambda terr: regles.is_ai_player(state, terr.owner)
                    and not regles.is_sanctuary_territory(state, terr.id))
                cible_tid = self.first_enemy(
                    state, lambda terr: ai_tid is not None
                    and terr.owner != state.territories[ai_tid].owner
                    and not regles.is_sanctuary_territory(state, terr.id))
                if ai_tid is not None and cible_tid is not None:
                    ai_player = state.territories[ai_tid].owner
                    target_player = state.territories[cible_tid].owner
                    def orig_offensive(ai_tid=ai_tid, cible_tid=cible_tid):
                        game.pending_offensive_alliance_ai = None
                        game.execute_shop_buy_offensive_alliance(game.territories[ai_tid])
                        if game.pending_offensive_alliance_ai is not None:
                            game.message = ""
                            game.execute_shop_buy_offensive_alliance(game.territories[cible_tid])
                    self.run_pair(
                        game, state, "alliance_offensive",
                        orig_offensive,
                        lambda ai_player=ai_player, target_player=target_player:
                            achats.acheter_alliance_offensive(state, ai_player, target_player),
                    )

                # --- Manipulation ONU : figer puis liberer ---
                tid = self.first_enemy(
                    state, lambda terr: not regles.is_sanctuary_territory(state, terr.id))
                if tid is not None:
                    self.run_pair(
                        game, state, "figer_onu",
                        lambda tid=tid: game.execute_shop_freeze_territory(game.territories[tid]),
                        lambda tid=tid: achats.figer_territoire(state, state.territories[tid]),
                    )
                sanctuary_ids = sorted(
                    tid for tid in state.sanctuary_territory_ids
                    if 0 <= tid < len(state.territories)
                )
                if sanctuary_ids:
                    tid = sanctuary_ids[0]
                    self.run_pair(
                        game, state, "liberer_onu",
                        lambda tid=tid: game.execute_shop_release_sanctuary(game.territories[tid]),
                        lambda tid=tid: achats.liberer_sanctuaire(state, state.territories[tid]),
                        seed_offset=11,
                    )

                # --- Association paradis fiscal (souvent un refus : compare aussi) ---
                tid = self.first_enemy(state)
                if tid is not None:
                    self.run_pair(
                        game, state, "association_pf",
                        lambda tid=tid: game.execute_shop_tax_haven_association(game.territories[tid]),
                        lambda tid=tid: achats.association_paradis_fiscal(state, state.territories[tid]),
                        seed_offset=12,
                    )

                # --- Ponts : construction (souvent refus geometrique) et destruction ---
                a = self.first_owned(state)
                b = self.first_enemy(state)
                if a is not None and b is not None and a != b:
                    def orig_pont(a=a, b=b):
                        game.pending_bridge_territory_id = a
                        game.execute_shop_build_bridge(game.territories[b])
                    self.run_pair(
                        game, state, "pont",
                        orig_pont,
                        lambda a=a, b=b: achats.construire_pont(
                            state, a, b, game.cell_width, game.cell_height),
                    )
                bridges = sorted(state.bridge_links)
                if bridges:
                    a, b = bridges[0]
                    def orig_detruire_pont(a=a, b=b):
                        game.pending_bridge_territory_id = a
                        game.execute_shop_destroy_bridge(game.territories[b])
                    self.run_pair(
                        game, state, "detruire_pont",
                        orig_detruire_pont,
                        lambda a=a, b=b: achats.detruire_pont(state, a, b),
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
