#!/usr/bin/env bash
# Wait for the "Claude Code Review" check run that the Claude GitHub App posts on the pull request
# head, and fail when it reports an Important finding. The review writes its counts on the last
# line of the check run text:
#   <!-- bughunter-severity: {"nit":1,"normal":2,"pre_existing":0} -->
# "normal" is the number of Important findings.
set -euo pipefail

check_name="Claude Code Review"
deadline=$((SECONDS + ${REVIEW_GATE_TIMEOUT_S:-2400}))

while true; do
  run=$(gh api "repos/${REPOSITORY}/commits/${HEAD_SHA}/check-runs" \
    -f check_name="${check_name}" -X GET \
    --jq '[.check_runs[] | select(.status == "completed" and .app.slug == "claude")] | sort_by(.completed_at) | last // empty')
  if [[ -n "${run}" ]]; then
    break
  fi
  if (( SECONDS > deadline )); then
    echo "::error::No completed '${check_name}' check on ${HEAD_SHA}. Ask for a review with an '@claude review' comment."
    exit 1
  fi
  echo "Waiting for ${check_name} on ${HEAD_SHA:0:7} ..."
  sleep 30
done

title=$(jq -r '.output.title // ""' <<<"${run}")
conclusion=$(jq -r '.conclusion' <<<"${run}")
echo "Claude Code Review: ${conclusion} - ${title}"

if [[ "${title}" == *"no new changes" ]]; then
  echo "No new changes since the last review."
  exit 0
fi
if [[ "${title}" == "Code review not repeated"* ]]; then
  echo "::error::Earlier findings are still open. Fix them and resolve the conversations."
  exit 1
fi

severity=$(jq -r '.output.text // ""' <<<"${run}" | grep -o 'bughunter-severity: {[^}]*}' | tail -1 | sed 's/^bughunter-severity: //' || true)
if [[ -z "${severity}" ]]; then
  echo "::error::The review has no severity line (title: ${title}). Ask for a new review with '@claude review'."
  exit 1
fi

important=$(jq -r '.normal // 0' <<<"${severity}")
echo "Findings: ${severity}"
if (( important > 0 )); then
  echo "::error::Claude Code Review found ${important} Important issue(s). Fix them before merging."
  exit 1
fi
echo "No Important findings."
