import { useEffect, useState } from "react";

/**
 * Which day the "Hoje" console shows.
 *
 * A fresh page always opens on the server's today (GET /api/data/today).
 * A day the planner picks by hand is kept only in this tab (sessionStorage)
 * and only while it is still the same day. Older versions kept the last day
 * in localStorage for good, so a console opened on a Sunday kept opening on
 * that Sunday (usage of 12/10/2026); that value is ignored and removed.
 */
export const CONSOLE_DAY_KEY = "pp1ConsoleDay";
export const LEGACY_CONSOLE_DAY_KEY = "pp1ConsoleLastDay";

export type ServerToday = { today_idx: number; date: string };

export type ConsoleDayChoice = {
  /** Server's today (GET /api/data/today) when the day was picked. */
  today: string;
  /** Browser's date when the day was picked: a tab left open overnight starts on today again. */
  local: string;
  /** Picked date; null for the preparation days before the horizon. */
  date: string | null;
  /** Picked day index (only used for the preparation days, which have no date). */
  day: number;
};

/** Browser's calendar date as YYYY-MM-DD. */
export function localDate(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function isChoice(value: unknown): value is ConsoleDayChoice {
  if (!value || typeof value !== "object") return false;
  const item = value as Record<string, unknown>;
  return typeof item.today === "string"
    && typeof item.local === "string"
    && (item.date === null || typeof item.date === "string")
    && typeof item.day === "number"
    && Number.isInteger(item.day);
}

/** The day picked earlier in this tab, if any. Also drops the old localStorage value. */
export function readConsoleDayChoice(): ConsoleDayChoice | null {
  try {
    window.localStorage.removeItem(LEGACY_CONSOLE_DAY_KEY);
  } catch {
    // Storage can be disabled; the old value is ignored either way.
  }
  try {
    const raw = window.sessionStorage.getItem(CONSOLE_DAY_KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    return isChoice(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Keep (or forget, with null) the picked day for this tab only. */
export function rememberConsoleDayChoice(choice: ConsoleDayChoice | null) {
  try {
    if (choice) window.sessionStorage.setItem(CONSOLE_DAY_KEY, JSON.stringify(choice));
    else window.sessionStorage.removeItem(CONSOLE_DAY_KEY);
  } catch {
    // Best effort only. Navigation must keep working if storage is unavailable.
  }
}

/**
 * The day to show: the picked day while it is still the same day (for the
 * server and for the browser) and the date is in this plan; otherwise today.
 */
export function resolveConsoleDay(
  choice: ConsoleDayChoice | null,
  today: ServerToday,
  workdays: string[],
  local: string = localDate(),
): number {
  if (!choice || choice.today !== today.date || choice.local !== local) return today.today_idx;
  if (choice.date !== null) {
    const idx = workdays.indexOf(choice.date);
    return idx >= 0 ? idx : today.today_idx;
  }
  return choice.day < 0 ? choice.day : today.today_idx;
}

/**
 * Browser's date, refreshed when the tab comes back into view and once a
 * minute, so a console left open overnight moves to the new day.
 */
export function useLocalDate(): string {
  const [value, setValue] = useState(() => localDate());
  useEffect(() => {
    const check = () => setValue(localDate());
    const timer = window.setInterval(check, 60_000);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, []);
  return value;
}
