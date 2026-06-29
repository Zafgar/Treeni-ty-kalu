#!/usr/bin/env bash
# Käynnistää Treeni-ty-kalu -sovelluksen paikallisesti.
# Käyttö:  ./run.sh
set -e

cd "$(dirname "$0")"

# Luo virtuaaliympäristö tarvittaessa ja asenna riippuvuudet.
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi

echo "Avaa selaimessa: http://localhost:8000"
cd backend
exec ../.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
