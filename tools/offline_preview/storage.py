"""Local, versioned profiles. Invalid files are preserved and never overwritten."""

import json
import os
from pathlib import Path
import shutil
import tempfile

from model import Profile, default_profile


def write_json(path, payload):
    """Validate the payload before touching disk; retain the preceding save."""
    path = Path(path).resolve()
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > 5_000_000:
        raise ValueError("Saved data exceeds the local settings size limit.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            shutil.copy2(path, path.with_name(f"{path.stem}.previous.json"))
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class ProfileStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.path = self.directory / "profiles.json"
        self.error = ""

    def load(self):
        if not self.path.exists():
            return [default_profile()], "first-character"
        try:
            if self.path.stat().st_size > 5_000_000:
                raise ValueError("Saved profiles are too large.")
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or type(data.get("version")) is not int or data.get("version") not in (1, 2, 3):
                raise ValueError("Unsupported saved-profile format.")
            raw = data.get("profiles")
            if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
                raise ValueError("Saved profiles must contain 1–100 characters.")
            profiles = [Profile.from_dict(item) for item in raw]
            ids = [p.id for p in profiles]
            if len(ids) != len(set(ids)) or data.get("active") not in ids:
                raise ValueError("Invalid profile identities or active profile.")
            return profiles, data["active"]
        except (OSError, ValueError, TypeError) as exc:
            self.error = f"Saved settings could not be read: {exc} Original file preserved; saving is disabled."
            return [default_profile()], "first-character"

    def save(self, profiles, active):
        if self.error:
            raise ValueError(self.error)
        if not 1 <= len(profiles) <= 100:
            raise ValueError("Keep between 1 and 100 profiles.")
        payload = {"version": 3, "active": active, "profiles": [p.to_dict() for p in profiles]}
        ids = [p.id for p in profiles]
        if len(ids) != len(set(ids)) or active not in ids:
            raise ValueError("Invalid active profile or duplicate profile IDs.")
        write_json(self.path, payload)
