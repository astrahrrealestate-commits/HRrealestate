@echo off
setlocal
echo ========================================================
echo Starting EstateOS QA Testing Stack...
echo ========================================================
echo.

:: 1. If the offline bundle tar exists in the same folder, load it automatically
if exist "%~dp0estateos-bundle.tar" (
    echo [1/2] Loading offline Docker images from estateos-bundle.tar...
    docker load -i "%~dp0estateos-bundle.tar"
    echo Done loading images.
    echo.
)

:: 2. Resolve compose file path (works whether placed in root or docker/ folder)
set COMPOSE_FILE=%~dp0docker\compose.test.yml
if not exist "%COMPOSE_FILE%" (
    set COMPOSE_FILE=%~dp0compose.test.yml
)

echo [2/2] Launching EstateOS containers...
docker compose -f "%COMPOSE_FILE%" up

pause
