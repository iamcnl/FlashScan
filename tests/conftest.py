import atexit
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

_SANDBOX_HOME = tempfile.mkdtemp(prefix="flashscan-test-home-")
for _var in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
    os.environ[_var] = _SANDBOX_HOME
atexit.register(shutil.rmtree, _SANDBOX_HOME, ignore_errors=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import webview  # noqa: F401
except ImportError:
    sys.modules["webview"] = types.ModuleType("webview")