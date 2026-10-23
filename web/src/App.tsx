import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ACTIVE_MAILBOX_KEY, api, AuthRequiredError } from "./api";
import type { AppEvent, CalendarSummary, EventIn, EventOut, Mailbox, Me, TaskItem } from "./types";
import type { ActiveMailboxSelection } from "./components/MailboxSwitcher";
import { Header } from "./components/Header";
import { EventsView } from "./components/EventsView";
import { EventForm } from "./components/EventForm";
import { RsvpsView } from "./components/RsvpsView";
import { CalendarView, type CalendarMode } from "./components/CalendarView";
import { LoginView } from "./components/LoginView";
import { VerifyView } from "./components/VerifyView";
import { OnboardingView } from "./components/OnboardingView";
import { UnofficialNote } from "./components/UnofficialNote";
import { RunningSha } from "./components/RunningSha";
import { ToastStack, type ToastMsg } from "./components/Toast";
import { AddMailboxModal } from "./components/AddMailboxModal";
import { ContactsPanel } from "./components/ContactsPanel";
import { TasksView, type ScanRange } from "./components/TasksView";
import { AiScanModal } from "./components/AiScanModal";
import { useAiAvailability } from "./aiTasks/useAiAvailability";
import { resetContactsSyncCheckpoint } from "./contacts/useContacts";
import { addDays, buildMonthGrid, fmtTimeShort, startOfDay, startOfWeek } from "./util";
import { useReminders } from "./useReminders";

