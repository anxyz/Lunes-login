#!/usr/bin/env bash
# The upstream installer uses `curl -so` for GitHub release assets, which
# returns an empty 302 response unless redirects are followed.
set -euo pipefail

curl() {
  command curl --fail --location --connect-timeout 15 --max-time 120 --retry 2 "$@"
}
export -f curl

exec bash "$1"
