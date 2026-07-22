"""Serveur web du jeu (etape 2 de la migration).

- ``partie.py`` : sessions de partie pures (moteur + arbitrage des sieges),
  sans dependance web — testables en unittest.
- ``app.py`` : application FastAPI (REST + WebSockets) qui expose les
  sessions aux clients.
"""
