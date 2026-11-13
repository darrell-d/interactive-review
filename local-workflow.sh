#!/bin/sh
# A local stand-in for a Pennsieve workflow with this app in it:
#
#   step A  test-ports-processor       a batch step, over its sample files
#   step B  test-ports-processor       a batch step, over step A's copies
#   files   interactive-review (this)  the workflow waits here for you
#   step D  processor-template-python  a batch step, over the manifest you saved
#
# Each step is a container run the way the platform runs it: the previous
# step's output folder as INPUT_DIR, its own OUTPUT_DIR, and its exit code
# deciding whether the next step runs. What this leaves out is the platform
# itself (the App Store, Step Functions, ECS, S3 between steps).
#
# The batch apps are built from their repositories next to this one;
# override with STEP_APP and NEXT_APP.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
STEP_APP=${STEP_APP:-$HERE/../test-ports-processor}
NEXT_APP=${NEXT_APP:-$HERE/../processor-template-python}
WORK=$HERE/data/workflow

for app in "$STEP_APP" "$NEXT_APP"; do
  [ -f "$app/Dockerfile" ] || { echo "no app at $app (clone it, or set STEP_APP / NEXT_APP)"; exit 2; }
done

rm -rf "$WORK"
mkdir -p "$WORK/a" "$WORK/b" "$WORK/files" "$WORK/d"

# batch NAME IMAGE INPUT OUTPUT: one batch step.
batch() {
  echo
  echo "== $1: running"
  docker run --rm -e INPUT_DIR=/data/input -e OUTPUT_DIR=/data/output \
    -v "$3:/data/input:ro" -v "$4:/data/output" "$2" >"$WORK/$1.log" 2>&1 \
    || { echo "== $1: FAILED (see $WORK/$1.log); the workflow stops"; exit 1; }
  echo "== $1: done. Its outputs:"
  (cd "$4" && find . -type f | sort | sed 's|^\./|     |')
}

echo "Building the steps' images..."
docker build -q -t local-workflow-step "$STEP_APP" >/dev/null
docker build -q -t local-workflow-next "$NEXT_APP" >/dev/null
(cd "$HERE" && docker compose down --remove-orphans >/dev/null 2>&1; docker compose build -q)

batch "step-a" local-workflow-step "$STEP_APP/sample-input" "$WORK/a"
batch "step-b" local-workflow-step "$WORK/a/copies" "$WORK/b"

echo
echo "== files: the workflow is PAUSED. Open http://localhost:8080"
if (cd "$HERE" && SESSION_INPUT="$WORK/b" SESSION_OUTPUT="$WORK/files" \
      docker compose up --exit-code-from app >"$WORK/files.log" 2>&1); then
  echo "== files: you saved. Its outputs:"
  (cd "$WORK/files" && find . -type f | sort | sed 's|^\./|     |')
else
  echo "== files: ended without a save (see $WORK/files.log); the workflow stops"
  exit 1
fi

batch "step-d" local-workflow-next "$WORK/files/manifest" "$WORK/d"

echo
echo "The workflow finished. Step D was given the manifest, with these changes:"
python3 -c "import json,sys; [print('    ', c['from'], '->', c['to']) for c in json.load(open(sys.argv[1]))['changes']] or print('     (none)')" "$WORK/files/manifest/manifest.json"
