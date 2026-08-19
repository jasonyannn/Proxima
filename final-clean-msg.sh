#!/bin/sh
# Read full commit message
msg="$(cat)"
# Remove any Co-authored-by lines that mention Copilot (case-insensitive)
msg="$(printf "%s" "$msg" | sed -E '/Co-authored-by:.*[Cc]opilot/d')"
# Get first line (subject) and the rest (body)
first="$(printf "%s" "$msg" | sed -n '1p')"
rest="$(printf "%s" "$msg" | sed -n '2,$p')"
# Remove duplicate leading 'Jason - Jason -' or multiple 'Jason - ' prefixes
first_clean="$(echo "$first" | sed -E 's/^Jason -[[:space:]]*Jason -[[:space:]]*/Jason - /; s/^(Jason -[[:space:]]*)+/Jason - /')"
# If subject already doesn't start with Jason - add it
if ! echo "$first_clean" | grep -qE '^Jason -'; then
  first_clean="Jason - $first_clean"
fi
# Trim trailing spaces
first_clean="$(echo "$first_clean" | sed -E 's/[[:space:]]+$//')"
# Reassemble
if [ -z "$rest" ]; then
  printf "%s" "$first_clean"
else
  printf "%s\n%s" "$first_clean" "$rest"
fi