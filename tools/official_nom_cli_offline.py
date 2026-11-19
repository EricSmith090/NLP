"""Run the instructors' `ocr-nom-align` CLI with all network access blocked.

Used by tools/official_check.py (Doc/FIX_PLAN_v24.md §6). Run it isolated:
    python -I tools/official_nom_cli_offline.py <tool-src-dir> <command> [args...]
`check`, `check-diff` and `score` never need the network; the block makes
sure no book text can leave the machine even if that changes.
"""

import os
import socket
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def _deny(*_a, **_k):
    raise RuntimeError("network blocked by official_nom_cli_offline")


socket.socket.connect = _deny
socket.socket.connect_ex = _deny
socket.create_connection = _deny
socket.getaddrinfo = _deny
urllib.request.urlopen = _deny

TOOL_SRC = os.path.abspath(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["NOM_ALIGN_OFFLINE"] = "1"
os.environ["NOM_ALIGN_ENV_FILE"] = os.path.join(TOOL_SRC, "__no_env_file__")
os.environ["NOM_ALIGN_CACHE"] = os.path.join(TOOL_SRC, "__cache_unused__.json")
for key in ("NOM_ALIGN_TABLE", "NOM_ALIGN_SIMILAR", "NOM_ALIGN_CONTACT", "NOM_ALIGN_OUT_DIR"):
    os.environ.pop(key, None)
sys.path.insert(0, TOOL_SRC)

from ocr_nom_align import cli  # noqa: E402
from ocr_nom_align import online as _online  # noqa: E402

_online.http_get = _deny

if __name__ == "__main__":
    cli.main(args=sys.argv[2:], prog_name="ocr-nom-align")
