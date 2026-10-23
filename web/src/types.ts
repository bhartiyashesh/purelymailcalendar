export type Me = {
  id: number;
  email: string;
  display_name?: string | null;
  has_mailbox: boolean;
};

export type Mailbox = {
  id: number;
  email: string;
  display_name: string;
  account_id: string;
  caldav_url: string;
  selected_calendar?: string | null;
  color?: string | null;
  last_scanned_at?: string | null;
  last_contacts_synced_at?: string | null;
};

export type MailboxFailure = {
  mailbox_id: number;
  mailbox_email: string;
  error: string;
};

export type MailboxCalendar = {
  mailbox_id: number;
  mailbox_email: string;
  mailbox_display_name: string;
  mailbox_color?: string | null;
  name: string;
};

export type MailboxCalendarsAll = {
  calendars: MailboxCalendar[];
  partial_failures: MailboxFailure[];
};

export type CalendarSummary = {
  name: string;
};

export type AttendeeIn = {
  email: string;
  name?: string | null;
};

export type AttendeeOut = {
  email: string;
  name?: string | null;
  partstat: string;
};

export type OrganizerOut = {
  email: string;
  name?: string | null;
};

export type ReminderOut = {
  action: "DISPLAY" | "EMAIL" | string;
  minutes_before: number;
  description?: string;
};

export type RecurrenceFreq = "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY";

export type RecurrenceIn = {
  freq: RecurrenceFreq;
  interval?: number;
  until?: string;  // YYYY-MM-DD
  count?: number;
};

export type RecurrenceOut = {
  freq: RecurrenceFreq;
  interval: number;
  until?: string | null;
  count?: number | null;
  text: string;
};

export type EventOut = {
  uid: string;
  summary: string;
  start: string;
  end: string;
  tz?: string | null;
  location: string;
  description: string;
  sequence: number;
  reminders?: ReminderOut[];
  organizer?: OrganizerOut | null;
  attendees: AttendeeOut[];
  bcc_invites?: boolean;
  recurrence?: RecurrenceOut | null;
  occurrence_id?: string;
  master_uid?: string;
};

export type ReminderIn = {
  action: "DISPLAY" | "EMAIL";
  minutes_before: number;
  description?: string;
  recipients?: string[];
};

export type EventIn = {
  account?: string;
  calendar?: string;
  summary: string;
  start: string;
  duration_minutes?: number;
  end?: string;
  tz: string;
  location?: string;
  description?: string;
  attendees: AttendeeIn[];
  bcc_invites?: boolean;
  reminders?: ReminderIn[];
  recurrence?: RecurrenceIn | null;
  dry_run?: boolean;
  uid?: string;
  sequence?: number;
};

export type CreateEventResponse = {
  uid: string;
  sent_to: string[];
  failed_to?: string[];
  dry_run: boolean;
};

export type CancelEventResponse = {
  uid: string;
  sent_to: string[];
  failed_to?: string[];
};

export type RsvpResultOut = {
  uid: string;
  attendee: string;
  partstat: string;
  summary: string;
  success: boolean;
  detail: string;
};

export type RsvpPollIn = {
  account?: string;
  calendar?: string;
  mailbox?: string;
  only_unseen?: boolean;
  mark_seen?: boolean;
};

export type RsvpPollOut = {
  mailbox: string;
  results: RsvpResultOut[];
};

export type MailboxEventOut = EventOut & {
  mailbox_id: number;
  mailbox_email: string;
  mailbox_display_name: string;
  mailbox_color?: string | null;
  calendar_name?: string | null;
};

// Union shape the app uses for in-memory event state. Single-mailbox view
// produces bare `EventOut` rows; the All-accounts overlay produces
// `MailboxEventOut`. Optional fields are present iff the row came from the
// overlay endpoint, so mutation code can route via `ev.mailbox_id` when set.
export type AppEvent = EventOut & {
  mailbox_id?: number;
  mailbox_email?: string;
  mailbox_display_name?: string;
  mailbox_color?: string | null;
  calendar_name?: string | null;
};


// AI-tasks ---------------------------------------------------------------

export type InboxMessage = {
  message_uid: string;
  subject: string;
  from: string;
  date?: string | null;
  body_text: string;
  truncated: boolean;
};

export type TaskItem = {
  id: number;
  mailbox_id: number;
  message_uid: string;
  task_index: number;
  title: string;
  due_at?: string | null;
  owner_email?: string | null;
  source_subject: string;
  source_from: string;
  source_date?: string | null;
  done_at?: string | null;
  snoozed_until?: string | null;
  as_event_uid?: string | null;
  created_at: string;
  extracted_at: string;
};

export type TaskBulkItem = {
  mailbox_id: number;
  message_uid: string;
  task_index: number;
  title: string;
  due_at?: string | null;
  owner_email?: string | null;
  source_subject: string;
  source_from: string;
  source_date?: string | null;
};

export type TaskBulkUpsertResult = {
  written: number;
  items: TaskItem[];
};

export type TaskPatchIn = {
  done?: boolean;
  snoozed_until?: string | null;
  as_event_uid?: string | null;
};

export type MailboxEventsAll = {
  events: MailboxEventOut[];
  partial_failures: MailboxFailure[];
};


// Contacts (feat/contacts) ----------------------------------------------

export type Contact = {
  id: number;
  mailbox_id: number;
  vcard_uid: string;
  full_name: string;
  primary_email?: string | null;
  emails: string[];
  org?: string | null;
  source_book: string;
  last_synced_at: string;
};

export type ContactSyncResult = {
  upserted: number;
  deleted: number;
  books: string[];
  last_synced_at: string;
  throttled: boolean;
};

export type ContactFromEventResult = {
  added: number;
  skipped: number;
  errors: number;
};
