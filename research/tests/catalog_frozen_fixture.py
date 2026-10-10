"""Test-only r3 snapshot; never amend frozen catalog pins to current code."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import subprocess

from research.catalog_date_revision import CHANGED_CODE

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT_COMMIT = "3dba038bced6c0a525098245a3f66d162f1b15bf"
OLD_PATH = "research/protocols/ms1-catalog-comparison-v2-execution-20260922-r2.json"
NEW_PATH = "research/protocols/ms1-catalog-comparison-v2-execution-20260923-r3.json"
RECORD_PATH = "research/protocols/ms1-catalog-date-revision-20260923.json"
PLAN_PATH = "research/protocols/ms1-catalog-comparison-v2.json"
FIXED_DIGESTS = {
    OLD_PATH: "14622f31c510607c8999026fe2fa308630ce6bb528bcfeb6667b3d46c349ea9b",
    NEW_PATH: "8bbe1301bf4cb5d81baa0688c5c643300fb1a463c82f213082a09d605bff9ca6",
    RECORD_PATH: "a97e4c3a8c338e23251782a336d1d4926ad03b62bfd574081908f840877c3694",
    PLAN_PATH: "e4d6d4b918d2b4ce85d8285ebe0d412ee2a5d429f43bb7d0e590f5e65e95df3d",
}


def _git(*args):
    return subprocess.run(
        ["git", "-c", "safe.directory=" + REPO.as_posix(), *args],
        cwd=REPO, capture_output=True, check=True,
    ).stdout


@lru_cache(maxsize=None)
def _blob(name):
    return _git("show", SNAPSHOT_COMMIT + ":" + name)


def _checked(name, expected):
    content = _blob(name)
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError("Historical fixture SHA mismatch: " + name)
    return content


def materialize_r3_fixture(destination, *, saved_proposal=False):
    """Populate a fresh synthetic repo, checking all hashes before any write.

    Proposal tests start with r2 plus exactly the accepted r3 code changes.
    Pin tests also need the immutable saved r3 proposal/amendment. The production
    proposal/validation functions and their changed-code allowlist stay intact.
    """
    destination = Path(destination)
    if any(destination.iterdir()):
        raise ValueError("Historical fixture requires an empty temporary repo")
    blobs = {name: _checked(name, digest) for name, digest in FIXED_DIGESTS.items()}
    revised = json.loads(blobs[NEW_PATH])
    for name, digest in revised["execution"]["code_hashes"].items():
        blobs[name] = _checked(name, digest)
    for name, digest in revised["pinned_files"].items():
        blobs[name] = _checked(name, digest)
    base = json.loads(blobs[PLAN_PATH])
    old = json.loads(blobs[OLD_PATH])
    for name, digest in base["pinned_files"].items():
        # The base plan predates the explicit date-only amendment.
        expected = revised["execution"]["code_hashes"][name] if name in CHANGED_CODE else digest
        blobs[name] = _checked(name, expected)
        if expected != digest and old["execution"]["code_hashes"].get(name) != digest:
            raise ValueError("Historical base/amendment pin mismatch: " + name)
    for name in ("inner/spec/requirements.json", "inner/spec/requirements-1.2.0.json"):
        blobs.setdefault(name, _blob(name))
    for name in _git("ls-tree", "-r", "--name-only", SNAPSHOT_COMMIT, "research/sharing").decode().splitlines():
        blobs.setdefault(name, _blob(name))
    if not saved_proposal:
        del blobs[NEW_PATH]
        del blobs[RECORD_PATH]
    for name, content in blobs.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)


def child_python_environment():
    """Keep the repo importable; CLI tests use the parent's Python environment."""
    env = os.environ.copy()
    entries = [str(REPO)]
    if env.get("PYTHONPATH"):
        entries.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(entries)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
