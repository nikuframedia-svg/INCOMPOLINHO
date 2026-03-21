// ═══════════════════════════════════════════════════════════
//  explicitText.ts — Formatadores de linguagem explícita
//  Cada número tem contexto. Cada estado tem consequência.
//  Cada acção tem resultado. PT-PT.
// ═══════════════════════════════════════════════════════════

import { differenceInBusinessDays, format, addDays } from 'date-fns';
import { pt } from 'date-fns/locale';
import { formatQuantity } from './helpers';

// ── Types ───────────────────────────────────────────────────

export interface ExplicitValue {
  raw: number;
  formatted: string;
  context: string;
  qualifier: string;
  semantic: 'good' | 'warning' | 'critical' | 'neutral';
}

export interface RelativeDate {
  label: string;
  semantic: 'past' | 'today' | 'tomorrow' | 'future';
  daysFromNow: number;
}

export interface ExplicitState {
  label: string;
  consequence: string;
  action: string;
  semantic: 'good' | 'warning' | 'critical' | 'neutral';
}

export interface EmptyStateText {
  title: string;
  description: string;
  actionLabel: string;
}

export interface ConfirmationText {
  title: string;
  detail: string;
  consequence: string;
}

// ── OTD ─────────────────────────────────────────────────────

export function formatOTD(
  otdPct: number,
  target: number = 95,
): ExplicitValue {
  const semantic: ExplicitValue['semantic'] =
    otdPct >= target ? 'good' : otdPct >= 85 ? 'warning' : 'critical';
  const status = otdPct >= target ? 'acima' : 'abaixo';
  return {
    raw: otdPct,
    formatted: `${otdPct.toFixed(0)}%`,
    context: `${status} do objectivo de ${target}%`,
    qualifier:
      semantic === 'good'
        ? 'Dentro do objectivo'
        : semantic === 'warning'
          ? 'Atenção necessária'
          : 'Critico — entregas em risco',
    semantic,
  };
}

// ── OTD Delivery (per-delivery) ─────────────────────────────

export function formatOTDDelivery(
  otdPct: number,
  target: number = 95,
): ExplicitValue {
  const semantic: ExplicitValue['semantic'] =
    otdPct >= target ? 'good' : otdPct >= 85 ? 'warning' : 'critical';
  return {
    raw: otdPct,
    formatted: `${otdPct.toFixed(1)}%`,
    context: `das entregas entregues a tempo`,
    qualifier:
      semantic === 'good'
        ? 'Dentro do objectivo'
        : semantic === 'warning'
          ? 'Algumas entregas em risco'
          : 'Entregas atrasadas — intervencao necessaria',
    semantic,
  };
}

// ── Coverage ────────────────────────────────────────────────

export function formatCoverage(
  pct: number,
  totalDemand: number,
  totalProduced: number,
): ExplicitValue {
  const missing = Math.max(0, totalDemand - totalProduced);
  const isComplete = pct >= 99.9;

  const demandStr = totalDemand >= 1000
    ? `${(totalDemand / 1000).toFixed(0)}K`
    : formatQuantity(totalDemand);
  const producedStr = totalProduced >= 1000
    ? `${(totalProduced / 1000).toFixed(0)}K`
    : formatQuantity(totalProduced);
  const missingStr = missing >= 1000
    ? `${(missing / 1000).toFixed(0)}K`
    : formatQuantity(missing);

  return {
    raw: pct,
    formatted: isComplete ? 'Tudo coberto' : `${pct.toFixed(1)}%`,
    context: isComplete
      ? `${demandStr} pecas planeadas — todas cobertas`
      : `de ${demandStr} pecas, ${producedStr} cobertas — ${missingStr} em falta`,
    qualifier: isComplete
      ? 'Todas as encomendas cobertas'
      : pct >= 90
        ? 'Quase completo — pequenos gaps'
        : 'Cobertura insuficiente — intervencao necessaria',
    semantic: isComplete ? 'good' : pct >= 90 ? 'warning' : 'critical',
  };
}

// ── Utilization ─────────────────────────────────────────────

export function formatUtilization(
  util: number,
  activeMachines: number,
  totalMachines: number,
): ExplicitValue {
  const pct = util * 100;
  const semantic: ExplicitValue['semantic'] =
    util >= 0.85 ? 'warning' : util >= 0.6 ? 'good' : 'neutral';

  return {
    raw: pct,
    formatted: `${pct.toFixed(0)}%`,
    context: `${activeMachines} de ${totalMachines} prensas activas`,
    qualifier:
      util >= 0.85
        ? 'Carga elevada — pouca margem'
        : util >= 0.6
          ? 'Equilibrada'
          : util >= 0.4
            ? 'Margem disponivel'
            : 'Sub-utilizada',
    semantic,
  };
}

// ── Setup Time ──────────────────────────────────────────────

export function formatSetupTime(
  totalMin: number,
  setupCount: number,
): ExplicitValue {
  const avgMin = setupCount > 0 ? totalMin / setupCount : 0;
  const hours = (totalMin / 60).toFixed(1);
  const semantic: ExplicitValue['semantic'] = avgMin <= 45 ? 'good' : 'warning';

  return {
    raw: totalMin,
    formatted: `${hours}h`,
    context: `${setupCount} mudancas, media ${Math.round(avgMin)}min`,
    qualifier: avgMin <= 45 ? 'Eficiente' : 'Elevado — considerar optimizacao',
    semantic,
  };
}

// ── Alerts ───────────────────────────────────────────────────

