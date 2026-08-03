"""Vercel serverless entry. /api/* is routed here; static served from public/."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # api/ (siblings)
from app import Handler as handler  # noqa: E402
