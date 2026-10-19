import { useCallback, useEffect, useState } from "react";
import type { Category, Session } from "../types/api";

export interface Selection {
  category: Category;
  session: Session;
  /** null = "today" (resolved from the server's IST date) */
  date: string | null;
  compare: boolean;
}

const CATS: Category[] = ["small-cap", "mid-cap", "large-cap"];
const SESS: Session[] = ["morning", "afternoon"];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function read(): Selection {
  const p = new URLSearchParams(window.location.search);
  const cat = p.get("category") as Category;
  const ses = p.get("session") as Session;
  const date = p.get("date");
  return {
    category: CATS.includes(cat) ? cat : "large-cap",
    session: SESS.includes(ses) ? ses : defaultSession(),
    date: date && DATE_RE.test(date) ? date : null,
    compare: p.get("compare") === "1",
  };
}

/** Before 15:00 IST the afternoon scan cannot exist yet, so default to the morning snapshot. */
function defaultSession(): Session {
  const hhmm = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false })
    .format(new Date())
    .replace(":", "");
  return Number(hhmm) >= 1500 ? "afternoon" : "morning";
}

function write(s: Selection) {
  const p = new URLSearchParams();
  p.set("category", s.category);
  p.set("session", s.session);
  if (s.date) p.set("date", s.date);
  if (s.compare) p.set("compare", "1");
  const url = `${window.location.pathname}?${p.toString()}`;
  if (url !== window.location.pathname + window.location.search) window.history.pushState(null, "", url);
}

/** Selection state mirrored to the URL, so views are linkable and Back/Forward work. Changing one
 *  field never resets the others (e.g. switching category keeps the date and session). */
export function useSelection() {
  const [sel, setSel] = useState<Selection>(read);

  useEffect(() => {
    const onPop = () => setSel(read());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const update = useCallback((patch: Partial<Selection>) => {
    setSel((prev) => {
      const next = { ...prev, ...patch };
      write(next);
      return next;
    });
  }, []);

  return [sel, update] as const;
}
