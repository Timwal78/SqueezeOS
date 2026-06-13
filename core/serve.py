import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
# Support being run either from repo root (root dir unset) or from core/ (root dir=core)
for p in (PARENT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
try:
    from core.app import create_app
except ModuleNotFoundError:
    from app import create_app
app = create_app()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8182))
    app.run(host="0.0.0.0", port=port, threaded=True)
