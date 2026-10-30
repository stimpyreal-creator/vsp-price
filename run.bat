@echo off
cd /d "%~dp0"
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m streamlit run app.py --server.address 0.0.0.0
) else (
  python -m streamlit run app.py --server.address 0.0.0.0
)