type Tab = "calendar" | "events" | "rsvps" | "tasks";
type FormState =
  | { open: false }
  | {
      open: true;
      mode: "create";
      initial: null;
      prefillStart?: Date | null;
      prefillDurationMinutes?: number | null;
      prefillSummary?: string | null;
      /** Set when the form was opened from a task. After a successful
       * create, we stamp `as_event_uid` on that task so it stops nagging. */
      fromTaskId?: number | null;
    }
  | { open: true; mode: "edit"; initial: AppEvent };

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
  if (route === "/about" || route === "/about/") {
    // In prod the FastAPI app serves /about directly. In dev Vite's
    // SPA fallback wins over its proxy for this exact path, so the
    // SPA loads first and bounces the user to /about.html (which Vite
    // serves correctly from public/).
    if (typeof window !== "undefined") window.location.replace("/about.html");
    return null;
  }
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
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([]);
  const [activeMailboxId, setActiveMailboxIdState] = useState<ActiveMailboxSelection | null>(() => {
    if (typeof window === "undefined") return null;
    const raw = localStorage.getItem(ACTIVE_MAILBOX_KEY);
    if (!raw) return null;
    if (raw === "all") return "all";
    if (!/^\d+$/.test(raw)) return null;
    return Number(raw);
  });
  const setActiveMailboxId = useCallback((id: ActiveMailboxSelection | null) => {
    setActiveMailboxIdState(id);
    try {
      if (id == null) localStorage.removeItem(ACTIVE_MAILBOX_KEY);
      else localStorage.setItem(ACTIVE_MAILBOX_KEY, String(id));
    } catch {
      // private mode; non-fatal
    }
    // The contact cache is per-mailbox on the server, but the hook keeps a
    // process-wide "last synced" checkpoint to throttle sync-on-open. Clear
    // it on every flip so the next event-form open re-syncs against the
    // newly-active mailbox.
    resetContactsSyncCheckpoint();
  }, []);
  const allActive = activeMailboxId === "all";
  const [showAddMailbox, setShowAddMailbox] = useState(false);
  const [showContacts, setShowContacts] = useState(false);

  const [calendars, setCalendars] = useState<CalendarSummary[]>([]);
  const [calendar, setCalendarState] = useState<string>(
    () => (typeof window !== "undefined" && localStorage.getItem("pmc.selectedCalendar")) || ""
  );
  // Track which mailbox the current `calendar` choice was loaded for, so the
  // calendar-load effect only fires when the user actually flips mailboxes
  // (not on every render where calendars happen to be empty).
  const calendarSeededForRef = useRef<number | null>(null);
  const setCalendar = useCallback((name: string) => {
    setCalendarState(name);
    try {
      if (name) localStorage.setItem("pmc.selectedCalendar", name);
    } catch {
      // localStorage can throw in private windows; non-fatal.
    }
  }, []);
  // Persist the calendar choice back to the active mailbox so auto-sync and
  // future sessions use it. Best-effort: a network glitch here shouldn't
  // surface as an error to the user.
  const persistSelectedCalendarRef = useRef<number | null>(null);
  useEffect(() => {
    if (!calendar) return;
    if (activeMailboxId == null) return;
    // In the All-accounts overlay there's no single mailbox to persist to;
    // the Calendar dropdown is hidden there anyway.
    if (activeMailboxId === "all") return;
    if (persistSelectedCalendarRef.current === activeMailboxId) {
      // Same mailbox: persist on changes only.
    }
    const active = mailboxes.find((m) => m.id === activeMailboxId);
    if (active && active.selected_calendar === calendar) return;
    persistSelectedCalendarRef.current = activeMailboxId;
    api
      .updateMailbox(activeMailboxId, { selected_calendar: calendar })
      .then((updated) => {
        setMailboxes((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
      })
      .catch(() => {
        // ignore
      });
  }, [calendar, activeMailboxId, mailboxes]);

  const [events, setEvents] = useState<AppEvent[]>([]);
  const [eventCounts, setEventCounts] = useState<Record<string, number>>({});
  const [days, setDays] = useState(60);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  // UIDs that we've written/optimistically rendered but the server hasn't
  // confirmed yet (Purelymail's CalDAV has a propagation lag). We keep their
  // optimistic entries on every refresh until the server response includes
  // them.
  const pendingUidsRef = useRef<Map<string, AppEvent>>(new Map());
  const markPending = useCallback((ev: AppEvent) => {
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
  const [syncingInvites, setSyncingInvites] = useState(false);

  // Browser-side LLM availability for the Tasks tab. The probe runs once
  // on mount and again when the page becomes visible; the Tasks tab and
  // its TabButton render only when the user has Chrome's Built-in AI
  // and is not on a touch-first device.
  const ai = useAiAvailability();
  // If the user is on the Tasks tab and the AI status flips to
  // unavailable mid-session, bounce them back to Calendar instead of
  // stranding them on a tab whose TabButton just disappeared.
  useEffect(() => {
    if (tab === "tasks" && ai.ready && !ai.supported) setTab("calendar");
  }, [tab, ai.ready, ai.supported]);

  // Tasks state. Loaded the first time the user opens the Tasks tab and
  // again after a scan completes. Snoozed/done tasks are excluded by
  // default on the server side.
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [scanOpen, setScanOpen] = useState(false);
  const [scanRange, setScanRange] = useState<ScanRange>("since-last-scan");
  const tasksLoadedRef = useRef(false);
  // refreshTasks is declared further down once `handle` exists. Hoisting
  // its dependencies here keeps the rest of the file readable.

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

  // Defined here (not where the tasks state is declared) because it
  // closes over `handle`, which itself depends on `onAuthLost`.
  const refreshTasks = useCallback(async () => {
    setTasksLoading(true);
    try {
      const out = await handle(() => api.listTasks());
      if (out) setTasks(out);
    } finally {
      setTasksLoading(false);
    }
  }, [handle]);

  useEffect(() => {
    if (tab !== "tasks") return;
    if (!ai.supported) return;
    if (tasksLoadedRef.current) return;
    tasksLoadedRef.current = true;
    refreshTasks();
  }, [tab, ai.supported, refreshTasks]);

  const refreshEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError(null);
    try {
      let list: AppEvent[] | undefined;
      if (allActive) {
        const out = await handle(() => api.eventsAll(days, fetchRange));
        if (out) {
          list = out.events;
          if (out.partial_failures.length > 0) {
            const names = out.partial_failures.map((f) => f.mailbox_email).join(", ");
            pushToast(
              "error",
              `${out.partial_failures.length} mailbox${out.partial_failures.length === 1 ? "" : "es"} failed to load (${names}).`,
            );
          }
        }
      } else {
        const raw = await handle(() => api.events(calendar || undefined, days, fetchRange));
        list = raw;
      }
      if (list) {
        const seenUids = new Set(list.map((e) => e.uid));
        // Server confirmed any pending UIDs that appear; drop them from pending.
        for (const uid of Array.from(pendingUidsRef.current.keys())) {
          if (seenUids.has(uid)) pendingUidsRef.current.delete(uid);
        }
        // Append still-pending optimistic events that the server hasn't picked
        // up yet, so they don't flicker off the calendar.
        const extras: AppEvent[] = [];
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
  }, [allActive, calendar, days, fetchRange, handle, pushToast]);

  const onSyncInvites = useCallback(async () => {
    if (syncingInvites) return;
    setSyncingInvites(true);
    try {
      const out = await handle(() =>
        api.syncInvites({ calendar: calendar || undefined })
      );
      if (!out) return;
      const c = out.counts;
      const total = c.created + c.updated + c.cancelled;
      if (total === 0 && c.error === 0) {
        pushToast("success", "No new invites to sync.");
      } else {
        const parts: string[] = [];
        if (c.created) parts.push(`${c.created} added`);
        if (c.updated) parts.push(`${c.updated} updated`);
        if (c.cancelled) parts.push(`${c.cancelled} cancelled`);
        if (c.error) parts.push(`${c.error} failed`);
        pushToast(c.error > 0 ? "error" : "success", `Synced: ${parts.join(", ")}.`);
      }
      refreshEvents();
    } catch (e: any) {
      pushToast("error", e?.message || "invite sync failed");
    } finally {
      setSyncingInvites(false);
    }
  }, [calendar, handle, pushToast, refreshEvents, syncingInvites]);

  // Load all of the user's mailboxes and decide which one is active. If the
  // stored activeMailboxId doesn't match any returned row (e.g. that mailbox
  // got removed elsewhere) we fall back to the first one.
  useEffect(() => {
    (async () => {
      try {
        const list = await handle(() => api.listMailboxes());
        if (!list) return;
        setMailboxes(list);
        if (list.length === 0) return;
        const stored = activeMailboxId;
        const valid = stored != null && list.some((m) => m.id === stored);
        if (!valid) {
          setActiveMailboxId(list[0].id);
        }
      } catch (e: any) {
        pushToast("error", `Accounts: ${e?.message || "could not load mailboxes"}`);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reload calendars + counts every time the active mailbox changes. The
  // server uses X-Mailbox-Id from localStorage (set synchronously by
  // setActiveMailboxId before we re-render), so re-running this effect is
  // enough to pull data for the newly-active mailbox.
  //
  // When the user picks "All accounts" we skip the per-mailbox calendar
  // dropdown entirely (the Header shows a static label instead) and let the
  // event-fetch effect pull /api/events/all directly.
  useEffect(() => {
    if (activeMailboxId == null) return;
    if (activeMailboxId === "all") {
      calendarSeededForRef.current = -1; // poison so a flip back re-seeds
      setCalendars([]);
      setEventCounts({});
      setCalendarState("");
      return;
    }
    if (calendarSeededForRef.current === activeMailboxId) return;
    calendarSeededForRef.current = activeMailboxId;
    (async () => {
      try {
        const c = await handle(() => api.calendars());
        if (!c) return;
        setCalendars(c);
        setEventCounts({});
        const activeMailbox = mailboxes.find((m) => m.id === activeMailboxId);
        // Per-mailbox preference wins. Otherwise the cached global choice if
        // it still exists. Otherwise we let the count probe below pick the
        // most-populated calendar.
        const preferred = activeMailbox?.selected_calendar || "";
        const cached = (typeof window !== "undefined" && localStorage.getItem("pmc.selectedCalendar")) || "";
        let initial = "";
        if (preferred && c.some((x) => x.name === preferred)) initial = preferred;
        else if (cached && c.some((x) => x.name === cached)) initial = cached;
        else if (c[0]) initial = c[0].name;
        if (initial) setCalendar(initial);

        const entries = await Promise.all(
          c.map(async (cal) => {
            try {
              const evList = await api.events(cal.name, 60);
              return [cal.name, evList.length] as const;
            } catch {
              return [cal.name, -1] as const;
            }
          })
        );
        const counts: Record<string, number> = {};
        for (const [n, v] of entries) counts[n] = v;
        setEventCounts(counts);
        // Only auto-pick the busiest calendar when neither a per-mailbox
        // preference nor a cached choice applied.
        if (!preferred && !cached) {
          const best = c
            .map((x) => ({ name: x.name, count: counts[x.name] ?? 0 }))
            .filter((x) => x.count > 0)
            .sort((a, b) => b.count - a.count)[0];
          if (best) setCalendar(best.name);
        }
      } catch (e: any) {
        pushToast("error", `Config: ${e?.message || "could not load calendars"}`);
      }
    })();
  }, [activeMailboxId, mailboxes, pushToast, handle, setCalendar]);

  useEffect(() => {
    refreshEvents();
  }, [refreshEvents]);

  const onCreateClick = () => {
    if (allActive) {
      pushToast(
        "error",
        "Pick a single account to create events. The Send-from picker arrives in the next update.",
      );
      return;
    }
    setForm({ open: true, mode: "create", initial: null });
  };
  const onCreateAt = (start: Date, durationMinutes?: number) => {
    if (allActive) {
      pushToast(
        "error",
        "Pick a single account to create events. The Send-from picker arrives in the next update.",
      );
      return;
    }
    setForm({
      open: true,
      mode: "create",
      initial: null,
      prefillStart: start,
      prefillDurationMinutes: durationMinutes ?? null,
    });
  };
  const onEditClick = (e: EventOut) => setForm({ open: true, mode: "edit", initial: e });

  /** Open the event form prefilled from a task. Defaults to tomorrow 9am
   * local when the task has no `due_at`, since Nano's date inference is
   * unreliable and we don't want to silently drop the task into a random
   * slot. The user can still adjust before submitting. */
  const openEventFormForTask = (task: TaskItem) => {
    let prefillStart: Date;
    if (task.due_at) {
      const d = new Date(task.due_at);
      prefillStart = isNaN(d.getTime()) ? defaultTomorrowMorning() : d;
    } else {
      prefillStart = defaultTomorrowMorning();
    }
    setForm({
      open: true,
      mode: "create",
      initial: null,
      prefillStart,
      prefillDurationMinutes: 60,
      prefillSummary: task.title,
      fromTaskId: task.id,
    });
  };

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
      bcc_invites: !!e.bcc_invites,
      uid: e.uid,
      sequence: e.sequence + 1,
    };
    try {
      const mailboxId = (e as AppEvent).mailbox_id;
      const r = await handle(() => api.updateEvent(e.uid, body, mailboxId != null ? { mailboxId } : undefined));
      if (!r) return;
      const optimistic = buildOptimisticEvent(body, r.uid, me);
      markPending(optimistic);
      setEvents((prev) => upsertEvent(prev, optimistic));
      pushToast("success", deliveryNote(r, `Moved. Update sent to ${r.sent_to.length}.`, "Moved."));
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
      bcc_invites: !!e.bcc_invites,
      uid: e.master_uid || e.uid,
      sequence: e.sequence + 1,
    };
    try {
      const mailboxId = (e as AppEvent).mailbox_id;
      const res = await handle(() =>
        api.cancelEvent(e.master_uid || e.uid, body, mailboxId != null ? { mailboxId } : undefined),
      );
      if (!res) return;
      clearPending(e.master_uid || e.uid);
      const masterUid = e.master_uid || e.uid;
      setEvents((prev) => prev.filter((x) => (x.master_uid || x.uid) !== masterUid));
      pushToast(
        "success",
        deliveryNote(
          res,
          `Cancelled. Notified ${res.sent_to.length} attendee${res.sent_to.length === 1 ? "" : "s"}.`,
          "Cancelled.",
        ),
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
      const mailboxId = (e as AppEvent).mailbox_id;
      const res = await handle(() =>
        api.cancelOccurrence(masterUid, e.start, mailboxId != null ? { mailboxId } : undefined),
      );
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
    // For edit, the mailbox is locked to whichever mailbox the event lives
    // on. We grab it from the original form initial event.
    const editMailboxId =
      mode === "edit" && form.open && form.mode === "edit"
        ? (form.initial as AppEvent).mailbox_id
        : undefined;
    if (mode === "create") {
      const fromTaskId =
        form.open && form.mode === "create" ? form.fromTaskId ?? null : null;
      const r = await handle(() => api.createEvent(payload));
      if (!r) return;
      const optimistic = buildOptimisticEvent(payload, r.uid, me);
      markPending(optimistic);
      setEvents((prev) => upsertEvent(prev, optimistic));
      pushToast(
        "success",
        r.dry_run
          ? `Created (dry run). UID ${r.uid.slice(0, 16)}…`
          : deliveryNote(
              r,
              `Sent invite to ${r.sent_to.length} attendee${r.sent_to.length === 1 ? "" : "s"}.`,
              `Created. UID ${r.uid.slice(0, 16)}…`,
            ),
      );
      // If this create was triggered from a task, stamp the resulting
      // event UID on the task so it stops appearing in the Tasks list.
      if (fromTaskId != null && !r.dry_run) {
        try {
          await handle(() => api.patchTask(fromTaskId, { as_event_uid: r.uid }));
          setTasks((prev) => prev.filter((t) => t.id !== fromTaskId));
        } catch {
          // Non-fatal: event is on the calendar; the task just won't be
          // auto-cleared. User can mark it done manually.
        }
      }
      // Best-effort: drop any new invitees into the automaticallyCollected
      // address book so they show up next time the user types. Mirrors
      // Purelymail webmail's behavior. Failures here never block the create
      // path; the event is already on CalDAV.
      if (!r.dry_run && payload.attendees && payload.attendees.length > 0) {
        api
          .contactsFromEvent(
            payload.attendees.map((a) => ({
              email: a.email,
              name: a.name || undefined,
            })),
          )
          .catch(() => {
            /* silent */
          });
      }
    } else {
      const r = await handle(() =>
        api.updateEvent(uid!, payload, editMailboxId != null ? { mailboxId: editMailboxId } : undefined),
      );
      if (!r) return;
      const optimistic = buildOptimisticEvent(payload, r.uid, me);
      markPending(optimistic);
      setEvents((prev) => upsertEvent(prev, optimistic));
      pushToast(
        "success",
        r.dry_run
          ? `Updated (dry run).`
          : deliveryNote(
              r,
              `Update sent to ${r.sent_to.length} attendee${r.sent_to.length === 1 ? "" : "s"}.`,
              "Updated.",
            ),
      );
      if (!r.dry_run && payload.attendees && payload.attendees.length > 0) {
        api
          .contactsFromEvent(
            payload.attendees.map((a) => ({
              email: a.email,
              name: a.name || undefined,
            })),
            editMailboxId != null ? { mailboxId: editMailboxId } : undefined,
          )
          .catch(() => {
            /* silent */
          });
      }
    }
    refreshEvents();
  };

  return (
    <div className="min-h-full">
      <Header
        me={me}
        mailboxes={mailboxes}
        activeMailboxId={activeMailboxId}
        onSwitchMailbox={(id) => {
          if (id === activeMailboxId) return;
          setActiveMailboxId(id);
          // Drop the previously-cached generic calendar choice so the per-
          // mailbox preference takes precedence when calendars reload.
          try { localStorage.removeItem("pmc.selectedCalendar"); } catch { /* ignore */ }
          setCalendarState("");
          setCalendars([]);
          setEventCounts({});
          setEvents([]);
        }}
        onAddAccount={() => setShowAddMailbox(true)}
        onChangeMailboxColor={(mailboxId, color) => {
          // Optimistic update first so the chip flips immediately.
          setMailboxes((prev) => prev.map((m) => (m.id === mailboxId ? { ...m, color } : m)));
          api
            .updateMailbox(mailboxId, { color })
            .then((updated) => {
              setMailboxes((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
            })
            .catch((e: any) => {
              pushToast("error", e?.message || "could not save color");
            });
        }}
        calendars={calendars}
        calendar={calendar}
        setCalendar={setCalendar}
        eventCounts={eventCounts}
        onNew={onCreateClick}
        onLogout={onSignOut}
        onSyncInvites={allActive ? undefined : onSyncInvites}
        syncingInvites={syncingInvites}
        onShowContacts={allActive ? undefined : () => setShowContacts(true)}
      />

      <div className="mx-auto max-w-6xl px-4">
        <QuietLoader active={eventsLoading} />
        <nav className="mt-4 flex gap-1 border-b border-accent-900/20">
          <TabButton active={tab === "calendar"} onClick={() => setTab("calendar")}>Calendar</TabButton>
          <TabButton active={tab === "events"} onClick={() => setTab("events")}>Events</TabButton>
          <TabButton active={tab === "rsvps"} onClick={() => setTab("rsvps")}>RSVPs</TabButton>
          {ai.ready && ai.supported && (
            <TabButton active={tab === "tasks"} onClick={() => setTab("tasks")}>Tasks (beta on Chrome)</TabButton>
          )}
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
          {tab === "tasks" && ai.supported && (
            <TasksView
              status={ai.status}
              mailboxCount={mailboxes.length}
              lastScannedAt={
                typeof activeMailboxId === "number"
                  ? mailboxes.find((m) => m.id === activeMailboxId)?.last_scanned_at ?? null
                  : null
              }
              tasks={tasks}
              loading={tasksLoading}
              onScan={(range) => {
                if (typeof activeMailboxId !== "number") {
                  pushToast("error", "Pick a single account from the switcher before scanning.");
                  return;
                }
                setScanRange(range);
                setScanOpen(true);
              }}
              onPickTime={(t) => openEventFormForTask(t)}
              onDone={async (t) => {
                setTasks((prev) => prev.filter((x) => x.id !== t.id));
                try {
                  await handle(() => api.patchTask(t.id, { done: true }));
                } catch (e: any) {
                  pushToast("error", e?.message || "could not mark done");
                  refreshTasks();
                }
              }}
              onSnooze={async (t, days) => {
                const until = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
                setTasks((prev) => prev.filter((x) => x.id !== t.id));
                try {
                  await handle(() => api.patchTask(t.id, { snoozed_until: until }));
                } catch (e: any) {
                  pushToast("error", e?.message || "could not snooze");
                  refreshTasks();
                }
              }}
              onDismiss={async (t) => {
                setTasks((prev) => prev.filter((x) => x.id !== t.id));
                try {
                  await handle(() => api.deleteTask(t.id));
                } catch (e: any) {
                  pushToast("error", e?.message || "could not dismiss");
                  refreshTasks();
                }
              }}
            />
          )}
        </main>

        <footer className="mt-12 border-t border-accent-900/20 pt-6 pb-10">
          <p className="font-serif text-sm italic leading-relaxed text-ink-700">
            Purelymail Calendar is served from a single Python container on
            Railway, with calendar storage on Purelymail's CalDAV. Source on
            GitHub. Reproducible via the public image at
            ghcr.io/bhartiyashesh/purelymailcalendar.
          </p>
          <div className="mt-4 flex flex-col items-start gap-2">
            <UnofficialNote />
            <RunningSha />
          </div>
        </footer>
      </div>

      {form.open && (
        <EventForm
          mode={form.mode}
          initial={form.mode === "edit" ? form.initial : null}
          prefillStart={form.mode === "create" ? form.prefillStart ?? null : null}
          prefillDurationMinutes={form.mode === "create" ? form.prefillDurationMinutes ?? null : null}
          prefillSummary={form.mode === "create" ? form.prefillSummary ?? null : null}
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

      {showAddMailbox && (
        <AddMailboxModal
          onClose={() => setShowAddMailbox(false)}
          onAdded={(mb) => {
            setShowAddMailbox(false);
            setMailboxes((prev) => {
              if (prev.some((x) => x.id === mb.id)) return prev;
              return [...prev, mb];
            });
            // Switch into the freshly-connected mailbox.
            setActiveMailboxId(mb.id);
            try { localStorage.removeItem("pmc.selectedCalendar"); } catch { /* ignore */ }
            setCalendarState("");
            setCalendars([]);
            setEventCounts({});
            setEvents([]);
            pushToast("success", `Connected ${mb.email}.`);
          }}
        />
      )}

      {showContacts && (
        <ContactsPanel
          onClose={() => setShowContacts(false)}
          activeMailbox={
            typeof activeMailboxId === "number"
              ? mailboxes.find((m) => m.id === activeMailboxId) || null
              : null
          }
        />
      )}

      {scanOpen && typeof activeMailboxId === "number" && (() => {
        const activeMb = mailboxes.find((m) => m.id === activeMailboxId);
        const useIncremental =
          scanRange === "since-last-scan" && !!activeMb?.last_scanned_at;
        const sinceDays =
          scanRange === "since-last-scan" ? 14 : Number(scanRange);
        return (
          <AiScanModal
            activeMailboxId={activeMailboxId}
            sinceIso={useIncremental ? activeMb!.last_scanned_at ?? null : null}
            sinceDays={sinceDays}
            onClose={() => setScanOpen(false)}
            onComplete={(written) => {
              pushToast(
                "success",
                written === 0
                  ? "Scan finished. No new tasks found."
                  : `Scan finished. ${written} task${written === 1 ? "" : "s"} found.`,
              );
              refreshTasks();
              // Stamp last_scanned_at so the next Fetch can default to
              // an incremental window. Best-effort; UI does not need to
              // block on this.
              api
                .markScanComplete(activeMailboxId)
                .then((updated) => {
                  setMailboxes((prev) =>
                    prev.map((m) => (m.id === updated.id ? updated : m)),
                  );
                })
                .catch(() => { /* ignore */ });
            }}
          />
        );
      })()}

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
      className={`-mb-px border-b px-3 py-2 font-serif text-xs uppercase tracking-[0.25em] transition-colors ${
        active
          ? "border-accent-900 text-accent-900"
          : "border-transparent text-accent-900/55 hover:text-accent-900"
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

function defaultTomorrowMorning(): Date {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(9, 0, 0, 0);
  return d;
}

function deliveryNote(
  r: { sent_to: string[]; failed_to?: string[] },
  sentText: string,
  noneText: string,
): string {
  const failed = r.failed_to ?? [];
  if (r.sent_to.length && failed.length) return `${sentText} Could not reach ${failed.join(", ")}.`;
  if (failed.length) return `Could not reach ${failed.join(", ")}.`;
  if (r.sent_to.length) return sentText;
  return noneText;
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
    bcc_invites: !!payload.bcc_invites,
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
