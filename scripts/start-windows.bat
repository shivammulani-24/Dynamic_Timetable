@echo off
rem Starts the Dynamic Timetable on this Windows laptop: server, worker and the app (Expo).
rem The app opens in this laptop's browser; scan the QR code with Expo Go to use it on a phone too.
rem Double-click this file, or run:  scripts\start-windows.bat
setlocal
set "ROOT=%~dp0.."

rem This laptop's Wi-Fi address, so a phone can reach it (blank if Wi-Fi is not connected).
set "IP="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias 'Wi-Fi' -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress"`) do set "IP=%%i"
if defined IP set "REACT_NATIVE_PACKAGER_HOSTNAME=%IP%"

start "Timetable server" /D "%ROOT%\backend" cmd /k ".venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port 8000"
start "Timetable worker" /D "%ROOT%\backend" cmd /k ".venv\Scripts\python -m app.worker"
start "Timetable app" /D "%ROOT%\mobile" cmd /k "npx expo start --clear --web"

echo.
echo Three windows are starting: server, worker and app. Keep them open; close them to stop.
echo.
echo   Laptop : the app opens in your browser (http://localhost:8081) once it has built.
if defined IP echo   Phone  : on the same Wi-Fi/hotspot, open http://%IP%:8000/healthz in the phone browser,
if defined IP echo            then scan the QR code in the "Timetable app" window with Expo Go.
if not defined IP echo   Phone  : Wi-Fi not detected - connect to Wi-Fi or your phone's hotspot and run this again.
echo.
echo   Login  : student.se.a1@demo.college.edu  /  Demo@12345   (more in docs\11-run-on-phone.md)
echo.
pause
