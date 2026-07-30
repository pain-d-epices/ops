@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Searcher - Demarrage complet
echo ============================================
echo.

echo [1/4] Verification de Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERREUR : Docker Desktop ne repond pas.
    echo Ouvrez Docker Desktop, attendez qu'il soit pret, puis relancez ce fichier.
    echo.
    pause
    exit /b 1
)

echo [2/4] Demarrage de la base de donnees et de Redis (Docker)...
docker compose up -d postgres redis
if errorlevel 1 (
    echo.
    echo ERREUR : le demarrage de Docker Compose a echoue. Voir le detail ci-dessus.
    echo.
    pause
    exit /b 1
)

echo Attente que la base de donnees soit prete...
timeout /t 5 /nobreak >nul

echo [3/4] Demarrage de l'API et du worker de taches (nouvelles fenetres)...
start "Searcher - API backend" cmd /k "cd /d "%~dp0backend" && set PYTHONIOENCODING=utf-8 && .venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload"
timeout /t 2 /nobreak >nul
start "Searcher - Worker (recherche, enrichissement, pivot)" cmd /k "cd /d "%~dp0backend" && set PYTHONIOENCODING=utf-8 && .venv\Scripts\python -m celery -A app.taches.celery_app worker -Q recherche,enrichissement,pivot,maintenance --pool=solo --loglevel=info"

echo [4/4] Demarrage de l'interface web (nouvelle fenetre)...
start "Searcher - Interface web" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo Attente du demarrage de l'interface avant d'ouvrir le navigateur...
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo ============================================
echo   Tout est lance.
echo ============================================
echo.
echo Trois nouvelles fenetres se sont ouvertes : API, worker, interface web.
echo NE LES FERMEZ PAS pendant que vous utilisez Searcher.
echo Pour tout arreter : fermez ces trois fenetres, puis lancez arreter.bat
echo (cela coupera aussi PostgreSQL et Redis).
echo.
echo Cette fenetre-ci peut etre fermee sans probleme.
echo.
pause
endlocal
