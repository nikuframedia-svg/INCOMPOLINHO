/**
 * isop/cell-styles.ts — Cell color detection for inoperational status.
 */

import * as XLSX from 'xlsx';

/**
 * Check if a cell has a red fill (background) colour.
 * Nikufra convention: red-highlighted machine/tool cells indicate "inoperacional".
 */
export function isCellRedHighlighted(ws: XLSX.WorkSheet, row: number, col: number): boolean {
  const addr = XLSX.utils.encode_cell({ r: row, c: col });
  const cell = ws[addr];
  if (!cell || !cell.s) return false;

  const style = cell.s as Record<string, unknown>;

  const fgColor = style.fgColor as { rgb?: string; theme?: number } | undefined;
  if (fgColor?.rgb && isRedColor(fgColor.rgb)) return true;

  const bgColor = style.bgColor as { rgb?: string; theme?: number } | undefined;
  if (bgColor?.rgb && isRedColor(bgColor.rgb)) return true;

  const fill = style.fill as Record<string, unknown> | undefined;
  if (fill) {
    const fillFg = fill.fgColor as { rgb?: string } | undefined;
    if (fillFg?.rgb && isRedColor(fillFg.rgb)) return true;
    const fillBg = fill.bgColor as { rgb?: string } | undefined;
    if (fillBg?.rgb && isRedColor(fillBg.rgb)) return true;
  }

  const font = style.font as Record<string, unknown> | undefined;
  if (font) {
    const fontColor = font.color as { rgb?: string } | undefined;
    if (fontColor?.rgb && isRedColor(fontColor.rgb)) return true;
  }

  return false;
}

/** Detect red tones: high R, low G and B */
export function isRedColor(rgb: string): boolean {
  const hex = rgb.length === 8 ? rgb.substring(2) : rgb;
  if (hex.length !== 6) return false;
  const r = parseInt(hex.substring(0, 2), 16);
  const g = parseInt(hex.substring(2, 4), 16);
  const b = parseInt(hex.substring(4, 6), 16);
  return r > 180 && g < 100 && b < 100;
}
