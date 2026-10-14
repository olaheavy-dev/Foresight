
## Import / onboarding (`/start`), built 14 Oct 2026

Captured by `e2e/import.spec.ts` with `SCREENSHOTS=1` (real local stack): `review-import-{files-empty,files-done,check-balance-needed,check-done}-{desktop,mobile,desktop-dark}.png`. The journey passes on desktop, mobile and dark with no serious axe issues: P1's Monzo CSV is imported (1,126 rows, format Monzo, "No balance column"), then "Check what we found" asks for today's balance, shows income and the eight largest regular payments with "Show 7 more", and leads to Home with the declared balance. It follows the auth-card layout used on Landing, with hairline panels, tinted icon chips and badges in green for imported, amber for needs-an-answer or balance-needed, and red for not imported.
