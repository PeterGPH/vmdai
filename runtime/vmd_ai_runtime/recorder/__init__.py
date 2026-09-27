"""
vmd_ai_runtime.recorder — per-task Tcl transcript recorder.

Goal: every successful VMD command the model emits during a task is
saved as a runnable, annotated Tcl script under
``<cwd>/.vmdai_runs/<task_id>/transcript.tcl``, so the user can
reproduce the same visualization by running

    vmd -e <cwd>/.vmdai_runs/<task_id>/transcript.tcl

against fresh VMD — locally, on a cluster, or in CI.

Design contract:
    * One run directory per *task* (one ``chat.send`` turn that may
      issue many tool calls).
    * Successful commands, and the applied part of a partly failed one,
      are written to ``transcript.tcl``; the unapplied rest is commented
      out. A command that fails outright is counted in the manifest but
      never persisted.
    * Snapshots captured via ``capture_vmd_snapshot`` are saved under
      ``snapshots/turn_NN.png`` and added to ``transcript.tcl`` as
      ``render snapshot snapshots/turn_NN.png`` lines, so replay
      reproduces the same image files.
    * No dependency on the live runtime — the recorder is a pure
      append-only state machine that can be wired in later from
      ``tool_bridge`` without changes here.
"""
from .run import RunRecorder, RunRecorderError  # noqa: F401

__all__ = ["RunRecorder", "RunRecorderError"]
