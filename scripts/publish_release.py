"""Verify all platform archives, then publish them together as a GitHub release."""

import argparse
import hashlib
import os
import subprocess
import tomllib
from pathlib import Path

TARGETS = {"windows-x64", "linux-x64", "linux-arm64", "macos-x64", "macos-arm64"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--assets", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    if args.tag != f"v{version}":
        raise SystemExit("Tag does not match the source version")
    assets, lines = [], []
    for target in sorted(TARGETS):
        extension = ".tar.gz" if target.startswith("linux") else ".zip"
        name = f"annotation-arranger-{args.tag}-{target}{extension}"
        archive = args.assets / name
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        line = f"{digest}  {name}"
        if archive.with_name(name + ".sha256").read_text().strip() != line:
            raise SystemExit(f"Checksum mismatch: {name}")
        assets.extend([str(archive), str(archive.with_name(name + ".sha256"))])
        lines.append(line)
    sums = args.assets / "SHA256SUMS.txt"
    sums.write_text("\n".join(lines) + "\n")
    assets.append(str(sums))
    # Publish only after every platform has passed tests and supplied verified assets.
    # A draft keeps partially uploaded assets out of a published release if upload fails.
    subprocess.run(
        [
            "gh",
            "release",
            "create",
            args.tag,
            *assets,
            "--verify-tag",
            "--draft",
            "--title",
            f"Annotation Arranger {args.tag}",
            "--notes-file",
            str(root / "packaging/RELEASE_NOTES.md"),
        ],
        check=True,
    )
    subprocess.run(["gh", "release", "edit", args.tag, "--draft=false", "--latest"], check=True)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            summary.write(
                f"Published {args.tag} with five native platform archives and checksums.\n"
            )


if __name__ == "__main__":
    main()
