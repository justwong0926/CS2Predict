@echo off
REM Daily forward-collection for CS2Predict (run via Windows Task Scheduler).
cd /d "C:\Users\justw\Documents\GithubProjects\CS2Predict"
".venv\Scripts\python.exe" -m jobs.collect_forward --days 7 >> "data\collect.log" 2>&1
