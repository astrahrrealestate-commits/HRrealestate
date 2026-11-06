@echo off
echo ========================================================
echo Starting EstateOS QA Testing Stack...
echo ========================================================
echo.
echo Running Docker Compose...
docker compose -f docker/compose.test.yml up --build

pause

