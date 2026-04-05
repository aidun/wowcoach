"""Add project root to sys.path so tests can import watcher, parser, engine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
