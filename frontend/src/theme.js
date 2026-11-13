import { useEffect, useState } from "react";

// Light, dark, or follow the operating system. The choice is saved in this browser only.
const KEY = "airport-taxi.theme";
export const THEME_CHOICES = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function savedChoice() {
  try {
    const value = localStorage.getItem(KEY);
    return THEME_CHOICES.some((t) => t.value === value) ? value : "system";
  } catch {
    return "system";
  }
}

// Sets data-theme on <html>, which the stylesheet reads.
function applyTheme(choice) {
  const dark = choice === "dark" || (choice === "system" && media?.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function useTheme() {
  const [choice, setChoice] = useState(savedChoice);

  useEffect(() => {
    applyTheme(choice);
    if (choice !== "system" || !media) return undefined;
    const follow = () => applyTheme("system");
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [choice]);

  function change(next) {
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* storage blocked: the choice still applies for this visit */
    }
    setChoice(next);
  }

  return { choice, change };
}
