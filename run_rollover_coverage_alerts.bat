@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py rollover_coverage_alerts >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\rollover_coverage_alerts.log" 2>&1
exit /b %ERRORLEVEL%
