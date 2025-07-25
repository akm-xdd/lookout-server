#!/bin/bash
# Azure App Service startup script
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000