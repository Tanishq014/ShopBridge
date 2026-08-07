from decimal import Decimal

def suggest_print_copies(unit: str | None, received_qty: Decimal | None) -> int | None:
    if received_qty is None:
        return None
        
    if received_qty == Decimal("0"):
        return 0
        
    unit_upper = (unit or "").strip().upper()
    
    if unit_upper in ("PCS", "NOS", "PAIR", "PKT", "BOX", ""):
        # Require integer received_qty for integer copies
        if received_qty % 1 == 0:
            return int(received_qty)
            
    # For DOZ, KG, or fractional PCS, return None (unresolved)
    return None
