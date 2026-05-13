# Security policy

## Reporting a vulnerability

If you find a security issue in Purelymail Calendar, please report it
privately first. Two channels:

1. Email **bhartiyashesh@gmail.com** with a description and reproduction steps.
2. Or file a private security advisory on GitHub:
   https://github.com/bhartiyashesh/purelymailcalendar/security/advisories/new

Please **do not** open a public issue with exploit details. I will respond
within 72 hours and aim to ship a fix within 7 days for credential-handling
or auth bugs, longer for low-severity issues. Coordinated disclosure is
appreciated; credit will be given in the release notes.

## Scope

- The hosted deployment at **https://purelymailcalendar.com**.
- The source code in this repository.
- The published container image at `ghcr.io/bhartiyashesh/purelymailcalendar`.

## Out of scope

- Vulnerabilities in third-party hosts the app depends on (Purelymail,
  Railway, Resend, GitHub Container Registry). Report those to their
  respective vendors.
- Social-engineering, physical attacks, or denial-of-service against the
  hosted deployment.

## What gets stored, and how

- User mailbox passwords are encrypted at rest with Fernet (AES-128 +
  HMAC-SHA-256) using a server-only key (`FERNET_KEY` env var). Decryption
  happens only at request time, exclusively to authenticate calls to
  `purelymail.com`, `smtp.purelymail.com`, and `imap.purelymail.com`.
- Mailbox passwords are never transmitted to any third party.
- Magic-link tokens are stored as SHA-256 hashes and expire after 15 minutes.
- Session cookies are HttpOnly, Secure, SameSite=Lax, and signed with
  `SESSION_SECRET`.

Users can disconnect their mailbox at any time from the signed-in user menu;
that hard-deletes the encrypted row.

## Verifying the running build

The chain of evidence linking the public repository to the live deployment
is documented in the README under "Verifying what's running". Short version:

- Public commit on GitHub
- Public CI build log on the Actions tab
- Public OCI image at `ghcr.io/bhartiyashesh/purelymailcalendar`
- Live SHA returned by `GET /api/version` on the running site

If you'd rather not trust the hosted deployment at all, the repository
ships a `docker-compose.yml` that lets you self-host the same image in
one command.
