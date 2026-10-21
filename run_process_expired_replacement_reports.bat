@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py process_expired_replacement_reports >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\process_expired_replacement_reports.log" 2>&1
