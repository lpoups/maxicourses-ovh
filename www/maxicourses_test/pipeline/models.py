from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class RawAdapterResult:
    """Container for data returned by a scraping adapter script."""

    adapter: str
    status: str
    payload: Dict[str, Any]
    started_at: datetime
    finished_at: datetime
    script_path: str
    command: List[str]
    env: Dict[str, str]
    exit_code: int
    stdout: str
    stderr: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineRun:
    """High level information for a full scraping pass."""

    ean: str
    image_path: Optional[str]
    started_at: datetime
    finished_at: datetime
    adapter_results: List[RawAdapterResult]
    notes: List[str] = field(default_factory=list)
    reference_title: Optional[str] = None
    reference_description: Optional[str] = None
    reference_source: Optional[str] = None
    reference_brand: Optional[str] = None
    reference_quantity: Optional[str] = None
    reference_image: Optional[str] = None
    reference_categories: Optional[str] = None
    reference_nutriscore_grade: Optional[str] = None
    reference_nutriscore_score: Optional[int] = None
    reference_nutriscore_image: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ean": self.ean,
            "image_path": self.image_path,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_seconds": (self.finished_at - self.started_at).total_seconds(),
            "reference": {
                "title": self.reference_title,
                "description": self.reference_description,
                "source": self.reference_source,
                "brand": self.reference_brand,
                "quantity": self.reference_quantity,
                "categories": self.reference_categories,
                "image": self.reference_image,
                "nutriscore_grade": self.reference_nutriscore_grade,
                "nutriscore_score": self.reference_nutriscore_score,
                "nutriscore_image": self.reference_nutriscore_image,
            },
            "notes": self.notes,
            "adapters": [
                {
                    "adapter": r.adapter,
                    "status": r.status,
                    "payload": r.payload,
                    "started_at": r.started_at.isoformat(),
                    "finished_at": r.finished_at.isoformat(),
                    "duration_seconds": (r.finished_at - r.started_at).total_seconds(),
                    "script_path": r.script_path,
                    "command": r.command,
                    "env": r.env,
                    "exit_code": r.exit_code,
                    "error": r.error,
                    "stderr": r.stderr,
                    "metadata": r.metadata,
                }
                for r in self.adapter_results
            ],
        }
