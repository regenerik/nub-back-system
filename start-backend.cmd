@echo off
cd /d "%~dp0"
"%~dp0myenv\Scripts\python.exe" run.py > server.out.log 2> server.err.log
