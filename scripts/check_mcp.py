"""Start both MCP servers, list their tools and make one call on each.

    python ..\\scripts\\check_mcp.py        (from the backend folder, venv active)

If a server fails to start, this prints the underlying error instead of a wrapped one, and the server's own
error output appears directly in this terminal.
"""

import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.mcp_client import McpToolbox  # noqa: E402


def check(name: str, module: str, env: dict, tool: str, args: dict) -> bool:
    print(f"\n[{name}] starting {sys.executable} -m {module}")
    try:
        box = McpToolbox(name, sys.executable, ["-m", module], env=env, cwd=str(BACKEND)).start()
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] FAILED TO START: {e}")
        return False
    try:
        print(f"[{name}] tools: {', '.join(t['name'] for t in box.list_tools())}")
        print(f"[{name}] {tool} -> {str(box.call(tool, args))[:200]}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] CALL FAILED: {type(e).__name__}: {e}")
        return False
    finally:
        box.close()


if __name__ == "__main__":
    outbox = tempfile.mkdtemp()
    ok = check("fhir", "app.mcp_servers.fhir_server", {}, "get_patient", {"patient": "SYN-00982"})
    ok &= check("outbound", "app.mcp_servers.outbound_server", {"OUTBOX_DIR": outbox}, "send_clinician_message",
                {"case_id": "check1", "patient": "SYN-00982", "subject": "Check", "body": "Health check message",
                 "approved_by": "check_mcp"})
    print("\nAll MCP servers OK" if ok else "\nSomething failed, see above")
    sys.exit(0 if ok else 1)
