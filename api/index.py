"""Vercel serverless entrypoint — wraps the Flask app for WSGI."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app
