export type AccessMode = "edit" | "view";

export const ACCESS_MODE_KEY = "pp1AccessMode";

export function getStoredAccessMode(): AccessMode {
  if (typeof window === "undefined") return "edit";
  return window.localStorage.getItem(ACCESS_MODE_KEY) === "view" ? "view" : "edit";
}

export function setStoredAccessMode(mode: AccessMode) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(ACCESS_MODE_KEY, mode);
}

export function isReadOnlyMode(): boolean {
  return getStoredAccessMode() === "view";
}

