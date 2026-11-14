# Arranca EITO Dev en local: Python 3.12 en Docker, con .env.dev y el PostgreSQL eito-dev-pg.
# El codigo se copia SIN .env para que load_dotenv() no rellene variables con las de produccion.
# Uso (desde cualquier carpeta): powershell -ExecutionPolicy Bypass -File scripts\dev.ps1   (Ctrl+C para parar)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..").Path

if (-not (Test-Path "$repo\.env.dev")) { throw "Falta .env.dev en $repo (DISCORD_TOKEN de EITO Dev y DATABASE_URL de eito-dev-pg)." }
if ((docker inspect -f "{{.State.Running}}" eito-dev-pg) -ne "true") { docker start eito-dev-pg | Out-Null }

docker run --rm -it --name eito-dev-bot --network eito-dev --env-file "$repo\.env.dev" `
    -v "${repo}:/src:ro" -v eito-dev-pip:/root/.cache/pip python:3.12-slim sh -c `
    "mkdir /app && tar -C /src --exclude=.env --exclude=.env.dev --exclude=.venv --exclude=.git --exclude=__pycache__ --exclude=.pytest_cache -cf - . | tar -C /app -xf - && cd /app && pip install -q --root-user-action=ignore -r requirements.txt && python -u eito_setup_bot.py"
