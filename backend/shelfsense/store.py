"""Storage abstraction: one tiny document-store interface with in-memory and Firestore backends.

Services depend only on ``DocStore`` + ``Repo``; swapping Firestore in is a config change
(``STORE_BACKEND=firestore``). Documents are plain JSON-able dicts (datetimes as ISO strings).
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel


class DocStore(Protocol):
    def put(self, coll: str, doc_id: str, data: dict[str, Any]) -> None: ...
    def get(self, coll: str, doc_id: str) -> dict[str, Any] | None: ...
    def list(self, coll: str, where: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...
    def delete(self, coll: str, doc_id: str) -> None: ...
    def clear(self, coll: str) -> None: ...


class MemoryDocStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def put(self, coll: str, doc_id: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._data.setdefault(coll, {})[doc_id] = copy.deepcopy(data)

    def get(self, coll: str, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._data.get(coll, {}).get(doc_id)
            return copy.deepcopy(doc) if doc is not None else None

    def list(self, coll: str, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            docs = list(self._data.get(coll, {}).values())
        if where:
            docs = [d for d in docs if all(d.get(k) == v for k, v in where.items())]
        return copy.deepcopy(docs)

    def delete(self, coll: str, doc_id: str) -> None:
        with self._lock:
            self._data.get(coll, {}).pop(doc_id, None)

    def clear(self, coll: str) -> None:
        with self._lock:
            self._data[coll] = {}


class FirestoreDocStore:
    """Firestore (Native mode) backend. Requires ``google-cloud-firestore`` and ADC credentials."""

    def __init__(self, project: str | None = None, database: str = "(default)") -> None:
        from google.cloud import firestore  # imported lazily so local runs need no GCP libs

        self._client = firestore.Client(project=project, database=database)

    def put(self, coll: str, doc_id: str, data: dict[str, Any]) -> None:
        self._client.collection(coll).document(doc_id).set(data)

    def get(self, coll: str, doc_id: str) -> dict[str, Any] | None:
        snap = self._client.collection(coll).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def list(self, coll: str, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        q: Any = self._client.collection(coll)
        for k, v in (where or {}).items():
            q = q.where(filter=_field_filter(k, v))
        return [d.to_dict() for d in q.stream()]

    def delete(self, coll: str, doc_id: str) -> None:
        self._client.collection(coll).document(doc_id).delete()

    def clear(self, coll: str) -> None:
        for doc in self._client.collection(coll).stream():
            doc.reference.delete()


def _field_filter(field: str, value: Any) -> Any:
    from google.cloud.firestore_v1.base_query import FieldFilter

    return FieldFilter(field, "==", value)


M = TypeVar("M", bound=BaseModel)


class Repo(Generic[M]):  # noqa: UP046 - keep compatible with older typing tooling
    """Typed view over one collection."""

    def __init__(self, store: DocStore, coll: str, model: type[M], id_field: str = "id") -> None:
        self.store, self.coll, self.model, self.id_field = store, coll, model, id_field

    def put(self, obj: M) -> M:
        data = obj.model_dump(mode="json")
        self.store.put(self.coll, str(data[self.id_field]), data)
        return obj

    def get(self, doc_id: str) -> M | None:
        d = self.store.get(self.coll, doc_id)
        return self.model.model_validate(d) if d is not None else None

    def list(self, where: dict[str, Any] | None = None) -> list[M]:
        return [self.model.model_validate(d) for d in self.store.list(self.coll, where)]

    def delete(self, doc_id: str) -> None:
        self.store.delete(self.coll, doc_id)

    def clear(self) -> None:
        self.store.clear(self.coll)


def build_store(backend: str, project: str | None, database: str) -> DocStore:
    if backend == "firestore":
        return FirestoreDocStore(project=project, database=database)
    return MemoryDocStore()
