# Hash canónico para snapshots
# Conforme SP-BE-04 e PP1_DOCUMENTO_MESTRE_v3.md Secção 7.4.1

import hashlib
import json
from typing import Any


def canonical_json(data: dict[str, Any] | list[Any]) -> str:
    """
    Gera JSON canónico (ordenação estável) conforme PP1_DOCUMENTO_MESTRE_v3.md Secção 7.4.1.

    Campos EXCLUÍDOS do hash:
    - snapshot_id (não determinístico)
    - created_at (não determinístico)
    - sources (file_hash_sha256 pode variar, metadata pode variar)

    Campos INCLUÍDOS:
    - semantics (series_semantics, setup_time_uom, mo_uom)
    - master_data (items, resources, tools, customers)
    - routing (com operações ordenadas)
    - series (ordenadas por item_sku, date)
    - trust_index (overall, causes)
    """
    if isinstance(data, dict):
        # Remover campos não determinísticos
        canonical = data.copy()
        canonical.pop("snapshot_id", None)
        canonical.pop("created_at", None)
        canonical.pop("sources", None)  # Excluir sources do hash

        # Ordenar recursivamente
        return json.dumps(
            _canonicalize_value(canonical),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),  # Sem espaços para determinismo
        )
    elif isinstance(data, list):
        return json.dumps(
            _canonicalize_value(data),
            sort_keys=False,  # Listas mantêm ordem, mas elementos são canónicos
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _canonicalize_value(value: Any) -> Any:
    """Canonicaliza recursivamente um valor"""
    if isinstance(value, dict):
        # Ordenar chaves e canonicalizar valores
        return {key: _canonicalize_value(val) for key, val in sorted(value.items())}
    elif isinstance(value, list):
        # Para listas, ordenar por key estável quando aplicável
        canonicalized = [_canonicalize_value(item) for item in value]

        # Tentar ordenar por key estável (id, code, sku, date, etc.)
        if canonicalized and isinstance(canonicalized[0], dict):
            # Encontrar key de ordenação
            sort_key = None
            for key in [
                "item_sku",
                "resource_code",
                "tool_code",
                "customer_code",
                "date",
                "id",
                "code",
            ]:
                if key in canonicalized[0]:
                    sort_key = key
                    break

            if sort_key:
                canonicalized.sort(key=lambda x: x.get(sort_key, ""))

        return canonicalized
    else:
        return value


def calculate_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """
    Calcula hash SHA-256 do snapshot canónico.

    Conforme PP1_DOCUMENTO_MESTRE_v3.md Secção 7.4.1:
    - snapshot_hash = sha256(canonical_json(snapshot))
    - O mesmo input lógico → o mesmo snapshot_hash
    """
    canonical = canonical_json(snapshot)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
