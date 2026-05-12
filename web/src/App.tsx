import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AuthRequiredError } from "./api";
import type { CalendarSummary, EventIn, EventOut, Me } from "./types";
import { Header } from "./components/Header";
import { EventsView } from "./components/EventsView";
import { EventForm } from "./components/EventForm";
import { RsvpsView } from "./components/RsvpsView";
import { CalendarView, type CalendarMode } from "./components/CalendarView";
import { LoginView } from "./components/LoginView";
import { VerifyView } from "./components/VerifyView";
import { OnboardingView } from "./components/OnboardingView";
import { UnofficialNote } from "./components/UnofficialNote";
import { ToastStack, type ToastMsg } from "./components/Toast";
import { addDays, buildMonthGrid, fmtTimeShort, startOfDay, startOfWeek } from "./util";
import { useReminders } from "./useReminders";

type Tab = "calendar" | "events" | "rsvps";
type FormState =
  | { open: false }
  | { open: true; mode: "create"; initial: null; prefillStart?: Date | null; prefillDurationMinutes?: number | null }
  | { open: true; mode: "edit"; initial: EventOut };

type Bootstrap =
  | { status: "loading" }
  | { status: "unauthed" }
  | { status: "needs-mailbox"; me: Me }
  | { status: "ready"; me: Me };

function getRoute(): string {
  return window.location.pathname;
}

