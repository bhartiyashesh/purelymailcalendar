# Purelymail Calendar

> Unofficial calendar and meeting-invite web app for Purelymail mailboxes — month/week/day views, real iTIP scheduling, and automatic RSVP tracking. Live at **[purelymailcalendar.com](https://purelymailcalendar.com)**.

![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688) ![React](https://img.shields.io/badge/frontend-React%20%2B%20Vite-61dafb) ![Postgres](https://img.shields.io/badge/db-Postgres-336791)

Purelymail is a great email host, but its calendar story is bare-bones — you can store events over CalDAV, but it doesn't ship an iMIP/iTIP scheduler, so sending real meeting invites and tracking RSVPs is missing. **Purelymail Calendar** fills that gap.

Sign in with a magic link, connect your Purelymail mailbox once, and you get:

- Month, week, and day views with click-to-create, drag-to-move, and a live "now" line
- Real iTIP `REQUEST` / `CANCEL` invites delivered from your own address, with the MIME structure that Apple Mail, Gmail, and Outlook all render correctly
- An IMAP poller that pulls attendee replies, matches them to events, and updates each `PARTSTAT` automatically
- Magic-link authentication, encrypted-at-rest credential storage (Fernet), and per-user data isolation — your calendar lives in your Purelymail mailbox, not in this app's database

**Made by [Yashesh Bharti](https://yasheshbharti.com). Not affiliated with, endorsed by, or sponsored by Purelymail.**

## Architecture

```
                 SMTP (REQUEST/CANCEL)            IMAP (REPLY)
                 ────────────────►                ◄────────────
   Purelymail Calendar ──────────► attendees ──────► Purelymail Calendar
       │                                                            │
       └─────► CalDAV PUT (canonical event store) ◄─────────────────┘
               https://purelymail.com/webdav/<account>/caldav/
```

Servers used (per signed-in user, discovered automatically from the mailbox):

| | host | port |
|---|---|---|
| CalDAV | `purelymail.com` | 443 (HTTPS) |
| SMTP | `smtp.purelymail.com` | 465 (SSL) or 587 (STARTTLS) |
| IMAP | `imap.purelymail.com` | 993 (SSL) |
| ManageSieve | `mailserver.purelymail.com` | 4190 (STARTTLS) |

## Project layout

```
calinvite/                 (upstream CLI package — see below)
calinvite_web/             FastAPI web app (multi-user, magic-link auth)
  app.py                   HTTP routes
  schemas.py               Pydantic request/response models
  services.py              CalDAV / SMTP / IMAP plumbing
  db.py models.py          SQLAlchemy: User / Mailbox / Session / MagicToken
  auth.py                  Magic-link auth + session cookie + current_user dep
  mailbox.py               POST /api/me/mailbox (auto-discovers account ID)
  crypto.py                Fernet helpers
  mailer_transactional.py  Magic-link sender (Resend → SMTP fallback)
web/                       React + Vite + TypeScript + Tailwind frontend
sieve/calinvite.sieve      Sieve script that routes METHOD:REPLY to an RSVPs mailbox
```

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web]"
cp .env.example .env
# fill in RESEND_API_KEY (or MAGIC_LINK_SMTP_* fallback) and any other vars
./scripts/dev.sh
```

That brings up:
- FastAPI on `http://127.0.0.1:8000`
- Vite on `http://127.0.0.1:5173` (proxies `/api/*` to uvicorn)

Open `http://127.0.0.1:5173`, sign in with magic link, paste your Purelymail mailbox password when prompted. The app auto-discovers your Purelymail account ID via PROPFIND on `/webdav/`.

## Environment variables

```env
# Database (SQLite by default for local; Postgres on Railway via DATABASE_URL)
DATABASE_URL=

# Magic-link delivery (preferred: Resend)
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=signin@yourdomain.com
RESEND_FROM_NAME=Purelymail Calendar

# SMTP fallback (used if RESEND_API_KEY is unset)
MAGIC_LINK_SMTP_HOST=smtp.purelymail.com
MAGIC_LINK_SMTP_PORT=465
MAGIC_LINK_SMTP_USER=you@yourdomain.com
MAGIC_LINK_SMTP_PASS=...

# Used to build the magic-link href
BASE_URL=https://purelymailcalendar.com

# Encryption key for mailbox passwords at rest
FERNET_KEY=

# True in production (HTTPS)
COOKIE_SECURE=true
```

## Underlying CLI

The web app sits on top of an internal Python package (`calinvite/`) that provides the iTIP plumbing. The CLI is still callable directly if you want to script things or run an external RSVP cron:

```bash
calinvite create \
  --account YASHESH \
  --calendar Personal \
  --summary "Quick sync" \
  --start 2026-05-15T14:00 --duration 60 \
  --tz America/Chicago \
  --attendee "advisor@example.com:Jane Doe"

calinvite rsvps --account YASHESH --mailbox RSVPs
```

The CLI uses `.env`-based single-user config (see `.env.example`); the web app uses the per-user database instead. They share the same iTIP and CalDAV layer.

### Sieve (optional but recommended for the RSVP poller)

By default the RSVP poller scans INBOX. With the bundled Sieve script installed, METHOD:REPLY messages get pre-filed into a dedicated `RSVPs` folder server-side, so the poller scans a small focused mailbox and your INBOX stays clean.

```bash
calinvite sieve install --account YASHESH   # uploads + activates the bundled script
calinvite rsvps --account YASHESH --mailbox RSVPs
```

The bundled script (`sieve/calinvite.sieve`):

```sieve
require ["fileinto", "mailbox", "body"];

if body :contains "METHOD:REPLY" {
    fileinto :create "RSVPs";
}
```

`body :contains` is the right test because `method=REPLY` lives inside the calendar MIME part's Content-Type — a header test would miss it. `:create` makes Purelymail auto-create the `RSVPs` mailbox the first time a reply arrives.

## Deploying

Hosted on Railway. The `Dockerfile` does a multi-stage build (Node builds the frontend, Python serves both the API and the static bundle). `railway.json` declares the build + healthcheck.

```bash
railway up --service web
```

Health: `GET /api/health` returns `200 {"ok":true}`.

## iTIP correctness notes

- `ORGANIZER` and `ATTENDEE` use `mailto:` URIs.
- The organizer is also added as an `ATTENDEE` with `PARTSTAT=ACCEPTED` and `RSVP=FALSE` — this makes Purelymail reliably show the event on the organizer's own calendar listing, and the organizer is filtered out of the SMTP recipient list so they don't get an invite to their own event.
- New events use `SEQUENCE:0`; updates/cancels bump it. Replies don't bump `SEQUENCE`.
- Updates and cancels reuse the original `UID`.
- The MIME body is `multipart/mixed[ multipart/alternative[ text/plain, text/calendar; method=REQUEST ], application/ics attachment ]`. Apple Mail keys off the inline `text/calendar` part; Gmail keys off either; Outlook on Windows is happiest with the attachment too — that layout covers all three.
- Stored CalDAV resources strip `METHOD` (RFC 4791 §4.1) — Purelymail rejects PUTs with `METHOD` even though the same blob is fine to send via SMTP.
- Time zones are emitted with a minimal `VTIMEZONE` referencing the IANA TZID. Clients resolve it against their local zoneinfo.
- The IMAP processor matches by `UID` and the responder's `mailto:` address; it won't write changes if `PARTSTAT` already matches.

## License

MIT. Made by [Yashesh Bharti](https://yasheshbharti.com).
