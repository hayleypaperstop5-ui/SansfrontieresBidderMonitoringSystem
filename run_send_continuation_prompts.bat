@echo off
cd /d "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem"
"C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\.venv\Scripts\python.exe" manage.py send_continuation_prompts >> "C:\Users\Wakura\SansfrontieresBidderMonitoringSystem\logs\send_continuation_prompts.log" 2>&1
exit /b %ERRORLEVEL%
