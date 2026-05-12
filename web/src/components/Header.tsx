import { useEffect, useRef, useState } from "react";
import type { CalendarSummary, Me } from "../types";

type Props = {
  me: Me;
  calendars: CalendarSummary[];
  calendar: string;
  setCalendar: (n: string) => void;
  eventCounts?: Record<string, number>;
  onNew: () => void;
  onLogout: () => void;
};

export function Header({ me, calendars, calendar, setCalendar, eventCounts = {}, onNew, onLogout }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    if (menuOpen) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuOpen]);

  const initials = (me.display_name || me.email).slice(0, 2).toUpperCase();

  return (
    <header className="sticky top-0 z-30 border-b border-ink-200 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <div className="flex items-center gap-2">
          <img src="/logo.png" alt="" className="h-8 w-8" />
          <span className="text-sm font-semibold tracking-tight">Purelymail Calendar</span>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-3">
          <a
            href="https://inbox.purelymail.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden text-sm font-medium uppercase tracking-wide text-accent-700 hover:text-accent-900 sm:inline-block"
          >
            Webmail
          </a>
          <div className="hidden sm:block">
            <label className="text-[10px] font-medium uppercase tracking-wide text-ink-500">Calendar</label>
            <select
              value={calendar}
              onChange={(e) => setCalendar(e.target.value)}
              className="ml-2 rounded-md border border-ink-200 bg-white px-2 py-1 text-sm shadow-sm focus:border-accent-500 focus:outline-none focus:ring-1 focus:ring-accent-500"
            >
              {calendars.length === 0 && <option value="">(default)</option>}
              {calendars.map((c) => {
                const count = eventCounts[c.name];
                const suffix =
                  count === undefined || count < 0 ? "" : ` (${count})`;
                return (
                  <option key={c.name} value={c.name}>
                    {c.name}{suffix}
                  </option>
                );
              })}
            </select>
          </div>
          <button onClick={onNew} className="btn-primary">+ New event</button>
          <div ref={menuRef} className="relative">
            <button
              onClick={() => setMenuOpen((v) => !v)}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-ink-200 text-xs font-semibold text-ink-700 hover:bg-ink-300"
              aria-label="user menu"
            >
              {initials}
            </button>
            {menuOpen && (
              <div className="absolute right-0 mt-2 w-56 overflow-hidden rounded-md border border-ink-200 bg-white shadow-lg">
                <div className="border-b border-ink-100 px-3 py-2">
                  <div className="truncate text-sm font-medium text-ink-800">{me.display_name || me.email}</div>
                  {me.display_name && <div className="truncate text-xs text-ink-500">{me.email}</div>}
                </div>
                <button
                  onClick={onLogout}
                  className="block w-full px-3 py-2 text-left text-sm text-ink-700 hover:bg-ink-50"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
