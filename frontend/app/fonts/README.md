# Fonts

Inter and Source Serif 4, Latin subset, variable weight (woff2, from Fontsource 5.3). Both are under
the SIL Open Font License 1.1 (`*-OFL.txt`). They are committed so the build never fetches fonts:
`next/font/local` in `app/layout.tsx` self-hosts them, as `next/font/google` did.
