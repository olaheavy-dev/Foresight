import type { ReactNode } from "react";
import { NotShipped } from "@/components/ui/NotShipped";

/** A section from the IA whose feature is not shipped yet: title, purpose, honest state. */
export function SectionPage({
  title,
  lede,
  what,
  children,
}: {
  title: string;
  lede: string;
  what: string;
  children?: ReactNode;
}) {
  return (
    <main className="page section-page" id="main">
      <h1>{title}</h1>
      <p className="lede">{lede}</p>
      <NotShipped title={what} />
      {children}
    </main>
  );
}
