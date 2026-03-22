/**
 * DataPage — Master data management with 5 tabs:
 * Upload, Machines, Tools, Products, Alternative Routings.
 */

import { useState } from 'react';
import { DataImportPage } from '@/features/data-import';
import { useDataStore } from '@/stores/useDataStore';
import { useOverrideCount } from '@/stores/useMasterDataStore';
import { C } from '@/theme/color-bridge';
import { MachinesTab } from '../components/MachinesTab';
import { ProductsTab } from '../components/ProductsTab';
import { RoutingsTab } from '../components/RoutingsTab';
import { ToolsTab } from '../components/ToolsTab';

const TABS = [
  { id: 'upload', label: 'Upload' },
  { id: 'machines', label: 'Máquinas' },
  { id: 'tools', label: 'Ferramentas' },
  { id: 'products', label: 'Produtos' },
  { id: 'routings', label: 'Routings' },
] as const;

export function DataPage() {
  const [tab, setTab] = useState<string>('upload');
  const data = useDataStore((s) => s.nikufraData);
  const overrideCount = useOverrideCount();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 16 }}>
      <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${C.bd}`, paddingBottom: 8 }}>
        {TABS.map((t) => {
          const isActive = tab === t.id;
          const count =
            t.id === 'machines'
              ? data?.machines.length
              : t.id === 'tools'
                ? data?.tools.length
                : t.id === 'products'
                  ? data?.operations.length
                  : undefined;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                border: 'none',
                background: isActive ? `${C.ac}18` : 'transparent',
                color: isActive ? C.ac : C.t3,
                fontSize: 12,
                fontWeight: isActive ? 600 : 500,
                cursor: 'pointer',
                fontFamily: 'inherit',
                transition: 'background 0.15s',
              }}
            >
              {t.label}
              {count !== undefined && (
                <span style={{ fontSize: 12, marginLeft: 4, opacity: 0.7 }}>({count})</span>
              )}
            </button>
          );
        })}
        {overrideCount > 0 && (
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 12,
              color: C.ac,
              fontWeight: 600,
              alignSelf: 'center',
            }}
          >
            {overrideCount} editado{overrideCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {tab === 'upload' && <DataImportPage />}

      {tab !== 'upload' && !data && (
        <div
          style={{
            padding: 40,
            textAlign: 'center',
            color: C.t4,
            fontSize: 12,
          }}
        >
          Carregue um ISOP primeiro no tab{' '}
          <button
            onClick={() => setTab('upload')}
            style={{
              background: 'none',
              border: 'none',
              color: C.ac,
              cursor: 'pointer',
              fontFamily: 'inherit',
              fontSize: 12,
              fontWeight: 600,
              textDecoration: 'underline',
            }}
          >
            Upload
          </button>
        </div>
      )}

      {tab === 'machines' && data && <MachinesTab data={data} />}
      {tab === 'tools' && data && <ToolsTab data={data} />}
      {tab === 'products' && data && <ProductsTab data={data} />}
      {tab === 'routings' && data && <RoutingsTab data={data} />}
    </div>
  );
}
