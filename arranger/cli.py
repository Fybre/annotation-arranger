"""Entry point shared by Python installs and frozen executables."""

import argparse
import multiprocessing
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
    parser.add_argument(
        "--backup",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable local original-file backups (default: off)",
    )
    parser.add_argument("--env-file", help="Read this .env file instead of the automatic location")
    parser.add_argument("--tenant", help="Therefore tenant name")
    parser.add_argument("--base-url", help="Therefore HTTPS REST API base URL")
    args = parser.parse_args()
    if args.self_test:
        from .self_test import run

        run()
        return
    from .config import Settings

    try:
        settings = Settings.from_env(
            args.env_file,
            {
                "HOST": args.host,
                "PORT": args.port,
                "BACKUP_DIR": args.backup_dir,
                "BACKUP_ENABLED": str(args.backup).lower() if args.backup is not None else None,
                "THEREFORE_TENANT": args.tenant,
                "THEREFORE_BASE_URL": args.base_url,
            },
        )
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn

    from .app import create_app

    uvicorn.run(
        create_app(settings=settings),
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
        http="h11",
        ws="none",
        loop="asyncio",
        lifespan="on",
    )
