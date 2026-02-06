# Execution Checklist

## Before Coding
- [ ] Read the project's CLAUDE.md (auto-loaded, but check TODO list)
- [ ] Identify which files will be touched
- [ ] Check if similar pattern exists in codebase — follow it
- [ ] If >3 files changing, use Plan Mode first

## During Coding
- [ ] Follow existing code style exactly (don't "improve" surrounding code)
- [ ] Don't add features beyond what was asked
- [ ] Update providers/routes if adding new screens
- [ ] Handle null cases in model fromMap/toMap
- [ ] Dispose controllers in StatefulWidget

## Before Committing
- [ ] Run `flutter analyze` — fix warnings
- [ ] Check for hardcoded strings that should be constants
- [ ] Check for duplicated code — extract if >3 lines repeated
- [ ] Verify imports are clean (no unused imports)
- [ ] Update CLAUDE.md TODO list if items completed or new issues found
- [ ] Use a subagent for code review on changes >50 lines

## Before Deploying
- [ ] Build succeeds: `flutter build apk --debug`
- [ ] No new analyzer warnings
- [ ] Test on device if UI changes

## After Session
- [ ] Update project CLAUDE.md if architecture changed
- [ ] Log new patterns to flutter-patterns.md if learned something
- [ ] Note any new issues in Known Issues section
