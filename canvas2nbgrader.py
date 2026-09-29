#!/usr/bin/env python
# coding: utf-8
"""
canvas2nbgrader.py
------------------
Downloaded Canvas submissions -> nbgrader `submitted/` layout.

For each downloaded file in submissions/<assignment>:
  * if it's a .ipynb: load it, SANITIZE the nbgrader metadata, then write it
    into submitted/<canvas_id>/<assignment>/<assignment>.ipynb
  * if it's NOT a .ipynb: it is NOT copied (nbgrader only grades notebooks);
    the report flags it so you can warn the student on Canvas if needed.

Sanitization (why):
  Students sometimes submit notebooks with DUPLICATED grade/solution cells
  (e.g. they copy-pasted a cell and could not delete it).  nbgrader's own
  sanitizer (`DeduplicateIds`) sets the duplicate cell's nbgrader metadata to
  {} and then `CheckCellMetadata` raises `SchemaTooOldError: Outdated schema
  version: 0 (expected 3)` — so autograde crashes on the whole submission.

  Instead of deleting the extra cells (which could hide student work), we
  STRIP the nbgrader metadata from the duplicate cell (keeping the cell
  content and adding a marker comment), so:
    - the duplicate no longer collides with the original grade_id
    - the cell stays in the notebook (visible, harmless, not graded)
    - nbgrader's own sanitize phase then runs cleanly.

  Why strip rather than rename?  OverwriteCells (later in the sanitize chain)
  looks up each grade_id in the gradebook; an id that is not in the database
  gets its grade_id DELETED, leaving nbgrader metadata with no grade_id, which
  CheckCellMetadata then rejects ("nbgrader cell does not have a grade_id").
  So a renamed id would still fail autograde.  Stripping the metadata entirely
  turns the cell into a plain cell that nbgrader ignores: the v3 validator
  skips cells with no 'nbgrader' key, and utils.is_grade()/is_solution()/
  is_locked() all return False for them.

  We also strip non-standard top-level keys from cell OUTPUTS (e.g. a
  'jetTransient' key leaked by an old matplotlib into display_data outputs).
  Outputs are never graded, so this only cleans what nbformat flags as invalid
  JSON on write; cell source code is NEVER modified.

Audit report (why):
  One CSV per course root (REPORT_FILE) records, per submission, the sanity
  status so you can quickly check e.g. downloaded count == graded count and
  which notebooks needed manual editing.  Overwritten on every run (nbgrader
  also overwrites its outputs each run).  Use pandas for easy filtering.

Columns:
  canvas_id        : student's Canvas ID (first all-digit token in filename)
  assignment       : assignment name
  originalfilename : downloaded file name
  sanity           : ok | sanitized | error | missing
  sanitize_notes   : e.g. "duplicate grade_id X stripped (cell 28)" or
                     "output 5.0 (display_data): stripped 'jetTransient'"
  integrity        : placeholder, filled in later (e.g. after autograde)
  notes            : free-form, e.g. "non-notebook file, not copied"

Dependencies: nbformat (ships with nbgrader env), pandas.
"""

import argparse
import glob
import logging
import os
import shutil

import nbformat
import pandas as pd

logger = logging.getLogger("canvas2nbgrader")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPORT_FILE = "gradereport.csv"   # written to the course root (CWD)
REPORT_COLUMNS = ["canvas_id", "assignment", "originalfilename", "sanity",
                  "sanitize_notes", "integrity", "notes"]
DUPLICATE_COMMENT = "# duplicated cell (nbgrader marking removed from {})"

