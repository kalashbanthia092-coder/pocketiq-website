"""
PythonAnywhere WSGI configuration.

This file is a TEMPLATE. PythonAnywhere does not read it from the repo.
Open the WSGI file linked on your Web tab, delete everything in it, then paste
the contents below, replacing YOURUSERNAME.

Note: the Procfile in this repo (gunicorn) is for Heroku-style hosts and is
ignored by PythonAnywhere, which uses this WSGI entry point instead.
"""

import os
import sys

# --- 1. Put the project on the import path -------------------------------
PROJECT_DIR = "/home/YOURUSERNAME/pocketiq-website"

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# --- 2. Load secrets -----------------------------------------------------
# backend.py already loads .env from its own directory, so this is belt and
# braces. Harmless if the file is missing.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_DIR, ".env"))
except ImportError:
    pass

# --- 3. Hand the Flask app to the server ---------------------------------
# Must be named `application`.
from backend import app as application  # noqa: E402
