from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel, Field

class GroundedField(BaseModel):
    bbox: list[int] | None = Field(default=None, description="[ymin, xmin, ymax, xmax]")
    value: str | float | None = None

class ExtractedRow(BaseModel):
    source_row_number: GroundedField | None = None
    raw_description: GroundedField | None = None
    normalized_description: GroundedField | None = None
    suggested_billing_item: str | None = None
    hsn_code: GroundedField | None = None
    quantity: GroundedField | None = None
    unit: GroundedField | None = None
    purchase_rate: GroundedField | None = None
    mrp: GroundedField | None = None
    supplier_product_code: GroundedField | None = None
    line_amount: GroundedField | None = None
    brand: GroundedField | None = None
    size: GroundedField | None = None
    color: GroundedField | None = None
    article_number: GroundedField | None = None
    batch_number: GroundedField | None = None
    expiry: GroundedField | None = None
    serial_number: GroundedField | None = None
    manufacturer: GroundedField | None = None
    design: GroundedField | None = None
    model_no: GroundedField | None = None
    discount: GroundedField | None = None
    
class ExtractedPage(BaseModel):
    page_number: int
    image_width: int | None = None
    image_height: int | None = None
    global_discounts: list[float] | None = Field(default_factory=list, description="Any global or bottom-of-page discount percentages (e.g. [37.00, 5.00, 4.76])")
    global_taxes: list[float] | None = Field(default_factory=list, description="Any global or bottom-of-page tax percentages (e.g. [2.5, 2.5])")
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
    def extract_invoice(
        self,
        file_paths: list[str],
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
