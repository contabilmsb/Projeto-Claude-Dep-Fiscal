"""
Inicializa o portal web de Apuração PIS/COFINS e abre o navegador automaticamente.
Uso: python iniciar_portal.py
"""

import sys
import time
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 8000
URL  = f"http://{HOST}:{PORT}"


def open_browser():
    time.sleep(2)
    webbrowser.open(URL)


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        print("[!] uvicorn não encontrado. Instale: pip install fastapi uvicorn python-multipart")
        sys.exit(1)

    print(f"\n  Portal disponível em: {URL}\n")
    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(
        "web.app:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
