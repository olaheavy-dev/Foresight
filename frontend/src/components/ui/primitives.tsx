import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { Icon, type IconName } from "@/components/icons/Icon";

export type Tone = "blue" | "green" | "red" | "amber" | "violet" | "grey";

/** Tinted circular icon holder (Atelier light). */
export function IconChip({
  icon,
  tone = "blue",
  size = "md",
}: {
  icon: IconName;
  tone?: Tone | "plain";
  size?: "sm" | "md";
}) {
  const toneClass = tone === "blue" ? "" : tone === "grey" ? "plain" : tone;
  return (
    <span className={["icon-chip", size === "sm" ? "sm" : "", toneClass].filter(Boolean).join(" ")}>
      <Icon name={icon} />
    </span>
  );
}

/** Status label: Checked / Rejected / Below buffer / Upcoming / Not shipped yet. */
export function Badge({ tone = "blue", icon, children }: { tone?: Tone; icon?: IconName; children: ReactNode }) {
  return (
    <span className={`badge ${tone}`}>
      {icon ? <Icon name={icon} /> : null}
      {children}
    </span>
  );
}

type ButtonLook = { variant?: "primary" | "secondary"; size?: "md" | "lg"; icon?: IconName; iconEnd?: IconName };

export function buttonClass({ variant = "secondary", size = "md" }: ButtonLook, extra?: string) {
  return ["btn", variant === "primary" ? "primary" : "", size === "lg" ? "lg" : "", extra ?? ""]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  variant,
  size,
  icon,
  iconEnd,
  className,
  children,
  type = "button",
  ...rest
}: ButtonLook & ComponentProps<"button">) {
  return (
    <button type={type} className={buttonClass({ variant, size }, className)} {...rest}>
      {icon ? <Icon name={icon} /> : null}
      {children}
      {iconEnd ? <Icon name={iconEnd} /> : null}
    </button>
  );
}

export function ButtonLink({
  variant,
  size,
  icon,
  iconEnd,
  className,
  children,
  href,
  ...rest
}: ButtonLook & ComponentProps<typeof Link>) {
  return (
    <Link href={href} className={buttonClass({ variant, size }, className)} {...rest}>
      {icon ? <Icon name={icon} /> : null}
      {children}
      {iconEnd ? <Icon name={iconEnd} /> : null}
    </Link>
  );
}

/** White rounded card with a hairline border. */
export function Card({ className, children, ...rest }: ComponentProps<"article">) {
  return (
    <article className={["card", className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </article>
  );
}

export function CardHead({
  icon,
  title,
  sub,
  titleId,
  level = 2,
  aside,
}: {
  icon: IconName;
  title: string;
  sub?: ReactNode;
  titleId?: string;
  level?: 2 | 3;
  aside?: ReactNode;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div className="card-head">
      <Icon name={icon} className="icon-bare" />
      <div>
        <Heading className="card-title" id={titleId}>
          {title}
        </Heading>
        {sub ? <p className="card-sub">{sub}</p> : null}
      </div>
      {aside}
    </div>
  );
}
