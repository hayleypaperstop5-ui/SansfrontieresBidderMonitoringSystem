@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py finalize_continuation_deadlines >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\finalize_continuation_deadlines.log" 2>&1
exit /b %ERRORLEVEL%
