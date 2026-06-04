"""DC&E Billing Audit — production launcher.

Serves the Flask app with waitress (a real WSGI server that runs on Windows,
macOS, and Linux). Use this instead of `python app.py` (which is Flask's
debug server) for anything you hand to the team.

    python run.py            # serves on http://localhost:5100
    PORT=8080 python run.py  # custom port
"""
import os

from waitress import serve

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5100"))
    print("=" * 56)
    print("  DC&E Billing Audit")
    print(f"  Open this in your browser:  http://localhost:{port}")
    print("  Press Ctrl+C to stop.")
    print("=" * 56, flush=True)
    serve(app, host="0.0.0.0", port=port, threads=8)
