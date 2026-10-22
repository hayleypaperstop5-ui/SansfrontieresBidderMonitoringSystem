@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py check_player_coverage >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\check_player_coverage.log" 2>&1
