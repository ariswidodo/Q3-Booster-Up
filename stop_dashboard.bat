@echo off
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*Q3_Booster_Up*server.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Q3 Booster Up server dihentikan.
timeout /t 2 >nul
