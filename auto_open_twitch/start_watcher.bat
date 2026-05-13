@echo off
REM Starts the Twitch live watcher.
REM
REM Run launch_opera.bat FIRST so the watcher can see your existing tabs via
REM Chrome DevTools Protocol. Make sure Ollama is running too if you want
REM LLM-generated lurk messages instead of the messages.txt templates.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Could not find .venv\Scripts\python.exe in %CD%.
    echo Recreate the venv via VS Code "Python: Create Environment" or:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" watcher.py
pause
