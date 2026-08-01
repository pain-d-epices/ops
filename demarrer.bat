@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Searcher - Demarrage complet
echo ============================================
echo.

REM ---------------------------------------------------------------------------
REM  Ordre de lancement : Docker, API, interface, PUIS worker.
REM  Le worker charge la base Maigret (3221 sites) : environ deux minutes qui
REM  saturent le processeur et le disque. Le lancer en dernier laisse l'interface
REM  demarrer sur une machine libre, au lieu d'attendre derriere lui.
REM  Chaque etape attend une disponibilite reelle, jamais un delai fixe.
REM ---------------------------------------------------------------------------

echo [1/5] Verification de Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERREUR : Docker Desktop ne repond pas.
    echo Ouvrez Docker Desktop, attendez qu'il soit pret, puis relancez ce fichier.
    echo.
    pause
    exit /b 1
)

echo [2/5] Demarrage de la base de donnees et de Redis...
docker compose up -d postgres redis
if errorlevel 1 (
    echo.
    echo ERREUR : le demarrage de Docker Compose a echoue. Voir le detail ci-dessus.
    echo.
    pause
    exit /b 1
)

echo       Attente que PostgreSQL accepte les connexions...
set /a essais=0
:attente_postgres
docker compose exec -T postgres pg_isready -q >nul 2>&1
if not errorlevel 1 goto postgres_pret
set /a essais+=1
if %essais% geq 60 (
    echo.
    echo ERREUR : PostgreSQL n'a pas repondu apres 60 secondes.
    echo Verifiez "docker compose logs postgres".
    echo.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto attente_postgres
:postgres_pret
echo       PostgreSQL est pret.

echo [3/5] Demarrage de l'API (nouvelle fenetre)...
start "Searcher - API backend" cmd /k "cd /d "%~dp0backend" && set PYTHONIOENCODING=utf-8 && .venv\Scripts\python -m uvicorn app.main:app --port 8010 --reload"

echo       Attente que l'API reponde...
set /a essais=0
:attente_api
curl --fail -s -o nul -m 2 http://localhost:8010/api/sante >nul 2>&1
if not errorlevel 1 goto api_prete
set /a essais+=1
if %essais% geq 60 (
    echo.
    echo ATTENTION : l'API n'a pas repondu apres 60 secondes.
    echo Regardez la fenetre "Searcher - API backend" : elle affiche l'erreur.
    echo Le demarrage continue quand meme.
    echo.
    goto api_prete
)
timeout /t 1 /nobreak >nul
goto attente_api
:api_prete
echo       L'API repond.

echo [4/5] Demarrage de l'interface web (nouvelle fenetre)...
start "Searcher - Interface web" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo       Attente que l'interface reponde...
set /a essais=0
:attente_front
curl --fail -s -o nul -m 3 http://localhost:5183/ >nul 2>&1
if not errorlevel 1 goto front_prete
set /a essais+=1
if %essais% geq 90 (
    echo.
    echo ATTENTION : l'interface n'a pas repondu apres 90 secondes.
    echo Regardez la fenetre "Searcher - Interface web".
    echo.
    goto front_prete
)
timeout /t 1 /nobreak >nul
goto attente_front
:front_prete
REM Une premiere requete force Vite a preparer le code de l'application : sans
REM elle, ce travail se ferait pendant que vous regardez une page blanche.
echo       Preparation du code de l'interface...
curl --fail -s -o nul -m 60 http://localhost:5183/src/main.tsx >nul 2>&1
echo       L'interface est prete.

echo [5/5] Demarrage du worker de taches (nouvelle fenetre)...
start "Searcher - Worker (recherche, enrichissement, pivot)" cmd /k "cd /d "%~dp0backend" && set PYTHONIOENCODING=utf-8 && .venv\Scripts\python -m celery -A app.taches.celery_app worker -Q recherche,enrichissement,pivot,maintenance --pool=solo --loglevel=info"

start "" "http://localhost:5183"

echo.
echo ============================================
echo   Tout est lance.
echo ============================================
echo.
echo Trois nouvelles fenetres se sont ouvertes : API, interface web, worker.
echo NE LES FERMEZ PAS pendant que vous utilisez Searcher.
echo.
echo L'interface est utilisable tout de suite. En revanche, le worker charge la
echo base Maigret : comptez environ deux minutes avant que la PREMIERE recherche
echo puisse demarrer. Les suivantes partent immediatement. La fenetre du worker
echo affiche "ready" quand il a fini de charger.
echo.
echo Pour tout arreter : fermez ces trois fenetres, puis lancez arreter.bat
echo (cela coupera aussi PostgreSQL et Redis).
echo.
echo Cette fenetre-ci peut etre fermee sans probleme.
echo.
pause
endlocal
