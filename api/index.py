"""
Vercel entry point — importa o app FastAPI de web/app.py.
"""
import sys
from pathlib import Path

# Garante que a raiz do projeto está no Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from web.app import app  # noqa: F401 — Vercel usa o objeto `app`
