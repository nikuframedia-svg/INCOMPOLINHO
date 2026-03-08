import { useState } from 'react';
import { C } from '../../../lib/engine';
import { useIntelCompute } from '../hooks/useIntelCompute';
import '../NikufraIntel.css';
import { type IntelTab, mono, TABS } from './intel-helpers';
import { BottleneckView } from './tabs/BottleneckCascadeTab';
import { HorizonView } from './tabs/CapacityHorizonTab';
import { RiskView } from './tabs/ClientRiskTab';
import { CrossClientView } from './tabs/CrossClientTab';
import { HeatmapView } from './tabs/DemandHeatmapTab';
import { ExplainView } from './tabs/ExplainTraceTab';
import { NetworkView } from './tabs/MachineNetworkTab';
import { SetupCrewView } from './tabs/SetupCrewTimelineTab';
import { ToolGroupView } from './tabs/ToolGroupingTab';
import { UrgencyView } from './tabs/UrgencyMatrixTab';

const snapTabs = new Set<IntelTab>([
  'heatmap',
  'horizon',
  'urgency',
  'risk',
  'crossclient',
  'bottleneck',
  'network',
  'explain',
]);

export function IntelligencePage() {
  const [tab, setTab] = useState<IntelTab>('heatmap');
  const { data, snap, loading, error } = useIntelCompute();

  if (loading) {
    return (
      <div className="ni-shell" style={{ padding: '16px 20px' }}>
        <h1
          style={{
            color: C.t1,
            fontSize: 22,
            fontWeight: 600,
            margin: 0,
            letterSpacing: '-0.02em',
          }}
        >
          NIKUFRA INTELLIGENCE
        </h1>
        <p className="page-desc">
          Análise avançada: padrões de procura, gargalos, risco por cliente e oportunidades de
          optimização.
        </p>
        <div className="ni-loading" style={{ marginTop: 40 }}>
          <div className="ni-loading__spinner" />
          <span className="ni-loading__text">
            A calcular intelligence a partir dos dados ISOP...
          </span>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="ni-shell" style={{ padding: '16px 20px' }}>
        <h1
          style={{
            color: C.t1,
            fontSize: 22,
            fontWeight: 600,
            margin: 0,
            letterSpacing: '-0.02em',
          }}
        >
          NIKUFRA INTELLIGENCE
        </h1>
        <p className="page-desc">
          Análise avançada: padrões de procura, gargalos, risco por cliente e oportunidades de
          optimização.
        </p>
        <div className="ni-error" style={{ marginTop: 40 }}>
          <div className="ni-error__icon">!</div>
          <div className="ni-error__msg">
            {error ||
              'Sem dados disponíveis. Verifique se os ficheiros ISOP foram importados correctamente.'}
          </div>
          <button className="ni-error__retry" onClick={() => window.location.reload()}>
            Tentar novamente
          </button>
        </div>
      </div>
    );
  }

  const views: Record<IntelTab, React.ReactNode> = {
    heatmap: <HeatmapView data={data} />,
    horizon: <HorizonView data={data} />,
    urgency: <UrgencyView data={data} />,
    risk: <RiskView data={data} />,
    crossclient: <CrossClientView data={data} />,
    bottleneck: <BottleneckView data={data} />,
    setup: <SetupCrewView data={data} />,
    toolgroup: <ToolGroupView data={data} />,
    network: <NetworkView data={data} />,
    explain: <ExplainView data={data} />,
  };

  return (
    <div
      className="ni-shell"
      style={{ background: C.bg, minHeight: '100vh', padding: '16px 20px' }}
    >
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 4 }}>
          <h1
            style={{
              color: C.t1,
              fontSize: 22,
              fontWeight: 600,
              margin: 0,
              letterSpacing: '-0.02em',
            }}
          >
            NIKUFRA INTELLIGENCE
          </h1>
          <span style={{ color: C.t4, fontSize: 11 }}>100% dados reais ISOP</span>
        </div>
        <p className="page-desc" style={{ marginBottom: 8 }}>
          Análise avançada: padrões de procura, gargalos, risco por cliente e oportunidades de
          optimização.
        </p>
        <div style={{ display: 'flex', gap: 16, color: C.t3, fontSize: 11, ...mono }}>
          <span>{data.machines.length} machines</span>
          <span>{data.explain.length} SKUs</span>
          <span>{data.workingDates.length} working days</span>
          <span>{data.crossClient.length} cross-client SKUs</span>
        </div>
      </div>

      <div
        style={{ display: 'flex', gap: 4, marginBottom: 20, overflowX: 'auto', paddingBottom: 4 }}
      >
        {TABS.map((t) => {
          const disabled = !snap && snapTabs.has(t.key);
          return (
            <button
              key={t.key}
              onClick={() => !disabled && setTab(t.key)}
              style={{
                padding: '7px 14px',
                borderRadius: 8,
                border: 'none',
                background: tab === t.key ? C.acS : 'transparent',
                color: disabled ? C.t4 : tab === t.key ? C.ac : C.t3,
                fontSize: 11,
                fontWeight: tab === t.key ? 700 : 500,
                cursor: disabled ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap' as const,
                opacity: disabled ? 0.5 : 1,
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      <div style={{ minHeight: 400 }}>{views[tab]}</div>
    </div>
  );
}
