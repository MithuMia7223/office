#!/bin/bash

# Navigate to project directory
cd /Users/mdmithumia/office

# Keep Mac awake during execution using caffeinate
# -d: prevents display sleep, -i: prevents system idle sleep, -s: prevents system sleep
caffeinate -dis /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
