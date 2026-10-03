"""Bounded, process-local previews. Restart requires a fresh preview."""

from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, is_dataclass
from uuid import uuid4

from fastapi import HTTPException

from backend.plans.serialize import value_fingerprint
from backend.plans.transactions import input_identity


def result_fingerprint(result, simulation=None) -> str:
    def content(value):
        return asdict(value) if is_dataclass(value) else vars(value) if value is not None else None

    return value_fingerprint({"result": content(result), "simulation": content(simulation)})


@dataclass
class PreparedPlanWrite:
    values: dict
    response: object
    file_identity: dict
    approval_action: str = "recompute"


@dataclass
class PreviewCandidate:
    id: str
    kind: str
    origin: dict
    parameters: dict
    result: object
    input_fingerprint: str
    candidate_fingerprint: str
    created_at: float = field(default_factory=time.monotonic)
    simulation: object | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def identity(self) -> dict:
        return {
            "candidate_id": self.id,
            "dataset_id": self.origin["dataset_id"],
            "base_revision": self.origin["base_revision"],
            "input_fingerprint": self.input_fingerprint,
            "candidate_fingerprint": self.candidate_fingerprint,
        }


class PreviewStore:
    def __init__(self, limit=32, ttl_seconds=1800):
        self.limit, self.ttl_seconds = limit, ttl_seconds
        self._lock = threading.RLock()
        self._items: OrderedDict[str, PreviewCandidate] = OrderedDict()

    def put(self, kind, baseline, parameters, result, *, simulation=None) -> PreviewCandidate:
        return self.put_for_origin(kind, input_identity(baseline), parameters, result,
                                   simulation=simulation)

    def put_for_origin(self, kind, origin, parameters, result, *, simulation=None):
        origin = copy.deepcopy(origin)
        result, simulation = copy.deepcopy(result), copy.deepcopy(simulation)
        candidate = PreviewCandidate(
            uuid4().hex,
            kind,
            origin,
            copy.deepcopy(parameters),
            result,
            value_fingerprint({"origin": origin, "parameters": parameters}),
            result_fingerprint(result, simulation),
            simulation=simulation,
        )
        with self._lock:
            self._items[candidate.id] = candidate
            while len(self._items) > self.limit:
                self._items.popitem(last=False)
        return candidate

    def get(self, candidate_id, kind, state, parameters) -> PreviewCandidate:
        return self.get_for_origin(candidate_id, kind, input_identity(state), parameters)

    def get_for_origin(self, candidate_id, kind, origin, parameters) -> PreviewCandidate:
        with self._lock:
            candidate = self._items.get(candidate_id)
        if candidate is None or time.monotonic() - candidate.created_at > self.ttl_seconds:
            raise HTTPException(
                409,
                {
                    "code": "preview_required",
                    "message": "Calcula uma nova pre-visualizacao antes de aplicar.",
                },
            )
        with candidate.lock:
            current = (
                candidate.kind == kind
                and candidate.origin == origin
                and candidate.parameters == parameters
                and candidate.candidate_fingerprint == result_fingerprint(
                    candidate.result, candidate.simulation
                )
            )
        if not current:
            raise HTTPException(
                409,
                {
                    "code": "stale_preview",
                    "message": "A pre-visualizacao ja nao corresponde aos dados atuais.",
                },
            )
        return candidate

    def get_prepared_write(self, candidate_id, kind, origin, parameters):
        with self._lock:
            candidate = self._items.get(candidate_id)
        if candidate is None or not isinstance(candidate.result, PreparedPlanWrite):
            return None
        return self.get_for_origin(candidate_id, kind, origin, parameters)


previews = PreviewStore()
