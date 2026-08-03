"""Vercel serverless entry for /api/*. Vercel requires a `handler` class defined
in this file, so we subclass app.py's Handler (which does all the routing)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ (siblings)
from app import Handler as _AppHandler  # noqa: E402


class handler(_AppHandler):
    pass
