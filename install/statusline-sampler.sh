#!/usr/bin/env bash
# A Claude Code status line that also feeds the quota dashboard.
#
# The dashboard draws from two files that Claude Code does not write by itself:
# ~/.claude/usage-now.json (the latest payload) and ~/.claude/usage-history.jsonl
# (a sampled log, which is where the curves come from). Something has to record
# them, and the status line is the only hook that fires often enough.
#
# Point Claude Code at this script -- in ~/.claude/settings.json:
#
#     "statusLine": {"type": "command",
#                    "command": "~/quota-dash/install/statusline-sampler.sh"}
#
# If you already have a status line of your own, keep it and copy the block
# between the RECORD markers to the top of it instead; everything after the
# markers here is just an ordinary status line you can throw away.
#
# Needs jq. This runs on every status line refresh, so nothing in it may break
# or slow down the prompt: every step is allowed to fail silently.

input=$(cat)

# ---8<--- RECORD: this is the part the quota dashboard needs ---8<---
# The whole payload, written atomically so a reader never sees half a file.
printf '%s' "$input" > ~/.claude/usage-now.json.tmp 2>/dev/null &&
  mv -f ~/.claude/usage-now.json.tmp ~/.claude/usage-now.json 2>/dev/null || true

# The rate limits, appended to a history log. Throttled to one line per
# SAMPLE_SECS by the log's own mtime, because the status line refreshes far
# more often than the quotas move.
HIST=~/.claude/usage-history.jsonl
SAMPLE_SECS=30
if [ -z "$(find "$HIST" -newermt "-$SAMPLE_SECS seconds" 2>/dev/null)" ]; then
  echo "$input" | jq -c --argjson now "$(date +%s)" '{
    ts: $now,
    five: .rate_limits.five_hour.used_percentage,
    five_reset: .rate_limits.five_hour.resets_at,
    week: .rate_limits.seven_day.used_percentage,
    week_reset: .rate_limits.seven_day.resets_at,
    ctx: .context_window.used_percentage,
    cost: .cost.total_cost_usd,
    model: .model.id,
    session: .session_id
  } | select(.five != null or .week != null)' >> "$HIST" 2>/dev/null || true
fi
# ---8<--- end RECORD ---8<---

ctx=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
five=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
five_reset=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
week=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')

parts=()

[ -n "$ctx" ] && parts+=("Ctx: $(printf '%.0f' "$ctx")%")
if [ -n "$five" ]; then
  five_label="5h: $(printf '%.0f' "$five")%"
  [ -n "$five_reset" ] && five_label+=" (reset $(date -d "@$five_reset" '+%H:%M'))"
  parts+=("$five_label")
fi
[ -n "$week" ] && parts+=("7d: $(printf '%.0f' "$week")%")

( IFS=' | '; echo "${parts[*]}" )
