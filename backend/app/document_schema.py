"""Explicit app-owned PDF/text scope; models receive no filesystem paths."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PDF_BYTES = 8 * 1024**2
MAX_TEXT_BYTES = 256 * 1024
MAX_DOCUMENTS = 4
MAX_CAPTURE_BYTES = 256 * 1024
MAX_CAPTURE_JSON = 3 * 1024**2
MAX_EXCERPT_BYTES = 12000
MIMES = {"application/pdf", "text/plain", "text/markdown"}


class DocumentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: UUID
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=1, le=MAX_PDF_BYTES, strict=True)
    mime_type: str = Field(max_length=100)
    name: str = Field(min_length=1, max_length=200)


class AgentDocumentScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_ids: list[UUID] = Field(min_length=1, max_length=MAX_DOCUMENTS)
    snapshots: list[DocumentSnapshot] = Field(default_factory=list, max_length=MAX_DOCUMENTS)

    @model_validator(mode="after")
    def selection(self):
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("Choose unique documents")
        if self.snapshots and [s.artifact_id for s in self.snapshots] != self.artifact_ids:
            raise ValueError("Document snapshots must match the selected files in order")
        return self
