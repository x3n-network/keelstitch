"""JSON command-line interface and entry point for stdio MCP."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .policy import Policy, PolicyError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True, type=Path, help='operator policy JSON file')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='list available aliases and descriptions')
    run = sub.add_parser('run', help='run an approved action')
    run.add_argument('target')
    run.add_argument('action')
    sub.add_parser('mcp', help='serve MCP over stdio')
    args = parser.parse_args(argv)
    try:
        policy = Policy.load(args.policy)
    except PolicyError as exc:
        print(json.dumps({'ok': False, 'status': 'invalid_policy', 'message': str(exc)}), file=sys.stderr)
        return 2
    if args.command == 'list':
        print(json.dumps({'targets': policy.catalog()}))
        return 0
    if args.command == 'mcp':
        from .mcp_server import serve

        serve(policy)
        return 0
    from .service import Service

    result = asyncio.run(Service(policy).run(args.target, args.action))
    print(json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
