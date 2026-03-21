/**
 * DayOrders — Table of all operations scheduled on the selected day.
 */

import { Collapsible } from '@/components/Common/Collapsible';
import type { Block } from '@/lib/engine';
import { fmtMin } from '@/lib/engine';
import './DayOrders.css';

interface DayOrdersProps {
  blocks: Block[];
  onBlockClick: (block: Block) => void;
}

export function DayOrders({ blocks, onBlockClick }: DayOrdersProps) {
  return (
    <div data-testid="day-orders">
      <Collapsible title="Ordens do Dia" defaultOpen badge={`${blocks.length}`}>
        {blocks.length === 0 ? (
          <p style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>
            Sem operações escalonadas para este dia.
          </p>
        ) : (
          <table className="dord__table">
            <thead>
              <tr>
                <th>Ferramenta</th>
                <th>SKU</th>
                <th>Nome</th>
                <th>Máquina</th>
                <th>Turno</th>
                <th style={{ textAlign: 'right' }}>Qtd</th>
                <th>Inicio</th>
                <th>Fim</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {blocks.map((b, i) => {
                const rowCls = `dord__row${b.type === 'infeasible' ? ' dord__row--infeasible' : ''}`;
                const statusType = b.type === 'ok' && b.isSystemReplanned ? 'replan' : b.type;

                return (
                  <tr
                    key={`${b.opId}-${i}`}
                    className={rowCls}
                    onClick={() => onBlockClick(b)}
                    data-testid={`dord-row-${b.opId}-${i}`}
                  >
                    <td className="dord__mono">{b.toolId}</td>
                    <td className="dord__mono">{b.sku}</td>
                    <td className="dord__name" title={b.nm}>
                      {b.nm}
                    </td>
                    <td className="dord__mono">{b.machineId}</td>
                    <td>{b.shift}</td>
                    <td
                      style={{
                        textAlign: 'right',
                        fontWeight: 600,
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      {b.qty.toLocaleString()}
                    </td>
                    <td className="dord__mono">{fmtMin(b.startMin)}</td>
                    <td className="dord__mono">{fmtMin(b.endMin)}</td>
                    <td>
                      <span className={`dord__badge dord__badge--${statusType}`}>{statusType}</span>
                      {b.moved && <span className="dord__badge dord__badge--moved">mov</span>}
                      {b.isAdvanced && (
                        <span className="dord__badge dord__badge--advanced">adv</span>
                      )}
                      {b.isTwinProduction && (
                        <span className="dord__badge dord__badge--twin">twin</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Collapsible>
    </div>
  );
}
