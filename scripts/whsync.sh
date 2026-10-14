# whsync: copy writing sessions from mytime.db into writing-habit.db.
#
# Source this file from ~/.zshrc or ~/.bashrc:
#     source /Users/blaine/6112MooersLabGitHubLabRepos/writing-habit/scripts/whsync.sh
# Then run from any directory:
#     whsync                      # every new or edited row since the first planned week
#     whsync --dry-run            # report only, write nothing
#     whsync --since 2026-10-05   # limit the days copied
#     whsync --scope all          # also keep projects missing from the legend
#
# The paths can be overridden with environment variables.
: "${WH_DB:=$HOME/org/writing-habit.db}"
: "${WH_MYTIME:=$HOME/6003TimeTracking/cb/mytime.db}"

whsync() {
    if command -v writing-habit >/dev/null 2>&1; then
        writing-habit track sync "$WH_MYTIME" --db "$WH_DB" "$@"
    else
        python3 -m writing_habit.cli track sync "$WH_MYTIME" --db "$WH_DB" "$@"
    fi
}
