"""Run the installed Device CLI against one explicitly selected project board.

Usage: python3 tools/product_device.py --port BY_ID --evidence DIR TAG CLI_ARGS...
Every invocation retains its JSON result and NDJSON events, including failures.
This does not discover devices, select a different port, retry or take ownership.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', required=True)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('tag')
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    temp = (args.evidence / 'tmp').resolve()
    temp.mkdir(exist_ok=True)
    env = dict(os.environ, TMPDIR=str(temp), TMP=str(temp), TEMP=str(temp))
    if not args.cli.is_file():
        parser.error('Installed Device CLI is missing')
    command = ['node', str(args.cli), *args.arguments, '--port', args.port, '--json']
    with (args.evidence / (args.tag + '.json')).open('wb') as output:
        with (args.evidence / (args.tag + '.ndjson')).open('wb') as events:
            completed = subprocess.run(command, env=env, stdout=output, stderr=events)
    result = (args.evidence / (args.tag + '.json')).read_text()
    try:
        envelope = json.loads(result)
        print(json.dumps(envelope, ensure_ascii=False))
    except ValueError:
        print(result)
    return completed.returncode


if __name__ == '__main__':
    sys.exit(main())
