#!/usr/bin/env python3
"""Generate a fake AWS ALB OIDC JWT for local testing.

Usage:
    python scripts/fake-jwt.py --email alice@example.com --groups eng,livesync-admin
    python scripts/fake-jwt.py --email bob@example.com

The script prints the JWT and a ready-to-paste curl command.
"""

import argparse
import json
import os
import time

try:
    from jose import jwt
except ImportError:
    import sys

    print("Install python-jose: pip install python-jose[cryptography]", file=sys.stderr)
    sys.exit(1)

SIGNING_KEY = os.environ.get("JWT_SIGNING_KEY", "dev-secret-key")


def main():
    parser = argparse.ArgumentParser(description="Generate a fake ALB OIDC JWT")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument(
        "--groups",
        default="",
        help="Comma-separated list of groups (e.g. eng,livesync-admin)",
    )
    parser.add_argument(
        "--ttl", type=int, default=86400, help="Token TTL in seconds (default: 24h)"
    )
    args = parser.parse_args()

    now = int(time.time())
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]

    claims = {
        "email": args.email,
        "groups": groups,
        "sub": args.email,
        "iss": "https://livesync-local-dev",
        "iat": now,
        "exp": now + args.ttl,
    }

    token = jwt.encode(claims, SIGNING_KEY, algorithm="HS256")

    print(f"JWT ({args.ttl}s TTL):")
    print(token)
    print()
    print("Claims:")
    print(json.dumps(claims, indent=2))
    print()
    print("curl example:")
    print(
        f'curl -s -H "x-amzn-oidc-data: {token}" http://localhost:8000/ | python3 -m json.tool'
    )


if __name__ == "__main__":
    main()
