import type {
  CalendarSummary,
  CancelEventResponse,
  CreateEventResponse,
  EventIn,
  EventOut,
  Mailbox,
  Me,
  RsvpPollIn,
  RsvpPollOut,
} from "./types";

export class AuthRequiredError extends Error {
  constructor() {
    super("not authenticated");
    this.name = "AuthRequiredError";
  }
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401) {
    throw new AuthRequiredError();
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // auth
  requestLink: (email: string) =>
    request<{ ok: boolean }>("/api/auth/request-link", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  verifyLink: (token: string) =>
    request<{ ok: boolean; email: string }>(`/api/auth/verify?token=${encodeURIComponent(token)}`),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  me: () => request<Me>("/api/auth/me"),

  // mailbox
  getMailbox: () => request<Mailbox | null>("/api/me/mailbox"),
  connectMailbox: (email: string, password: string, display_name?: string) =>
    request<Mailbox>("/api/me/mailbox", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name }),
    }),
  deleteMailbox: () => request<{ ok: boolean }>("/api/me/mailbox", { method: "DELETE" }),

  // data
  calendars: () => request<CalendarSummary[]>("/api/calendars"),
  events: (
    calendar?: string,
    days = 60,
    range?: { from: Date; to: Date }
  ) => {
    const q = new URLSearchParams();
    q.set("days", String(days));
    if (calendar) q.set("calendar", calendar);
    if (range) {
      q.set("start", range.from.toISOString());
      q.set("end", range.to.toISOString());
    }
    return request<EventOut[]>(`/api/events?${q.toString()}`);
  },
  createEvent: (body: EventIn) =>
    request<CreateEventResponse>("/api/events", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateEvent: (uid: string, body: EventIn) =>
    request<CreateEventResponse>(`/api/events/${encodeURIComponent(uid)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  cancelEvent: (uid: string, body: EventIn) =>
    request<CancelEventResponse>(`/api/events/${encodeURIComponent(uid)}/cancel`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancelOccurrence: (uid: string, occurrenceStartIso: string) =>
    request<{ ok: boolean }>(`/api/events/${encodeURIComponent(uid)}/cancel-occurrence`, {
      method: "POST",
      body: JSON.stringify({ occurrence_start: occurrenceStartIso }),
    }),
  pollRsvps: (body: RsvpPollIn) =>
    request<RsvpPollOut>("/api/rsvps/poll", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  syncInvites: (body?: { calendar?: string; mailbox?: string; only_unseen?: boolean; mark_seen?: boolean }) =>
    request<{
      mailbox: string;
      counts: { created: number; updated: number; cancelled: number; skipped: number; error: number };
      results: { uid: string; summary: string; action: string; success: boolean; detail: string }[];
    }>("/api/invites/sync", {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
};
