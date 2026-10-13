/**
 * Theme choice (Light / Dark / System). "System" removes data-theme so the prefers-color-scheme
 * tokens in tokens.css apply. The choice is applied before first paint by THEME_INIT_SCRIPT
 * (inlined in the root layout), so there is no flash; storage is optional throughout.
 */
export const THEME_KEY = "foresight-theme";
export const THEME_CHOICES = ["light", "dark", "system"] as const;
export type ThemeChoice = (typeof THEME_CHOICES)[number];

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return typeof value === "string" && (THEME_CHOICES as readonly string[]).includes(value);
}

export function applyTheme(choice: ThemeChoice, root: HTMLElement = document.documentElement) {
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  root.dataset.themeChoice = choice;
}

export function readTheme(): ThemeChoice {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function saveTheme(choice: ThemeChoice) {
  try {
    localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Storage unavailable: the choice still applies for this page view.
  }
}

// The key is written literally (it must stay equal to THEME_KEY; a test checks it) so no value
// is interpolated into script source.
/** Runs in <head> before paint. `?theme=dark|light|system` overrides and is remembered. */
export const THEME_INIT_SCRIPT = `(function(){try{var k="foresight-theme",c=["light","dark","system"],u=new URLSearchParams(location.search).get("theme"),s=null;try{s=localStorage.getItem(k)}catch(e){}var v=c.indexOf(u)>=0?u:s;if(c.indexOf(v)<0)v="system";if(u&&c.indexOf(u)>=0){try{localStorage.setItem(k,u)}catch(e){}}var r=document.documentElement;if(v==="system")r.removeAttribute("data-theme");else r.setAttribute("data-theme",v);r.dataset.themeChoice=v}catch(e){}})();`;
