"""Run one persisted project training request. No global model activation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

if __name__ == "__main__":
    from app import django_bridge
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit("Expected an integer training run ID")
    if not django_bridge.ensure_django_ready():
        raise SystemExit("Database unavailable")
    from app.correction_training import run_training
    run_training(int(sys.argv[1]))
