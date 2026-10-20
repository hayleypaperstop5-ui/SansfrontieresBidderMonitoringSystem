@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py close_expired_coverage >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\close_expired_coverage.log" 2>&1
