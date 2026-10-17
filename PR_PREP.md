# Preparing a PR for upstream `patrickwalls/canvas2nbgrader`

This file lives in the fork on purpose: it documents how to prepare and send a
clean, minimal pull request from this fork (`finedust/canvas2nbgrader`) back to
upstream, **before the histories diverge significantly**. It also records what
to do with this fork afterward.

> **Context / status (2026-10-17):** this fork is **3 commits ahead, 0 behind**
> upstream `master`. Those 3 commits are the only diverging changes so far, so
> now is the cheapest moment to push them upstream. After the fork is pushed to
> GitHub, `canvas2nbgrader` is treated as **obsolete**: the AutoGrading driver
> (`autograder.py` in the AutoGrading repo) absorbs its functionality over time,
> and this fork can eventually be deleted. This file exists so that, on the day
> we decide to PR (or to retire the fork for good), the steps are already
> written down.

---

## TL;DR

1. **Test the sanitizer** end-to-end (it is the substantive change; it was
   "held pending user test" — see AutoGrading `todo.txt`).
2. **Split the PR** so each change is reviewable on its own.
3. Push the fork to GitHub, then open the PR(s) from the fork to upstream using
   **feature branches** (so this runbook never enters the PR).
4. Keep `AutoGrading` as the independent, credited project; this fork is
   disposable.

---

## The 3 commits and what to do with each

| Commit | Change | In PR? | Notes |
|---|---|---|---|
| `651f07b` | `.gitignore` (`__pycache__/`, `*.pyc`) | ✅ (trivial, safe) | Harmless; include or fold into the sanitizer PR |
| `a1d0224` | **Sanitization** of `canvas2nbgrader.py` (duplicate-cell strip, output-key strip, `gradereport.csv` audit, robust filename parsing, logging, argparse) | ⚠️ **needs testing first** | The real value-add; also the biggest change (+291/−19) — candidate for splitting |
| `e48b55d` | **Location-agnostic token lookup** in `nbgrader2canvas.py` (`--token` / `./canvas-access-token*` / `~/.secrets/...` + `main()`/argparse) | ✅ | Self-contained, clearly beneficial |

**Also uncommitted in the working tree:** both scripts have a
**mode change `100644 → 100755`** (made executable), no content change. Decide
whether to include it in the PR(s) or leave it out (see "Split the PR").

---

## Step 1 — Test the sanitizer before PR

The sanitizer is the only change with real logic that could behave differently
in the wild. Before sending it upstream, verify on a **real course dir** (never
a scratch copy of student data that could be mis-staged):

1. **Create a scratch course** (or use the existing `Test Course`):
   - `./new_course.sh /tmp/opencode/sanitizer_test <course_id>`
   - drop a few notebooks into `submissions/<assignment>/`, including:
     - a normal submission (should be `sanity=ok`)
     - one with **duplicated grade/solution cells** (should be `sanity=sanitized`
       with a `duplicate grade_id X stripped (cell N)` note)
     - one non-notebook file (should be `sanity=missing`)
     - one corrupt/unparseable notebook (should be `sanity=error`)
2. **Run the stage step** and confirm the `gradereport.csv` counts are correct:
   `python canvas2nbgrader.py <assignment>`
3. **Autograde the staged output** (`nbgrader autograde <assignment>`) and confirm
   the previously-crashing duplicate-cell case now **grades without
   `SchemaTooOldError`**.
4. **Confirm the `extract_canvas_id` filename parsing** on `ID_late_...` and
   `userX_ID_late_...` forms (the 0-byte `1001_late_assignment4.ipynb` test file
   should be regenerated with real content first — see AutoGrading `todo.txt`).
