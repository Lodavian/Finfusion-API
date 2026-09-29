"""Read-only example: python -m examples.query_accounts --help"""
import argparse
import asyncio
import json
from pathlib import Path
from client_sdk import FinfusionClient


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    client = FinfusionClient(args.url, args.client_id, args.private_key.read_bytes())
    print(json.dumps(await client.request("GET", "/v1/accounts"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
