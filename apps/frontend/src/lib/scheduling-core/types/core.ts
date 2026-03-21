// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Core Domain Types
//  Nikufra factory data structures (input format)
// ═══════════════════════════════════════════════════════════

export interface NikufraMachine {
  id: string; // e.g. "PRM019"
  area: string; // "PG1" or "PG2"
  man: number[]; // MAN minutes per day
  status?: 'running' | 'down';
}

export interface NikufraTool {
  id: string; // e.g. "BFP079"
  m: string; // primary machine code
  alt: string; // alternative machine code (or "-")
  s: number; // setup time in hours
  pH: number; // pieces per hour rate
  op: number; // operators required
  skus: string[]; // item SKU codes
  nm: string[]; // item names
  lt: number; // lot economic quantity
  stk: number; // current stock
  wip?: number; // WIP (work in progress)
  status?: 'running' | 'down';
}

export interface NikufraOperation {
  id: string; // e.g. "OP01"
  m: string; // machine code
  t: string; // tool code
  sku: string; // item SKU
  nm: string; // item name
  pH: number; // pieces per hour
  atr: number; // atraso (backlog)
  d: number[]; // daily quantities (demand)
  s: number; // setup time in hours
  op: number; // operators required
  cl?: string; // customer code
  clNm?: string; // customer name
  pa?: string; // parent SKU / produto acabado
  wip?: number; // WIP
  qe?: number; // qtd exp
  ltDays?: number; // manufacturing lead time in working days (Prz.Fabrico)
  twin?: string; // Peça Gémea SKU reference
}

export interface NikufraMOLoad {
  PG1: number[]; // daily team capacity for PG1
  PG2: number[]; // daily team capacity for PG2
  poolPG1?: number[];
  poolPG2?: number[];
}

export interface NikufraCustomer {
  code: string;
  name: string;
}

export interface NikufraData {
  dates: string[];
  days_label: string[];
  mo: NikufraMOLoad;
  machines: NikufraMachine[];
  tools: NikufraTool[];
  operations: NikufraOperation[];
  history: NikufraHistoryEvent[];
  customers?: NikufraCustomer[];
  workday_flags?: boolean[];
}

export interface NikufraHistoryEvent {
  dt: string;
  type: string;
  mach: string;
  tool: string;
  action: string;
  result: string;
  roi: string;
}

// ── Master ISOP Types ──

export interface MasterToolRecord {
  id: string;
  m: string;
  alt: string;
  s: number;
  pH: number;
  op: number;
  lt: number;
  mpCode?: string;
  mpConsumption?: number;
  calco?: string;
}

export interface MasterISOPData {
  tools: MasterToolRecord[];
  machines: Array<{ id: string; area: string }>;
  mo: NikufraMOLoad;
}
