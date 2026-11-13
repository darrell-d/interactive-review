# interactive-review

An **interactive** Pennsieve app: a small file manager that pauses a workflow.
A person opens it in their browser, renames files and folders and drags them
into other folders, and saves. Nothing is moved: the step's output is a
**manifest** of what they did, as instructions for a later step to execute.

It is also the reference for a **web app session** (`sessionType: webapp`):
any web server in a container can be a human-in-the-loop step by following the
contract below. This one is a small Flask app.

(The repository is still named for its first version, which approved or
rejected files. That is `v0.1.0`.)

## How it fits the platform

```
data source or        interactive-review (this)        next step
previous step    ─▶   the workflow waits, the     ─▶   gets OUTPUT_DIR/manifest/
  files in             person rearranges them           manifest.json
  INPUT_DIR
```

1. The run reaches this step and starts the container on Fargate. The
   workflow waits.
2. The run page shows **Open App**. It opens the app in a new browser tab,
   through the platform's auth proxy.
3. The person clicks **Save and continue workflow**. The app writes
   `OUTPUT_DIR/manifest/manifest.json` and exits 0. The next step runs on it.

## The manifest

The manifest is a list of **instructions for another app to execute**: what
the person did in the page, in the order they did it.

```json
{
  "version": 1,
  "at": "2026-11-13T20:21:59+00:00",
  "notes": "tidied the raw scans",
  "operations": [
    { "op": "rename", "kind": "folder", "path": "raw", "name": "source" },
    { "op": "rename", "kind": "file", "path": "source/scan a.csv", "name": "scan_a.csv" },
    { "op": "create_folder", "path": "archive" },
    { "op": "move", "kind": "file", "path": "provenance.json", "to": "archive" }
  ],
  "files": [
    { "from": "raw/scan a.csv", "to": "source/scan_a.csv", "size": 23 },
    { "from": "provenance.json", "to": "archive/provenance.json", "size": 132 }
  ]
}
```

| Operation | Does |
|---|---|
| `create_folder` | makes the folder at `path` (its parent exists by then) |
| `rename` | gives the file or folder at `path` the new `name`, in the same folder |
| `move` | puts the file or folder at `path` into the folder `to` (`""` is the top), keeping its name |

How to execute it:

- **In order.** Each operation's `path` is where the thing is after the
  operations before it, not where it started. In the example the second
  rename says `source/scan a.csv` because the first one renamed `raw`.
- **A folder operation carries what's in it.** Renaming or moving a folder is
  one operation, however many files it holds.
- **`files` is the result to check against**: every input file, with the path
  it started at (`from`) and the path it should have once the operations are
  done (`to`).
- Operations are recorded as done, not minimised: a rename followed by another
  rename is two operations. Anything undone in the page is not in the list.

Paths are relative to the step's input folder, not Pennsieve package ids: the
input folder doesn't carry those, so the executing app has to match paths to
packages. To get a dataset's own folders into the app, choose a folder when
picking the run's files (it arrives with what's in it), or the placement that
keeps the files' paths in the dataset.

## The web app session contract

What the platform gives the container, and what it expects back. Nothing here
is specific to Flask or Python.

| | |
|---|---|
| `INPUT_DIR` | the step's input files, already downloaded |
| `OUTPUT_DIR` | what the next step gets; each output in `app.yml` is its own subfolder, `OUTPUT_DIR/<output>/` |
| each parameter in `app.yml` | an environment variable of the same name |
| listen on `127.0.0.1:8888` | the auth proxy runs next to the container, shares its network, and forwards to that port. Nothing else can reach the app |
| authentication | none in the app: the proxy checks the person's session token on every request, and only whoever started the run gets one |
| `POST /api/shutdown` | the proxy calls it when someone clicks **End Session** on the run page. Stop the server and exit |
| exit code `0` | the workflow continues with everything under `OUTPUT_DIR` |
| any other exit code | the step and the run fail |
| `SIGTERM` | the platform is stopping the task (a cancel, or teardown): exit, there is nothing to report |

The app never handles the workflow's task token. A sidecar the platform adds
holds it, waits for the container to exit, uploads `OUTPUT_DIR` and resumes
the workflow.

## How a session ends

| What happened | Exit | The workflow |
|---|---|---|
| **Save and continue workflow** in the app | 0 | continues with the manifest |
| **Stop workflow** in the app | 1 | fails at this step; the notes are in its log |
| **End Session** on the run page, before a save | 1 | fails: nothing was saved |
| No request for `IDLE_TIMEOUT_SECONDS` (default 1 hour) | 1 | fails: nothing was saved |
| The run is cancelled | 0 | already ending |

## Things to know before changing it

- **Write to `OUTPUT_DIR` only once the workflow should continue.** The
  platform uploads `OUTPUT_DIR` every few minutes while a session runs, and a
  session that fails after such a checkpoint still hands it to the next steps.
  That is right for a notebook (keep the work); for a step that decides whether
  the workflow goes on, it means a "stop" that wrote anything could be ignored.
- **The idle timeout is the app's job.** A notebook shuts itself down when
  idle; the platform has nothing of the kind for web apps, only a 12 hour cap,
  and the task is billed while it runs. `processor/main.py` watches for it.
- **No Pennsieve token.** An interactive step's container gets no session
  token, so the app can't call the Pennsieve API as the user.
- **Don't log requests.** The first request of a session carries the session
  token in its URL, and the step's log is readable by everyone with access to
  the run. Werkzeug's access log is turned off for that reason.
- **Files chosen by a saved view don't arrive.** A data source's files and
  folders picked for the run are downloaded; a view's are not, for an
  interactive step (a notebook fetches them on request).
- **`/files/` is limited on some compute nodes.** On basic and compliant nodes
  the platform's gateway refuses file responses over 50 MB on that path, so a
  large file can't be previewed there.

## `app.yml`

`runtime.interactive: true` and `runtime.sessionType: webapp` are what make
this a live step. The rest is what every app declares: its inputs, outputs and
parameters.

## Running it locally

```sh
make run     # the app behind the platform's auth proxy, on http://localhost:8080
make end     # in another terminal: what End Session on the run page does
make workflow  # a local stand-in for a workflow: two batch steps, this one, one more
make test    # unit tests (pip install -r processor/requirements.txt first)
```

`make run` mounts `sample-input/` as `INPUT_DIR` and writes to `data/output/`.
It exits with the app's exit code, so `0` means the workflow would continue.
`docker-compose.yml` runs the real `pennsieve/session-proxy` image next to the
app with auth turned off, sharing its network as it does in the ECS task.

`make workflow` (`local-workflow.sh`) runs the app inside a small pipeline:
two batch steps, then this step, which waits for you at http://localhost:8080,
then a batch step that is given the manifest you saved. Each step is a container
run the way the platform runs it; the platform itself is what's left out. It
needs `test-ports-processor` and `processor-template-python` cloned next to
this repository.

## Project structure

```
processor/
  main.py        # start the server, wait for the session to end, write the manifest
  app.py         # the Flask routes: the page, a file, the save, /api/shutdown
  session.py     # how the session ended, shared by the request threads and main
  layout.py      # list INPUT_DIR, replay the operations to check them, write manifest.json
  templates/     # the file manager page (its logic is in index.html) and the "ended" page
app.yml
Dockerfile
docker-compose.yml / dev.env / Makefile / local-workflow.sh   # local dev
sample-input/    # files to organize locally
tests/
```

## Publishing

As for any app: the Pennsieve GitHub App on the repository, then a release
(`v0.1.0` for the first). The compute node the workflow runs on must have
interactive sessions turned on.
