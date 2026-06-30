@echo off
REM ============================================================
REM  Treeni-ty-kalu - Windows-kaynnistys
REM  Tuplaklikkaa tata tiedostoa. Se asentaa tarvittavat
REM  ensimmaisella kerralla, kaynnistaa sovelluksen ja avaa
REM  selaimen osoitteeseen http://localhost:8000
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Treeni-ty-kalu

REM --- Etsi Python. Suositaan vakaita versioita (3.12/3.11), joille loytyy
REM     varmasti valmiit paketit. Hyvin uusi versio voi puuttua paketteja. ---
set "PYEXE="
where py >nul 2>nul
if %errorlevel%==0 (
  for %%V in (3.12 3.11 3.13 3.10) do (
    if not defined PYEXE (
      py -%%V -c "import sys" >nul 2>nul
      if !errorlevel!==0 set "PYEXE=py -%%V"
    )
  )
  if not defined PYEXE set "PYEXE=py -3"
)
if not defined PYEXE (
  where python >nul 2>nul
  if !errorlevel!==0 set "PYEXE=python"
)
if not defined PYEXE (
  echo.
  echo  Pythonia ei loytynyt koneelta.
  echo  Asenna Python 3.12: https://www.python.org/downloads/release/python-3127/
  echo  TARKEAA: rastita asennuksessa "Add Python to PATH".
  echo.
  pause
  exit /b 1
)
echo  Kaytetaan Pythonia: !PYEXE!

REM --- Luo virtuaaliymparisto jos puuttuu ---
if not exist ".venv\Scripts\python.exe" (
  echo  Luodaan ymparisto...
  !PYEXE! -m venv .venv
)

REM --- Asenna riippuvuudet jos puuttuvat (myos jos edellinen asennus jai kesken) ---
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, pydantic" >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Asennetaan tarvittavat osat... Tama voi kestaa pari minuuttia.
  echo.
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, sqlalchemy, pydantic" >nul 2>nul
  if errorlevel 1 (
    echo.
    echo  Asennus epaonnistui.
    echo  Yleisin syy: kayttamasi Python-versio on niin uusi, ettei valmiita
    echo  paketteja ole viela. Korjaus: asenna Python 3.12 ja kokeile uudelleen:
    echo    https://www.python.org/downloads/release/python-3127/
    echo  (Voit poistaa .venv-kansion ennen uutta yritysta.)
    echo.
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

REM --- Kaynnista palvelin (jaa tahan pyorimaan). 0.0.0.0 = myos puhelin samassa
REM     wifissa paasee kasiksi; sovellus nayttaa osoitteen ruudulla. Windows voi
REM     kysya palomuurilupaa ensimmaisella kerralla -> valitse "Salli". ---
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo  Palvelin sammutettu.
pause
