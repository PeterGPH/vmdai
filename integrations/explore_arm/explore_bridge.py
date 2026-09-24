"""explore_bridge.py — decorator bridge for the explore arm.

Wraps any inner VMD bridge (SubprocessVmdBridge / HeadlessVmdBridge / a fake in tests —
same pattern as RetrievalAugmentingBridge) and adds the lab surface:

- lab_try(code)     → inner run_vmd_command; result/error returned verbatim (after
                      sanitize_env_text strips the shared bridge's steer-to-domain-tools
                      suffix), with LabProtocol guidance (loop-breaker / budget) appended.
- lab_note(text)    → recorded in the protocol; no interpreter call.
- lab_commit(code)  → refused with the protocol's structured message until the gate opens;
                      once open, the final code runs end-to-end in the inner session.
- run_vmd_command   → defensively aliased to lab_try (the name is hidden from the tool
                      list, but a provider that emits it anyway must not bypass the arm).
- anything else     → delegated to the inner bridge untouched.

Every lab result carries the executed code as result["tcl"] for transcript artifacts.
"""
from scaffold import LabProtocol, sanitize_env_text


class ExploreScaffoldBridge:
    def __init__(self, inner, protocol=None):
        self.inner = inner
        self.protocol = protocol if protocol is not None else LabProtocol()

    # ------------------------------------------------------------- lifecycle
    def reset(self):
        self.protocol.reset()
        if hasattr(self.inner, "reset"):
            self.inner.reset()

    def close(self):
        if hasattr(self.inner, "close"):
            self.inner.close()

    # ------------------------------------------------------------- internals
    def _run_code(self, code, **kw):
        res = dict(self.inner.execute_tool(
            tool_name="run_vmd_command", tool_input={"command": str(code)}, **kw) or {})
        if res.get("error"):
            res["error"] = sanitize_env_text(res["error"])
        if res.get("output"):
            res["output"] = sanitize_env_text(res["output"])
        return res

    @staticmethod
    def _append(res, field, text):
        res[field] = ((res.get(field) or "").rstrip() + "\n\n[lab] " + text).strip()

    # ------------------------------------------------------------ tool entry
    def execute_tool(self, *, tool_name="", tool_input=None, **kw):
        ti = tool_input or {}

        if tool_name in ("lab_try", "run_vmd_command"):
            code = str(ti.get("code") or ti.get("command") or "")
            res = self._run_code(code, **kw)
            guidance = self.protocol.record_try(
                code, ok=bool(res.get("ok")), error=str(res.get("error") or ""))
            if guidance:
                self._append(res, "output" if res.get("ok") else "error", guidance)
            res["tcl"] = code
            return res

        if tool_name == "lab_note":
            text = str(ti.get("text") or "")
            if not text.strip():
                return {"ok": False, "output": "", "error": "lab_note needs non-empty text"}
            return {"ok": True, "output": self.protocol.record_note(text), "error": ""}

        if tool_name == "lab_commit":
            code = str(ti.get("code") or "")
            if not code.strip():
                return {"ok": False, "output": "", "error": "lab_commit needs the final solution code"}
            refusal = self.protocol.commit_gate()
            if refusal:
                return {"ok": False, "output": "", "error": refusal}
            res = self._run_code(code, **kw)
            self.protocol.record_commit(bool(res.get("ok")))
            if res.get("ok"):
                res["output"] = ("COMMITTED.\n" + (res.get("output") or "")).strip()
            res["tcl"] = code
            return res

        return self.inner.execute_tool(tool_name=tool_name, tool_input=ti, **kw)

    # misc attribute access (e.g. inner-specific state) falls through to the inner bridge
    def __getattr__(self, name):
        return getattr(self.inner, name)
