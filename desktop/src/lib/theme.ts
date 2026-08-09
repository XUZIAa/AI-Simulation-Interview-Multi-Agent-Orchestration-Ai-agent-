export type ThemeMode = "light" | "dark" | "system";

const STORAGE_KEY = "interviewer.theme";

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function readTheme(): ThemeMode {
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved === "light" || saved === "dark" || saved === "system" ? saved : "system";
}

export function applyTheme(mode: ThemeMode): void {
  const dark = mode === "dark" || (mode === "system" && systemPrefersDark());
  document.documentElement.classList.toggle("dark", dark);
  localStorage.setItem(STORAGE_KEY, mode);
}

/** 跟随系统时要响应系统切换，否则用户改了外观这边不动。 */
export function watchSystemTheme(onChange: () => void): () => void {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const handler = () => {
    if (readTheme() === "system") onChange();
  };
  query.addEventListener("change", handler);
  return () => query.removeEventListener("change", handler);
}
