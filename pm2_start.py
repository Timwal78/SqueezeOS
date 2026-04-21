"""Argus Omega — PM2 launcher wrapper."""
import uvicorn
from app.main import app
from app.config import HOST

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=8181)
