from __future__ import annotations

import argparse
import signal
import sys

from vmd_ai_runtime import RuntimeApp, create_server
from vmd_ai_runtime.logging_utils import configure_logging


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="VMD AI runtime skeleton server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--store-dir", default=None)
    parser.add_argument("--log-level", default="INFO")
    # LLM Wiki flags. Defaults live in RuntimeApp; CLI overrides win.
    parser.add_argument(
        "--wiki-root",
        default=None,
        help="Directory where the LLM-maintained wiki lives. "
             "Default: ~/.vmdai/wiki/",
    )
    parser.add_argument(
        "--wiki-raw-root",
        default=None,
        help="Directory containing immutable raw sources for the wiki to "
             "pin. Default: ~/.vmdai/raw/",
    )
    parser.add_argument(
        "--disable-wiki",
        action="store_true",
        help="Run without the wiki tools (e.g. for the no-wiki arm of "
             "an A/B experiment).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logger = configure_logging(args.log_level)
    app = RuntimeApp(
        store_dir=args.store_dir,
        logger=logger,
        wiki_root=args.wiki_root,
        wiki_raw_root=args.wiki_raw_root,
        enable_wiki=not args.disable_wiki,
    )
    server = create_server(app, host=args.host, port=args.port)

    shutdown = {"requested": False}

    def _handle_signal(_signum, _frame):
        shutdown["requested"] = True
        server.shutdown()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("runtime listening on http://127.0.0.1:%s", server.server_port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        logger.info("runtime stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
