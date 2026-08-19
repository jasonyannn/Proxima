#!/bin/sh
msg="$(cat)"
# remove co-authored-by Copilot lines
msg="$(printf "%s" "$msg" | sed -E '/Co-authored-by: .*Copilot/d')"
# split subject and rest
first="$(printf "%s" "$msg" | sed -n '1p')"
rest="$(printf "%s" "$msg" | sed -n '2,$p')"
# if subject already has a Type suffix, keep it but ensure single Jason prefix
if echo "$first" | grep -qE ' -Feature$| -Fix$| -Docs$| -Chore$| -Test$| -Other$'; then
  # collapse multiple leading 'Jason - '
  subj="$(echo "$first" | sed -E 's/^(Jason - )+//')"
  # put single prefix
  subject="Jason - $subj"
else
  subj="$(echo "$first" | sed -E 's/^(Jason - )+//')"
  lc="$(echo "$subj" | tr '[:upper:]' '[:lower:]')"
  if echo "$lc" | grep -qE 'feat|feature'; then type='Feature'
  elif echo "$lc" | grep -qE 'fix|bug'; then type='Fix'
  elif echo "$lc" | grep -qE 'doc|readme'; then type='Docs'
  elif echo "$lc" | grep -qE 'chore'; then type='Chore'
  elif echo "$lc" | grep -qE 'test'; then type='Test'
  else type='Other'
  fi
  subject="Jason - $subj -$type"
fi
# output cleaned message
printf "%s\n%s" "$subject" "$rest"