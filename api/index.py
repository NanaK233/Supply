"""Vercel serverless entry for the API. Vercel routes /api/* here (see vercel.json);
static files are served from public/ directly. Reuses app.py's request Handler."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import Handler as handler  # noqa: E402
