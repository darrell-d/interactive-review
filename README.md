# interactive-review

An **interactive** Pennsieve app: a step that pauses a workflow so a person can
look over the files from the previous step in their browser, approve or reject
each one, leave notes, and either continue the workflow or stop it.

It is also the reference for a **web app session** (`sessionType: webapp`):
any web server in a container can be a human-in-the-loop step by following the
contract below. This one is a small Flask app.

## How it fits the platform

```
previous step ─▶ interactive-review (this) ─▶ next step
   its outputs       the workflow waits,        gets OUTPUT_DIR/approved/
   in INPUT_DIR      the reviewer decides       (and review/review.json)
```

1. The run reaches this step and starts the container on Fargate. The
   workflow waits.
2. The run page shows **Open App**. It opens the app in a new browser tab,
   through the platform's auth proxy.
3. The reviewer clicks **Continue workflow**. The app copies the approved
   files to `OUTPUT_DIR/approved/`, writes `OUTPUT_DIR/review/review.json` and
   exits 0. The next step runs on those files.

## The web app session contract

What the platform gives the container, and what it expects back. Nothing here
is specific to Flask or Python.

| | |
|---|---|
| `INPUT_DIR` | the previous step's files, already downloaded |
| `OUTPUT_DIR` | what the next step gets; each output in `app.yml` is its own subfolder, `OUTPUT_DIR/<output>/` |
| each parameter in `app.yml` | an environment variable of the same name |
| listen on `127.0.0.1:8888` | the auth proxy runs next to the container, shares its network, and forwards to that port. Nothing else can reach the app |
| authentication | none in the app: the proxy checks the reviewer's session token on every request, and only the person who started the run gets one |
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
| **Continue workflow** in the app | 0 | continues with the approved files |
| **Stop workflow** in the app | 1 | fails at this step; the notes are in its log |
| **End Session** on the run page, before a review | 1 | fails: nothing was approved |
| No request for `IDLE_TIMEOUT_SECONDS` (default 1 hour) | 1 | fails: nothing was approved |
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
- **Inputs come from a previous step.** Files a data source selects by view
  are not downloaded for an interactive step (a notebook fetches them on
  request), so put this step after a processor, not directly after such a
  data source.
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
make test    # unit tests (pip install -r processor/requirements.txt first)
```

`make run` mounts `sample-input/` as `INPUT_DIR` and writes to `data/output/`.
It exits with the app's exit code, so `0` means the workflow would continue.
`docker-compose.yml` runs the real `pennsieve/session-proxy` image next to the
app with auth turned off, sharing its network as it does in the ECS task.

## Project structure

```
processor/
  main.py        # start the server, wait for the session to end, write the outputs
  app.py         # the Flask routes: the page, a file, the review, /api/shutdown
  session.py     # how the session ended, shared by the request threads and main
  review.py      # list INPUT_DIR, write review.json, copy the approved files
  templates/     # the page and the "session ended" page
app.yml
Dockerfile
docker-compose.yml / dev.env / Makefile   # local dev
sample-input/    # files to review locally
tests/
```

## Publishing

As for any app: the Pennsieve GitHub App on the repository, then a release
(`v0.1.0` for the first). The compute node the workflow runs on must have
interactive sessions turned on.
