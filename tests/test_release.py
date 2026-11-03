import hashlib
import sys
import tomllib
from pathlib import Path

import pytest

from scripts import publish_release

VERSION = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())[
    "project"
]["version"]
TAG = f"v{VERSION}"


def assets(tmp_path):
    for target in publish_release.TARGETS:
        extension = ".tar.gz" if target.startswith("linux") else ".zip"
        name = f"annotation-arranger-{TAG}-{target}{extension}"
        path = tmp_path / name
        path.write_bytes(target.encode())
        path.with_name(name + ".sha256").write_text(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}\n"
        )


def test_publisher_verifies_every_target_before_draft_and_publish(tmp_path, monkeypatch):
    assets(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    commands = []
    monkeypatch.setattr(
        sys, "argv", ["publish_release.py", "--tag", TAG, "--assets", str(tmp_path)]
    )
    monkeypatch.setattr(
        publish_release.subprocess, "run", lambda args, **kwargs: commands.append(args)
    )
    publish_release.main()
    assert commands[0][:3] == ["gh", "release", "create"]
    assert "--draft" in commands[0]
    assert commands[1][:3] == ["gh", "release", "edit"]
    assert "--draft=false" in commands[1]
    assert len((tmp_path / "SHA256SUMS.txt").read_text().splitlines()) == 5


def test_corrupt_archive_prevents_release(tmp_path, monkeypatch):
    assets(tmp_path)
    next(tmp_path.glob("*.zip")).write_bytes(b"corrupt")
    commands = []
    monkeypatch.setattr(
        sys, "argv", ["publish_release.py", "--tag", TAG, "--assets", str(tmp_path)]
    )
    monkeypatch.setattr(
        publish_release.subprocess, "run", lambda args, **kwargs: commands.append(args)
    )
    with pytest.raises(SystemExit, match="Checksum mismatch"):
        publish_release.main()
    assert commands == []


def test_wrong_tag_prevents_release(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["publish_release.py", "--tag", "v99.0.0", "--assets", str(tmp_path)]
    )
    with pytest.raises(SystemExit, match="Tag does not match"):
        publish_release.main()
