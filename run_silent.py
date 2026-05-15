# run_silent.py
import uvicorn
import sys
import os

# Suppress all output
sys.stdout = open(os.devnull, 'w')
sys.stderr = open(os.devnull, 'w')

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=4321,
        log_level="critical",
        access_log=False
    )