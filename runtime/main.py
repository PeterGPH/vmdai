from __future__ import annotations

import argparse
import os
import signal
import sys
import threading

from vmd_ai_runtime import RuntimeApp, create_server
from vmd_ai_runtime.constants import RUNTIME_PROTOCOL, RUNTIME_VERSION
from vmd_ai_runtime.launch import (
    format_ready_line,
    generate_launch_token,
    remove_token_file,
    write_token_file,
)
from vmd_ai_runtime.logging_utils import configure_logging, default_log_path

# Reentrant: a second SIGTERM/SIGINT can run its handler on the main thread
# while the first one still holds the lock (inside thread.start()).
_SHUTDOWN_LOCK = threading.RLock()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ChatVMD runtime: JSON-RPC over loopback HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port", type=int, default=8765,
        help="TCP port on 127.0.0.1; 0 picks a free ephemeral port",
    )
    parser.add_argument("--store-dir", default=None)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--log-file", default=None,
        help="Rotating log file. Default: ~/.vmdai/logs/runtime.log",
    )
    parser.add_argument(
        "--announce", action="store_true",
        help="Print one VMDAI_READY line (with the launch token) on stdout, "
             "log only to the file, and refuse tokenless sessions.",
    )
    parser.add_argument(
        "--watch-stdin", action="store_true",
        help="Exit when stdin reaches EOF (the plugin's pipe was closed).",
    )
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


def _start_shutdown(server) -> threading.Thread:
    """Run server.shutdown() on its own thread and return that thread.

    shutdown() blocks until serve_forever() returns, so calling it from a
    signal handler on the serving thread deadlocks (the old SIGTERM bug).
    Repeated calls return the thread the first call started.
    """
    with _SHUTDOWN_LOCK:
        thread = getattr(server, "_vmdai_shutdown_thread", None)
        if thread is None:
            thread = threading.Thread(target=server.shutdown, name="vmdai-shutdown", daemon=True)
            server._vmdai_shutdown_thread = thread
            thread.start()
    return thread


def _watch_stdin(server, logger) -> threading.Thread:
    """Shut down when stdin reaches EOF, so a VMD crash leaves no orphan."""
    def _run():
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        reader = getattr(stream, "read1", stream.read)
        try:
            while reader(65536):
                pass
        except Exception:
            pass
        logger.info("stdin closed; shutting down")
        _start_shutdown(server)

    thread = threading.Thread(target=_run, name="vmdai-stdin-watch", daemon=True)
    thread.start()
    return thread


def _serve(args, logger, log_path) -> int:
    token = generate_launch_token()
    holder = {}

    def _request_shutdown():
        server = holder.get("server")
        if server is not None:
            _start_shutdown(server)

    app = RuntimeApp(
        store_dir=args.store_dir,
        logger=logger,
        wiki_root=args.wiki_root,
        wiki_raw_root=args.wiki_raw_root,
        enable_wiki=not args.disable_wiki,
        launch_token=token,
        allow_tokenless_v1=not args.announce,
        on_shutdown=_request_shutdown,
    )
    server = create_server(app, host=args.host, port=args.port)
    holder["server"] = server
    port = int(server.server_port)
    pid = os.getpid()

    def _handle_signal(_signum, _frame):
        _start_shutdown(server)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    token_file = None
    if args.announce:
        # The launch token appears here and nowhere else (§2e).
        sys.stdout.write(format_ready_line(port, pid, RUNTIME_VERSION, RUNTIME_PROTOCOL, token) + "\n")
        sys.stdout.flush()
    else:
        token_file = write_token_file(port, pid, token, RUNTIME_PROTOCOL)
        logger.info("launch token file: %s", token_file)
    if args.watch_stdin:
        _watch_stdin(server, logger)

    logger.info("runtime listening on http://127.0.0.1:%s (log: %s)", port, log_path)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if token_file is not None:
            remove_token_file(token_file)
        logger.info("runtime stopped")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    log_path = args.log_file or default_log_path()
    # A failure before this line (bad Python, ImportError, unwritable log
    # dir) prints its traceback to stderr, which the plugin merges into the
    # pipe with 2>@1 and shows in the "Runtime didn't start" banner.
    logger = configure_logging(args.log_level, log_path=log_path, stderr=not args.announce)
    try:
        return _serve(args, logger, log_path)
    except Exception:
        logger.exception("runtime failed to start or crashed")
        raise


if __name__ == "__main__":
    sys.exit(main())
