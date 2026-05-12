export type Me = {
  id: number;
  email: string;
  display_name?: string | null;
  has_mailbox: boolean;
};

export type Mailbox = {
  email: string;
  display_name: string;
  account_id: string;
  caldav_url: string;
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
  reminders?: ReminderIn[];
  recurrence?: RecurrenceIn | null;
  dry_run?: boolean;
  uid?: string;
  sequence?: number;
};

export type CreateEventResponse = {
  uid: string;
  sent_to: string[];
  dry_run: boolean;
};

export type CancelEventResponse = {
  uid: string;
  sent_to: string[];
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