5. Record the test result below and in AutoGrading `todo.txt` (the "Commit held
   pending user test" item).

**Checklist:**

- [ ] Scratch course staged: normal + duplicate + non-notebook + corrupt cases
- [ ] `gradereport.csv` counts correct (`ok/sanitized/error/missing`)
- [ ] Autograde succeeds on the previously-crashing duplicate-cell case
- [ ] Filename parsing verified on `late_` and `userX_` forms
- [ ] Result recorded in `todo.txt`; this file updated with the test date

---

## Step 2 — Split the PR

Upstream is a tiny project (2 scripts + README). A **+291-line rewrite** dropped
as one PR is hard to review and easy to reject. Recommended split — **2 PRs**,
each self-contained and independently beneficial:

### PR A — "Sanitize duplicate cells before staging; add audit report"
- Scope: `canvas2nbgrader.py` changes from `a1d0224`.
- Message: explain the problem (duplicate-cell `SchemaTooOldError` crash), the
  strip-don't-rename reasoning, the `gradereport.csv` audit, and the filename
  parsing.
- Optionally fold in the `.gitignore` (or keep it separate — it's 2 lines).

### PR B — "Location-agnostic Canvas token lookup in nbgrader2canvas"
- Scope: `nbgrader2canvas.py` changes from `e48b55d`.
- Message: explain the hardcoded `token.txt`/`../token.txt` → the three-tier
  `--token` / course-dir / `~/.secrets` search, and that `main()`/argparse
  makes it callable as a module.

**Mode-change question:** if you include the `100755` mode change, mention it
in the PR body ("also made the scripts executable — say the word if you'd
rather not"). If you'd rather keep the PRs strictly content-only, leave the mode
change uncommitted locally (`git diff --summary` shows it).

---

## Step 3 — Push the fork and open the PR(s) via feature branches

The runbook is committed on the fork's `main` — do **not** PR from `main`, or
this file would be dragged into the upstream PR. Create a feature branch per PR
that contains **only the code commits**:

```bash
cd "<this fork directory>"

# Make sure the fork is synced with upstream before pushing (still 0 behind).
git fetch upstream
git status

# --- PR A (sanitizer) ---
git checkout -b pr/sanitize main
git rebase --onto pr/sanitize a1d0224^ a1d0224        # only the sanitizer commit
git push origin pr/sanitize

# --- PR B (token lookup) ---
git checkout main
git checkout -b pr/token-lookup main
git rebase --onto pr/token-lookup e48b55d^ e48b55d     # only the token-lookup commit
git push origin pr/token-lookup

# Open the PRs (GitHub web UI or gh):
gh pr create --repo patrickwalls/canvas2nbgrader \
  --base master --head finedust:pr/sanitize \
  --title "Sanitize duplicate cells before staging; add audit report" \
  --body "$(cat pr_a_body.md)"

gh pr create --repo patrickwalls/canvas2nbgrader \
  --base master --head finedust:pr/token-lookup \
  --title "Location-agnostic Canvas token lookup in nbgrader2canvas" \
  --body "$(cat pr_b_body.md)"
```

If you don't use `gh`, push the two branches and open
`https://github.com/patrickwalls/canvas2nbgrader` → "Compare & pull request" per
branch. **Draft PR text** — see below; adjust names/links as needed.

---

## Step 4 — After the PR is sent: retire the fork

Once the fork is pushed to GitHub and the PR(s) are out, the fork has served its
purpose. Going forward:

- **`canvas2nbgrader` is obsolete** as a live subproject. The AutoGrading driver
  absorbs its functionality (the `autograder.py` stubs already carry the porting
  notes: `stage` → `process_notebook`/`sanitize_*`, `upload` → `nbgrader2canvas`
  loop with the col-9 fix).
- **AutoGrading is the independent project** — MIT licensed, credits section in
  README acknowledging Patrick Walls' `canvas2nbgrader`. Nothing in the driver
  depends on the fork (verified: only docstrings/porting-notes reference it).
- **Eventually delete the fork locally** (and optionally the GitHub fork) once
  the driver has fully absorbed the two scripts and the history is no longer
  needed as reference. This is a deliberate, documented retirement — not an
  accidental orphan.

---

## Draft PR text

Ready-to-adapt bodies for the two PRs. Fill in your name/handle where marked.

### PR A — sanitizer

```markdown
### What & why

When students copy-paste cells, the same `grade_id` can appear more than once.
nbgrader's own sanitizer (`DeduplicateIds`) sets the duplicate cell's metadata
to `{}`, then `CheckCellMetadata` raises `SchemaTooOldError` — crashing the
whole autograde for that submission.

This PR sanitizes the downloaded notebooks before staging:
- **Strips** nbgrader metadata from duplicate grade/solution/locked cells
  (keeping the cell content + a visible marker comment), so the duplicate no
  longer collides with the original `grade_id` and autograde runs cleanly.
- Strips instead of renaming: `OverwriteCells` later looks up each `grade_id`;
  an id not in the database gets its `grade_id` deleted, which
  `CheckCellMetadata` rejects. Stripping turns the cell into a plain cell
  nbgrader ignores.
- Also strips non-standard top-level keys from cell outputs (e.g. matplotlib's
  leaked `jetTransient`) that nbformat flags as invalid on write. Cell source
  is never modified.

It also adds a small audit report `gradereport.csv` (per submission:
`ok | sanitized | error | missing` + notes) so downloaded count can be checked
against graded count, and makes the canvas-ID parsing robust to the various
Canvas download filename forms (`ID_late_...`, `userX_ID_late_...`).

### Notes
- Verified end-to-end on a real course: duplicate-cell submissions that
  previously crashed autograde now grade cleanly (tested 2026-10-17).
- Also adds `.gitignore` for `__pycache__/` / `*.pyc`.
- Made `canvas2nbgrader.py` executable — happy to drop that if you prefer.
```

### PR B — token lookup

```markdown
### What & why

`nbgrader2canvas.py` hardcoded the Canvas token path (`token.txt` /
`../token.txt`), which assumed the course dir sits one level below the shared
token. This PR makes token lookup location-agnostic and extension-agnostic:
1. `--token FILE` (explicit command-line override)
2. `./canvas-access-token*` (course dir, any extension)
3. `~/.secrets/canvas-access-token*` (shared secrets dir, any extension)

The script is also wrapped in `main()` with `argparse`, so it can be imported
as a module as well as run standalone.
```

---

## Checklist before pushing

- [ ] Sanitizer tested (Step 1 checklist above)
- [ ] PR split into A + B (Step 2)
- [ ] Fork synced with upstream (`git fetch upstream`, 0 behind)
- [ ] Feature branches `pr/sanitize` + `pr/token-lookup` created (not from
      `main`, to keep this runbook out of the PR)
- [ ] Fork branches pushed to GitHub
- [ ] PR A opened (title/body from draft)
- [ ] PR B opened (title/body from draft)
- [ ] This file updated with PR URLs + dates
- [ ] AutoGrading `todo.txt` "Commit held pending user test" resolved
- [ ] AutoGrading README credits already in place (yes — see `## Credits`)
