@echo off
chcp 65001 > nul
cd /d %~dp0
python -m pip install -q playwright pypdf
python genelife_pdf_export.py %*
pause
