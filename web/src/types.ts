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

export type EventOut = {
  uid: string;
  summary: string;
  start: string;
  end: string;
  tz?: string | null;
  location: string;
  description: string;
  sequence: number;
  organizer?: OrganizerOut | null;
  attendees: AttendeeOut[];
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
