from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel, Field

class ExtractedField(BaseModel):
    value: str | float | None = None
    source_column: str | None = None
    bbox: list[int] | None = Field(default=None, description="[ymin, xmin, ymax, xmax]")

class ExtractedAttribute(BaseModel):
    semantic_key: str
    template_names: list[str] = Field(default_factory=list)
    field: ExtractedField

class ExtractedRow(BaseModel):
    source_row_number: ExtractedField | None = None
    raw_description: ExtractedField | None = None
    suggested_billing_item: str | None = None
    hsn_code: ExtractedField | None = None
    quantity: ExtractedField | None = None
    unit: ExtractedField | None = None
    purchase_rate: ExtractedField | None = None
    line_amount: ExtractedField | None = None
    attributes: list[ExtractedAttribute] = Field(default_factory=list)
    
class ExtractedPage(BaseModel):
    page_number: int
    image_width: int | None = None
    image_height: int | None = None
    rows: list[ExtractedRow] = Field(default_factory=list)

class ExtractedDocument(BaseModel):
    provider: str
    provider_model: str
    provider_version: str
    extracted_at: str
    pages: list[ExtractedPage] = Field(default_factory=list)

class ExtractionJobResult(BaseModel):
    document: ExtractedDocument | None = None
    raw_provider_response: str | None = None
    tokens_used: int | None = None
    prompt_tokens: int | None = None
    candidate_tokens: int | None = None
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
