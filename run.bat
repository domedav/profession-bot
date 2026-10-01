@echo off
cd /d "%~dp0"
if not exist ".venv" (
  py -3 -m venv .venv
)
call .venv\Scripts\activate
python -m pip install -r requirements.txt
if not exist "%USERPROFILE%\AppData\Local\ms-playwright" (
  python -m playwright install firefox
)
python server.py %*
