"""Run the Local Diff Viewer locally.

Usage:
    python run.py [--port 8000] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Diff Viewer")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1, local-only)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload (development only)")
    args = parser.parse_args()

    print(f"Local Diff Viewer starting at http://{args.host}:{args.port}")
    print("Everything runs locally -- no files ever leave this machine.")
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
