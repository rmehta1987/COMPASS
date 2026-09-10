#!/usr/bin/env bash
# The site loop's gate. Green or `git reset --hard HEAD`.
#   1 no_fabrication  every number on the page traces to an artifact
#   2 no_instrument   no instrument wording or variable key under site/
#   3 links           no dead internal link, anchor or fetch target
#   4 parse           HTML balanced, every script passes node --check
#   5 offline         zero external requests
#   6 tracked         every loaded artifact is git-tracked and not ignored
#   7 render_endpoint  the live branch: enumerate, posed launch, metrics structure
#   8 render_race      a stage change mid-run is not overridden when it lands
# Steps 7 and 8 drive the endpoint branch with a STUBBED route, so they need no
# server and no withheld payload. They sat outside this gate on the reasoning
# that they "assert endpoint behaviour", which was never the same thing as
# needing one -- and while they sat outside it, a rail-vocabulary change left
# three of their assertions stale and one vacuous with the gate green
# throughout.
# Step 2 needs the withheld dictionary; on the training machine it sits at the
# root of the operator's clone. Exits 2 (red) when it cannot be found.
set -u
cd "$(dirname "$0")"
export COMPASS_DICTIONARY="${COMPASS_DICTIONARY:-/home/mehta5/COMPASS/dictionary.json}"
export PYTHONDONTWRITEBYTECODE=1
echo "site-check @ $(git rev-parse --short HEAD) $(git status --porcelain | wc -l) dirty path(s)"
red=0
for step in no_fabrication no_instrument links parse offline tracked; do
  if ! python3 "site/tools/$step.py"; then red=1; fi
done
for step in render_endpoint render_race; do
  if ! node "site/tools/$step.js" site/; then red=1; fi
done
if [ "$red" -ne 0 ]; then echo "RED"; exit 1; fi
echo "GREEN"
