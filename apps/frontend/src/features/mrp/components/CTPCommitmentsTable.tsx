/**
 * CTPCommitmentsTable — displays committed CTP promises in a table.
 */

import { C } from '@/theme/color-bridge';
import type { CTPCommitment } from '../utils/ctp-compute';
import { fmtQty, mono } from '../utils/mrp-helpers';

function CommitmentRow({ c }: { c: CTPCommitment }) {
  return (
    <tr>
      <td style={{ ...mono, fontSize: 12, color: C.t1 }}>{c.sku}</td>
      <td style={{ fontSize: 12, color: C.t2 }}>{c.customer ?? '-'}</td>
      <td style={{ ...mono, fontSize: 12, color: C.t1, textAlign: 'right' }}>
        {fmtQty(c.quantity)}
      </td>
      <td style={{ ...mono, fontSize: 12, color: C.ac }}>{c.promisedDate}</td>
      <td style={{ ...mono, fontSize: 12, color: C.t2 }}>{c.machine}</td>
      <td style={{ ...mono, fontSize: 12, color: C.t3 }}>{c.confidencePercent}%</td>
    </tr>
  );
}

export function CTPCommitmentsTable({ commitments }: { commitments: CTPCommitment[] }) {
  if (commitments.length === 0) return null;

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Compromissos Registados ({commitments.length})
      </div>
      <table className="mrp__table">
        <thead>
          <tr>
            <th>SKU</th>
            <th>Cliente</th>
            <th style={{ textAlign: 'right' }}>Qtd</th>
            <th>Data Prometida</th>
            <th>Máquina</th>
            <th>Confiança</th>
          </tr>
        </thead>
        <tbody>
          {commitments.map((c) => (
            <CommitmentRow key={c.id} c={c} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
