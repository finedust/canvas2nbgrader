from canvasapi import Canvas
import argparse
import glob
import tempfile
import os
import hashlib
import json
import pandas as pd

# globals
UPLOAD_LOG = "upload_log.csv"
UPLOAD_LOG_COLUMNS = ["canvas_id", "assignment_name", "file_upload_hash"]

# Canvas API access token lookup.  The token name is matched extension-agnostic
# (any of .txt/.key/.token/... or no extension), searched in this order:
#   1. --token FILE                    (explicit command-line location)
#   2. ./canvas-access-token*          (course dir, any extension)
#   3. ~/.secrets/canvas-access-token* (shared secrets dir, any extension)
def find_token_file(explicit=None):
    """Return the path of the Canvas API token, or raise SystemExit if not found."""
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        raise SystemExit("ERROR: token file not found: {}".format(explicit))

    home = os.path.expanduser("~")
    search_dirs = [".", os.path.join(home, ".secrets")]
    for base in search_dirs:
        hits = sorted(glob.glob(os.path.join(base, "canvas-access-token.*"))) + \
               sorted(glob.glob(os.path.join(base, "canvas-access-token")))
        for hit in hits:
            if os.path.isfile(hit):
                return hit

    raise SystemExit(
        "ERROR: could not find the Canvas API token. Provide it with "
        "--token FILE, ./canvas-access-token*, or ~/.secrets/canvas-access-token*.")

# functions
def open_upload_log():
    try:
        upload_history = pd.read_csv(UPLOAD_LOG)
    except FileNotFoundError:
        upload_history = pd.DataFrame(columns=UPLOAD_LOG_COLUMNS)
    return upload_history.set_index(UPLOAD_LOG_COLUMNS[0:2])

def parse_notebook_as_json(path):
    with open(path) as file:
        json_dict = json.load(file)

    for index, cell_dict in enumerate(json_dict["cells"]):
        # complex outputs can slow down hashing, and could be random
        if "outputs" in cell_dict.keys():
            json_dict["cells"][index].pop("outputs")
        # time of execution hampers the comparison
        if "execution" in cell_dict["metadata"].keys():
            json_dict["cells"][index]["metadata"].pop("execution")

    return json_dict

def sha256(string):
    return hashlib.sha256(string.encode("utf-8")).hexdigest()

# Main
def main():
    parser = argparse.ArgumentParser(
        description="Upload autograded nbgrader results to Canvas.")
    parser.add_argument("--token", default=None,
                        help="path to the Canvas API token file (overrides the "
                             "default search: ./canvas-access-token*, "
                             "~/.secrets/canvas-access-token*)")
    args = parser.parse_args()

    API_URL = "https://ubc.instructure.com"
    token_file = find_token_file(args.token)
    with open(token_file, "r") as f:
        API_KEY = f.read()
    canvas = Canvas(API_URL, API_KEY)

    canvas_course_id = input('Canvas course ID: ')
    canvas_course_id = int(canvas_course_id)
    canvas_assignment_id = input('Canvas assignment ID: ')
    canvas_assignment_id = int(canvas_assignment_id)
    assignment_name = input('Assignment name: ')

    course = canvas.get_course(canvas_course_id)
    assignment = course.get_assignment(canvas_assignment_id)
    upload_history = open_upload_log()

    with open('grades.csv') as f:
        lines = f.readlines()
        lines = [line for line in lines if line.split(',')[0] == assignment_name]

    for line in lines:
        items = line.split(',')
        canvas_id = int(items[3])
        try:
            submission = assignment.get_submission(canvas_id)
        except:
            print('Could not find assignment for {}'.format(canvas_id))
            continue
        source = glob.glob(os.path.join("autograded",str(canvas_id),assignment_name,assignment_name + ".ipynb"))
        if len(source) == 0:
            print('Could not find autograded notebook for {}'.format(canvas_id))
            continue
        else:
            source = source[0]
        score = float(items[7])

        try:
            previous_upload_hash = upload_history.loc[(canvas_id, assignment_name), UPLOAD_LOG_COLUMNS[2]]
        except KeyError:
            previous_upload_hash = 0
        source_hash = sha256(str(parse_notebook_as_json(source)))
        if (source_hash == previous_upload_hash):
            print("{}'s autograded notebook is (functionally) identical to the previously uploaded notebook, skipping.".format(canvas_id))
            continue
        upload_history.loc[(canvas_id, assignment_name), UPLOAD_LOG_COLUMNS[2]] = source_hash

        print("Uploading grade and feedback for {} ...".format(canvas_id))
        submission.edit(submission={'posted_grade': score})
        f = tempfile.NamedTemporaryFile('w+')
        f.name = '{}_autograded.ipynb'.format(assignment_name)
        with open(source,'r') as fsource:
            f.write(fsource.read())
        f.seek(0)
        submission.upload_comment(f)
        f.close()

        upload_history.to_csv(UPLOAD_LOG)

if __name__ == "__main__":
    main()
