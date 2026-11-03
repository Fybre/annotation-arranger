"""Build, smoke-test and archive a native standalone service executable."""

import argparse
import hashlib
import json
import platform
import plistlib
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from importlib import metadata
from pathlib import Path

from smoke_test import smoke_test

ROOT = Path(__file__).resolve().parents[1]
WINSW_URL = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"
WINSW_SHA256 = "05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da"


def target_name():
    systems = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}
    machines = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}
    return f"{systems[platform.system()]}-{machines[platform.machine().lower()]}"


def download(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def notices(folder):
    destination = folder / "THIRD_PARTY_LICENSES"
    destination.mkdir()
    inventory = []
    # Include available license texts for the locked build environment (a superset
    # of bundled modules), alongside the inventory and upstream project URLs.
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        inventory.append(
            {
                "name": name,
                "version": dist.version,
                "license": dist.metadata.get("License-Expression", dist.metadata.get("License")),
                "projectUrls": dist.metadata.get_all("Project-URL", []),
            }
        )
        for index, file in enumerate(dist.files or []):
            if file.name.lower().startswith(("license", "copying", "notice")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    shutil.copyfile(source, destination / f"{name}-{index}-{file.name}")
    (folder / "DEPENDENCIES.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (destination / "PYTHON-LICENSE.txt").write_bytes(
        download(
            f"https://raw.githubusercontent.com/python/cpython/v{platform.python_version()}/LICENSE"
        )
    )


def service_files(folder, target):
    destination = folder / "service"
    destination.mkdir()
    if target.startswith("windows"):
        blob = download(WINSW_URL)
        if hashlib.sha256(blob).hexdigest() != WINSW_SHA256:
            raise RuntimeError("WinSW checksum did not match")
        (destination / "annotation-arranger-service.exe").write_bytes(blob)
        (destination / "WinSW-LICENSE.txt").write_bytes(
            download("https://raw.githubusercontent.com/winsw/winsw/v2.12.0/LICENSE.txt")
        )
        text = (ROOT / "deploy/annotation-arranger.xml").read_text()
        text = text.replace(
            "C:\\annotation-arranger\\.venv\\Scripts\\python.exe",
            "%BASE%\\..\\annotation-arranger.exe",
        )
        text = text.replace("  <arguments>-m arranger</arguments>\n", "")
        text = text.replace("C:\\annotation-arranger", "%BASE%\\..")
        (destination / "annotation-arranger-service.xml").write_text(text, encoding="utf-8")
    elif target.startswith("linux"):
        text = (
            (ROOT / "deploy/annotation-arranger.service")
            .read_text()
            .replace(
                "ExecStart=/opt/annotation-arranger/.venv/bin/python -m arranger",
                "ExecStart=/opt/annotation-arranger/annotation-arranger",
            )
        )
        (destination / "annotation-arranger.service").write_text(text, encoding="utf-8")
    else:
        config = plistlib.loads((ROOT / "deploy/com.annotation-arranger.plist").read_bytes())
        config["ProgramArguments"] = ["/opt/annotation-arranger/annotation-arranger"]
        (destination / "com.annotation-arranger.plist").write_bytes(plistlib.dumps(config))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", help="Expected native target, e.g. windows-x64")
    parser.add_argument("--tag", help="Release tag; must match the project version")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    target = target_name()
    if args.target and args.target != target:
        raise SystemExit(f"Expected {args.target}, but this runner is {target}")
    if args.tag and args.tag != f"v{version}":
        raise SystemExit(f"Release tag must be v{version}")
    work = ROOT / ".build" / target
    binaries = work / "binaries"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(binaries),
            "--workpath",
            str(work / "work"),
            str(ROOT / "packaging/annotation-arranger.spec"),
        ],
        check=True,
        cwd=ROOT,
    )
    executable = binaries / (
        "annotation-arranger.exe" if target.startswith("windows") else "annotation-arranger"
    )
    smoke_test(executable)
    name = f"annotation-arranger-v{version}-{target}"
    folder = work / "package" / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    shutil.copy2(executable, folder / executable.name)
    shutil.copy2(ROOT / "packaging/README.md", folder / "README.md")
    shutil.copy2(ROOT / ".env.example", folder / "settings.example.env")
    (folder / "var" / "backups").mkdir(parents=True)
    service_files(folder, target)
    notices(folder)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    (folder / "BUILD-INFO.json").write_text(
        json.dumps(
            {
                "version": version,
                "target": target,
                "python": platform.python_version(),
                "runner": platform.platform(),
                "commit": commit.stdout.strip() or "local",
                "package": "PyInstaller single-file executable",
                "signed": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    releases = ROOT / "dist" / "releases"
    releases.mkdir(parents=True, exist_ok=True)
    archive = Path(
        shutil.make_archive(
            str(releases / name),
            "gztar" if target.startswith("linux") else "zip",
            root_dir=folder.parent,
            base_dir=folder.name,
        )
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Release archive ready: {archive}")


if __name__ == "__main__":
    main()
