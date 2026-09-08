@echo off
REM Launches AGNIES: nginx (reverse proxy, :8050), Django/waitress (:8060),
REM and the workflow worker (TCP :8765, websocket :8061) each in their own
REM Windows Terminal tab, in one window.

wt -w -1 ^
  new-tab --title "nginx" -d "C:\nginx" cmd /k nginx.exe ; ^
  new-tab --title "waitress" -d "C:\Users\souls\Desktop\Manoj\AGNEIS\agnies_agent" cmd /k ..\.venv\Scripts\waitress-serve.exe --host=127.0.0.1 --port=8060 backend.wsgi:application ; ^
  new-tab --title "workflow" -d "C:\Users\souls\Desktop\Manoj\AGNEIS\agnies_agent" cmd /k ..\.venv\Scripts\python.exe -m workflow.main
