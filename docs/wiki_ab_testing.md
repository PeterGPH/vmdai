# Testing wiki-on vs wiki-off

Two layers of testing prove the wiki feature is doing useful work:

## Layer 1 — deterministic A/B tests (CI, no LLM)

These run in CI on every commit. They use a scripted "agent" that
replays a fixed tool-call sequence against both configurations and
verify that the *plumbing* produces measurable differences.

```bash
PYTHONPATH=runtime python3 -m pytest tests/test_wiki_ab.py -v
```

What they prove:

- With wiki enabled, `wiki_list` / `wiki_read` / `wiki_update` succeed
  and produce knowledge accumulation (pages on disk, sources pinned,
  log entries appended).
- With wiki disabled, the same tool calls return structured
  "wiki not configured" errors and nothing accumulates.
- The bench harness's derived metrics (citation rate, pages filed,
  distinct sources cited) reflect the difference correctly.
- A control trial that never calls wiki tools produces identical
  outcomes in both arms — confirms the harness isn't biasing results.

These are unit tests. They run in 100ms and cost nothing. They catch
regressions when someone breaks the wiki wiring.

## Layer 2 — live-LLM benchmark (manual, costs API calls)

This is the "does the wiki actually help?" experiment. It runs the
*same prompts* against the *same model* with the wiki turned on vs.
turned off and measures what the model actually does.

### Setup

```bash
# Provider credentials — pick one.
export OPENROUTER_API_KEY=sk-or-...
# Or:
export ANTHROPIC_API_KEY=sk-ant-...
# Or for Ollama:
export VMD_AI_OLLAMA_MODEL=llama3.1:8b

# Seed your raw sources. The wiki arm will pin its citations against
# files under this directory. If you've already built a docs index,
# point this at the same location.
mkdir -p ~/.vmdai/raw
# ...copy VMD manual HTML / Tcl reference / etc. into ~/.vmdai/raw/...
```

### Run

```bash
python scripts/bench_wiki.py \
    --prompts evals/wiki_bench_prompts.json \
    --raw-root ~/.vmdai/raw \
    --out bench-out/
```

For a meaningful comparison, **pre-seed the wiki** before running:

```bash
# Option 1 — share a persistent wiki across runs:
python scripts/bench_wiki.py \
    --prompts evals/wiki_bench_prompts.json \
    --wiki-root ~/.vmdai/wiki \
    --out bench-out/

# Option 2 — let the bench use a fresh tmp wiki (default). This shows
# "cold-start" behavior: how quickly does the wiki grow useful from
# zero?
python scripts/bench_wiki.py --prompts evals/wiki_bench_prompts.json
```

If the wiki is empty in both arms, the wiki-on arm only wins when the
model files pages mid-bench and reuses them in later prompts. To
isolate the "knowledge already compiled" effect, run an ingest pass
first:

```bash
# Hand-seed: have the model ingest a few sources before benching.
# (Use the running VMD plugin and tell it to file pages, OR write a
# small ingest script that calls wiki_update directly.)
```

### Output

`bench-out/report.md` is the human-readable comparison. The headline
table looks like:

```
| metric                   | with_wiki | without_wiki |
| ---                      | ---       | ---          |
| trials                   | 6         | 6            |
| errors                   | 0         | 0            |
| avg duration (ms)        | 8234.0    | 7891.0       |
| median duration (ms)     | 7900.0    | 7610.0       |
| avg tool calls           | 4.50      | 3.83         |
| citation rate            | 83.33%    | 0.00%        |
| pages filed              | 4         | 0            |
| distinct sources cited   | 7         | 0            |
```

Headline metrics to compare:

- **citation rate** — % of trials whose answer cited at least one
  pinned source. The headline win for the wiki pattern. A real LLM
  with wiki tools should land in the 60-90% range on prompts where
  pinned sources exist; without-wiki should be 0% because there's
  nothing to cite.
- **pages filed** — how much the wiki grew during the bench. A high
  number means the agent is using `wiki_update` actively; a low number
  means it's only *reading* the wiki, not maintaining it. Both are
  legitimate uses; the right number depends on whether your prompts
  were "look up" or "ingest".
- **distinct sources cited** — citation diversity. A wiki arm that
  cites the same one source on every answer is suspicious.
- **avg tool calls** — wiki-on usually shows +1 (the `wiki_list` call
  most turns make). If it's much higher, the agent is fanning out to
  read too many pages — tune the schema in `wiki/CLAUDE.md`.
- **avg duration** — wiki calls are local-disk-fast, so the cost
  should be a few hundred ms per trial. If duration spikes far above
  the no-wiki arm, something is wrong.

`bench-out/report.json` contains the same data structured for further
analysis (pull into a pandas notebook, plot trends across days, etc.).

## Layer 3 — manual eyeballing (the only way to judge quality)

The two automated layers tell you *what* the agent did. They cannot
tell you whether the answer was actually *good*. After running the
bench, open `bench-out/report.md` and read the final answers
side-by-side for each prompt. Things to look for:

- Does the wiki arm name specific sources by path
  (`raw/vmd-manual/atomselect.html`)? That's the "pin the source to
  the reference" payoff.
- Does the wiki arm reuse prior pages? Check the
  `Per-trial detail → read:` lines.
- Does the no-wiki arm hallucinate plausible-but-wrong VMD syntax?
  The wiki arm should hallucinate less because it grounds itself in
  pinned sources.
- Does the wiki arm file *good* pages? Inspect
  `~/.vmdai/wiki/concepts/*.md` after the run.

Use these qualitative findings to tune `wiki/CLAUDE.md` — the schema
is what makes the agent a good wiki maintainer, and it's the easiest
thing to iterate on.

## Tracking drift over time

The wiki bench script doesn't yet emit per-source-file metrics, but
once a wiki is established, you can verify it with the in-process
tool the agent already has:

```bash
# Verify all pinned sources against current raw/ contents.
python3 -c "
import sys; sys.path.insert(0, 'runtime')
from vmd_ai_runtime.wiki_store import WikiStore
from pathlib import Path
w = WikiStore(Path.home() / '.vmdai/wiki', raw_root=Path.home() / '.vmdai/raw')
import json
print(json.dumps(w.verify_pins(), indent=2))
"
```

Anything that comes back as `drift` is a page whose pinned source has
changed upstream — revisit it.

## Cost notes

Layer 1 is free. Layer 2 costs roughly:

- N prompts × 2 arms × M turns ≈ 2NM LLM calls
- For OpenRouter/Anthropic at typical 2-5K-token turns, that's
  ~$0.10-$0.50 per bench run with 6 prompts.

Cap the bench size when iterating on the wiki schema; run the full
suite only when you ship a real change to the wiki tools or the
agent's system prompt.
