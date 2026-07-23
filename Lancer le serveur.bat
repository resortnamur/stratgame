@echo off
rem Lance le serveur du jeu web. Laisser cette fenetre ouverte pour jouer ;
rem la fermer (ou Ctrl+C) arrete le serveur.
cd /d "%~dp0"
echo Serveur du jeu : http://localhost:8000  (Ctrl+C pour arreter)
python -m uvicorn serveur.app:app --app-dir . --port 8000
pause
