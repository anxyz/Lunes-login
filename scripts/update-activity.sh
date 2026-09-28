#!/usr/bin/env bash
set -euo pipefail

git config user.name "$GITHUB_REPOSITORY_OWNER"
git config user.email "${ACTIVITY_OWNER_ID}+${GITHUB_REPOSITORY_OWNER}@users.noreply.github.com"
for attempt in 1 2 3; do
  git fetch origin "$ACTIVITY_BRANCH"
  git checkout --detach FETCH_HEAD
  date -u +'%Y-%m-%dT%H:%M:%SZ' > .last-active
  git add -- .last-active
  if git diff --cached --quiet; then
    exit 0
  fi
  git commit --allow-empty-message -m ''
  if git push origin "HEAD:refs/heads/$ACTIVITY_BRANCH"; then
    exit 0
  fi
  sleep 2
done
exit 1
