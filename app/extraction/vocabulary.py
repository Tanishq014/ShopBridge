"""
Single Source of Truth for the Semantic Extraction Vocabulary.
Every AI provider and semantic mapper targets this structure.
"""

VOCABULARY_V1 = {
    # Core invoice level fields that apply to all items
    "core_fields": [
        "raw_description", 
        "normalized_description", 
        "suggested_billing_item", 
        "quantity", 
        "unit", 
        "purchase_rate", 
        "mrp", 
        "supplier_product_code"
    ],
    # Specialized semantic attributes that templates might request
    "known_attributes": [
        "brand", 
        "size", 
        "color", 
        "article_number", 
        "batch_number", 
        "expiry", 
        "serial_number", 
        "manufacturer",
        "design",
        "model_no"
    ]
}

def get_all_semantic_keys() -> list[str]:
    """Returns a flat list of all known semantic fields."""
    return VOCABULARY_V1["core_fields"] + VOCABULARY_V1["known_attributes"]
