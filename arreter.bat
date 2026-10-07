@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Ops - Arret complet
echo ============================================
echo.
echo Fermez d'abord manuellement les fenetres "Ops - ..." si elles sont
echo encore ouvertes (API, worker, interface web), puis appuyez sur une touche
echo pour arreter PostgreSQL et Redis.
echo.
pause

echo Arret de PostgreSQL et Redis...
docker compose stop postgres redis

echo.
echo Tout est arrete.
echo.
pause
endlocal
