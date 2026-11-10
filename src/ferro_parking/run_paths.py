"""Reserve fresh output directories without replacing an earlier run."""
from datetime import date
from pathlib import Path


def new_run_dir(task, root=Path('data/runs'), day=None):
    base = Path(root) / (day or date.today().isoformat())
    index = 1
    while True:
        folder = base if index == 1 else base.with_name(f'{base.name}_{index}')
        try:
            folder.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            index += 1
    result = folder / task
    if str(task) not in ("", "."):
        result.mkdir(parents=True, exist_ok=False)
    return result


def reserve_output(path):
    """Explicit output paths are also append-only, including outside data/runs."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    return path
