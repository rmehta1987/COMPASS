#!/usr/bin/env bash
# The site loop's gate. Green or `git reset --hard HEAD`.
#   1 no_fabrication  every number on the page traces to an artefact
#   2 no_instrument   no instrument wording or variable key under site/
#   3 links           no dead internal link, anchor or fetch target
#   4 parse           HTML balanced, every script passes node --check
#   5 offline         zero external requests
#   6 tracked         every loaded artefact is git-tracked and not ignored
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
if [ "$red" -ne 0 ]; then echo "RED"; exit 1; fi
echo "GREEN"
