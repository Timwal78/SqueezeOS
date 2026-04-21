"""
Pytest conftest — ensures project root is on sys.path for all test modules.
This eliminates the need for manual PYTHONPATH manipulation.
"""
import sys
import os

# Ensure project root is importable
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
