from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(120), unique=True, nullable=True, index=True)
    cost_rule_type = Column(String(40), nullable=True) # "MARKUP", "GROSS_MARGIN"
    cost_rule_percent = Column(Numeric(10, 2), nullable=True)
    mrp_discount_percent = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TemplateMaster(Base):
    __tablename__ = "template_masters"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(String(80), nullable=False, unique=True, index=True)
    template_name = Column(String(200), nullable=False)
    label_size = Column(String(80), nullable=True)
    has_logo = Column(Boolean, nullable=False, default=False)
    category = Column(String(120), nullable=True)
    bartender_file_path = Column(String(500), nullable=False)
    printer_name = Column(String(200), nullable=True)
    required_fields = Column(Text, nullable=True)
    default_field_values = Column(Text, nullable=True)
    barcode_sample_value = Column(String(120), nullable=True)
    fields_extracted_file_mtime = Column(String(80), nullable=True)
    semantic_mappings = Column(Text, nullable=True)
    active_status = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class TallyItem(Base):
    __tablename__ = "tally_items"

    id = Column(Integer, primary_key=True)
    name = Column(String(250), unique=True, nullable=False, index=True)
    normalized_name = Column(String(250), index=True)
    active_status = Column(String(40), default="active", nullable=False)
    tally_guid = Column(String(120), nullable=True, index=True)
    stock_group = Column(String(120), nullable=True)
    unit_name = Column(String(80), nullable=True)
    aliases = Column(Text, nullable=True)
    source = Column(String(40), default="odbc", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ProductFamily(Base):
    __tablename__ = "product_families"

    id = Column(Integer, primary_key=True, index=True)
    family_name = Column(String(200), nullable=False, index=True)
    tally_stock_item_name = Column(String(250), nullable=True, index=True)
    category = Column(String(120), nullable=True, index=True)
    default_tax_rate = Column(Numeric(10, 2), nullable=False, default=0)
    default_unit = Column(String(50), nullable=False, default="PCS")
    default_template_id = Column(Integer, ForeignKey("template_masters.id"), nullable=True)
    
    cost_rule_type = Column(String(40), nullable=True) # "MARKUP", "GROSS_MARGIN"
    cost_rule_percent = Column(Numeric(10, 2), nullable=True)
    mrp_discount_percent = Column(Numeric(10, 2), nullable=True)

    active_status = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    default_template = relationship("TemplateMaster", foreign_keys=[default_template_id])
    variants = relationship("LabelVariant", back_populates="family")


class LabelVariant(Base):
    __tablename__ = "label_variants"

    id = Column(Integer, primary_key=True, index=True)
    barcode = Column(String(80), nullable=False, unique=True, index=True)
    family_id = Column(Integer, ForeignKey("product_families.id"), nullable=False, index=True)
    brand = Column(String(160), nullable=True, index=True)
    item_display_name = Column(String(250), nullable=False, index=True)
    article_no = Column(String(120), nullable=True, index=True)
    size = Column(String(80), nullable=True)
    color = Column(String(80), nullable=True)
    batch_no = Column(String(120), nullable=True)
    season = Column(String(120), nullable=True)
    expiry = Column(String(120), nullable=True)
    mrp = Column(Numeric(10, 2), nullable=True)
    selling_price = Column(Numeric(10, 2), nullable=True)
    coded_price = Column(String(120), nullable=True)
    billing_price_missing = Column(Boolean, nullable=False, default=False)
    extra_field_values = Column(Text, nullable=True)
    template_id = Column(Integer, ForeignKey("template_masters.id"), nullable=True)
    status = Column(String(40), nullable=False, default="active", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    family = relationship("ProductFamily", back_populates="variants")
    template = relationship("TemplateMaster", foreign_keys=[template_id])
    print_jobs = relationship("PrintJob", back_populates="variant")


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id = Column(Integer, primary_key=True, index=True)
    variant_id = Column(Integer, ForeignKey("label_variants.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("template_masters.id"), nullable=False, index=True)
    copies = Column(Integer, nullable=False, default=1)
    status = Column(String(40), nullable=False, default="pending", index=True)
    csv_file_path = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    printed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    variant = relationship("LabelVariant", back_populates="print_jobs")
    template = relationship("TemplateMaster", foreign_keys=[template_id])


class PosCart(Base):
    __tablename__ = "pos_carts"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String(40), nullable=False, default="active", index=True)
    cart_mode = Column(String(40), nullable=False, default="normal", server_default="normal", index=True)
    source_sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("PosCartItem", back_populates="cart", cascade="all, delete-orphan")


class PosCartItem(Base):
    __tablename__ = "pos_cart_items"

    id = Column(Integer, primary_key=True, index=True)
    cart_id = Column(Integer, ForeignKey("pos_carts.id"), nullable=False, index=True)
    variant_id = Column(Integer, ForeignKey("label_variants.id"), nullable=True, index=True)
    qty = Column(Integer, nullable=False, default=1)
    unit_price = Column(Numeric(10, 2), nullable=True)
    item_name_snapshot = Column(String(250), nullable=True)
    barcode_snapshot = Column(String(80), nullable=True)
    tally_stock_item_name_snapshot = Column(String(250), nullable=True)
    mrp_snapshot = Column(Numeric(10, 2), nullable=True)
    rate_snapshot = Column(Numeric(10, 2), nullable=True)
    source_type = Column(String(40), nullable=True)
    is_manual_line = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    cart = relationship("PosCart", back_populates="items")
    variant = relationship("LabelVariant", foreign_keys=[variant_id])


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, index=True)
    bill_number = Column(String(40), nullable=False, unique=True, index=True)
    status = Column(String(40), nullable=False, default="completed", index=True)
    subtotal = Column(Numeric(10, 2), nullable=False, default=0)
    discount_total = Column(Numeric(10, 2), nullable=False, default=0)
    round_off = Column(Numeric(10, 2), nullable=False, default=0)
    total = Column(Numeric(10, 2), nullable=False, default=0)
    payment_mode = Column(String(40), nullable=False, default="cash")
    buyer_name = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    print_status = Column(String(40), nullable=False, default="not_printed", index=True)
    tally_sync_status = Column(String(40), nullable=False, default="not_started", index=True)
    tally_voucher_number = Column(String(120), nullable=True)
    tally_voucher_guid = Column(String(120), nullable=True)
    tally_last_error = Column(Text, nullable=True)
    upi_vpa = Column(String(200), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False, index=True)
    label_variant_id = Column(Integer, ForeignKey("label_variants.id"), nullable=True, index=True)
    barcode = Column(String(80), nullable=False, index=True)
    item_name = Column(String(250), nullable=False)
    tally_stock_item_name = Column(String(250), nullable=True, index=True)
    qty = Column(Integer, nullable=False, default=1)
    rate = Column(Numeric(10, 2), nullable=False)
    mrp = Column(Numeric(10, 2), nullable=True)
    discount_amount = Column(Numeric(10, 2), nullable=False, default=0)
    amount = Column(Numeric(10, 2), nullable=False)

    sale = relationship("Sale", back_populates="items")
    label_variant = relationship("LabelVariant", foreign_keys=[label_variant_id])


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    structured_aliases = Column(Text, nullable=True)
    extraction_notes = Column(Text, nullable=True)
    invoice_profile = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class SupplierProductMapping(Base):
    __tablename__ = "supplier_product_mappings"
    __table_args__ = (UniqueConstraint('supplier_id', 'supplier_product_code', name='_supplier_product_code_uc'),)

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier_product_code = Column(String(120), nullable=True, index=True)
    supplier_description = Column(String(250), nullable=True)
    family_id = Column(Integer, ForeignKey("product_families.id"), nullable=False, index=True)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    confidence = Column(Numeric(5, 2), nullable=True)

    supplier = relationship("Supplier")
    family = relationship("ProductFamily")


class ReceivingSession(Base):
    __tablename__ = "receiving_sessions"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    invoice_number = Column(String(120), nullable=True, index=True)
    invoice_date = Column(DateTime, nullable=True)
    source_document_path = Column(String(500), nullable=True)
    status = Column(String(40), nullable=False, default="DRAFT", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = relationship("Supplier")
    items = relationship("ReceivingItem", back_populates="session", cascade="all, delete-orphan")


class ReceivingItem(Base):
    __tablename__ = "receiving_items"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("receiving_sessions.id"), nullable=False, index=True)
    bill_row_number = Column(Integer, nullable=True)

    raw_description = Column(String(500), nullable=True)
    normalized_description = Column(String(500), nullable=True)
    billing_item = Column(String(250), nullable=True)
    supplier_product_code = Column(String(120), nullable=True, index=True)
    hsn_code = Column(String(100), nullable=True)
    extraction_confidence = Column(Numeric(5, 4), nullable=True)
    source_provenance = Column(Text, nullable=True)
    extracted_attributes = Column(Text, nullable=True)
    manual_overrides = Column(Text, nullable=True)

    expected_qty = Column(Numeric(10, 3), nullable=True)
    received_qty = Column(Numeric(10, 3), nullable=True)
    unit = Column(String(40), nullable=True)
    
    purchase_rate = Column(Numeric(10, 2), nullable=True)
    list_price = Column(Numeric(10, 2), nullable=True)
    mrp = Column(Numeric(10, 2), nullable=True)
    discount = Column(Numeric(10, 2), nullable=True)
    line_amount = Column(Numeric(10, 2), nullable=True)

    landing_price = Column(Numeric(10, 2), nullable=True)
    confirmed_selling_price = Column(Numeric(10, 2), nullable=True)
    pricing_rule_applied = Column(String(200), nullable=True)
    pricing_confirmed_at = Column(DateTime, nullable=True)

    family_id = Column(Integer, ForeignKey("product_families.id"), nullable=True, index=True)
    matched_variant_id = Column(Integer, ForeignKey("label_variants.id"), nullable=True, index=True)
    template_id = Column(Integer, ForeignKey("template_masters.id"), nullable=True, index=True)

    tally_status = Column(String(40), nullable=False, default="UNVERIFIED", index=True)
    pricing_status = Column(String(40), nullable=False, default="PENDING", index=True)
    label_status = Column(String(40), nullable=False, default="UNRESOLVED", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("ReceivingSession", back_populates="items")
    family = relationship("ProductFamily")
    matched_variant = relationship("LabelVariant")


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("receiving_sessions.id"), nullable=True, index=True)
    provider = Column(String(50), nullable=True)
    provider_version = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    input_pages = Column(Integer, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    cost = Column(Numeric(10, 4), nullable=True)
    raw_provider_response = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    processing_time = Column(Numeric(10, 2), nullable=True)

    session = relationship("ReceivingSession")


class SupplierExtractionExample(Base):
    __tablename__ = "supplier_extraction_examples"

    id = Column(Integer, primary_key=True, index=True)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True, index=True)
    raw_description = Column(Text, nullable=True)
    normalized_description = Column(Text, nullable=True)
    billing_item = Column(Text, nullable=True)
    attributes = Column(Text, nullable=True)
    approved_by_user = Column(Boolean, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    supplier = relationship("Supplier")
