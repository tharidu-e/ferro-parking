"""Non-secret sheet settings; FERRO_* environment variables override config."""
import os
from pathlib import Path
import tomllib

CONFIG_DIR = Path(__file__).resolve().parents[2] / 'config'
with (CONFIG_DIR / 'sheets.toml').open('rb') as stream:
    SETTINGS = tomllib.load(stream)


def setting(name):
    return os.environ.get('FERRO_' + name.upper(), SETTINGS[name])
