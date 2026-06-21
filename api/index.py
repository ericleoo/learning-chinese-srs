"""Vercel serverless entrypoint — wraps the Flask app for WSGI."""

import os
import sys

# Ensure the project root is on sys.path so imports (app, db) resolve correctly
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from app import app

# Vercel's Python runtime looks for a WSGI-compatible callable named `app`
