# ChatVMD round 1 — visual review (M3 exit)

The M3 exit criterion (spec Part A §8) is a visual review of the real panel against the Native prototype screenshots in `docs/design/round1/screenshots/native/` (states A–G), with the Part B grafts applied. This file is that review's record, and it closes round 1 (§1 Success).

- **Reference:** `screenshots/native/<state>.png`, the judged Native renders (half size).
- **Capture:** `screenshots/panel/<state>.png`, the real plugin, made with `tools/capture_locked.sh tools/capture_panel.tcl <A..G> <absolute out.png>` (paths under `docs/design/round1/`).
- **Content:** the captures replay `tests/fixtures/events/03_conversation.jsonl` (load 1hck as a cartoon, a failed then recovered background command, a snapshot, then the radius of gyration). The prototype shows its own scripted conversation, so the words and step counts differ. The review compares layout, type, colour and behaviour, not wording.

| Field | Value |
|---|---|
| Plugin commit | 168bf33 |
| Captured on | 2026-09-28 |
| macOS and Tk | macOS 14.4.1, Tk 8.6.12 (VMD.app's bundled framework) |
| System appearance while capturing | Light (each state forces its own window's appearance; the desktop's own appearance never matters) |

Each **Result** cell and header value starts unfilled and is filled with what was observed: `pass`, or `fixed in <commit>: <what changed>`. The review is complete when no cell is left unfilled.

## Expected differences from the Native screenshots

The Native prototype predates the grafts and the spec's required fixes (Part B V1), and round 1 leaves some of its features out (V9). These differences are by design, not defects:

1. **No "tunnel" in the status bar.** The left segment reads `Ollama · qwen3.8:27b · 127.0.0.1:11435`, not `… tunnel 127.0.0.1:11435` (V1 required fixes, V4 Status bar).
2. **No "Run in VMD" link.** A code block's header and the step detail offer `Copy` only (V4 "Run in VMD… / Run again…", V9).
3. **Step chips and a run summary** on each run header, such as `1 failed, recovered · N s` (cards graft, V4 Run header).
4. **A run footer:** `Copy Tcl · Save .tcl…` once the run applied a statement, and a muted usage line `N evaluated · M out` (console graft, M3).
5. **Collapse.** When run 2 starts, run 1 hides its work log; its header and chips, the failed row with its error line, the last snapshot card and the answer stay (cards graft, V4 Collapse).
6. **Tcl syntax colours** in the step detail (console graft, V4 Step detail).
7. **The console snapshot card:** purpose, `1280 × 1547 · TachyonInternal`, the file name, `Open · Reveal · Save PNG…` and `✓ Sent to the model` (V4 Snapshot card).
8. **Stop** is a pill with `stop_bg` in the Send cell while a request runs (cards graft, V4 Composer).
9. **The empty state** has four bordered example cards (2×2 at 520 px and wider), the Ready group with its trust row, and the key hints row (cards graft, V4 Empty state); Native D has a one-column "Try" list.
10. **Settings is a titled window** ("ChatVMD Settings", ttk notebook Model / Keys / Panel), not the override-redirect sheet (V1 "Not carried over"). It is also genuinely wider than the 560 px panel (~686 px; the Model tab's Profile row carries a combobox plus New…/Delete… buttons), unlike Native's narrow sheet, so `E_settings.png` is 716×808, not 560×808 — see the note under state E below.
11. **Chevrons** (▸) are `muted`, not `faint` (V1 required fixes).
12. **Window title** `ChatVMD — <chat title>`; the toolbar shows the chat title.

## A — Light (`A_light.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| A1 | 560 × 780; toolbar with New chat and History icons on the left, the title centred in ChatMetaBold, ⋯ and the gear on the right; a hairline under it | V3, V4 Toolbar | pass |
| A2 | "You" in ChatRole with the time right-aligned on the same line; the prompt in ChatBody | V4 Transcript blocks | pass |
| A3 | Each tool row is one line: glyph, command (mono, `text2`), muted suffix, duration, ▸ | V4 Tool rows | pass |
| A4 | The failed row's error line sits directly under it in `err`, visible without a click, also in the collapsed run 1 | V1, V4 Collapse | pass |
| A5 | Sealed prose is Markdown: `1hck` bold, `display backgroundcolor` as tinted inline code on one line; no `**` and no backticks | V4 Markdown | fixed in 168bf33: the inline-code tint no longer fills the paragraph's 8 px gap band (was a 24 px slab); `1hck` bold and no literal `**`/backticks were already correct. This state's own final answer ("Loaded **1hck** as a cartoon on a white background.") has no inline code — the `display backgroundcolor` narration is folded into collapsed run 1's hidden work log here, so the tinted inline code itself is visible in `C_midrun.png`, not in this state; verified there (see C's note and the graft row below). |
| A6 | The snapshot thumbnail is cropped of its border, fits 256 × 192 and is not cropped to fill; the caption is difference 7 | V4 Snapshot card | pass |
| A7 | A hairline rule before each final answer; footer and usage line right-aligned and muted | V4 Prose, Run footer | pass |
| A8 | Composer: rounded field, accent focus ring, the two-line draft; Send is the default button | V4 Composer | pass |
| A9 | Status bar: `●` in `ok`, provider · model · host:port on the left; `Auto-run Tcl ▾ │ ~/proj/cdk2 · N runs` on the right | V4 Status bar | fixed in c86d2af: the right segment keeps its 14 px pad when idle |
| A10 | Chrome, surface, hairline and accent match `A_light.png` region by region | V2 | pass |

## B — Dark (`B_dark.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| B1 | Surface `#1e1e1e`, text `#e6e6eb`, the dark window background as chrome, hairlines `#0c0c0d` | V2 | pass |
| B2 | Title bar, scrollbar and Send button are dark (this window's MacWindowStyle appearance is `darkaqua`) | V2 System appearance | pass |
| B3 | Accent `#4ea1ff`, ok `#3bd16f`, err `#ff6b64`: glyphs and the error line read clearly | V2 | pass |
| B4 | Inline code on `#313135`; code blocks and step details on `#28282b` with the dark syntax colours | V2 | pass |
| B5 | Nothing is left in a Light colour (compare every region with `A_light.png`) | V2, P10-T06 | pass (pixel-scanned `B_dark.png`: 452,480 px total, only 45 near-white px, all sub-pixel anti-aliasing on light-on-dark text/glyph edges, no light-mode region) |
| B6 | Muted text (times, suffixes, the usage line) is readable on surface and chrome | V2 contrast | pass |

## C — Mid-run (`C_midrun.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| C1 | Status bar: a spinner, `Step 3 · running VMD command · 00:1x`, and `Esc to stop` on the right | V4 Status bar | pass |
| C2 | The running row shows the spinner and `running…` | V4 Tool rows | pass |
| C3 | Step 1's detail: a `code_bg` block indented 24 with `-lmargincolor`; the rationale muted; the exact command bytes with syntax colours; the `→` output; `Copy` | V4 Step detail | pass |
| C4 | Composer: the busy placeholder "Reply once this run finishes — or press Esc to stop" and the Stop pill in the Send cell | V4 Composer | pass |
| C5 | New chat and History are disabled | V4 Toolbar | pass |
| C6 | The run header's chips show the steps so far (`✓ ✗ •`) | V4 Run header | pass |

*Capture-tool note (not a plugin defect):* the fixture events update the status bar's activity text via `panel::render`/`_apply_status`, but the panel's own `busy` flag (composer mode, toolbar disable, the status bar's busy rendering) is normally flipped only by a real `bridge::send` round trip. `capture_panel.tcl` drives it directly with `::vmdai::panel::set_busy 1`, the same call `test_panel.tcl`/`test_keymap.tcl`/`test_settings.tcl` already use to simulate a running request headlessly.

*Inline code (A5, fixed in 168bf33):* this is the state that actually shows tinted inline code — the mid-run narration "`display backgroundcolor` does not exist; the `color` command alone is enough." — and the fix is visible here: the tint hugs exactly the text line, with no extra 8 px slab below it (confirmed both visually in `C_midrun.png` and by the `md-icode-tint` tcltest).

## D — Empty state (`D_empty.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| D1 | Visually centred: the mark, "What should VMD do?", the muted lead line | V4 Empty state | pass |
| D2 | Four bordered example cards in 2 × 2: Load & style, Binding pocket, Color by B-factor, Trajectory RMSD | V4 Empty state | pass |
| D3 | The Ready group with row dividers: Runtime, Model (Change), Folder (Change), and the trust row "Model-written Tcl runs unsandboxed in this VMD session. Only load files you trust." | V4 Empty state | pass |
| D4 | The key hints row `⏎ send · ⇧⏎ newline · ↑ last prompt · esc stop` | V4 Empty state | pass |
| D5 | Composer placeholder "Ask VMD to load, show or measure something…"; toolbar title "New chat" | V4 Composer | pass |
| D6 | In column mode (transcript < 520 px, e.g. a 420 px window) and in pair mode below about 650 px of height, the Ready group, trust row and key hints stay reachable (the overlay scrolls or the cards compact); parked from plan 09 T02 | V4 Empty state | fixed in 1bba8df: `layout_empty_state` now also reads the transcript's real height, tightening mark/ready/keys spacing and hiding the lead line below 650 px, and (in column mode) hiding each card's description line too. Verified at 560×600 (fully reachable) and 420×300 (Runtime/Model/Folder/trust group all reachable; only the trust row's wrapped 2nd line and the key hints can still run past the bottom edge). None of the 7 committed states are this short, so `D_empty.png` (560×780) is pixel-identical before/after. A fully guaranteed fix at the panel's documented minimum size (`wm minsize` 380×420) needs a scrollable overlay (embedding it in the transcript `Text` as a window, which already has a scrollbar and the `CVScroll` wheel bindtag for exactly this) — left for round 2 as a bigger, riskier change than this review's scope. |

## E — Settings (`E_settings.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| E1 | Settings is a titled transient window, "ChatVMD Settings", at least 460 px wide | V4 Settings | pass |
| E2 | ttk notebook tabs Model, Keys, Panel; the Model tab shows Profile, Provider, Server (mono) with its hint, Model with Refresh, Context, Snapshots, Test connection | V4 Settings | pass |
| E3 | Right-aligned regular-weight labels, one field column, hints under the fields | V4 Settings | pass |
| E4 | The footer "Changes apply to the next message." with Cancel and Save | V4 Settings | pass |
| E5 | The panel behind the dialog looks as in A | — | pass |

*Capture note (deviation from the brief's Step 3 "every PNG is 560×808" line, not a plugin defect):* the real Settings window is genuinely wider than the 560 px panel (~686 px — the Model tab's Profile row carries a combobox plus New…/Delete… buttons; Native's own settings is a narrow override-redirect sheet that was explicitly not carried over, difference 10). A capture region sized to just the panel clips Cancel/Save; a single screenshot of the panel+dialog union rectangle would show whatever real window sits behind the uncovered corner on the capturing desktop (a screen-content leak, not acceptable to commit). `capture_panel.tcl`'s `shoot` proc now screenshots the panel and the dialog separately and composites them with a Tk photo image, so `E_settings.png` is `716×808` and any uncovered corner is blank — see the code comment at `shoot` for the full reasoning. Every other state is still exactly `560×808` (`466×808` for F).

## F — Narrow, 466 px (`F_narrow.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| F1 | Narrow class: `-padx 14`, prose wraps, nothing scrolls sideways | V6 | pass |
| F2 | Rows stay one line; long commands end in an ellipsis and never drop below 12 characters | V6 Row refit | pass (this fixture's commands are all short enough not to need eliding at 466 px; the row-refit mechanism itself is unchanged M2/M3 code, exercised at forcing widths by `tests/tcl/test_tool_rows.tcl`) |
| F3 | The run header drops the model name first | V6 Run header | pass (`ChatVMD qwen3.8:27b … ✓ 1 step · 8 s` already fits at 466 px in this fixture, so dropping never triggers here; the refit itself — "drop the model name, then shorten…" — is `plugin/transcript.tcl`'s header-refit code, exercised at forcing widths elsewhere) |
| F4 | The snapshot caption stacks under the image | V4 Snapshot card, V6 | pass |
| F5 | Status segments drop in the order host, run count, folder, provider; `Auto-run ▾` stays | V4 Status bar | fixed in c86d2af: the right segment keeps its 14 px pad when idle. This is the exact narrow state the finding named (466 px, where the missing pad let the window corner clip the "s" of "runs"); the drop-order mechanism itself is unchanged (both status segments already fit at 466 px in this fixture without dropping) and is exercised directly by `tests/tcl/test_statusbar_banner.tcl`. |
| F6 | Inline code never breaks across lines | V4 Markdown, V8 | pass |

## G — Disconnected (`G_disconnected.png`)

| # | Check | Spec | Result |
|---|---|---|---|
| G1 | The banner in slot 2: `warn_bg`, the warning triangle, bold "Runtime not reachable", a detail line with host:port and a countdown, pill buttons Retry now and Open log | V4 Banner | pass |
| G2 | One timeline note "Connection lost at … · your draft is kept", centred and muted | V4 Timeline notes | pass |
| G3 | The status bar shows the reconnecting state with the dot in `warn`, and no "tunnel" | V4 Status bar | pass |
| G4 | Send is disabled while the banner shows; the draft is kept | V4 Banner | pass |

## Grafts (Part B V1)

| Graft | Seen in | Result |
|---|---|---|
| Paint registry (console `theme::paint/repaint`) | B: every colour switched, including the native controls | pass |
| Tcl syntax colours (console `syntax::tokens`) | C: step 1's detail; B: the same in dark | pass |
| Snapshot card (console `snap::autocrop/thumb/card`) | A, F | pass |
| Status bar fitting (console `ui::status_fit`) | F | pass (mechanism `::vmdai::statusbar::_fit`; this fixture's segments already fit at 466 px, so dropping isn't visible in `F_narrow.png` itself — see F5) |
| Width classes (console `wide`/`narrow` elide tags) | F | pass |
| Read-only transcript (cards proxy) | A: the transcript takes focus and selects text; `ro-1` covers the behaviour | pass (`tests/tcl/test_transcript.tcl::ro-1`, run via `tests/test_tk_transcript.py::test_ro_1`) |
| Inline code with NBSP (cards `md::inline`) | C | fixed in 168bf33: seen in `C_midrun.png`'s `display backgroundcolor` narration — A and F's own final answers have no inline code (A's narration is folded into collapsed run 1's hidden work log). The tint now hugs its own line instead of filling the 8 px paragraph gap; the NBSP no-wrap behaviour itself was already correct (F6, `md-inline-nowrap`). |
| Collapse (cards group `-elide`) | A: run 1 collapsed | pass |
| Empty state (cards `welcome` cards) | D | pass |

## Round 1 exit (§1 Success, §8)

| # | Criterion | Measured by | Result |
|---|---|---|---|
| S1 | A follow-up sees prior turns, tool blocks included | pytest (the 2nd `chat.send`'s prior) in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S2 | No transcript glue | Tk goldens `03_conversation`, `reasoning_answer` and the P10-T06 goldens | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S3 | Kill or restart: at most 1 notice per state change, recovery within 10 s | tclsh bridge test in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S4 | Close/reopen and reload repeat cleanly; SIGTERM exit within 2 s | pytest SIGTERM test and tclsh registry test in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S5 | Ollama `qwen3.8:27b` sees snapshots | `tests/test_live_ollama.py` against the live server | pass (tests/test_live_ollama.py: 2 passed, 2026-09-28) |
| S6 | An unreachable Ollama fails within 3 s with the right hint | socket tests in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S7 | No benchmark-visible change with `options=None` | golden requests, retry pin, bridge guard, hashes in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S8 | Å, → and ° round-trip | tclsh 8.6 with http 2.9.5 in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S9 | Suite green, hermetic, under 60 s | `env -u VMD_AI_PROVIDER python -m pytest tests -q` | pass (1356 passed, 5 skipped, 10 subtests passed in 46.04 s, well under 60 s) |
| S10 | `save_path` writes a real file; `puts` output reaches the model | executor tests in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S11 | Foreign Host or Origin rejected; privileged RPCs need the token | security tests in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| S12 | A ```` ```tcl ```` block in prose runs nothing | pytest (no `tool_start`) in `tests` | pass (tests: 1356 passed, 5 skipped, 10 subtests passed in 46.04 s) |
| V | Visual review A–G with the grafts | this file | pass (every A–G and graft row is `pass` or `fixed in <sha>`; D6 is `fixed in 1bba8df` with a documented residual limit at the panel's minimum size, left for round 2; A9/F5 are `fixed in c86d2af` (status bar right pad) and A5/the NBSP graft row are `fixed in 168bf33` (inline-code tint), both recaptured) |
| — | `vmdbench` 90 passed; `explore_arm` + `scivisagentbench` 62 passed; no runtime, integrations, vmdbench or scripts change in M3 | the Step 6 commands | pass (90 / 62 / no diff — `python -m pytest vmdbench/tests -q`: 90 passed in 13.00 s; `python -m pytest integrations/explore_arm/tests integrations/scivisagentbench -q`: 62 passed in 1.15 s; `git diff main --stat -- runtime/ integrations/ vmdbench/ scripts/` printed nothing; `perl -ne '...' plugin/syntax.tcl plugin/markdown.tcl` printed nothing) |

## Fix round 1 (P10-T07 review)

Two plugin fixes, recaptured across all 7 states (A, B, D, E, F, G for the status-bar pad; C for the
inline-code tint), each with a failing-first tcltest:

- **`c86d2af`** — the status bar's 14 px right pad lived on `.hint`'s `padx`, which is
  grid-removed when idle, so the right segment touched the window edge (0 px) whenever the bar
  was idle; at 466 px (state F) this clipped the "s" of "runs". The pad now lives on an
  always-present empty grid column. New tcltest `status_right_pad`.
- **`168bf33`** — `md_p`'s own `-spacing3 8` let a tinted inline-code span on a paragraph's last
  line paint across the full 24 px line-plus-gap band instead of a 16 px line. The 8 px gap now
  lives on its own blank `md_sp` line (the cards graft's own fix, `prototypes/cards/proto.tcl:635-638`).
  New tcltest `md-icode-tint`.

**T04 carry-forward (b), scratch only, never committed:** rendered a sample (a paragraph with
inline code, a list item with inline code, a ```` ```tcl ```` block, and a following paragraph) in
the real assembled panel, light and dark, via `capture_locked.sh`. Confirmed in both: code lines
are tight (no extra spacing inside the fence), the gap between every block is a consistent 8 px,
and the inline-code tint hugs exactly its own text line in both the paragraph and the list item —
no regressions from the `md_sp` change. Not part of this task's committed deliverables.
