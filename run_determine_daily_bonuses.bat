@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py determine_daily_bonuses >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\determine_daily_bonuses.log" 2>&1
