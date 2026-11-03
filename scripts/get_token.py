"""Obtain a JWT without storing a password or printing a token to the terminal."""

import argparse
import getpass
import json
import os
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    password = getpass.getpass("Therefore password: ")
    with httpx.Client(timeout=30, trust_env=False) as client:
        response = client.post(
            f"https://{args.tenant}.thereforeonline.com/theservice/v0001/restun/GetJWTToken",
            auth=(args.username, password),
            headers={"TenantName": args.tenant, "Content-Type": "application/json; charset=utf-8"},
            json={},
        )
    if not response.is_success:
        raise SystemExit(f"Token request failed: HTTP {response.status_code}")
    result = response.json()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(result["JWTToken"])
    print(json.dumps({"tokenFile": str(args.output), "expiresAt": result.get("ExpiresAtISO8601")}))


if __name__ == "__main__":
    main()
