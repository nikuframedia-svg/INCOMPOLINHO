/**
 * isop/parse.ts — Main ISOP XLSX parser orchestrator.
 *
 * Mirrors backend logic at backend/src/domain/ingest/isop_parser.py.
 * Auto-detects header row and column positions for flexibility across ISOP formats.
 */

import * as XLSX from 'xlsx';
import type { LoadMeta } from '../../stores/useDataStore';
import { buildNikufraData } from './build-data';
import { isCellRedHighlighted } from './cell-styles';
import {
  buildColumnMap,
  findHeaderRow,
  findMetadataRow,
  findWorkdayFlagsRow,
} from './header-detection';
import {
  normalizeCode,
  normalizeString,
  type ParsedRow,
  parseDateCell,
  parseInteger,
  parseNumeric,
} from './helpers';

export interface ParseResult {
  success: true;
  data: import('../nikufra-types').NikufraData;
  meta: LoadMeta;
  sourceColumns: {
    hasSetup: boolean;
    hasAltMachine: boolean;
    hasRate: boolean;
    hasParentSku: boolean;
    hasLeadTime: boolean;
    hasQtdExp: boolean;
    hasTwin: boolean;
  };
}

export interface ParseError {
  success: false;
  errors: string[];
}

export function parseISOPFile(
  arrayBuffer: ArrayBuffer,
  _semantics: string = 'DEMAND_QTY_BY_DATE',
): ParseResult | ParseError {
  // 1. Read workbook
  let wb: XLSX.WorkBook;
  try {
    wb = XLSX.read(arrayBuffer, { type: 'array', cellDates: true, cellStyles: true });
  } catch {
    return { success: false, errors: ['Ficheiro XLSX inválido — não foi possível abrir.'] };
  }

  // 2. Find sheet "Planilha1"
  const sheetName = wb.SheetNames.find((n) => n === 'Planilha1' || n.toLowerCase() === 'planilha1');
  if (!sheetName) {
    return { success: false, errors: ['Sheet "Planilha1" não encontrada no ficheiro.'] };
  }

  const ws = wb.Sheets[sheetName];
  const allRows: unknown[][] = XLSX.utils.sheet_to_json(ws, {
    header: 1,
    raw: true,
    defval: null,
  });

  if (allRows.length < 3) {
    return { success: false, errors: ['Ficheiro com menos de 3 linhas — formato ISOP inválido.'] };
  }

  // 3. Find header row dynamically
  const headerResult = findHeaderRow(allRows);
  if (!headerResult) {
    return {
      success: false,
      errors: [
        'Nenhuma linha de cabeçalho encontrada com "Referência Artigo" e "Máquina" (procurado nas primeiras 16 linhas).',
      ],
    };
  }

  const { rowIndex: headerRowIndex, headers } = headerResult;
  const headerRow = allRows[headerRowIndex] ?? [];

  // 4. Map columns by header name
  const colMap = buildColumnMap(headers);
  if (!colMap) {
    return {
      success: false,
      errors: ['Colunas "Referência Artigo" e "Máquina" não encontradas nos cabeçalhos.'],
    };
  }

  // 5. Find date columns
  const lastTextCol = Math.max(
    colMap.atraso,
    colMap.stockA,
    colMap.wip,
    colMap.nPessoas,
    colMap.pecasH,
    colMap.ferramenta,
    colMap.qtdExp,
    colMap.maquina,
  );
  const dateSearchStart = lastTextCol >= 0 ? lastTextCol + 1 : 10;

  const dates: Date[] = [];
  const dateColIndices: number[] = [];

  for (let ci = dateSearchStart; ci < headerRow.length; ci++) {
    const d = parseDateCell(headerRow[ci]);
    if (d) {
      dates.push(d);
      dateColIndices.push(ci);
    }
  }

  if (dates.length === 0) {
    for (let ci = 10; ci < headerRow.length; ci++) {
      const d = parseDateCell(headerRow[ci]);
      if (d) {
        dates.push(d);
        dateColIndices.push(ci);
      }
    }
  }

  if (dates.length === 0) {
    return {
      success: false,
      errors: [`Nenhuma coluna de data encontrada no cabeçalho (linha ${headerRowIndex + 1}).`],
    };
  }

  // 6. Parse working day flags
  let workdayFlags = findWorkdayFlagsRow(allRows, headerRowIndex, dateColIndices);
  if (!workdayFlags) {
    workdayFlags = dates.map((d) => {
      const dow = d.getDay();
      return dow >= 1 && dow <= 5;
    });
  }
  if (workdayFlags.length !== dates.length) {
    workdayFlags = dates.map(() => true);
  }

  // 7. Parse data rows
  const dataStartRow = headerRowIndex + 1;
  const parsedRows: ParsedRow[] = [];
  const warnings: string[] = [];

  for (let ri = dataStartRow; ri < allRows.length; ri++) {
    const row = allRows[ri];
    if (!row || row.length === 0) continue;

    const item_sku = normalizeCode(row[colMap.refArtigo]);
    if (!item_sku) continue;

    const resource_code = normalizeCode(row[colMap.maquina]);
    if (!resource_code) {
      warnings.push(`Linha ${ri + 1}: SKU "${item_sku}" sem máquina — ignorada.`);
      continue;
    }

    const alt_resource = colMap.maqAlt >= 0 ? normalizeCode(row[colMap.maqAlt]) : '';
    const tool_code = colMap.ferramenta >= 0 ? normalizeCode(row[colMap.ferramenta]) : '';
    const rate = colMap.pecasH >= 0 ? parseNumeric(row[colMap.pecasH]) : 0;

    if (rate <= 0 && colMap.pecasH >= 0) {
      warnings.push(
        `Linha ${ri + 1}: SKU "${item_sku}" rate=0 — incluída mas não será agendada (rate inválido).`,
      );
    }
    if (
      colMap.tpSetup >= 0 &&
      typeof row[colMap.tpSetup] === 'string' &&
      isNaN(Number(String(row[colMap.tpSetup]).replace(',', '.')))
    ) {
      warnings.push(
        `Linha ${ri + 1}: SKU "${item_sku}" setup inválido ("${row[colMap.tpSetup]}") — interpretado como 0.`,
      );
    }

    let invalidCellsThisRow = 0;
    const daily_quantities: (number | null)[] = dateColIndices.map((ci) => {
      const raw = row[ci];
      if (raw == null || (typeof raw === 'string' && raw.trim() === '')) return null;
      if (typeof raw === 'string' && isNaN(Number(raw.replace(',', '.')))) {
        invalidCellsThisRow++;
        return null;
      }
      return parseNumeric(raw);
    });
    if (invalidCellsThisRow > 0) {
      warnings.push(
        `Linha ${ri + 1}: SKU "${item_sku}" tem ${invalidCellsThisRow} célula(s) de data não-numérica(s) — interpretada(s) como 0.`,
      );
    }

    parsedRows.push({
      customer_code: colMap.cliente >= 0 ? normalizeCode(row[colMap.cliente]) : '',
      customer_name: colMap.nome >= 0 ? normalizeString(row[colMap.nome]) : '',
      parent_sku: colMap.produtoAcabado >= 0 ? normalizeCode(row[colMap.produtoAcabado]) : '',
      item_sku,
      item_name: colMap.designacao >= 0 ? normalizeString(row[colMap.designacao]) : item_sku,
      lot_economic_qty: colMap.loteEcon >= 0 ? parseInteger(row[colMap.loteEcon], 0) : 0,
      lead_time_days: colMap.przFabrico >= 0 ? parseInteger(row[colMap.przFabrico], 0) : 0,
      resource_code,
      alt_resource: alt_resource === '-' ? '' : alt_resource,
      tool_code,
      setup_time: colMap.tpSetup >= 0 ? parseNumeric(row[colMap.tpSetup]) : 0,
      rate,
      operators_required: colMap.nPessoas >= 0 ? parseInteger(row[colMap.nPessoas], 1) : 1,
      qtd_exp: colMap.qtdExp >= 0 ? parseNumeric(row[colMap.qtdExp]) : 0,
      stock: 0,
      wip: colMap.wip >= 0 ? parseNumeric(row[colMap.wip]) : 0,
      atraso: colMap.atraso >= 0 ? parseNumeric(row[colMap.atraso]) : 0,
      daily_quantities,
      machine_down:
        (colMap.estadoMaq >= 0
          ? /inact|down|avaria|parad|inoper/i.test(normalizeString(row[colMap.estadoMaq]))
          : false) || isCellRedHighlighted(ws, ri, colMap.maquina),
      tool_down:
        (colMap.estadoFerr >= 0
          ? /inact|down|avaria|parad|inoper/i.test(normalizeString(row[colMap.estadoFerr]))
          : false) ||
        (colMap.ferramenta >= 0 && isCellRedHighlighted(ws, ri, colMap.ferramenta)),
      twin: colMap.pecaGemea >= 0 ? normalizeCode(row[colMap.pecaGemea]) : '',
    });
  }

  if (parsedRows.length === 0) {
    return {
      success: false,
      errors: [`Nenhuma linha de dados válida encontrada (a partir da linha ${dataStartRow + 1}).`],
    };
  }

  // Metadata logging
  const metaRow = findMetadataRow(allRows, headerRowIndex);
  if (metaRow >= 0) {
    const metaCell = normalizeString(allRows[metaRow]?.[0]);
    if (metaCell) {
      warnings.push(`Metadata detectada na linha ${metaRow + 1}: "${metaCell.slice(0, 60)}"`);
    }
  }
  warnings.push(
    `Cabeçalho detectado na linha ${headerRowIndex + 1}, dados a partir da linha ${dataStartRow + 1}, ${dates.length} datas, ${parsedRows.length} operações.`,
  );

  // 8. Build NikufraData
  const sourceColumns = {
    hasSetup: colMap.tpSetup >= 0,
    hasAltMachine: colMap.maqAlt >= 0,
    hasRate: colMap.pecasH >= 0,
    hasParentSku: colMap.produtoAcabado >= 0,
    hasLeadTime: colMap.przFabrico >= 0,
    hasQtdExp: colMap.qtdExp >= 0,
    hasTwin: colMap.pecaGemea >= 0,
  };

  const result = buildNikufraData({
    parsedRows,
    dates,
    workdayFlags,
    warnings,
    headerRowIndex,
    dataStartRow,
    sourceColumns,
  });

  return { success: true, ...result };
}

export type { LoadMeta };
