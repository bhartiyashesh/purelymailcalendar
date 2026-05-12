require ["fileinto", "mailbox", "body"];

# calinvite — server-side pre-filter for iTIP RSVPs.
#
# When an attendee accepts/declines/tentatively-accepts a calendar invite,
# their mail client emits a message containing a `text/calendar; method=REPLY`
# part. We file those into a dedicated folder so the RSVP poller scans a small
# focused mailbox instead of all of INBOX every cron tick.
#
# Body :contains is the only reliable test here — the `method=REPLY` parameter
# lives inside the calendar MIME part's Content-Type, not the top-level
# message Content-Type, so a header test wouldn't catch it.

if body :contains "METHOD:REPLY" {
    fileinto :create "RSVPs";
}
