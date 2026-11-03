"""Create and push the version tag that triggers the GitHub release workflow."""

import argparse
import subprocess
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    tag = f"v{version}"

    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()

    if git("status", "--porcelain"):
        raise SystemExit("Commit your changes before creating a release")
    if git("branch", "--show-current") != "main":
        raise SystemExit("Create release tags from main")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        raise SystemExit("Push main before creating a release tag")
    for command in [
        ["git", "tag", "-a", tag, "-m", f"Annotation Arranger {tag}"],
        ["git", "push", "origin", f"refs/tags/{tag}"],
    ]:
        print(" ".join(command), flush=True)
        if not args.dry_run:
            subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()
