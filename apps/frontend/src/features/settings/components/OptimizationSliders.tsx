import { useCallback, useEffect, useRef } from 'react';
import type { ConfigWeights } from '../useConfigPreview';
import { useConfigPreview } from '../useConfigPreview';

const SLIDER_KEYS: { key: keyof ConfigWeights; label: string }[] = [
  { key: 'otd', label: 'OTD (entrega)' },
  { key: 'setup', label: 'Min. Setups' },
  { key: 'utilization', label: 'Utilizacao' },
];

export function OptimizationSliders() {
  const weights = useConfigPreview((s) => s.weights);
  const setWeight = useConfigPreview((s) => s.setWeight);
  const previewKpis = useConfigPreview((s) => s.previewKpis);
  const isComputing = useConfigPreview((s) => s.isComputing);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const handleChange = useCallback(
    (key: keyof ConfigWeights, raw: number) => {
      // Normalize: ensure all 3 sum to 100
      const others = SLIDER_KEYS.filter((s) => s.key !== key);
      const remaining = 100 - raw;
      const otherSum = others.reduce((acc, s) => acc + weights[s.key], 0);

      if (otherSum === 0) {
        // Split remaining equally
        const each = Math.round(remaining / 2);
        setWeight(key, raw);
        setWeight(others[0].key, each);
        setWeight(others[1].key, remaining - each);
      } else {
        // Scale others proportionally
        const scale = remaining / otherSum;
        setWeight(key, raw);
        const first = Math.round(weights[others[0].key] * scale);
        setWeight(others[0].key, first);
        setWeight(others[1].key, remaining - first);
      }

      // Debounce preview recomputation
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        // Parent will handle recomputation via store subscription
      }, 300);
    },
    [weights, setWeight],
  );

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const total = weights.otd + weights.setup + weights.utilization;

  return (
    <div className="opt-sliders" data-testid="optimization-sliders">
      {SLIDER_KEYS.map(({ key, label }) => (
        <div className="opt-sliders__row" key={key}>
          <span className="opt-sliders__label">{label}</span>
          <input
            type="range"
            min={0}
            max={100}
            value={weights[key]}
            onChange={(e) => handleChange(key, Number(e.target.value))}
            className="opt-sliders__track"
            data-testid={`slider-${key}`}
          />
          <span className="opt-sliders__value">{weights[key]}%</span>
        </div>
      ))}

      {Math.abs(total - 100) > 1 && (
        <div className="opt-sliders__impact opt-sliders__impact--stale">
          Total: {total}% (deve somar 100%)
        </div>
      )}

      {isComputing && (
        <div className="opt-sliders__impact opt-sliders__impact--stale">
          A recalcular schedule...
        </div>
      )}

      {previewKpis && !isComputing && (
        <div className="opt-sliders__impact" data-testid="sliders-impact">
          OTD {previewKpis.otdPct.toFixed(1)}% · Tardiness {previewKpis.avgTardinessDays.toFixed(1)}
          d · Setups {Math.round(previewKpis.totalSetupMin)}min
        </div>
      )}
    </div>
  );
}
