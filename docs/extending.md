# Extending Bizzbell

Bizzbell's core is small on purpose. Everything else is added as new files at four extension points:
a **command**, a **rubric**, a **local check**, and (for paid work) a call through the **ledger**.

All code is Python 3.9+ standard library only. Run the tests with:

```
python3 -m unittest discover -s tests -v
```

## 1. Add a `bb` command (one file, never edit `bb.py`)

Create `scripts/bizzbell/commands/<name>.py`:

```python
"""bb hello: say hello."""
from .. import project
from ..cli import add_project_arg      # standard --project/-p option
from ..errors import BBError, UsageError

NAME = "hello"                         # the subcommand
HELP = "say hello"                     # one line for `bb --help`


def register(p):                       # p is an argparse subparser
    add_project_arg(p)
    p.add_argument("--who", default="world")


def run(args):                         # return an exit code (None means 0)
    root = project.find_project(args.project)
    print("hello", args.who, root)
    return 0
```

- `bb` imports every module in `scripts/bizzbell/commands/` whose name does not start with `_`, sorted by name.
  A module missing `NAME`, `HELP`, `register` or `run` is skipped with a warning; one that fails to import is
  reported and skipped, so a broken command never breaks the others.
- Expected failures: raise `errors.BBError` (exit 1) or a subclass (`UsageError` 2, `GateFailed` 3,
  `RoundsExhausted` 4, `PaymentRequired` 5, `NotAvailable` 6, `BudgetExceeded` 7, `Blocked` 8). The CLI prints
  `bizzbell: <message>` (passed through `redact()`) without a traceback. `--debug` anywhere shows tracebacks.
- Never print a key. Pass any text that may contain one through `hidrogen.redact()`.

## 2. Make a paid call (always through the ledger)

```python
from bizzbell import hidrogen, ledger, project

root = project.find_project(None)
led = ledger.Ledger(root)
png, resp = led.call("image",
                     lambda: hidrogen.image(prompt, refs=[sheet_path], aspect="9:16",
                                            model=project.model_for(root, "image")),
                     model=project.model_for(root, "image"), purpose="keyframe s03",
                     quote_params={"count": 1})
```

`Ledger.call(kind, fn, model, purpose, units=1, estimate_inr=None, quote_params=None, ref="")` reserves the
estimate (from `/v1/media/quote` when `quote_params` is given and the quote answers, else
`bizzbell.json budget.rates_inr[kind] x units`), refuses with `BudgetExceeded` past the cap or before a budget
was approved, runs `fn`, and settles with the INR the reply reports (`charged_inr`). Kinds: `chat`, `judge`,
`image`, `video` (units = seconds), `voice`, `music`. `PaymentRequired`, `NotAvailable`, `Blocked` and other
4xx release the reservation (charged 0).

## 3. Write a rubric (`rubrics/<stage>.json`)

A project may override any rubric with `<project>/rubrics/<stage>.json`. Stage ids: `brief`, `research`,
`story`, `humanize`, `screenplay`, `characters`, `keyframes`, `audio`, `video_a`, `video_b`, `final`. The media
sub-layers have their own rubrics: `voice`, `music`, `mix` (the `audio` stage passes when all three pass) and
`clips`, `version_a` (the `video_a` stage). `bb final` derives `final_a` and `final_b` from `final.json` (one per
version) and writes them into the project's `rubrics/` folder.

```json
{
  "stage": "screenplay",
  "version": 1,
  "title": "Screenplay, every second",
  "layer": {"kind": "text", "files": ["screenplay.md", "screenplay.json"]},
  "references": ["story_humanized.md", "brief.md"],
  "pass_score": 95,
  "judge_notes": "optional extra context for the judge",
  "verify_evidence": true,
  "restructure": {"targets": ["screenplay.md", "screenplay.json"]},
  "questions": [
    {"id": "SP1", "text": "Does every second from 0 to the end have a row?", "check": "rows_cover_every_second"},
    {"id": "SP2", "text": "Does every spoken line of the humanized story appear word for word?", "weight": 3,
     "evidence": "Quote any line that is missing or changed."},
    {"id": "SP3", "text": "Is every frame free of requests to draw text, a logo or a number plate?", "weight": 2,
     "hard": true, "quote": false}
  ]
}
```

| Field | Meaning |
|---|---|
| `stage` | stage id (informational; the file name decides which stage it gates) |
| `layer.kind` | `"text"` (judged with `chat()`) or `"media"` (judged with `media_judge()`, files attached) |
| `layer.files` | paths or globs, relative to the project; text files are pasted into the prompt |
| `layer.max_files` | media only: at most this many files are attached (default 8) |
| `references` | paths/globs the layer is judged against (pasted into the prompt, text files only) |
| `pass_score` | default 95 |
| `judge_notes` | optional extra instructions for the judge |
| `verify_evidence` | text layers: a `yes` whose quote is not in the layer/references becomes `partly` (default true) |
| `restructure.targets` | files `bb restructure` may rewrite (default: the layer's text files; media layers name their prompt files) |
| `questions[].id` | unique, letters/digits/`_.-` |
| `questions[].text` | phrased so **yes is good** |
| `questions[].weight` | positive number, default 1 |
| `questions[].hard` | `true`: a final `no` fails the gate whatever the score |
| `questions[].evidence` | hint: what evidence the judge should quote |
| `questions[].quote` | `false` exempts a `yes` from the quote check (answers about absence) |
| `questions[].check` | name of a registered local check: answered locally, never by a model |
| `questions[].args` | keyword arguments for the check |

Scoring: yes 1, partly 0.5, no 0; score = weighted %. Two judge passes (mean per question); a third pass when
they differ by more than 10 points or disagree on a hard question (median per question). Pass = score >=
`pass_score` and no hard question at 0. Each run is saved as `gates/<stage>.<n>.json`.

## 4. Add a local check (`scripts/bizzbell/checks/<module>.py`)

```python
from ..gate import check


@check("rows_cover_every_second")
def rows_cover_every_second(ctx, file="screenplay.json"):
    rows = ctx.json(file, {}).get("rows", [])
    ...
    return "yes", "rows 0-29 present"          # or "partly"/"no"; or True/False; or {"answer", "evidence"}
```

`ctx` is a `gate.GateContext`: `root`, `stage`, `rubric`, `settings`, `state`, `layer_files`,
`reference_files` (absolute paths), `layer` / `references` (dict of relative path -> text), `layer_text`,
`read(rel)`, `json(rel, default)`, `rel(path)`. A check that raises answers `no` with the error as evidence.
Built-in checks: `files_exist`, `word_count`, `json_valid`, `contains_none`, `has_sections`.

## 5. The mock server

`python3 scripts/bb.py mock --port 0 --behaviour judge_low_then_high` (or
`PYTHONPATH=scripts python3 -m bizzbell.mock_server --port 0`) prints its URL. Use it with
`HIDROGEN_API_URL=<url> HIDROGEN_API_KEY=hi_test_0000000000000000fake`. In tests:
`with MockHidrogen(["media404"]) as m: ...` (see `tests/helpers.py`). Behaviours: `pay402`, `media404`, `block`,
`slow_job`, `flaky`, `no_opus`, `judge_low_then_high`, `judge_always_low`, `judge_disagree`, `judge_hard_no`,
`judge_bad_json_once`. Switch at runtime with `POST /_mock/behaviour {"set": [...]}`.
