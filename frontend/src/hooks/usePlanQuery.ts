import { useEffect, useState } from "react";
import { useDataStore } from "../stores/useDataStore";

export function usePlanKey(): string {
  return useDataStore((state) => JSON.stringify([state.datasetId, state.planRevision]));
}

/** Never render or accept results belonging to another plan or parameter set. */
export function usePlanQuery<T>(parameters: string, load: () => Promise<T>) {
  const plan = usePlanKey();
  const key = JSON.stringify([plan, parameters]);
  const [result, setResult] = useState<{ key: string; data?: T; error?: string } | null>(null);
  useEffect(() => {
    let current = true;
    load().then(
      (data) => { if (current) setResult({ key, data }); },
      (error) => { if (current) setResult({ key, error: String(error) }); },
    );
    return () => { current = false; };
  }, [key, load]);
  return { data: result?.key === key ? result.data ?? null : null,
    error: result?.key === key ? result.error ?? null : null };
}
