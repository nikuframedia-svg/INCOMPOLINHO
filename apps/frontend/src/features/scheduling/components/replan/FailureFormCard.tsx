/**
 * FailureFormCard — Failure/breakdown registration form and active failures list.
 */

import { C } from '@/theme/color-bridge';
import { Card, Pill, Tag } from '../atoms';
import { FailureListItems } from './FailureListItems';
import type { FailureFormCardProps } from './types';

export function FailureFormCard({
  machines,
  tools,
  focusIds,
  failures,
  failureImpacts,
  showFailureForm,
  ffResType,
  ffResId,
  ffSev,
  ffCap,
  ffStartDay,
  ffEndDay,
  ffDesc,
  cascRunning,
  wdi,
  dates,
  dnames,
  setShowFailureForm,
  setFfResType,
  setFfResId,
  setFfSev,
  setFfCap,
  setFfStartDay,
  setFfEndDay,
  setFfDesc,
  addFailure,
  removeFailure,
  runCascadingReplan,
}: FailureFormCardProps) {
  const labelStyle = {
    fontSize: 12,
    color: C.t4,
    marginBottom: 3,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '.04em',
  };

  const selectStyle = {
    padding: '3px 4px',
    borderRadius: 4,
    border: `1px solid ${C.bd}`,
    background: C.s2,
    color: C.t1,
    fontSize: 12,
    fontFamily: 'inherit',
  } as const;

  return (
    <Card style={{ padding: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: failures.length > 0 || showFailureForm ? 10 : 0,
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
          Avarias / Indisponibilidades{' '}
          {failures.length > 0 && <Tag color={C.rd}>{failures.length}</Tag>}
        </div>
        <button
          onClick={() => setShowFailureForm(!showFailureForm)}
          style={{
            padding: '4px 10px',
            borderRadius: 4,
            border: `1px solid ${C.rd}33`,
            background: showFailureForm ? C.rdS : 'transparent',
            color: C.rd,
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {showFailureForm ? 'Cancelar' : '+ Registar Avaria'}
        </button>
      </div>

      {showFailureForm && (
        <div
          style={{
            padding: 12,
            background: C.bg,
            borderRadius: 6,
            border: `1px solid ${C.bd}`,
            marginBottom: 10,
          }}
        >
          <div
            style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8 }}
          >
            <div>
              <div style={labelStyle}>Tipo</div>
              <div style={{ display: 'flex', gap: 4 }}>
                {(['machine', 'tool'] as const).map((t) => (
                  <Pill
                    key={t}
                    active={ffResType === t}
                    color={C.bl}
                    onClick={() => {
                      setFfResType(t);
                      setFfResId('');
                    }}
                    size="sm"
                  >
                    {t === 'machine' ? 'Máquina' : 'Ferramenta'}
                  </Pill>
                ))}
              </div>
            </div>
            <div>
              <div style={labelStyle}>Recurso</div>
              <select
                value={ffResId}
                onChange={(e) => setFfResId(e.target.value)}
                style={{
                  width: '100%',
                  padding: '4px 6px',
                  borderRadius: 4,
                  border: `1px solid ${C.bd}`,
                  background: C.s2,
                  color: C.t1,
                  fontSize: 12,
                  fontFamily: 'inherit',
                }}
              >
                <option value="">Selecionar...</option>
                {ffResType === 'machine'
                  ? machines.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.id} ({m.area})
                      </option>
                    ))
                  : tools
                      .filter(
                        (t) =>
                          focusIds.includes(t.m) ||
                          (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
                      )
                      .map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.id}
                        </option>
                      ))}
              </select>
            </div>
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr 1fr',
              gap: 10,
              marginBottom: 8,
            }}
          >
            <div>
              <div style={labelStyle}>Severidade</div>
              <div style={{ display: 'flex', gap: 3 }}>
                {(
                  [
                    ['total', C.rd],
                    ['partial', C.yl],
                    ['degraded', C.bl],
                  ] as const
                ).map(([s, c]) => (
                  <Pill
                    key={s}
                    active={ffSev === s}
                    color={c}
                    onClick={() => setFfSev(s)}
                    size="sm"
                  >
                    {s === 'total' ? 'Total' : s === 'partial' ? 'Parcial' : 'Degradada'}
                  </Pill>
                ))}
              </div>
            </div>
            {ffSev !== 'total' && (
              <div>
                <div style={labelStyle}>Capacidade restante</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <input
                    type="number"
                    value={ffCap}
                    onChange={(e) => setFfCap(Math.max(0, Math.min(99, Number(e.target.value))))}
                    style={{
                      width: 50,
                      padding: '3px 6px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.s2,
                      color: C.t1,
                      fontSize: 12,
                      fontFamily: "'JetBrains Mono',monospace",
                      textAlign: 'center',
                    }}
                  />
                  <span style={{ fontSize: 12, color: C.t3 }}>%</span>
                </div>
              </div>
            )}
            <div>
              <div style={labelStyle}>Período</div>
              <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                <select
                  value={ffStartDay}
                  onChange={(e) => setFfStartDay(Number(e.target.value))}
                  style={selectStyle}
                >
                  {wdi.map((i) => (
                    <option key={i} value={i}>
                      {dnames[i]} {dates[i]}
                    </option>
                  ))}
                </select>
                <span style={{ fontSize: 12, color: C.t4 }}>—</span>
                <select
                  value={ffEndDay}
                  onChange={(e) => setFfEndDay(Number(e.target.value))}
                  style={selectStyle}
                >
                  {wdi
                    .filter((i) => i >= ffStartDay)
                    .map((i) => (
                      <option key={i} value={i}>
                        {dnames[i]} {dates[i]}
                      </option>
                    ))}
                </select>
              </div>
            </div>
          </div>
          <div style={{ marginBottom: 8 }}>
            <div style={labelStyle}>Descrição</div>
            <input
              type="text"
              value={ffDesc}
              onChange={(e) => setFfDesc(e.target.value)}
              placeholder="Ex: Manutenção preventiva"
              style={{
                width: '100%',
                padding: '4px 8px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: C.s2,
                color: C.t1,
                fontSize: 12,
                fontFamily: 'inherit',
              }}
            />
          </div>
          <button
            onClick={addFailure}
            disabled={!ffResId}
            style={{
              padding: '6px 16px',
              borderRadius: 4,
              border: 'none',
              background: ffResId ? C.rd : C.s3,
              color: ffResId ? C.t1 : C.t4,
              fontSize: 12,
              fontWeight: 600,
              cursor: ffResId ? 'pointer' : 'default',
              fontFamily: 'inherit',
            }}
          >
            Registar
          </button>
        </div>
      )}

      <FailureListItems
        failures={failures}
        failureImpacts={failureImpacts}
        dnames={dnames}
        dates={dates}
        removeFailure={removeFailure}
        cascRunning={cascRunning}
        runCascadingReplan={runCascadingReplan}
        showFailureForm={showFailureForm}
      />
    </Card>
  );
}
