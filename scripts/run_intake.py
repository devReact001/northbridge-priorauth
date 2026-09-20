"""Run the intake agent on a sample note from the command line.

Usage (from the backend/ folder, with ANTHROPIC_API_KEY set):
    python ../scripts/run_intake.py app/data/sample_notes/note_01_mri_lumbar.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.intake import run_intake  # noqa: E402

if __name__ == "__main__":
    text = Path(sys.argv[1]).read_text()
    print(run_intake(text).model_dump_json(indent=2))
