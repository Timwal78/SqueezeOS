"""
Minimal entrypoint for Render Python-runtime services where the build step
does not reliably install requirements.txt into the venv (gunicorn missing).
Uses Flask's built-in WSGI server — works with just Flask + this app's deps,
which ARE present (the app imports successfully).
"""
import os
from core.app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8182))
    app.run(host="0.0.0.0", port=port, threaded=True)
