"use client";

import { useEffect } from "react";

/**
 * Opens and scrolls to the run a link names (`/activity#run-…`, Home's "How it was checked"), so
 * the evidence chain lands on that run's trace rather than the top of the feed.
 */
export function OpenLinkedRun() {
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (!id.startsWith("run-")) return;
    const item = document.getElementById(id);
    const details = item?.querySelector("details");
    if (details) details.open = true;
    item?.scrollIntoView({ block: "start" });
  }, []);
  return null;
}
