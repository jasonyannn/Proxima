#!/bin/sh
msg="$(cat)"
first="$(printf "%s\n" "$msg" | sed -n '1p')"
body="$(printf "%s\n" "$msg" | sed -n '2,$p')"
lc=$(echo "$first" | tr '[:upper:]' '[:lower:]')
if echo "$lc" | grep -qE 'feat|feature'; then type="Feature"
elif echo "$lc" | grep -qE 'fix|bug'; then type="Fix"
elif echo "$lc" | grep -qE 'doc|readme'; then type="Docs"
elif echo "$lc" | grep -qE 'chore'; then type="Chore"
elif echo "$lc" | grep -qE 'test'; then type="Test"
else type="Other"
fi
# remove common prefixes
desc=$(echo "$first" | sed -E 's/^[[:space:]]*(feat|feature|fix|chore|docs|doc|test|refactor)[: -]*//I' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
if [ -z "$desc" ]; then desc="$first"; fi
printf "Jason - %s -%s\n\n%s" "$desc" "$type" "$body"