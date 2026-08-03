"""Vercel serverless entry for the API.

Vercel routes /api/* here (see vercel.json). Static files are served directly
from public/ by Vercel. This reuses the existing request Handler from app.py,
which already routes every /api/... path; static requests never reach it.
"""

import os
import sys

# Make the shared modules at the project root importable from inside /api.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import Handler as handler  # noqa: E402  (Vercel Python looks for `handler`)
