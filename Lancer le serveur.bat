@echo off
rem Lance le serveur du jeu web et ouvre le navigateur.
rem Laisser cette fenetre ouverte pour jouer ; la fermer arrete le serveur.
cd /d "%~dp0"

rem Si un serveur ecoute deja sur le port 8000, inutile d'en lancer un
rem deuxieme (cela echouerait) : on ouvre simplement le navigateur.
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo Le serveur tourne deja : ouverture du navigateur.
    start "" http://localhost:8000
    timeout /t 4 >nul
    exit /b
)

echo Serveur du jeu : http://localhost:8000  (fermer la fenetre pour arreter)
rem Ouvre le navigateur dans 3 secondes, le temps que le serveur demarre.
start "" cmd /c "timeout /t 3 >nul & start "" http://localhost:8000"
python -m uvicorn serveur.app:app --app-dir . --port 8000
echo.
echo Le serveur s'est arrete. Si un message d'erreur s'affiche au-dessus,
echo montre-le a Claude.
pause