export default function App() {
  const [route, setRoute] = useState<string>(() => getRoute());
  const [boot, setBoot] = useState<Bootstrap>({ status: "loading" });

  useEffect(() => {
    function onPop() {
      setRoute(getRoute());
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const bootstrap = useCallback(async () => {
    try {
      const me = await api.me();
      setBoot({ status: me.has_mailbox ? "ready" : "needs-mailbox", me });
    } catch (e) {
      if (e instanceof AuthRequiredError) {
        setBoot({ status: "unauthed" });
      } else {
        setBoot({ status: "unauthed" });
      }
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  // Routing for non-app pages.
  if (route === "/auth/verify") {
    return <VerifyView onDone={() => { setRoute("/"); window.history.replaceState({}, "", "/"); bootstrap(); }} />;
  }

  if (boot.status === "loading") {
    return (
      <div className="flex min-h-full items-center justify-center">
        <div className="text-sm text-ink-500">Loading…</div>
      </div>
    );
  }

  if (boot.status === "unauthed" || route === "/login") {
    return <LoginView />;
  }

  if (boot.status === "needs-mailbox") {
    return (
      <OnboardingView
        me={boot.me}
        onConnected={() => bootstrap()}
        onLogout={async () => {
          try { await api.logout(); } catch {}
          setBoot({ status: "unauthed" });
        }}
      />
    );
  }

  return <AuthedApp me={boot.me} onSignOut={async () => {
    try { await api.logout(); } catch {}
    setBoot({ status: "unauthed" });
  }} onAuthLost={() => setBoot({ status: "unauthed" })} />;
}

function AuthedApp({ me, onSignOut, onAuthLost }: { me: Me; onSignOut: () => void; onAuthLost: () => void }) {
  const [calendars, setCalendars] = useState<CalendarSummary[]>([]);
  const [calendar, setCalendarState] = useState<string>(
    () => (typeof window !== "undefined" && localStorage.getItem("pmc.selectedCalendar")) || ""
  );
  const setCalendar = useCallback((name: string) => {
    setCalendarState(name);
    try {
      if (name) localStorage.setItem("pmc.selectedCalendar", name);
    } catch {
      // localStorage can throw in private windows; non-fatal.
    }
  }, []);

  const [events, setEvents] = useState<EventOut[]>([]);
  const [eventCounts, setEventCounts] = useState<Record<string, number>>({});
  const [days, setDays] = useState(60);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  // UIDs that we've written/optimistically rendered but the server hasn't
  // confirmed yet (Purelymail's CalDAV has a propagation lag). We keep their
  // optimistic entries on every refresh until the server response includes
  // them.
  const pendingUidsRef = useRef<Map<string, EventOut>>(new Map());
  const markPending = useCallback((ev: EventOut) => {
    pendingUidsRef.current.set(ev.uid, ev);
  }, []);
  const clearPending = useCallback((uid: string) => {
    pendingUidsRef.current.delete(uid);
  }, []);

  const [tab, setTab] = useState<Tab>("calendar");
  const [calMode, setCalMode] = useState<CalendarMode>("month");
  const [calAnchor, setCalAnchor] = useState<Date>(() => startOfDay(new Date()));
  const [form, setForm] = useState<FormState>({ open: false });
  const [cancelChoice, setCancelChoice] = useState<EventOut | null>(null);

  // Compute the CalDAV fetch range from the active tab + view state, so the
  // server only returns events that are actually visible. Calendar tab uses
  // the visible grid range; Events tab uses the `now → now+days` window.
  const fetchRange = useMemo<{ from: Date; to: Date } | undefined>(() => {
    if (tab !== "calendar") return undefined;
    if (calMode === "month") {
      const grid = buildMonthGrid(calAnchor);
      return { from: grid[0], to: addDays(grid[grid.length - 1], 1) };
    }
    if (calMode === "week") {
      const start = startOfWeek(calAnchor);
      return { from: start, to: addDays(start, 7) };
    }
    const day = startOfDay(calAnchor);
    return { from: day, to: addDays(day, 1) };
  }, [tab, calMode, calAnchor]);

  const [toasts, setToasts] = useState<ToastMsg[]>([]);
  const toastIdRef = useRef(1);
  const pushToast = useCallback((kind: ToastMsg["kind"], text: string) => {
    const id = toastIdRef.current++;
    setToasts((t) => [...t, { id, kind, text }]);
  }, []);
  const dismissToast = useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  // In-tab reminder scheduler. Fires a blocking fullscreen alert that the user
  // must dismiss, plus a native browser Notification (if granted) for when the
  // tab isn't focused.
  const [reminderAlerts, setReminderAlerts] = useState<
    { id: number; title: string; offsetText: string; event: EventOut }[]
  >([]);
  const reminderIdRef = useRef(1);
  useReminders(events, (ev, _r, offsetText) => {
    const id = reminderIdRef.current++;
    setReminderAlerts((prev) => [...prev, { id, title: ev.summary, offsetText, event: ev }]);
    const notifBody = `Starts ${offsetText} — ${new Date(ev.start).toLocaleString()}`;
    try {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification(`Reminder: ${ev.summary}`, { body: notifBody, tag: ev.uid });
      }
    } catch {
      // ignore
    }
    try {
      const orig = document.title;
      document.title = `🔔 ${ev.summary}`;
      setTimeout(() => { document.title = orig; }, 8000);
    } catch {
      // ignore
    }
  });
  const dismissReminder = useCallback((id: number) => {
    setReminderAlerts((prev) => prev.filter((r) => r.id !== id));
  }, []);

  const handle = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
      try {
        return await fn();
      } catch (e: any) {
        if (e instanceof AuthRequiredError) {
          onAuthLost();
          return undefined;
        }
        throw e;
      }
    },
    [onAuthLost]
  );

  const refreshEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      const list = await handle(() => api.events(calendar || undefined, days, fetchRange));
      if (list) {
        const seenUids = new Set(list.map((e) => e.uid));
        // Server confirmed any pending UIDs that appear; drop them from pending.
        for (const uid of Array.from(pendingUidsRef.current.keys())) {
          if (seenUids.has(uid)) pendingUidsRef.current.delete(uid);
        }
        // Append still-pending optimistic events that the server hasn't picked
        // up yet, so they don't flicker off the calendar.
        const extras: EventOut[] = [];
        for (const ev of pendingUidsRef.current.values()) {
          if (!seenUids.has(ev.uid)) extras.push(ev);
        }
        const merged = [...list, ...extras];
        merged.sort((a, b) => +new Date(a.start) - +new Date(b.start));
        setEvents(merged);
      }
    } catch (e: any) {
      setEventsError(e?.message || "failed to load events");
    } finally {
      setEventsLoading(false);
    }
  }, [calendar, days, fetchRange, handle]);

  useEffect(() => {
    (async () => {
      try {
        const c = await handle(() => api.calendars());
        if (c) {
          setCalendars(c);
          // Honor the cached choice if it still exists on the server; otherwise
          // pick the calendar with the most events; otherwise the first.
          const cached = (typeof window !== "undefined" && localStorage.getItem("pmc.selectedCalendar")) || "";
          if (!cached || !c.some((x) => x.name === cached)) {
            if (c[0]) setCalendar(c[0].name);
          }
          // Fire counts in parallel so we can show them in the dropdown.
          const entries = await Promise.all(
            c.map(async (cal) => {
              try {
                const list = await api.events(cal.name, 60);
                return [cal.name, list.length] as const;
              } catch {
                return [cal.name, -1] as const;
              }
            })
          );
          const counts: Record<string, number> = {};
          for (const [n, v] of entries) counts[n] = v;
          setEventCounts(counts);
          // If nothing was selected yet and one calendar clearly has events,
          // prefer that over the alphabetical default.
          if (!cached) {
            const best = c
              .map((x) => ({ name: x.name, count: counts[x.name] ?? 0 }))
              .filter((x) => x.count > 0)
              .sort((a, b) => b.count - a.count)[0];
            if (best) setCalendar(best.name);
          }
        }
      } catch (e: any) {
        pushToast("error", `Config: ${e?.message || "could not load calendars"}`);
      }
    })();
  }, [pushToast, handle, setCalendar]);

  useEffect(() => {
    refreshEvents();
  }, [refreshEvents]);

  const onCreateClick = () => setForm({ open: true, mode: "create", initial: null });
  const onCreateAt = (start: Date, durationMinutes?: number) =>
    setForm({
      open: true,
      mode: "create",
      initial: null,
      prefillStart: start,
      prefillDurationMinutes: durationMinutes ?? null,
    });
  const onEditClick = (e: EventOut) => setForm({ open: true, mode: "edit", initial: e });

  const onMoveEvent = async (e: EventOut, newStart: Date) => {
    const newEnd = new Date(newStart.getTime() + durationMinutes(e) * 60000);
    const oldStart = new Date(e.start);
    const sameTime =
      oldStart.getFullYear() === newStart.getFullYear() &&
      oldStart.getMonth() === newStart.getMonth() &&
      oldStart.getDate() === newStart.getDate() &&
      oldStart.getHours() === newStart.getHours() &&
      oldStart.getMinutes() === newStart.getMinutes();
    if (sameTime) return;
    const desc = `${newStart.toDateString()} at ${fmtTimeShort(newStart)}`;
    const recipientCount = e.attendees.length;
    const msg =
      recipientCount > 0
        ? `Move "${e.summary}" to ${desc} and email ${recipientCount} attendee${recipientCount === 1 ? "" : "s"} an update?`
        : `Move "${e.summary}" to ${desc}?`;
    if (!confirm(msg)) return;
    const body: EventIn = {
      calendar: calendar || undefined,
      summary: e.summary,
      start: toLocalIsoMinute(newStart),
      end: toLocalIsoMinute(newEnd),
      duration_minutes: durationMinutes(e),
      tz: e.tz || "America/Chicago",
      location: e.location,
      description: e.description,
      attendees: e.attendees.map((a) => ({ email: a.email, name: a.name || undefined })),
      uid: e.uid,
      sequence: e.sequence + 1,
    };
    try {
      const r = await handle(() => api.updateEvent(e.uid, body));
      if (!r) return;
      const optimistic = buildOptimisticEvent(body, r.uid, me);
      markPending(optimistic);
      setEvents((prev) => upsertEvent(prev, optimistic));
      pushToast(
        "success",
        r.sent_to.length ? `Moved. Update sent to ${r.sent_to.length}.` : "Moved."
      );
      refreshEvents();
    } catch (err: any) {
      pushToast("error", err?.message || "move failed");
    }
  };

  // Cancel the entire series (or a one-off event). Used by the simple
  // confirm flow and by the "Entire series" path of the recurring chooser.
  const cancelWholeEvent = async (e: EventOut) => {
    const body: EventIn = {
      calendar: calendar || undefined,
      summary: e.summary,
      start: toLocalIsoMinute(new Date(e.start)),
      duration_minutes: durationMinutes(e),
      tz: e.tz || "America/Chicago",
      location: e.location,
      description: e.description,
      attendees: e.attendees.map((a) => ({ email: a.email, name: a.name || undefined })),
      uid: e.master_uid || e.uid,
      sequence: e.sequence + 1,
    };
    try {
      const res = await handle(() => api.cancelEvent(e.master_uid || e.uid, body));
      if (!res) return;
      clearPending(e.master_uid || e.uid);
      const masterUid = e.master_uid || e.uid;
      setEvents((prev) => prev.filter((x) => (x.master_uid || x.uid) !== masterUid));
      pushToast(
        "success",
        res.sent_to.length
          ? `Cancelled. Notified ${res.sent_to.length} attendee${res.sent_to.length === 1 ? "" : "s"}.`
          : "Cancelled."
      );
      refreshEvents();
    } catch (err: any) {
      pushToast("error", err?.message || "cancel failed");
    }
  };

  // Cancel a single occurrence of a recurring event (adds EXDATE on master,
  // sends iTIP CANCEL with RECURRENCE-ID for that date).
  const cancelOneOccurrence = async (e: EventOut) => {
    try {
      const masterUid = e.master_uid || e.uid;
      const res = await handle(() => api.cancelOccurrence(masterUid, e.start));
      if (!res) return;
      const occId = e.occurrence_id;
      setEvents((prev) => prev.filter((x) => (occId ? x.occurrence_id !== occId : x.uid !== e.uid)));
      pushToast("success", "Cancelled this occurrence.");
      refreshEvents();
    } catch (err: any) {
      pushToast("error", err?.message || "cancel failed");
    }
  };

  const onCancelClick = async (e: EventOut) => {
    if (e.recurrence) {
      setCancelChoice(e);  // Show the 3-way modal
      return;
    }
    if (!confirm(`Cancel "${e.summary}" and notify attendees?`)) return;
    await cancelWholeEvent(e);
  };

  const submitForm = async (body: EventIn, mode: "create" | "edit", uid: string | null) => {
    const payload: EventIn = { ...body, calendar: calendar || body.calendar };
    if (mode === "create") {
      const r = await handle(() => api.createEvent(payload));
      if (!r) return;
      const optimistic = buildOptimisticEvent(payload, r.uid, me);
      markPending(optimistic);
      setEvents((prev) => upsertEvent(prev, optimistic));
      pushToast(
        "success",
        r.dry_run
          ? `Created (dry run). UID ${r.uid.slice(0, 16)}…`
          : r.sent_to.length
          ? `Sent invite to ${r.sent_to.length} attendee${r.sent_to.length === 1 ? "" : "s"}.`
          : `Created. UID ${r.uid.slice(0, 16)}…`
      );
    } else {
      const r = await handle(() => api.updateEvent(uid!, payload));
      if (!r) return;
      const optimistic = buildOptimisticEvent(payload, r.uid, me);
      markPending(optimistic);
      setEvents((prev) => upsertEvent(prev, optimistic));
      pushToast(
        "success",
        r.dry_run
          ? `Updated (dry run).`
          : r.sent_to.length
          ? `Update sent to ${r.sent_to.length} attendee${r.sent_to.length === 1 ? "" : "s"}.`
          : `Updated.`
      );
    }
    refreshEvents();
  };

  return (
    <div className="min-h-full">
      <Header
        me={me}
        calendars={calendars}
        calendar={calendar}
        setCalendar={setCalendar}
        eventCounts={eventCounts}
        onNew={onCreateClick}
        onLogout={onSignOut}
      />

      <div className="mx-auto max-w-6xl px-4">
        <QuietLoader active={eventsLoading} />
        <nav className="mt-4 flex gap-1 border-b border-ink-200">
          <TabButton active={tab === "calendar"} onClick={() => setTab("calendar")}>Calendar</TabButton>
          <TabButton active={tab === "events"} onClick={() => setTab("events")}>Events</TabButton>
          <TabButton active={tab === "rsvps"} onClick={() => setTab("rsvps")}>RSVPs</TabButton>
        </nav>

        <main className="py-5">
          {tab === "calendar" && (
            <CalendarView
              events={events}
              loading={eventsLoading}
              error={eventsError}
              onRefresh={refreshEvents}
              onCreateAt={onCreateAt}
              onEdit={onEditClick}
              onMove={onMoveEvent}
              mode={calMode}
              setMode={setCalMode}
              anchor={calAnchor}
              setAnchor={setCalAnchor}
            />
          )}
          {tab === "events" && (
            <EventsView
              events={events}
              loading={eventsLoading}
              error={eventsError}
              onEdit={onEditClick}
              onCancel={onCancelClick}
              onRefresh={refreshEvents}
              days={days}
              setDays={setDays}
            />
          )}
          {tab === "rsvps" && (
            <RsvpsView
              account={me.email}
              calendar={calendar}
              onError={(m) => pushToast("error", m)}
              onSuccess={(m) => pushToast("success", m)}
            />
          )}
        </main>

        <footer className="mt-8 border-t border-ink-200 py-6 text-center">
          <UnofficialNote />
        </footer>
      </div>

      {form.open && (
        <EventForm
          mode={form.mode}
          initial={form.mode === "edit" ? form.initial : null}
          prefillStart={form.mode === "create" ? form.prefillStart ?? null : null}
          prefillDurationMinutes={form.mode === "create" ? form.prefillDurationMinutes ?? null : null}
          defaultAccount={me.email}
          defaultCalendar={calendar}
          onClose={() => setForm({ open: false })}
          onSubmit={submitForm}
          onCancelEvent={(ev) => {
            setForm({ open: false });
            onCancelClick(ev);
          }}
        />
      )}

      {cancelChoice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="cancel-choice-title"
            className="w-full max-w-md rounded-xl border border-ink-200 bg-white p-5 shadow-2xl"
          >
            <h2 id="cancel-choice-title" className="text-base font-semibold text-ink-900">
              Cancel recurring event
            </h2>
            <p className="mt-1 text-sm text-ink-600">
              <span className="font-medium text-ink-800">{cancelChoice.summary}</span> repeats
              {cancelChoice.recurrence?.text ? ` (${cancelChoice.recurrence.text.toLowerCase()})` : ""}.
              What do you want to cancel?
            </p>
            <p className="mt-1 text-xs text-ink-500">
              Showing the occurrence on{" "}
              {new Date(cancelChoice.start).toLocaleString(undefined, {
                weekday: "short",
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              })}
              .
            </p>
            <div className="mt-4 flex flex-col gap-2">
              <button
                className="btn-secondary"
                onClick={async () => {
                  const target = cancelChoice;
                  setCancelChoice(null);
                  await cancelOneOccurrence(target);
                }}
              >
                Just this occurrence
              </button>
              <button
                className="btn-danger"
                onClick={async () => {
                  const target = cancelChoice;
                  setCancelChoice(null);
                  if (!confirm(`Cancel the entire "${target.summary}" series and notify attendees?`)) return;
                  await cancelWholeEvent(target);
                }}
              >
                Entire series
              </button>
              <button className="btn-secondary" onClick={() => setCancelChoice(null)}>
                Keep event
              </button>
            </div>
          </div>
        </div>
      )}

      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      {reminderAlerts.length > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/70 p-4">
          {(() => {
            const a = reminderAlerts[0];
            return (
              <div
                role="alertdialog"
                aria-modal="true"
                aria-labelledby="reminder-title"
                className="w-full max-w-md rounded-xl border border-ink-200 bg-white p-6 text-center shadow-2xl"
              >
                <div className="mb-3 flex justify-center text-accent-600">
                  <svg
                    aria-hidden="true"
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 32 32"
                    fill="currentColor"
                    className="h-12 w-12"
                  >
                    <path d="M30,23.3818l-2-1V20a6.0046,6.0046,0,0,0-5-5.91V12H21v2.09A6.0046,6.0046,0,0,0,16,20v2.3818l-2,1V28h6v2h4V28h6ZM28,26H16V24.6182l2-1V20a4,4,0,0,1,8,0v3.6182l2,1Z" />
                    <path d="M28,6a2,2,0,0,0-2-2H22V2H20V4H12V2H10V4H6A2,2,0,0,0,4,6V26a2,2,0,0,0,2,2h4V26H6V6h4V8h2V6h8V8h2V6h4v6h2Z" />
                  </svg>
                </div>
                <h2 id="reminder-title" className="text-xl font-semibold text-ink-900">
                  {a.title}
                </h2>
                <p className="mt-1 text-sm font-medium text-accent-700">Starts {a.offsetText}</p>
                <dl className="mt-4 grid gap-2 text-left text-sm">
                  <div>
                    <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">When</dt>
                    <dd className="text-ink-800">
                      {new Date(a.event.start).toLocaleString()}
                      {a.event.tz ? ` · ${a.event.tz}` : ""}
                    </dd>
                  </div>
                  {a.event.location && (
                    <div>
                      <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Where</dt>
                      <dd className="break-words text-ink-800">{a.event.location}</dd>
                    </div>
                  )}
                  {a.event.attendees && a.event.attendees.length > 0 && (
                    <div>
                      <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">
                        Attendees ({a.event.attendees.length})
                      </dt>
                      <dd className="break-words text-ink-700">
                        {a.event.attendees.map((x) => x.email).join(", ")}
                      </dd>
                    </div>
                  )}
                  {a.event.description && (
                    <div>
                      <dt className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Description</dt>
                      <dd className="whitespace-pre-wrap text-ink-700">{a.event.description}</dd>
                    </div>
                  )}
                </dl>
                {reminderAlerts.length > 1 && (
                  <p className="mt-3 text-xs text-ink-500">
                    +{reminderAlerts.length - 1} more reminder{reminderAlerts.length - 1 === 1 ? "" : "s"} queued
                  </p>
                )}
                <button
                  autoFocus
                  onClick={() => dismissReminder(a.id)}
                  className="btn-primary mt-5 w-full"
                >
                  Dismiss
                </button>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}

function QuietLoader({ active }: { active: boolean }) {
  return (
    <div className="mt-2 h-[2px] w-full overflow-hidden rounded-full bg-ink-100" aria-hidden="true">
      <div
        className={`h-full w-1/3 rounded-full bg-accent-500 ${active ? "animate-loader-slide" : "opacity-0"}`}
      />
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
        active ? "border-accent-600 text-ink-900" : "border-transparent text-ink-500 hover:text-ink-800"
      }`}
    >
      {children}
    </button>
  );
}

function durationMinutes(e: EventOut): number {
  const ms = new Date(e.end).getTime() - new Date(e.start).getTime();
  return Math.max(15, Math.round(ms / 60000));
}

function toLocalIsoMinute(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function parseLocalIsoMinute(s: string, tz: string): Date {
  // The EventForm produces local-naive datetime strings (e.g. "2026-05-15T14:00")
  // which represent the wall-clock time in the chosen timezone. We parse them
  // and reinterpret in that timezone by going through the offset of `now` in
  // that zone. Good enough for upcoming events that aren't crossing a DST seam.
  const local = new Date(s);
  if (Number.isNaN(local.getTime())) return new Date();
  try {
    const offsetMinutesAtThatTime = -new Date(
      local.toLocaleString("en-US", { timeZone: tz })
    ).getTimezoneOffset();
    const localOffset = -local.getTimezoneOffset();
    return new Date(local.getTime() - (offsetMinutesAtThatTime - localOffset) * 60000);
  } catch {
    return local;
  }
}

function buildOptimisticEvent(payload: EventIn, uid: string, me: Me): EventOut {
  const tz = payload.tz || "America/Chicago";
  const start = parseLocalIsoMinute(payload.start, tz);
  const durationMin = payload.duration_minutes ?? 60;
  const end = payload.end ? parseLocalIsoMinute(payload.end, tz) : new Date(start.getTime() + durationMin * 60000);
  return {
    uid,
    summary: payload.summary,
    start: start.toISOString(),
    end: end.toISOString(),
    tz,
    location: payload.location || "",
    description: payload.description || "",
    sequence: payload.sequence ?? 0,
    organizer: { email: me.email, name: me.display_name || me.email },
    attendees: (payload.attendees || []).map((a) => ({
      email: a.email,
      name: a.name || null,
      partstat: "NEEDS-ACTION",
    })),
  };
}

function upsertEvent(list: EventOut[], next: EventOut): EventOut[] {
  const idx = list.findIndex((e) => e.uid === next.uid);
  const out = idx === -1 ? [...list, next] : list.map((e, i) => (i === idx ? next : e));
  out.sort((a, b) => +new Date(a.start) - +new Date(b.start));
  return out;
}
