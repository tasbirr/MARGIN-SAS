#!/usr/bin/env python3
"""Simple server runner"""
import os
import sys

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Import after preparing folders so app startup can write artifacts safely.
from app import app

if __name__ == '__main__':
    print("Starting MARGIN-SAS API Server...")
    print("Server running at http://127.0.0.1:5000")
    print("Press Ctrl+C to stop")
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
