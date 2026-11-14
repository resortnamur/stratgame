"""Parite moteur <-> x45 au chargement d'une sauvegarde (etape 1b).

Chaque sauvegarde de parties_en_cours/ est chargee deux fois :
- par x45 (GraphicalGame headless, pilote video SDL "dummy"), via
  ``apply_saved_game_state`` qui execute les sanitisations de regles ;
- par le moteur, via ``GameState.from_payload`` + ``sanitize_after_load``.

Les deux resultats sont ensuite serialises (``build_game_payload`` cote x45,
``to_payload`` cote moteur) et compares cle par cle : ils doivent etre
strictement identiques. L'aleatoire (attribution des territoires dores sans
proprietaire) est aligne en ressemant le meme germe des deux cotes.

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
from moteur.regles import sanitize_after_load

SAVES_DIR = Path(__file__).resolve().parents[1] / "parties_en_cours"
RANDOM_SEED = 20260722

# Cles emises par x45 comme ``list(set)`` sans ordre garanti ; le moteur les
# normalise en listes triees. Ce sont semantiquement des ensembles : elles
# sont comparees apres tri.
SET_LIKE_KEYS = {
    "base_ai_players", "auto_controlled_players", "human_controlled_players",
    "eliminated_human_players", "commercial_city_players",
    "super_territory_ids", "ultra_super_territory_ids",
    "golden_territory_ids", "sanctuary_territory_ids",
    "fortress_territory_ids", "industry_territory_ids",
    "factory_territory_ids", "airport_territory_ids", "port_territory_ids",
    "university_territory_ids", "temple_territory_ids",
    "last_stand_bonus_players",
}

# Listes d'objets emises par x45 dans l'ordre d'insertion de ses dicts ; le
# moteur les emet triees par cle. L'ordre est sans signification (rechargees
# dans des dicts) : elles sont comparees apres tri canonique.
ALLIANCE_LIST_KEYS = {
    "active_alliances": ("human", "ai"),
    "active_ai_alliances": ("ai_a", "ai_b"),
    "active_offensive_alliances": ("human", "ai"),
}


# Cles d'etat nees APRES x45-original.py : la reference figee ne les produit
# pas. Les tests de parite contre l'original les retirent du payload moteur,
# mais seulement apres avoir verifie qu'elles sont vides — sinon la
# comparaison masquerait une vraie divergence de mise en place ou d'achat.
CLES_ABSENTES_DE_L_ORIGINAL = (
    "ruin_territory_ids", "eternal_ally_player", "eternal_ally_patron",
    "victory_milestones", "ai_last_missile_turns",
    "apocalypse_site_stages", "apocalypse_site_owners",
    "special_territories", "special_territory_holders",
)
# Cles qu'une regle nouvelle remplit des le premier achat concerne (compteur
# de merveilles baties, plafond de novembre 2026) : retirees sans verifier
# qu'elles sont vides, puisqu'elles ne le sont pas des que l'on batit.
# L'objectif en cours (novembre 2026) : la partie ne vise plus qu'une
# condition de victoire a la fois. Elle est tiree des le premier examen des
# paliers, donc jamais vide — et l'original figé n'en sait rien.
CLES_SANS_EQUIVALENT_DANS_L_ORIGINAL = (
    "player_wonders_built", "victory_objective", "victory_objective_turn",
)
# Meme chose dans les instantanes de replay, ou la cle porte un autre nom.
CLES_D_INSTANTANE_ABSENTES_DE_L_ORIGINAL = ("ruins",)


# Les annonces qu'une regle nouvelle inscrit dans les evenements majeurs :
# l'original fige ne les connait pas. L'objectif en cours (novembre 2026)
# s'annonce des la mise en place, puis a chaque palier franchi.
ANNONCES_HORS_ORIGINAL = ("OBJECTIF DE LA PARTIE", "NOUVEL OBJECTIF")


def _sans_annonces_nouvelles(evenements):
    return [
        evenement for evenement in evenements
        if not any(marque in str(evenement) for marque in ANNONCES_HORS_ORIGINAL)
    ]


def retirer_annonces_hors_original(payload):
    """Retire des evenements majeurs ce que l'original n'annonce pas."""
    if isinstance(payload.get("recent_major_events"), list):
        payload["recent_major_events"] = _sans_annonces_nouvelles(
            payload["recent_major_events"],
        )
    attente = payload.get("pending_major_events_for_humans")
    if isinstance(attente, dict):
        restant = {}
        for joueur, evenements in attente.items():
            garde = _sans_annonces_nouvelles(evenements)
            # Une file que le filtrage a videe n'existait pas du tout dans
            # l'original : elle disparait, au lieu de rester en liste vide.
            if garde or not evenements:
                restant[joueur] = garde
        payload["pending_major_events_for_humans"] = restant
    # La fenetre d'evenement majeur ouverte par la seule annonce de
    # l'objectif n'existe pas non plus dans l'original.
    modal = payload.get("major_event_modal")
    if isinstance(modal, dict) and isinstance(modal.get("events"), list):
        garde = _sans_annonces_nouvelles(modal["events"])
        payload["major_event_modal"] = None if not garde else dict(modal, events=garde)
    file_modale = payload.get("major_event_modal_queue")
    if isinstance(file_modale, list):
        restantes = []
        for fenetre in file_modale:
            if not isinstance(fenetre, dict) or not isinstance(fenetre.get("events"), list):
                restantes.append(fenetre)
                continue
            garde = _sans_annonces_nouvelles(fenetre["events"])
            if garde:
                restantes.append(dict(fenetre, events=garde))
        payload["major_event_modal_queue"] = restantes
    return payload


def retirer_cles_hors_original(test, payload):
    retirer_annonces_hors_original(payload)
    for cle in CLES_SANS_EQUIVALENT_DANS_L_ORIGINAL:
        payload.pop(cle, None)
    for cle in CLES_ABSENTES_DE_L_ORIGINAL:
        valeur = payload.pop(cle, None)
        test.assertFalse(valeur, f"'{cle}' devrait etre vide face a x45-original")
    for instantane in payload.get("replay_history", []):
        if not isinstance(instantane, dict):
            continue
        for cle in CLES_D_INSTANTANE_ABSENTES_DE_L_ORIGINAL:
            valeur = instantane.pop(cle, None)
            test.assertFalse(
                valeur, f"'{cle}' devrait etre vide dans les instantanes de replay",
            )
    return payload


def iter_save_files():
    return sorted(SAVES_DIR.glob("*.json"))


class TestPariteChargementX45(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.save_files = iter_save_files()
        if not cls.save_files:
            raise unittest.SkipTest("Aucune sauvegarde dans parties_en_cours/.")
        try:
            import x45
        except Exception as exc:  # pygame absent ou affichage impossible
            raise unittest.SkipTest(f"x45 non importable ici : {exc}")
        cls.x45 = x45
        cls.game = x45.GraphicalGame()

    def load_payload(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def as_json(self, payload):
        # Normalise tuples/sets en types JSON purs, comme un vrai fichier,
        # puis trie les cles qui representent des ensembles.
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

    def test_parite_apres_sanitisations(self):
        for path in self.save_files:
            with self.subTest(sauvegarde=path.name):
                payload = self.load_payload(path)

                random.seed(RANDOM_SEED)
                # L'instance x45 est reutilisee : on remet la phase d'avant
                # chargement, comme un chargement depuis le menu (et comme
                # sanitize_after_load cote moteur).
                self.game.phase = "setup"
                self.game.apply_saved_game_state(json.loads(json.dumps(payload)))
                x45_payload = self.as_json(self.game.build_game_payload())

                random.seed(RANDOM_SEED)
                state = GameState.from_payload(payload)
                sanitize_after_load(state)
                engine_payload = self.as_json(state.to_payload())

                self.assertEqual(
                    sorted(x45_payload.keys()), sorted(engine_payload.keys()),
                    "jeux de cles differents entre x45 et le moteur",
                )
                for key in sorted(x45_payload.keys()):
                    self.assertEqual(
                        x45_payload[key], engine_payload[key],
                        f"divergence sur la cle '{key}'",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
