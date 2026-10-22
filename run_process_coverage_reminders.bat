@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py process_coverage_reminders >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\process_coverage_reminders.log" 2>&1
