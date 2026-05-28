from decimal import Decimal
from typing import Optional

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
