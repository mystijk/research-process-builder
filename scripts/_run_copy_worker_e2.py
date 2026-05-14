"""Wrapper: loads env from multiple locations, then delegates to motorica_copy_worker_e2."""
import sys
import os
from pathlib import Path

def load_env_file(path: Path):
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

repo_root = Path(__file__).resolve().parents[1]
workspace_root = Path(__file__).resolve().parents[2]
load_env_file(repo_root / ".env")
load_env_file(workspace_root / ".env")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "motorica_copy_worker_e2",
    Path(__file__).resolve().parent / "motorica_copy_worker_e2.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.main()
