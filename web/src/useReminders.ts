import { useEffect, useRef } from "react";
import type { EventOut, ReminderOut } from "./types";

type FireFn = (ev: EventOut, reminder: ReminderOut, offsetText: string) => void;

const MAX_SETTIMEOUT_MS = 2_147_000_000; // ~24.8 days

export function useReminders(events: EventOut[], onFire: FireFn) {
  const firedRef = useRef<Set<string>>(new Set());
  const timersRef = useRef<number[]>([]);
  const onFireRef = useRef(onFire);
  onFireRef.current = onFire;

  useEffect(() => {
    if (typeof window === "undefined") return;
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => undefined);
    }
  }, []);

  useEffect(() => {
    timersRef.current.forEach((id) => clearTimeout(id));
    timersRef.current = [];

    const now = Date.now();
    for (const ev of events) {
      const reminders = (ev.reminders || []).filter((r) => r.action === "DISPLAY");
      if (reminders.length === 0) continue;
      const startMs = new Date(ev.start).getTime();
      if (Number.isNaN(startMs)) continue;

      for (const r of reminders) {
        const fireAt = startMs - r.minutes_before * 60_000;
        const delay = fireAt - now;
        const key = `${ev.uid}|${r.minutes_before}|${r.action}`;
        if (firedRef.current.has(key)) continue;
        if (delay <= 0) continue; // already past; don't surprise the user
        if (delay > MAX_SETTIMEOUT_MS) continue;

        const id = window.setTimeout(() => {
          firedRef.current.add(key);
          const offsetText = r.minutes_before === 0
            ? "now"
            : r.minutes_before < 60
            ? `in ${r.minutes_before} min`
            : r.minutes_before % 60 === 0
            ? `in ${r.minutes_before / 60}h`
            : `in ~${Math.round(r.minutes_before)} min`;
          onFireRef.current(ev, r, offsetText);
        }, delay);
        timersRef.current.push(id);
      }
    }

    return () => {
      timersRef.current.forEach((id) => clearTimeout(id));
      timersRef.current = [];
    };
  }, [events]);
}
