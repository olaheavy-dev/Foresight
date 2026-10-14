/** "Good morning" etc. and today's date, in the profile's own time zone. */
export function greeting(now: Date, timeZone: string, locale = "en-GB") {
  let hour = now.getUTCHours();
  try {
    hour = Number(new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone }).format(now));
  } catch {
    // Unknown time zone: fall back to UTC.
  }
  const part = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  let date: string;
  try {
    date = new Intl.DateTimeFormat(locale, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone,
    }).format(now);
  } catch {
    date = new Intl.DateTimeFormat(locale, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(now);
  }
  return { part, date };
}

export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}
