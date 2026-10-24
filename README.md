# منصة الأفكار — Ideas Platform

تطبيق لكتابة الأفكار وتنظيمها في أقسام وتصنيفات، ثم إرسالها إلى Claude ليحللها
(تحسينات، اقتراحات، نسبة الرواج مقارنة بمشاريع مشابهة، ما فاتك) ويرجع لك أسئلة
تجيب عنها بنعم/لا أو بإجابة أطول.

A personal, Arabic-first (RTL) ideas notebook. Installable as an app on phone and
desktop (PWA), works offline.

## Features (v1)

- Sections (editable), project type, goal, personal vs. for publishing, status, tags
- Autosave and per-idea version history with restore
- Search and filters
- Export for Claude / import Claude's analysis (see [docs/claude-format.md](docs/claude-format.md))
- Claude's analysis view: popularity meter, similar projects, improvements, missed points, questions with yes/no + long answers
- Manual backup file with a weekly reminder
- Sync between phone and computer through Supabase (email + password sign-in)
- Weekly backup to Google Drive (folder "Ideas Backup", newest 8 kept) with restore

## Cloud setup

Fill in `js/config.js`:

- `supabaseUrl`, `supabaseKey`: from Supabase Project Settings -> API. Run
  `supabase/schema.sql` once in the Supabase SQL editor.
- `googleClientId`: an OAuth "Web application" client from Google Cloud with the
  Drive API enabled and `https://mahmouddughim.github.io` as an authorized
  JavaScript origin.

These values are public by design; data is protected by sign-in and row level security.

## Roadmap

- Claude imports and writes analysis directly, without files

## Run locally

No build step. Serve the folder with any static server:

```sh
python3 -m http.server 8000
```

Then open http://localhost:8000. On a phone, open the hosted URL and choose
"Add to Home Screen" to install it.

## Structure

- `index.html`, `styles.css` — shell and styles
- `js/db.js` — IndexedDB storage on the device
- `js/model.js` — ideas, sections, version history
- `js/transfer.js` — export / import and merge rules
- `js/sync.js` — Supabase sync
- `js/drive.js` — Google Drive backups
- `js/app.js` — views and routing
- `sw.js`, `manifest.webmanifest` — offline support and install
