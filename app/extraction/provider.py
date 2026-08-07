from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel, Field

class ProvenanceInfo(BaseModel):
    source_text: str
    page: int | None = None
    bbox: list[int] | None = None
    source_column: str | None = None

class ExtractedItem(BaseModel):
    raw_description: str | None = None
    normalized_description: str | None = None
    suggested_billing_item: str | None = None
    supplier_product_code: str | None = None
    quantity: float | None = None
    unit: str | None = None
    purchase_rate: float | None = None
    mrp: float | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    review_required: bool = False
    provenance: dict[str, ProvenanceInfo] = Field(default_factory=dict)

class ExtractionJobResult(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)
    raw_provider_response: str | None = None
    tokens_used: int | None = None
    cost: float | None = None
    input_pages: int | None = None

class ExtractionProvider(ABC):
    """
    Abstract interface for AI Document Extraction.
    Providers like Gemini, Azure, or Claude will implement this interface.
    """
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def provider_version(self) -> str:
        pass

    @abstractmethod
    async def extract_invoice(
        self,
        file_path: str,
        mime_type: str,
        templates: list[dict[str, Any]],
        structured_aliases: dict[str, str] | None,
        extraction_notes: str | None,
        few_shot_examples: list[dict[str, Any]] | None
    ) -> ExtractionJobResult:
        """
        Extracts semantic fields from an invoice document using the unified VOCABULARY_V1.
        """
        pass
