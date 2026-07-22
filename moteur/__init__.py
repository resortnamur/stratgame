"""Moteur de jeu pur (sans pygame) pour la future version en ligne.

Premiere etape de la migration : l'etat complet d'une partie vit ici, dans des
dataclasses Python pures, serialisables en JSON avec le meme format que les
sauvegardes de x45.py (parties_en_cours/*.json).
"""

from .etat import GameState, Territory, SAVE_SCHEMA_VERSION
from .regles import sanitize_after_load

__all__ = ["GameState", "Territory", "SAVE_SCHEMA_VERSION", "sanitize_after_load"]
