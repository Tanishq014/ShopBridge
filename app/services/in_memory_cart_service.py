"""In-memory catalogue and cart service for Phase 1 voice billing."""
from __future__ import annotations

from decimal import Decimal
import json
import logging
from typing import Sequence

from app.schemas_voice import (
    CatalogueProduct,
    CartAction,
    CartItemSnapshot,
    CartStateSnapshot,
)

logger = logging.getLogger(__name__)

DEFAULT_CATALOGUE: list[CatalogueProduct] = [
    CatalogueProduct(
        product_id="P001",
        name="Rakhi",
        aliases=["rakhi", "राखी", "fancy rakhi", "20 wali rakhi", "25 wali rakhi"],
        category="Festive",
    ),
    CatalogueProduct(
        product_id="P002",
        name="Cotton Hanky",
        aliases=["hanky", "रुमाल", "cotton hanky", "rumal", "50 wale hanky"],
        category="Clothing",
    ),
    CatalogueProduct(
        product_id="P003",
        name="Hand Soap",
        aliases=["hand soap", "soap", "साबुन", "handwash", "liquid soap"],
        category="Toiletries",
    ),
    CatalogueProduct(
        product_id="P004",
        name="Lux Soap",
        aliases=["lux", "lux soap", "लक्स", "lux sabun"],
        category="Soap",
    ),
    CatalogueProduct(
        product_id="P005",
        name="Dove Cream Bar",
        aliases=["dove", "डव", "dove soap", "dove cream bar"],
        category="Soap",
    ),
]


def load_catalogue_from_db() -> list[CatalogueProduct]:
    """Loads active items from SQLite tally_items, falling back to DEFAULT_CATALOGUE."""
    products: list[CatalogueProduct] = list(DEFAULT_CATALOGUE)
    existing_ids = {p.product_id for p in products}

    try:
        from app.db import SessionLocal
        from app.models import TallyItem

        with SessionLocal() as db:
            items = (
                db.query(TallyItem)
                .filter(TallyItem.active_status == "active")
                .order_by(TallyItem.name)
                .all()
            )
            for t in items:
                pid = f"T{t.id}"
                if pid in existing_ids:
                    continue
                aliases = []
                if t.aliases:
                    aliases = [a.strip() for a in t.aliases.split("|") if a.strip()]
                products.append(
                    CatalogueProduct(
                        product_id=pid,
                        name=t.name,
                        aliases=aliases,
                        category=t.stock_group or "Cosmetics",
                    )
                )
                existing_ids.add(pid)
        logger.info("Loaded %d catalogue products (including shop inventory).", len(products))
    except Exception as exc:
        logger.warning("Failed to load inventory from DB, using default catalogue: %s", exc)

    return products


