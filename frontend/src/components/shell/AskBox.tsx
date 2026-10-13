"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { Icon } from "@/components/icons/Icon";

/** "Ask Foresight about your finances…" — opens the AI Workspace with the question. */
export function AskBox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = q.trim();
    router.push(text ? `/workspace?q=${encodeURIComponent(text)}` : "/workspace");
  };
  return (
    <form className="search" role="search" onSubmit={submit}>
      <Icon name="search" />
      <label className="sr-only" htmlFor="ask-box">
        Ask Foresight about your finances
      </label>
      <input
        id="ask-box"
        type="search"
        placeholder="Ask Foresight about your finances…"
        value={q}
        maxLength={2000}
        onChange={(e) => setQ(e.target.value)}
      />
    </form>
  );
}
