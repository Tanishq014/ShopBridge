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
)
from sqlalchemy.orm import relationship

from app.db import Base


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
    active_status = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProductFamily(Base):
    __tablename__ = "product_families"

    id = Column(Integer, primary_key=True, index=True)
    family_name = Column(String(200), nullable=False, index=True)
    tally_stock_item_name = Column(String(250), nullable=True, index=True)
    category = Column(String(120), nullable=True, index=True)
    default_tax_rate = Column(Numeric(10, 2), nullable=False, default=0)
    default_unit = Column(String(50), nullable=False, default="PCS")
    default_template_id = Column(Integer, ForeignKey("template_masters.id"), nullable=True)
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
