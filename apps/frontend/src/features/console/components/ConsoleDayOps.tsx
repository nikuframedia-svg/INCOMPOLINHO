import { Collapsible } from '@/components/Common/Collapsible';
import type { Block } from '@/domain/types/scheduling';
import { fmtMin } from '@/utils/format';

export function ConsoleDayOps({
  title,
  blocks,
  defaultOpen,
  onBlockClick,
}: {
  title: string;
  blocks: Block[];
  defaultOpen: boolean;
  onBlockClick: (block: Block) => void;
}) {
  return (
    <Collapsible title={title} defaultOpen={defaultOpen} badge={`${blocks.length}`}>
      {blocks.length === 0 ? (
        <div className="cday__empty">Sem operações {title.toLowerCase()}.</div>
      ) : (
        <div className="cday__ops-list">
          {blocks.map((b) => (
            <div
              key={b.opId}
              className="cday__op-row"
              role="button"
              tabIndex={0}
              onClick={() => onBlockClick(b)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onBlockClick(b);
                }
              }}
            >
              <span className="cday__op-sku">{b.sku}</span>
              <span className="cday__op-machine">{b.machineId}</span>
              <span className="cday__op-time">
                {fmtMin(b.startMin)}–{fmtMin(b.endMin)}
              </span>
              <span className="cday__op-pcs">{b.qty.toLocaleString()} pcs</span>
              <span className="cday__op-client">{b.nm}</span>
            </div>
          ))}
        </div>
      )}
    </Collapsible>
  );
}
