"""Compatibility import for the project's shared Blender helpers."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'src'))
from aha3d.blender import roomkit
sys.modules[__name__] = roomkit
