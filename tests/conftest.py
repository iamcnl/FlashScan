import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import webview  # noqa: F401
except ImportError:
    sys.modules["webview"] = types.ModuleType("webview")