export function formatAlerts(
  violationCount: number,
  infeasibleCount: number,
  overflowCount: number,
): ExplicitValue {
  const total = violationCount + infeasibleCount;
  const semantic: ExplicitValue['semantic'] =
    total === 0 ? 'good' : total <= 3 ? 'warning' : 'critical';

  const parts: string[] = [];
  if (violationCount > 0) parts.push(`${violationCount} violações`);
  if (infeasibleCount > 0) parts.push(`${infeasibleCount} inviaveis`);
  if (overflowCount > 0) parts.push(`${overflowCount} overflow`);

  return {
    raw: total,
    formatted: `${total}`,
    context: parts.length > 0 ? parts.join(' · ') : 'Nenhum problema detectado',
    qualifier:
      total === 0
        ? 'Sem problemas'
        : total <= 3
          ? 'Atenção'
          : 'Intervencao necessaria',
    semantic,
  };
}

// ── Delivery Delta ──────────────────────────────────────────

export function formatDeliveryDelta(deadline: Date, now: Date = new Date()): RelativeDate {
  const bizDays = differenceInBusinessDays(deadline, now);
  const weekday = format(deadline, 'EEEE', { locale: pt });
  const dateStr = format(deadline, "d 'de' MMMM", { locale: pt });

  if (bizDays < -1) {
    return {
      label: `Atrasada ${Math.abs(bizDays)} dias (prazo era ${dateStr})`,
      semantic: 'past',
      daysFromNow: bizDays,
    };
  }
  if (bizDays === -1) {
    return {
      label: `Atrasada 1 dia (prazo era ontem)`,
      semantic: 'past',
      daysFromNow: -1,
    };
  }
  if (bizDays === 0) {
    return { label: 'Prazo e hoje', semantic: 'today', daysFromNow: 0 };
  }
  if (bizDays === 1) {
    return { label: 'Prazo e amanha', semantic: 'tomorrow', daysFromNow: 1 };
  }
  return {
    label: `${weekday}, ${dateStr} — daqui a ${bizDays} dias uteis`,
    semantic: 'future',
    daysFromNow: bizDays,
  };
}

// ── Time Since ──────────────────────────────────────────────

export function formatTimeSince(startMs: number, nowMs: number = Date.now()): string {
  const mins = Math.floor((nowMs - startMs) / 60_000);
  if (mins < 1) return 'agora';
  if (mins < 60) return `ha ${mins} minutos`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (m === 0) return `ha ${h}h`;
  return `ha ${h}h${m.toString().padStart(2, '0')}`;
}

// ── Stock Coverage ──────────────────────────────────────────

export function formatStockCoverage(
  stock: number,
  dailyConsumption: number,
  today: Date = new Date(),
): string {
  if (dailyConsumption <= 0) return 'Sem consumo previsto';
  const days = stock / dailyConsumption;
  if (days < 1) return 'Stock chega a zero hoje';
  if (days < 2) {
    const exhaustDate = addDays(today, 1);
    return `Stock dura ate amanha a tarde (${format(exhaustDate, 'd/MM')})`;
  }
  if (days < 5) {
    const exhaustDate = addDays(today, Math.floor(days));
    return `Stock dura mais ${Math.floor(days)} dias (ate ${format(exhaustDate, 'd/MM')})`;
  }
  if (days < 14) return 'Stock para mais de 1 semana';
  return 'Stock para mais de 2 semanas. Sem preocupacao.';
}

// ── Machine State ───────────────────────────────────────────

export function formatMachineState(
  state: 'running' | 'down' | 'idle' | 'maintenance',
  opts: {
    machineId: string;
    downtimeSinceMs?: number;
    category?: string;
    blocksAtRisk?: number;
    nextToolId?: string;
    nextStartMin?: number;
  } = { machineId: '' },
): ExplicitState {
  const { machineId, downtimeSinceMs, category, blocksAtRisk = 0, nextToolId, nextStartMin } = opts;

  switch (state) {
    case 'down': {
      const elapsed = downtimeSinceMs ? formatTimeSince(downtimeSinceMs) : '';
      return {
        label: `${machineId} — Parada ${elapsed}`,
        consequence:
          blocksAtRisk > 0
            ? `Afecta ${blocksAtRisk} encomenda${blocksAtRisk > 1 ? 's' : ''} esta semana`
            : 'Sem impacto imediato em entregas',
        action: category ?? 'Verificar causa da paragem',
        semantic: 'critical',
      };
    }
    case 'maintenance': {
      const elapsed = downtimeSinceMs ? formatTimeSince(downtimeSinceMs) : '';
      return {
        label: `${machineId} — Em manutencao ${elapsed}`,
        consequence: 'Manutencao planeada — sem impacto em entregas',
        action: 'Manutencao preventiva',
        semantic: 'neutral',
      };
    }
    case 'idle':
      return {
        label: `${machineId} — Sem produção`,
        consequence: nextToolId
          ? `Próxima operação: ${nextToolId}${nextStartMin != null ? ` as ${fmtMinutes(nextStartMin)}` : ''}`
          : 'Sem ordens atribuidas',
        action: 'Máquina disponível',
        semantic: 'neutral',
      };
    default:
      return {
        label: `${machineId} — A produzir normalmente`,
        consequence: '',
        action: '',
        semantic: 'good',
      };
  }
}

function fmtMinutes(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
}

// ── Block Label (Gantt) ─────────────────────────────────────

export function formatBlockLabel(
  toolId: string,
  clientAbbrev?: string,
  completionPct?: number,
): string {
  const parts: string[] = [];
  if (clientAbbrev) parts.push(clientAbbrev);
  parts.push(toolId);
  if (completionPct != null) parts.push(`${Math.round(completionPct)}%`);
  return parts.join(' ');
}


// Re-export UI text functions for backwards compatibility
export {
  emptyStateMessage,
  confirmationText,
  badgeTooltip,
  tradeoffText,
  toastMessage,
} from './explicitText-ui';
