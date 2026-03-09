/**
 * isop/header-detection.ts — Header row detection and column mapping.
 */

import { normalizeString, parseNumeric } from './helpers';

// ── Column map type ──

export interface ColumnMap {
  cliente: number;
  nome: number;
  refArtigo: number;
  designacao: number;
  loteEcon: number;
  przFabrico: number;
  maquina: number;
  maqAlt: number;
  ferramenta: number;
  tpSetup: number;
  pecasH: number;
  nPessoas: number;
  qtdExp: number;
  produtoAcabado: number;
  stockA: number;
  wip: number;
  atraso: number;
  estadoMaq: number;
  estadoFerr: number;
  pecaGemea: number;
}

/** Scan rows 0-15 for the header row (must contain "Referência Artigo" + "Máquina") */
export function findHeaderRow(
  allRows: unknown[][],
): { rowIndex: number; headers: string[] } | null {
  const maxScan = Math.min(allRows.length, 16);
  for (let ri = 0; ri < maxScan; ri++) {
    const row = allRows[ri];
    if (!row || row.length < 5) continue;
    const strs = row.map((h) => normalizeString(h));
    const hasRef = strs.some(
      (h) =>
        h.includes('Referência Artigo') ||
        h.includes('Referencia Artigo') ||
        h.includes('REFERÊNCIA ARTIGO') ||
        h.includes('Ref. Artigo') ||
        h.includes('REF. ARTIGO'),
    );
    const hasMaq = strs.some(
      (h) =>
        h.includes('Máquina') ||
        h.includes('Maquina') ||
        h.includes('MÁQUINA') ||
        h.includes('MAQUINA'),
    );
    if (hasRef && hasMaq) {
      return { rowIndex: ri, headers: strs };
    }
  }
  return null;
}

/** Map column names to indices based on header row content */
export function buildColumnMap(headers: string[]): ColumnMap | null {
  const find = (...patterns: string[]): number => {
    for (let i = 0; i < headers.length; i++) {
      const h = headers[i].toLowerCase();
      for (const p of patterns) {
        if (h.includes(p.toLowerCase())) return i;
      }
    }
    return -1;
  };

  const refArtigo = find('referência artigo', 'referencia artigo', 'ref. artigo', 'ref artigo');
  const maquina = find('máquina', 'maquina');

  if (refArtigo < 0 || maquina < 0) return null;

  return {
    cliente: find('cliente'),
    nome: find('nome'),
    refArtigo,
    designacao: find('designação', 'designacao'),
    loteEcon: find('lote econ', 'lote económico', 'lote economico'),
    przFabrico: find('prz.fabrico', 'prz fabrico', 'prazo fabrico', 'prazo de fabrico'),
    maquina,
    maqAlt: find('máq. alt', 'maq. alt', 'máquina alt', 'maquina alt'),
    ferramenta: find('ferramenta'),
    tpSetup: find('tp.setup', 'tp setup', 'setup'),
    pecasH: find(
      'peças/h',
      'pecas/h',
      'pcs/h',
      'pçs/h',
      'peças / h',
      'pecas / h',
      'cadência',
      'cadencia',
      'rate',
    ),
    nPessoas: find('nº pessoas', 'n pessoas', 'num pessoas', 'nº pess', 'n. pess', 'pessoas'),
    qtdExp: find('qtd exp', 'qtd. exp', 'qtd expedição', 'qtd expedicao'),
    produtoAcabado: find('produto acabado', 'prod. acabado', 'prod acabado', 'pa', 'parent'),
    stockA: find('stock-a', 'stock a', 'stock'),
    wip: find('wip'),
    atraso: find('atraso'),
    estadoMaq: find(
      'estado máq',
      'estado maq',
      'status máq',
      'status maq',
      'estado máquina',
      'estado maquina',
    ),
    estadoFerr: find('estado ferr', 'status ferr', 'estado ferramenta', 'status ferramenta'),
    pecaGemea: find('peca gemea', 'peça gémea', 'peça gemea', 'pç gemea', 'twin'),
  };
}

/** Find the metadata row (contains "PA:" pattern) above the header row */
export function findMetadataRow(allRows: unknown[][], headerRowIndex: number): number {
  for (let ri = Math.max(0, headerRowIndex - 3); ri < headerRowIndex; ri++) {
    const row = allRows[ri];
    if (!row) continue;
    const firstCell = normalizeString(row[0]);
    if (firstCell.includes('PA:') || firstCell.includes('Atrasos:')) return ri;
  }
  return -1;
}

/** Find workday flags row (0/1 values in date columns) */
export function findWorkdayFlagsRow(
  allRows: unknown[][],
  headerRowIndex: number,
  dateColIndices: number[],
): boolean[] | null {
  for (let ri = Math.max(0, headerRowIndex - 4); ri < headerRowIndex; ri++) {
    const row = allRows[ri];
    if (!row) continue;
    let is01 = true;
    let count = 0;
    for (const ci of dateColIndices) {
      const v = row[ci];
      if (v == null) continue;
      const n = parseNumeric(v, -1);
      if (n !== 0 && n !== 1) {
        is01 = false;
        break;
      }
      count++;
    }
    if (is01 && count > 3) {
      return dateColIndices.map((ci) => {
        const v = row[ci];
        if (v == null) return true;
        return parseNumeric(v, 1) === 1;
      });
    }
  }
  return null;
}
