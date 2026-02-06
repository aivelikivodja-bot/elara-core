Review recent code changes for bugs, quality issues, and pattern violations.

1. Check git diff for staged and unstaged changes
2. For each changed file, verify it follows existing patterns in the codebase
3. Check the execution checklist at ~/.claude/projects/-home-neboo/memory/execution-checklist.md
4. Use the code-reviewer subagent if changes are >50 lines
5. Report findings as: CRITICAL / WARNING / SUGGESTION
6. If clean, confirm "Ready to commit" with a summary of what changed
