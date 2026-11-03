"""Entry point shared by Python installs and frozen executables."""

import argparse
import multiprocessing
import os
from importlib.metadata import version


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Therefore Annotation Arranger REST service")
    parser.add_argument("--version", action="version", version=version("annotation-arranger"))
    parser.add_argument(
        "--self-test", action="store_true", help="Test PDF engines without credentials"
    )
    parser.add_argument("--host", help="Listener address (default: HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Listener port (default: PORT or 8765)")
    parser.add_argument("--backup-dir", help="Private writable backup directory")
    parser.add_argument("--tenant", help="Therefore tenant name")
    parser.add_argument("--base-url", help="Therefore HTTPS REST API base URL")
    parser.add_argument("--allowed-categories", help="Comma-separated category numbers")
    args = parser.parse_args()
    if args.self_test:
        from .self_test import run

        run()
        return
    for value, key in [
        (args.host, "HOST"),
        (args.port, "PORT"),
        (args.backup_dir, "BACKUP_DIR"),
        (args.tenant, "THEREFORE_TENANT"),
        (args.base_url, "THEREFORE_BASE_URL"),
        (args.allowed_categories, "ALLOWED_CATEGORIES"),
    ]:
        if value is not None:
            os.environ[key] = str(value)
    import uvicorn

    from .app import create_app

    uvicorn.run(
        create_app(),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8765")),
        workers=1,
        access_log=False,
        http="h11",
        ws="none",
        loop="asyncio",
        lifespan="on",
    )
