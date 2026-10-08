let revision = 0;
let datasetId: string | null = null;

export interface PlanIdentity {
  datasetId: string;
  planRevision: number;
}

export function getReadIdentity(): PlanIdentity | null {
  return datasetId === null ? null : { datasetId, planRevision: revision };
}

export function getPlanRevision(): number {
  return revision;
}

// Only an accepted, coherent PlanView advances the revision used by commands.
export function commitPlanRevision(value: number, dataset: string | null = null) {
  revision = value;
  datasetId = dataset;
}
