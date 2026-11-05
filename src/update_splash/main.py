"""Точка входа TwoWingsUpdate.exe.

TwoWingsUpdate.exe --version 1.5.2 --from 1.5.1 --installer-url URL --checksum-url URL
               --work-dir DIR --done-file FILE
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.update_splash.app import run_update_window
from src.update_splash.worker import Job, Worker


def main() -> None:
    parser = argparse.ArgumentParser(prog="TwoWingsUpdate")
    parser.add_argument("--version", required=True)
    parser.add_argument("--from", dest="from_version", default="")
    parser.add_argument("--installer-url", required=True)
    parser.add_argument("--checksum-url", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--done-file", required=True, type=Path)
    args = parser.parse_args()
    job = Job(args.version, args.from_version, args.installer_url, args.checksum_url, args.work_dir, args.done_file)
    run_update_window(Worker(job))


if __name__ == "__main__":
    main()
