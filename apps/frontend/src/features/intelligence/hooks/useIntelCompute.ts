import { useEffect, useMemo, useState } from 'react';
import type { NikufraData } from '../../../domain/nikufra-types';
import { useDataStore } from '../../../stores/useDataStore';
import { nikufraDataToNkData, nikufraDataToSnapshot } from '../intel-adapter';
import { computeAll, type IntelData, type NkData, type SnapshotFixture } from '../intel-compute';

export interface IntelComputeResult {
  data: IntelData | null;
  snap: SnapshotFixture | null;
  loading: boolean;
  error: string | null;
}

export function useIntelCompute(): IntelComputeResult {
  const [snap, setSnap] = useState<SnapshotFixture | null>(null);
  const [nk, setNk] = useState<NkData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const nikufraData = useDataStore((s) => s.nikufraData);
  const trustScore = useDataStore((s) => s.meta?.trustScore);

  useEffect(() => {
    setLoading(true);
    setError(null);

    const load = async (): Promise<NikufraData> => {
      if (nikufraData) return nikufraData;
      const r = await fetch('/fixtures/nikufra/nikufra_data.json');
      if (!r.ok) throw new Error(`NikufraData: ${r.status}`);
      return r.json() as Promise<NikufraData>;
    };

    load()
      .then((d) => {
        setNk(nikufraDataToNkData(d));
        if (d.operations && d.operations.length > 0) {
          setSnap(nikufraDataToSnapshot(d, trustScore ?? undefined));
        } else {
          setSnap(null);
        }
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Unknown error');
        setLoading(false);
      });
  }, [nikufraData, trustScore]);

  const data = useMemo<IntelData | null>(() => {
    if (!nk) return null;
    return computeAll(snap, nk);
  }, [snap, nk]);

  return { data, snap, loading, error };
}
