"""Stub runtime that dies at import time, like a missing module (P06-T05).

It writes a traceback to stderr and exits 1 without a READY line, so the
plugin must show "Runtime didn't start" with this text in the pipe tail.
"""
import sys

sys.stderr.write("Traceback (most recent call last):\n")
sys.stderr.write('  File "runtime/main.py", line 12, in <module>\n')
sys.stderr.write("    import vmd_ai_runtime_missing\n")
sys.stderr.write("ModuleNotFoundError: No module named 'vmd_ai_runtime_missing'\n")
sys.stderr.flush()
sys.exit(1)
