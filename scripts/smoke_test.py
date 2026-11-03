"""Exercise the frozen executable from outside the source checkout."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def smoke_test(executable):
    executable = str(Path(executable).resolve())
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONHOME", "PYTHONPATH")}
    with tempfile.TemporaryDirectory(prefix="arranger-smoke-") as temp:
        subprocess.run([executable, "--self-test"], check=True, cwd=temp, env=env, timeout=120)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with open(Path(temp) / "service.log", "w+") as log:
            process = subprocess.Popen(
                [
                    executable,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--backup-dir",
                    str(Path(temp) / "backups"),
                ],
                cwd=temp,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 90
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Frozen service exited during startup")
                    try:
                        with opener.open(base + "/health", timeout=2) as response:
                            if json.load(response) == {"status": "ok"}:
                                break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.5)
                else:
                    raise RuntimeError("Frozen service did not become healthy")
                with opener.open(base + "/openapi.json", timeout=5) as response:
                    schema = json.load(response)
                assert "/arrange-annotations" in schema["paths"]
                assert "flatten" in schema["components"]["schemas"]["ArrangeRequest"]["properties"]
                request = urllib.request.Request(
                    base + "/arrange-annotations",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    opener.open(request, timeout=5)
                    raise RuntimeError("Invalid request unexpectedly succeeded")
                except urllib.error.HTTPError as exc:
                    assert exc.code == 422
                print("Frozen HTTP service smoke test passed")
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read())
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    smoke_test(parser.parse_args().executable)
