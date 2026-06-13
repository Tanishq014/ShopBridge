from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import LabelVariant, PrintJob, TemplateMaster
from app.services.barcode_service import assign_barcode, barcode_exists, normalize_barcode
from app.services.field_config import field_label, parse_required_fields
from app.services.price_code_service import extract_price_code_candidates, generate_coded_price
from app.services.settings_service import get_price_code_settings, get_template_field_settings
from app.services.template_folder_service import template_path_exists
from app.services.workflow.form_state_service import format_extra_field_values, parse_extra_field_values
from app.services.workflow.item_service import find_exact_variant, find_or_create_family
from app.services.workflow.pricing_workflow_service import candidate_payload, compact_money, find_candidate_by_key, money
from app.services.workflow.print_service import create_print_job
from app.services.workflow.validation_service import decimal_or_none, int_or_none, label_details_changed


@dataclass(frozen=True)
class PrintNewStockInput:
    workflow_mode: str
    existing_variant_id: str
    family_id: str
    family_name: str
    category: str
    barcode: str
    brand: str
    item_display_name: str
    article_no: str
    size: str
    batch_no: str
    expiry: str
    mrp: str
    selling_price: str
    coded_price: str
    extra_field_values: str
    selected_price_code_key: str
    print_without_billing_price: bool
    force_new_barcode: bool
    template_id: int
    copies: int
    manual_barcode_override: bool


@dataclass(frozen=True)
class PrintNewStockResult:
    job: PrintJob
    template: TemplateMaster
    category: str


