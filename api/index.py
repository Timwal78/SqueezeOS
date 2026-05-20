import os
os.environ.setdefault('VERCEL', '1')
from core.app import create_app
app = create_app()
