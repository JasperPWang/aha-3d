"""Validate the explicit file inventory of an offline inspection package."""
import hashlib
import json
from pathlib import Path
import re


def bundle_artifacts(manifest, *, root, entry=None):
    """Return verified files, including the manifest; never authorize a directory."""
    root = Path(root).resolve()
    manifest = Path(manifest).resolve(strict=True)
    if not manifest.is_relative_to(root) or not manifest.is_file():
        raise ValueError("Inspection manifest must be a file inside the project")
    data = json.loads(manifest.read_text())
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported inspection bundle schema")
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts or data.get("entry") not in artifacts:
        raise ValueError("Inspection bundle requires an inventoried entry and files")
    paths = {manifest}
    for name, expected in artifacts.items():
        relative = Path(name)
        if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name:
            raise ValueError("Inspection artifact must be a local relative file")
        candidate = manifest.parent / relative
        if any(part.is_symlink() for part in [candidate, *candidate.parents]
               if part.is_relative_to(manifest.parent)):
            raise ValueError("Inspection bundle cannot contain symlinks")
        candidate = candidate.resolve(strict=True)
        if not candidate.is_relative_to(manifest.parent) or not candidate.is_file():
            raise ValueError("Inspection artifact escapes its package or is not a file")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Inspection artifact requires a SHA256 digest")
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError("Inspection artifact changed: " + name)
        paths.add(candidate)
    actual_entry = (manifest.parent / data["entry"]).resolve(strict=True)
    if entry is not None and Path(entry).resolve(strict=True) != actual_entry:
        raise ValueError("Linked inspection report differs from bundle entry")
    return paths
