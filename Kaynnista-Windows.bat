@echo off
REM ============================================================
REM  Treeni-ty-kalu - Windows-kaynnistys
REM  Tuplaklikkaa tata tiedostoa. Se asentaa tarvittavat
REM  ensimmaisella kerralla, kaynnistaa sovelluksen ja avaa
REM  selaimen osoitteeseen http://localhost:8000
REM ============================================================
setlocal
cd /d "%~dp0"
title Treeni-ty-kalu

REM --- Etsi Python (py-launcher tai python) ---
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo.
  echo  Pythonia ei loytynyt koneelta.
  echo  Asenna Python 3.11 tai uudempi: https://www.python.org/downloads/
  echo  TARKEAA: rastita asennuksessa "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

REM --- Ensimmainen kaynnistys: luo ymparisto ja asenna riippuvuudet ---
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  Ensimmainen kaynnistys: asennetaan tarvittavat osat...
  echo  Tama voi kestaa pari minuuttia. Odota rauhassa.
  echo.
  %PYEXE% -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo  Asennus epaonnistui. Tarkista internetyhteys ja yrita uudelleen.
    pause
    exit /b 1
  )
)

echo.
echo  Kaynnistetaan Treeni-ty-kalu...
echo  Selain aukeaa hetken kuluttua: http://localhost:8000
echo  Sulje tama musta ikkuna kun haluat sammuttaa sovelluksen.
echo.

REM --- Avaa selain ~4 sekunnin kuluttua (kun palvelin on pystyssa) ---
start "" /min cmd /c "ping -n 5 127.0.0.1 >nul & start http://localhost:8000"

REM --- Kaynnista palvelin (jaa tahan pyorimaan) ---
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo  Palvelin sammutettu.
pause