class WorkflowPrintError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def process_new_stock_print(db: Session, data: PrintNewStockInput) -> PrintNewStockResult:
    template = db.get(TemplateMaster, data.template_id)
    if not template or not template.active_status:
        raise WorkflowPrintError("Select an active template.")
    if not template_path_exists(template):
        raise WorkflowPrintError("Selected template file is missing on this PC. Fix it in Settings -> Templates.")
    if not parse_required_fields(template.required_fields):
        raise WorkflowPrintError("Extract fields for the selected template before printing.")

    source_variant = db.get(LabelVariant, int_or_none(data.existing_variant_id)) if data.existing_variant_id else None
    if data.workflow_mode == "quick_reprint":
        if not source_variant:
            raise WorkflowPrintError("Select an existing item before quick reprint.")
        job = create_print_job(db, source_variant, template, data.copies)
        return PrintNewStockResult(job=job, template=template, category=data.category)

    required_fields = parse_required_fields(template.required_fields)
    required_field_set = set(required_fields)
    template_field_settings = get_template_field_settings()

    def is_in_template(field_name: str) -> bool:
        if field_name in {"article", "article_no"}:
            return bool({"article", "article_no"} & required_field_set)
        if field_name in {"item_display_name", "design"}:
            return bool({"item_display_name", "design"} & required_field_set)
        if field_name in {"selling_price", "rate"}:
            return bool({"selling_price", "rate"} & required_field_set)
        if field_name in {"batch_no", "shade", "shade_color"}:
            return bool({"batch_no", "shade", "shade_color"} & required_field_set)
        return field_name in required_field_set

    def field_is_required(field_name: str) -> bool:
        if template_field_settings.is_optional(field_name):
            return False
        return is_in_template(field_name)

    def value_or_preserved(field_name: str, raw_value: str, attr_name: str | None = None) -> str:
        detail_fields = {"item_display_name", "design", "article", "article_no", "size", "batch_no", "expiry", "brand"}

        # Hidden detail fields must not leak/save ghost values from another template.
        if field_name in detail_fields and not is_in_template(field_name):
            return ""

        clean_value = (raw_value or "").strip()
        if clean_value:
            return clean_value

        # Keep old preserve behavior only for non-detail hidden fields/source variant compatibility.
        if source_variant and not is_in_template(field_name):
            stored_value = getattr(source_variant, attr_name or field_name, None)
            return "" if stored_value is None else str(stored_value)

        return ""

    final_category = data.category.strip().lower()
    final_family_name = data.family_name.strip() or data.item_display_name.strip()
    if not final_family_name:
        raise WorkflowPrintError("Enter an item name.")

    brand_value = value_or_preserved("brand", data.brand)
    item_name_raw = value_or_preserved("item_display_name", data.item_display_name)
    item_name_value = final_family_name if (not item_name_raw and field_is_required("item_display_name")) else item_name_raw
    article_value = value_or_preserved("article_no", data.article_no)
    size_value = value_or_preserved("size", data.size)
    batch_value = value_or_preserved("batch_no", data.batch_no)
    expiry_value = value_or_preserved("expiry", data.expiry)
    mrp_value = decimal_or_none(value_or_preserved("mrp", data.mrp))
    selling = decimal_or_none(value_or_preserved("selling_price", data.selling_price))
    extra_values = parse_extra_field_values(data.extra_field_values)
    source_extra_values = parse_extra_field_values(source_variant.extra_field_values if source_variant else None)
    for field_name, field_value in source_extra_values.items():
        if field_name not in extra_values and source_variant and not is_in_template(field_name):
            extra_values[field_name] = field_value

    price_code_settings = get_price_code_settings()
    raw_coded_price = data.coded_price.strip().upper()
    if raw_coded_price:
        coded = raw_coded_price
    elif selling is not None:
        coded = generate_coded_price(selling, price_code_settings) or ""
    else:
        coded = value_or_preserved("coded_price", data.coded_price)

    field_values = {
        "brand": brand_value,
        "item_display_name": item_name_value,
        "design": item_name_value,
        "family_name": final_family_name,
        "article": article_value,
        "article_no": article_value,
        "size": size_value,
        "batch_no": batch_value,
        "expiry": expiry_value,
        "mrp": compact_money(mrp_value),
        "selling_price": money(selling),
        "coded_price": coded,
    }
    field_values.update(extra_values)

    price_code_candidates, _priority_code_found = extract_price_code_candidates(
        field_values,
        required_fields,
        price_code_settings,
    )
    selected_candidate = find_candidate_by_key(price_code_candidates, data.selected_price_code_key.strip())
    if selected_candidate:
        selling = selected_candidate.selling_price
        if not raw_coded_price:
            coded = selected_candidate.code
    elif selling is None and price_code_candidates:
        if len(price_code_candidates) == 1:
            selected_candidate = price_code_candidates[0]
            selling = selected_candidate.selling_price
            if not raw_coded_price:
                coded = selected_candidate.code
        elif price_code_candidates:
            options = "; ".join(candidate["label"] for candidate in map(candidate_payload, price_code_candidates))
            raise WorkflowPrintError("Multiple codes found. Choose one or enter Selling Price manually. " + options)
    elif selling is None:
        raise WorkflowPrintError("Code cannot be decoded. Please enter a valid Code.")

    billing_price_missing = selling is None and data.print_without_billing_price
    if selling is not None and not coded:
        coded = generate_coded_price(selling, price_code_settings) or ""
    field_values["selling_price"] = money(selling)
    field_values["coded_price"] = coded
    missing_fields = [
        field_label(field_name)
        for field_name in required_fields
        if field_name != "barcode" and field_is_required(field_name) and not str(field_values.get(field_name, "")).strip()
    ]
    if missing_fields:
        raise WorkflowPrintError("Required for selected template: " + ", ".join(missing_fields))

    exact_variant = None
    workflow_mode = data.workflow_mode
    if not data.force_new_barcode:
        exact_variant = find_exact_variant(
            db,
            category=final_category,
            template=template,
            required_fields=required_fields,
            family_name=final_family_name,
            item_display_name=item_name_value,
            brand=brand_value,
            article_no=article_value,
            size=size_value,
            batch_no=batch_value,
            expiry=expiry_value,
            extra_field_values=extra_values,
            mrp=mrp_value,
            selling_price=selling,
            coded_price=coded,
        )
        if exact_variant:
            source_variant = exact_variant
            workflow_mode = "print"

    family = find_or_create_family(
        db=db,
        category=final_category,
        family_id=int_or_none(data.family_id),
        family_name=final_family_name,
        item_display_name=item_name_value,
    )

    details_changed = label_details_changed(
        source_variant,
        category=final_category,
        family_name=final_family_name,
        template=template,
        brand=brand_value,
        item_display_name=item_name_value,
        article_no=article_value,
        size=size_value,
        batch_no=batch_value,
        expiry=expiry_value,
        extra_field_values=extra_values,
        mrp=mrp_value,
        selling_price=selling,
        coded_price=coded,
    )
    explicit_new_barcode = data.force_new_barcode or workflow_mode == "duplicate"
    create_new_barcode = (
        source_variant is None
        or explicit_new_barcode
        or (details_changed and workflow_mode != "update_existing")
    )
    update_existing = source_variant is not None and not create_new_barcode

    if update_existing:
        variant = source_variant
        requested_barcode = data.barcode.strip()
        if data.manual_barcode_override and requested_barcode and requested_barcode != variant.barcode:
            try:
                variant.barcode = assign_barcode(
                    db,
                    requested_barcode,
                    exclude_variant_id=variant.id,
                    template=template,
                )
            except ValueError as exc:
                raise WorkflowPrintError(str(exc)) from exc
    else:
        requested_barcode = data.barcode
        if (
            source_variant
            and details_changed
            and not data.manual_barcode_override
            and normalize_barcode(requested_barcode) == normalize_barcode(source_variant.barcode)
        ):
            requested_barcode = ""
        if (
            not data.manual_barcode_override
            and requested_barcode.strip()
            and barcode_exists(db, normalize_barcode(requested_barcode))
        ):
            requested_barcode = ""
        try:
            final_barcode = assign_barcode(db, requested_barcode, template=template)
        except ValueError as exc:
            raise WorkflowPrintError(str(exc)) from exc
        variant = LabelVariant(
            barcode=final_barcode,
            family_id=family.id,
            item_display_name=item_name_value,
        )

    variant.family_id = family.id
    variant.brand = brand_value or None
    variant.item_display_name = item_name_value
    variant.article_no = article_value or None
    variant.size = size_value or None
    variant.batch_no = batch_value or None
    variant.expiry = expiry_value or None
    variant.mrp = mrp_value
    variant.selling_price = selling
    variant.coded_price = coded or None
    variant.billing_price_missing = billing_price_missing
    variant.extra_field_values = format_extra_field_values(extra_values)
    variant.template_id = template.id
    variant.status = "active"
    db.add(variant)
    db.commit()
    db.refresh(variant)

    try:
        job = create_print_job(db, variant, template, data.copies)
    except Exception as exc:
        raise WorkflowPrintError(f"Variant saved, but print job failed: {exc}", status_code=500) from exc

    return PrintNewStockResult(job=job, template=template, category=data.category)
