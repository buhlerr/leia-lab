"""Entrypoint do Django Admin (protótipo B4, bead leia-lab-1g1.5).

Uso (da raiz do repo):
    uv run python -m src.management.manage migrate
    uv run python -m src.management.manage createsuperuser
    uv run python -m src.management.manage runserver 0.0.0.0:8000
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "src.management.leia_admin.settings")


def main() -> None:
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
