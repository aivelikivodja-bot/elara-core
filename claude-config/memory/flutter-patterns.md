# Flutter Patterns & Lessons

## Architecture Patterns (Our Projects)

### State Management
- **Riverpod** for all state. StateNotifier for CRUD, StreamProvider for Firestore, FutureProvider for one-shot loads.
- Provider composition: base providers (Firebase instances) → service providers → data providers → UI providers
- Keep providers close to features (e.g., `dashboard/providers.dart`) except shared ones in `core/providers.dart`

### Navigation
- **GoRouter** with redirect guards for auth/onboarding
- Route constants in a `RoutePaths` class — never hardcode strings in screens
- Pass IDs via path params, complex data via `extra`

### File Structure
```
lib/
├── core/          # Theme, router, providers, constants
├── models/        # Data classes with toMap/fromMap/copyWith
├── services/      # External integrations (Firebase, storage, APIs)
├── providers/     # Riverpod state (or per-feature)
└── features/
    └── feature_name/
        ├── screens/    # Full-page widgets
        └── widgets/    # Reusable components
```

### Screen Template Pattern
- ConsumerStatefulWidget for forms (needs controllers + dispose)
- ConsumerWidget for display-only screens
- Always dispose TextEditingControllers
- Load data in `initState` or via provider, never in `build`

## Common Gotchas

### Flutter
- `.withOpacity()` is deprecated in Flutter 3.22+ → use `.withValues(alpha: X)`
- `copyWith()` on models must handle nullable fields explicitly (use `clearX` bool params)
- Date parsing: always handle Timestamp, String, and null cases in `fromMap()`
- `DateTime.now()` as default in fromMap masks data corruption — log warnings instead

### Firebase (HandyBill)
- Subcollection path: `users/{uid}/{collection}/{docId}`
- Invoice number generation needs atomic increment (current implementation is racy)
- Receipt storage path: `users/{uid}/receipts/{docId}.jpg`
- Always check `currentUser` is non-null before Firestore ops

### SharedPreferences (PlanPulse)
- Must call `StorageService.initialize()` before any read/write
- No schema versioning — model changes can break deserialization silently
- JSON stored as strings — keep models backward-compatible

## Performance
- Avoid expensive calculations in providers that rebuild on every frame (streak calculations)
- Use `.family` providers for per-item computed values
- Firestore queries: always paginate for collections that grow (invoices, expenses)

## UI Patterns
- Dark theme only (both projects)
- Card radius: 16px (HandyBill), 18px (PlanPulse)
- Borderless filled inputs
- Status chips with semantic colors (success/warning/error/info)
- Category icons in colored CircleAvatars
- Bottom nav: 4 tabs max

## Packages We Use
| Package | Version | Notes |
|---------|---------|-------|
| flutter_riverpod | 2.4-3.1 | State management |
| go_router | 13-17 | Navigation |
| fl_chart | 0.66-1.1 | Bar + pie charts |
| pdf + printing | 3.11 | Invoice PDF generation |
| geolocator | 12-14 | GPS tracking |
| image_picker | 1.1 | Receipt camera/gallery |
| share_plus | 7-12 | System share dialog |
| intl | 0.19-0.20 | Date formatting |
| google_fonts | 6.2 | Inter font (PlanPulse) |

## Mistakes to Avoid
- Don't add features without updating CLAUDE.md TODO list
- Don't leave dead code (Firebase stubs in PlanPulse)
- Don't hardcode IRS rates or tax data without versioning
- Don't duplicate classes across files (e.g., _LineItemState in HandyBill)
- Don't store both URL and storage path for same asset (redundant)
- Always recalculate computed fields (totals) in copyWith, don't trust stored values