class InMemoryCartService:
    """Thread-safe, Decimal-precise cart service for voice-driven POS operations."""

    def __init__(self, catalogue: Sequence[CatalogueProduct] | None = None) -> None:
        if catalogue is None:
            catalogue = load_catalogue_from_db()
        self.catalogue: dict[str, CatalogueProduct] = {p.product_id: p for p in catalogue}
        self.items: list[CartItemSnapshot] = []
        self._line_seq: int = 1

    def get_catalogue_list(self) -> list[CatalogueProduct]:
        return list(self.catalogue.values())

    def get_catalogue_json(self) -> str:
        data = [p.model_dump() for p in self.catalogue.values()]
        return json.dumps(data, ensure_ascii=False, indent=2)

    def get_catalogue_text(self) -> str:
        """Returns compact pipe-delimited catalogue table for LLM context."""
        lines = ["product_id | name | category"]
        for p in self.catalogue.values():
            cat = p.category or "General"
            lines.append(f"{p.product_id} | {p.name} | {cat}")
        return "\n".join(lines)

    def get_cart_summary_text(self) -> str:
        """Returns a concise description of current items on the bill for LLM context."""
        if not self.items:
            return ""
        lines = []
        for it in self.items:
            mrp_str = f" (MRP ₹{it.mrp})" if it.mrp is not None else ""
            lines.append(
                f"- Line {it.line_id}: {it.name} (ID: {it.product_id}) x{it.quantity} @ ₹{it.rate}{mrp_str} = ₹{it.amount}"
            )
        subtotal = sum((it.amount for it in self.items), Decimal("0.0"))
        lines.append(f"Subtotal: ₹{subtotal}")
        return "\n".join(lines)

    def execute_action(self, action: CartAction) -> CartStateSnapshot:
        action_type = action.action_type.upper()
        if action_type == "ADD":
            self._add_item(action)
        elif action_type == "SET_QUANTITY":
            self._set_quantity(action)
        elif action_type == "UPDATE_PRICE":
            self._update_price(action)
        elif action_type == "REMOVE":
            self._remove_item(action)
        elif action_type == "CLEAR":
            self.items.clear()
        else:
            raise ValueError(f"Unsupported actionType: {action.action_type}")

        return self.get_snapshot()

    def _add_item(self, action: CartAction) -> None:
        if not action.product_id:
            raise ValueError("productId is required for ADD action")

        product = self.catalogue.get(action.product_id)
        if not product:
            raise ValueError(f"Unknown productId: '{action.product_id}'. Product must exist in catalogue.")

        rate = action.rate
        mrp = action.mrp
        quantity = max(1, action.quantity or 1)

        # Compatible merge rule: same product_id AND same rate AND same mrp
        for idx, item in enumerate(self.items):
            if item.product_id == action.product_id and item.rate == rate and item.mrp == mrp:
                new_qty = item.quantity + quantity
                new_amt = Decimal(new_qty) * (rate or Decimal("0.0"))
                self.items[idx] = item.model_copy(
                    update={"quantity": new_qty, "amount": new_amt}
                )
                logger.info(
                    "Merged into existing line %s: %s qty=%d, rate=%s, mrp=%s",
                    item.line_id,
                    product.name,
                    new_qty,
                    rate,
                    mrp,
                )
                return

        # Coexistence rule: different rate or different MRP or first addition creates separate line
        line_id = f"L{self._line_seq:03d}"
        self._line_seq += 1
        amount = Decimal(quantity) * (rate or Decimal("0.0"))
        new_item = CartItemSnapshot(
            line_id=line_id,
            product_id=product.product_id,
            name=product.name,
            quantity=quantity,
            rate=rate,
            mrp=mrp,
            amount=amount,
        )
        self.items.append(new_item)
        logger.info(
            "Created new line %s: %s qty=%d, rate=%s, mrp=%s",
            line_id,
            product.name,
            quantity,
            rate,
            mrp,
        )

    def _set_quantity(self, action: CartAction) -> None:
        new_qty = action.quantity if action.quantity is not None else 1
        if new_qty <= 0:
            self._remove_item(action)
            return

        # 1. Target by line_id if explicitly specified
        if action.line_id:
            for idx, item in enumerate(self.items):
                if item.line_id == action.line_id:
                    rate = action.rate if action.rate is not None else item.rate
                    mrp = action.mrp if action.mrp is not None else item.mrp
                    amt = Decimal(new_qty) * (rate or Decimal("0.0"))
                    self.items[idx] = item.model_copy(
                        update={"quantity": new_qty, "rate": rate, "mrp": mrp, "amount": amt}
                    )
                    logger.info("Updated line %s qty=%d, rate=%s, amount=%s", item.line_id, new_qty, rate, amt)
                    return
            raise ValueError(f"Line not found: {action.line_id}")

        # 2. Target by product_id if unambiguous
        if not action.product_id:
            # Check if there is only 1 line in the entire cart
            if len(self.items) == 1:
                item = self.items[0]
                rate = action.rate if action.rate is not None else item.rate
                mrp = action.mrp if action.mrp is not None else item.mrp
                amt = Decimal(new_qty) * (rate or Decimal("0.0"))
                self.items[0] = item.model_copy(
                    update={"quantity": new_qty, "rate": rate, "mrp": mrp, "amount": amt}
                )
                logger.info("Updated single line %s qty=%d, rate=%s", item.line_id, new_qty, rate)
                return
            raise ValueError("Either line_id or product_id must be provided to set quantity.")

        matching = [item for item in self.items if item.product_id == action.product_id]
        if len(matching) == 1:
            idx = self.items.index(matching[0])
            rate = action.rate if action.rate is not None else matching[0].rate
            mrp = action.mrp if action.mrp is not None else matching[0].mrp
            amt = Decimal(new_qty) * (rate or Decimal("0.0"))
            self.items[idx] = matching[0].model_copy(
                update={"quantity": new_qty, "rate": rate, "mrp": mrp, "amount": amt}
            )
            logger.info("Updated product %s line %s qty=%d, rate=%s", action.product_id, matching[0].line_id, new_qty, rate)
        elif len(matching) > 1:
            rates = ", ".join(f"{it.line_id} (@₹{it.rate})" for it in matching)
            raise ValueError(
                f"Multiple lines exist for product {action.product_id}: {rates}. Please specify which line or rate."
            )
        else:
            raise ValueError(f"Product {action.product_id} is not in the cart.")

    def _update_price(self, action: CartAction) -> None:
        """Updates rate and/or MRP on an existing line (e.g. negotiation: 'kajal 90 ka kar do')."""
        if action.rate is None and action.mrp is None:
            raise ValueError("Rate or MRP is required to update price.")

        target_idx: int | None = None
        if action.line_id:
            for idx, item in enumerate(self.items):
                if item.line_id == action.line_id:
                    target_idx = idx
                    break
            if target_idx is None:
                raise ValueError(f"Line not found: {action.line_id}")
        elif action.product_id:
            matching = [idx for idx, item in enumerate(self.items) if item.product_id == action.product_id]
            if len(matching) == 1:
                target_idx = matching[0]
            elif len(matching) > 1:
                lines_info = ", ".join(f"{self.items[i].line_id} (@₹{self.items[i].rate})" for i in matching)
                raise ValueError(
                    f"Multiple lines exist for product {action.product_id}: {lines_info}. Specify line_id to update price."
                )
            else:
                raise ValueError(f"Product {action.product_id} is not in the cart.")
        elif len(self.items) == 1:
            target_idx = 0
        else:
            raise ValueError("Either line_id or product_id must be provided to update price.")

        item = self.items[target_idx]
        new_rate = action.rate if action.rate is not None else item.rate
        new_mrp = action.mrp if action.mrp is not None else item.mrp
        new_amt = Decimal(item.quantity) * (new_rate or Decimal("0.0"))
        self.items[target_idx] = item.model_copy(
            update={"rate": new_rate, "mrp": new_mrp, "amount": new_amt}
        )
        logger.info(
            "Updated price for line %s (%s): rate=%s (was %s), mrp=%s, amount=%s",
            item.line_id,
            item.name,
            new_rate,
            item.rate,
            new_mrp,
            new_amt,
        )

    def _remove_item(self, action: CartAction) -> None:
        target_idx: int | None = None

        # 1. Target by line_id if explicitly specified
        if action.line_id:
            for idx, item in enumerate(self.items):
                if item.line_id == action.line_id:
                    target_idx = idx
                    break
            if target_idx is None:
                raise ValueError(f"Line not found: {action.line_id}")

        # 2. Target by product_id (with optional rate disambiguation)
        elif action.product_id:
            matching_indices = [
                idx for idx, item in enumerate(self.items)
                if item.product_id == action.product_id
            ]
            if len(matching_indices) == 1:
                target_idx = matching_indices[0]
            elif len(matching_indices) > 1:
                # If rate is specified, try disambiguating by rate
                if action.rate is not None:
                    rate_matches = [
                        idx for idx in matching_indices
                        if self.items[idx].rate == action.rate
                    ]
                    if len(rate_matches) == 1:
                        target_idx = rate_matches[0]
                if target_idx is None:
                    lines_info = ", ".join(f"{self.items[i].line_id} (@₹{self.items[i].rate})" for i in matching_indices)
                    raise ValueError(
                        f"Multiple lines exist for product {action.product_id}: {lines_info}. Specify line_id or rate to remove."
                    )
            else:
                raise ValueError(f"Product {action.product_id} is not in the cart.")

        # 3. If single line in cart and no line/product specified
        elif len(self.items) == 1:
            target_idx = 0
        else:
            raise ValueError("Either line_id or product_id must be provided to remove an item.")

        target_item = self.items[target_idx]

        # Check quantity: if specified and less than current quantity, subtract!
        if action.quantity is not None and action.quantity > 0 and action.quantity < target_item.quantity:
            new_qty = target_item.quantity - action.quantity
            new_amt = Decimal(new_qty) * (target_item.rate or Decimal("0.0"))
            self.items[target_idx] = target_item.model_copy(
                update={"quantity": new_qty, "amount": new_amt}
            )
            logger.info(
                "Subtracted %d from line %s (%s). New qty=%d, amount=%s",
                action.quantity,
                target_item.line_id,
                target_item.name,
                new_qty,
                new_amt,
            )
        else:
            # Whole line removal
            removed = self.items.pop(target_idx)
            logger.info("Removed entire line %s (%s)", removed.line_id, removed.name)

    def get_snapshot(self) -> CartStateSnapshot:
        subtotal = sum((item.amount for item in self.items), Decimal("0.0"))
        return CartStateSnapshot(items=list(self.items), subtotal=subtotal)


# --- Server-Side Session Continuity Registry ---
import uuid

_active_carts: dict[str, InMemoryCartService] = {}


def get_or_create_cart(session_id: str | None = None) -> tuple[str, InMemoryCartService]:
    """Retrieves an existing cart session or initializes a new one for session_id."""
    global _active_carts
    if session_id and session_id in _active_carts:
        cart = _active_carts[session_id]
        logger.info(
            "Reconnected to existing cart session: %s (items=%d, subtotal=%s)",
            session_id,
            len(cart.items),
            cart.get_snapshot().subtotal,
        )
        return session_id, cart

    resolved_id = session_id if session_id else f"bill_{uuid.uuid4().hex[:8]}"
    cart = InMemoryCartService()
    _active_carts[resolved_id] = cart
    logger.info("Initialized new cart session: %s", resolved_id)
    return resolved_id, cart


def clear_cart_session(session_id: str) -> None:
    """Clears all items in the specified cart session."""
    if session_id in _active_carts:
        _active_carts[session_id].items.clear()
        logger.info("Cleared cart session: %s", session_id)


def reset_cart_registry() -> None:
    """Helper for unit tests to clear all registered cart sessions."""
    _active_carts.clear()
