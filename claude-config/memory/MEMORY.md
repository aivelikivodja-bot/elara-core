# Project Memory

## Active Projects
- **HandyBill** (`/home/neboo/handybill`) - Flutter invoice/expense/mileage tracking app
- **PlanPulse** (`/home/neboo/planpulse`) - Flutter activity/time tracker (restored from Windows git)

## HandyBill Status
- Dark theme: DONE (commit c878ae8, 17 files)
- CLAUDE.md: DONE (full architecture map, design system, known issues, TODOs)
- Deploy script: `hb-deploy` (build + install on device)
- Still TODO: gradient summary cards, section header uppercase styling, further polish
- Last commit: `86a92ea` (expense detail, tax entry, invoice UI)

## PlanPulse Status
- CLAUDE.md: DONE (full architecture map, design system, known issues, TODOs)
- Deploy script: `pp-deploy` (build + install on device)
- Firebase stubs need cleanup (dead code: auth_service, firestore_sync, login_screen)
- 35 Dart files, 1 commit, no GitHub remote yet
- **Next:** flutter pub get + build + run, assess what needs work

## Capability System
- **flutter-patterns.md** - Persistent Flutter/Dart knowledge, package notes, gotchas
- **execution-checklist.md** - Pre/post coding verification steps
- **idea-framework.md** - Structured idea evaluation (5-axis scoring, /25)
- **Commands:** `/review` (code review), `/pitch` (idea evaluation), `/new-screen` (per project)
- **Agents:** `code-reviewer` (Flutter code review), `idea-evaluator` (product/feature scoring)

## User Preferences
- Prefers dark themes
- Wants polished, professional UI
- Testing on physical Android device via USB

## Deploy Commands
- `hb-deploy` — Build + install HandyBill on device
- `pp-deploy` — Build + install PlanPulse on device
