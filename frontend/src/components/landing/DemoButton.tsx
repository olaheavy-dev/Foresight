"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/primitives";
import { startDemo } from "@/lib/api";

/** Opens the read-only demo profile (sets the session cookie), then goes to Home. */
export function DemoButton({ label = "Explore the live demo" }: { label?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const go = async () => {
    setBusy(true);
    setFailed(false);
    const profile = await startDemo("P1");
    if (profile) {
      router.push("/home");
      return;
    }
    setBusy(false);
    setFailed(true);
  };
  return (
    <>
      <Button variant="primary" size="lg" iconEnd="arrowright" onClick={go} aria-busy={busy} disabled={busy}>
        {busy ? "Opening the demo…" : label}
      </Button>
      {failed ? (
        <p className="form-error" role="alert">
          The demo couldn’t be opened just now. Please try again.
        </p>
      ) : null}
    </>
  );
}
