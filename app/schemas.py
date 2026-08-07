from decimal import Decimal
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TemplateMasterBase(BaseModel):
    template_id: str
    template_name: str
    label_size: Optional[str] = None
    has_logo: bool = False
    category: Optional[str] = None
    bartender_file_path: str
    printer_name: Optional[str] = None
    required_fields: Optional[str] = None
    default_field_values: Optional[str] = None
    barcode_sample_value: Optional[str] = None
    active_status: bool = True


class TemplateMasterRead(TemplateMasterBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class ProductFamilyBase(BaseModel):
    family_name: str
    tally_stock_item_name: Optional[str] = None
    category: Optional[str] = None
    default_tax_rate: Decimal = Decimal("0")
    default_unit: str = "PCS"
    default_template_id: Optional[int] = None
    active_status: bool = True


class ProductFamilyRead(ProductFamilyBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class LabelVariantBase(BaseModel):
    barcode: str
    family_id: int
    brand: Optional[str] = None
    item_display_name: str
    article_no: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    batch_no: Optional[str] = None
    season: Optional[str] = None
    expiry: Optional[str] = None
    mrp: Optional[Decimal] = None
    selling_price: Optional[Decimal] = None
    coded_price: Optional[str] = None
    billing_price_missing: bool = False
    extra_field_values: Optional[str] = None
    template_id: Optional[int] = None
    status: str = "active"


class LabelVariantRead(LabelVariantBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class PrintJobBase(BaseModel):
    variant_id: int
    template_id: int
    copies: int = 1
    status: str = "pending"
    csv_file_path: Optional[str] = None
    error_message: Optional[str] = None


class PrintJobRead(PrintJobBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class SupplierBase(BaseModel):
    name: str

class SupplierRead(SupplierBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SupplierProductMappingCreate(BaseModel):
    supplier_id: int
    supplier_product_code: Optional[str] = None
    supplier_description: Optional[str] = None
    family_id: int
    confidence: Optional[Decimal] = None

class SupplierProductMappingRead(SupplierProductMappingCreate):
    id: int
    last_seen_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ReceivingSessionCreate(BaseModel):
    supplier_id: int
    invoice_number: Optional[str] = None
    invoice_date: Optional[datetime] = None
    source_document_path: Optional[str] = None

class ReceivingSessionRead(ReceivingSessionCreate):
    id: int
    status: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ReceivingItemCreate(BaseModel):
    session_id: int
    bill_row_number: Optional[int] = None
    
    raw_description: Optional[str] = None
    normalized_description: Optional[str] = None
    supplier_product_code: Optional[str] = None
    extraction_confidence: Optional[Decimal] = None
    source_provenance: Optional[str] = None
    
    expected_qty: Optional[Decimal] = None
    unit: Optional[str] = None
    
    purchase_rate: Optional[Decimal] = None
    list_price: Optional[Decimal] = None
    mrp: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    line_amount: Optional[Decimal] = None
    
    family_id: Optional[int] = None

class ReceivingItemRead(ReceivingItemCreate):
    id: int
    received_qty: Optional[Decimal] = None
    matched_variant_id: Optional[int] = None
    tally_status: str
    pricing_status: str
    label_status: str
    landing_price: Optional[Decimal] = None
    confirmed_selling_price: Optional[Decimal] = None
    pricing_rule_applied: Optional[str] = None
    pricing_confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
    
    @property
    def suggested_label_copies(self) -> Optional[int]:
        from app.services.workflow.label_policy_service import suggest_print_copies
        return suggest_print_copies(self.unit, self.received_qty)
    
    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        d["suggested_label_copies"] = self.suggested_label_copies
        return d


class TallyItemRequest(BaseModel):
    received_qty: Decimal


class ConfirmPricingRequest(BaseModel):
    landing_price: Optional[Decimal] = None
    mrp: Optional[Decimal] = None
    selling_price: Decimal
    manual_barcode: Optional[str] = None

class PrintLabelRequest(BaseModel):
    copies: int
    force_reprint: bool = False

class MatchFamilyRequest(BaseModel):
    family_id: int

class UpdateDraftRequest(BaseModel):
    template_id: Optional[int] = None
    billing_item: Optional[str] = None
    manual_overrides: Optional[str] = None
