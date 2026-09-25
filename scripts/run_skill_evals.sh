#!/usr/bin/env bash
# Runs `claude plugin eval` against every skill under .claude/skills that has
# an evals/ directory, and writes each skill's JSON report to eval-results/.
#
# Requires `claude plugin eval` to be enabled for your account (it is
# early-access as of this writing). Until then this will just print the
# "early access" message once per skill and exit non-zero.
set -uo pipefail

cd "$(dirname "$0")/.."
mkdir -p eval-results

skills=(
  calendar-write-confirmation
  deadline-digest
  grounded-answering
  grounding-check
  note-chunking
  quiz-generation
  rubric-critique
  syllabus-extraction
  wrong-answer-analysis
)

overall_status=0

for skill in "${skills[@]}"; do
  dir=".claude/skills/$skill"
  if [ ! -d "$dir/evals" ]; then
    echo "skip: $skill has no evals/ directory"
    continue
  fi

  echo "=== $skill ==="
  claude plugin eval "$dir" --json "eval-results/$skill.json" "$@"
  status=$?
  if [ $status -ne 0 ]; then
    overall_status=1
  fi
  echo
done

exit $overall_status
