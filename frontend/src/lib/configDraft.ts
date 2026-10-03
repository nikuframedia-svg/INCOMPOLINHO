export function remainingDraft<T>(current: Record<string, T>, applied: Record<string, T>): Record<string, T> {
  return Object.fromEntries(Object.entries(current).filter(([key, value]) => (
    !Object.hasOwn(applied, key) || !Object.is(value, applied[key])
  )));
}

export function remainingToolDraft(
  current: Record<string, { setup_hours?: number; alt?: string | null }>,
  applied: Record<string, { setup_hours?: number; alt?: string | null }>,
) {
  return Object.fromEntries(Object.entries(current).flatMap(([key, value]) => {
    const remaining = remainingDraft(value, applied[key] ?? {});
    return Object.keys(remaining).length ? [[key, remaining]] : [];
  }));
}