# Allowed top-level keys per nbformat output type (v4).  Anything else
# (e.g. matplotlib's leaked 'jetTransient' key) is stripped from outputs.
# Outputs never affect grading; code cells' source is never modified here.
ALLOWED_OUTPUT_KEYS = {
    "stream": {"name", "text", "output_type"},
    "display_data": {"data", "metadata", "output_type"},
    "execute_result": {"execution_count", "data", "metadata", "output_type"},
    "error": {"ename", "evalue", "traceback", "output_type"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def extract_canvas_id(filename):
    """Canvas ID = first all-digit token in the filename (after splitting on '_').

    Handles the various Canvas download name formats, e.g.
      user1_1001_12300_assignment4.ipynb      -> 1001
      1001_late_assignment4.ipynb             -> 1001
      username_1001_late_assignment4.ipynb    -> 1001
    Falls back to None if no all-digit token is found.
    """
    parts = filename.split("_")
    for part in parts:
        if part.isdigit():
            return part
    return None


def sanitize_notebook(nb):
    """Strip nbgrader metadata from duplicate grade/solution/locked cells.

    Returns (nb, list_of_changes) where each change is
    (old_grade_id, cell_index).
    """
    seen = set()
    changes = []
    for idx, cell in enumerate(nb.cells):
        meta = cell.metadata.get("nbgrader", {})
        if not (meta.get("grade") or meta.get("solution") or meta.get("locked")):
            continue
        gid = meta.get("grade_id")
        if not gid:
            continue
        if gid in seen:
            # duplicate -> drop the nbgrader marking (cell stays, becomes
            # a plain cell nbgrader ignores) and add a visible marker.
            if cell.cell_type == "code":
                cell.source = DUPLICATE_COMMENT.format(gid) + "\n" + cell.source
            else:
                cell.source = "<!-- duplicated cell (nbgrader marking removed from {}) -->\n\n".format(
                    gid) + cell.source
            del cell.metadata["nbgrader"]
            changes.append((gid, idx))
        else:
            seen.add(gid)
    return nb, changes


def sanitize_outputs(nb):
    """Strip non-standard top-level keys from cell outputs (outputs only).

    Returns (nb, list_of_changes) where each change is
    (cell_index, output_index, output_type, removed_key).
    Never touches cell source, nbgrader metadata, or output *data* contents.
    """
    changes = []
    for idx, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        outputs = cell.get("outputs", [])
        for oidx, output in enumerate(outputs):
            otype = output.get("output_type")
            allowed = ALLOWED_OUTPUT_KEYS.get(otype)
            if allowed is None:
                continue
            for key in list(output.keys()):
                if key not in allowed:
                    del output[key]
                    changes.append((idx, oidx, otype, key))
    return nb, changes


def process_notebook(src, dst, assignment, canvas_id, originalfilename):
    """Sanitize a single notebook and write it to dst.

    Returns a report row (dict) describing what happened.
    """
    row = {
        "canvas_id": canvas_id,
        "assignment": assignment,
        "originalfilename": originalfilename,
        "sanity": "ok",
        "sanitize_notes": "",
        "integrity": "",
        "notes": "",
    }
    try:
        nb = nbformat.read(src, as_version=4)
    except Exception as exc:  # unparseable / corrupt notebook
        row["sanity"] = "error"
        row["notes"] = "could not parse notebook: {}".format(exc)
        return row

    nb, changes = sanitize_notebook(nb)
    nb, out_changes = sanitize_outputs(nb)
    if changes:
        row["sanity"] = "sanitized"
        row["sanitize_notes"] = "; ".join(
            "duplicate grade_id {} stripped (cell {})".format(old, idx) for old, idx in changes)
    if out_changes:
        if not row["sanitize_notes"]:
            row["sanitize_notes"] = "; ".join(
                "output {}.{} ({}): stripped '{}'".format(ci, oi, ot, key)
                for ci, oi, ot, key in out_changes)
        else:
            row["sanitize_notes"] += "; " + "; ".join(
                "output {}.{} ({}): stripped '{}'".format(ci, oi, ot, key)
                for ci, oi, ot, key in out_changes)

    if changes or out_changes:
        # nbgrader writes notebooks; use nbformat to keep JSON structure valid
        try:
            nbformat.write(nb, dst)
        except Exception as exc:
            row["sanity"] = "error"
            row["notes"] = "failed to write sanitized notebook: {}".format(exc)
            return row
        logger.info("sanitized %s: %s", canvas_id, row["sanitize_notes"])
    else:
        # no changes: plain copy (fast, preserves exact student bytes)
        shutil.copyfile(src, dst)
    return row


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Copy downloaded Canvas submissions into the nbgrader "
                    "submitted/ layout, sanitizing duplicate cells.")
    parser.add_argument("assignment", help="name of the assignment, e.g. assignment1")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="log at DEBUG level (default: INFO)")
    args = parser.parse_args()
    assignment = args.assignment

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )
    # nbformat validates notebooks on read/write and reports schema violations
    # (e.g. a leaked matplotlib 'jetTransient' key) through the 'traitlets'
    # logger, which otherwise bubbles up to our root handler as stderr noise.
    # We already strip those keys in sanitize_outputs, so silence that channel.
    logging.getLogger("traitlets").setLevel(logging.CRITICAL)

    submissions_dir = os.path.join("submissions", assignment)
    if not os.path.isdir(submissions_dir):
        logger.error("cannot find folder %s", submissions_dir)
        raise SystemExit(1)

    files = sorted(glob.glob(os.path.join(submissions_dir, "*")))
    os.makedirs("submitted", exist_ok=True)

    report_rows = []
    for filepath in files:
        filename = os.path.basename(filepath)
        canvas_id = extract_canvas_id(filename)
        if canvas_id is None:
            # cannot determine student id -> report and skip
            report_rows.append({
                "canvas_id": "", "assignment": assignment,
                "originalfilename": filename, "sanity": "error",
                "sanitize_notes": "", "integrity": "",
                "notes": "could not extract canvas id from filename",
            })
            continue

        destination = os.path.join("submitted", canvas_id, assignment)
        os.makedirs(destination, exist_ok=True)
        # clean previous outputs for this student
        for old_file in glob.glob(os.path.join(destination, "*")):
            os.remove(old_file)

        if not filename.lower().endswith(".ipynb"):
            # non-notebook: don't copy, but flag for possible warning to student
            report_rows.append({
                "canvas_id": canvas_id, "assignment": assignment,
                "originalfilename": filename, "sanity": "missing",
                "sanitize_notes": "", "integrity": "",
                "notes": "non-notebook file, not copied to submitted/",
            })
            logger.warning("skipping non-notebook %s: %s", canvas_id, filename)
            continue

        dst = os.path.join(destination, assignment + ".ipynb")
        row = process_notebook(filepath, dst, assignment, canvas_id, filename)
        report_rows.append(row)

    # Write the audit report (overwrite previous run)
    report = pd.DataFrame(report_rows, columns=REPORT_COLUMNS)
    report.to_csv(REPORT_FILE, index=False)
    n_ok = (report["sanity"] == "ok").sum()
    n_san = (report["sanity"] == "sanitized").sum()
    n_err = (report["sanity"] == "error").sum()
    n_missing = (report["sanity"] == "missing").sum()
    logger.info(
        "%d files processed for '%s': %d ok, %d sanitized, %d error, %d missing/skipped",
        len(report_rows), assignment, n_ok, n_san, n_err, n_missing)
    logger.info("report written to %s", REPORT_FILE)


if __name__ == "__main__":
    main()
