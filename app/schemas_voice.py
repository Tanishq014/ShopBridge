"""Pydantic schemas for voice billing with Gemini Live and ShopBridge."""
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field


class CatalogueProduct(BaseModel):
    product_id: str
    name: str
    aliases: list[str] = []
    category: str | None = None


class CartAction(BaseModel):
    action_type: Literal["ADD", "SET_QUANTITY", "UPDATE_PRICE", "REMOVE", "CLEAR"] = Field(
        description="The cart operation to perform. Use UPDATE_PRICE when Dad changes or negotiates the price of an existing item (e.g. 'kajal 90 ka kar do')."
    )
    product_id: str | None = Field(
        default=None,
        description="Exact productId from catalogue. Required for ADD, or used to identify line for UPDATE_PRICE / SET_QUANTITY / REMOVE.",
    )
    line_id: str | None = Field(
        default=None,
        description="Specific line_id (e.g. 'L001') to modify for SET_QUANTITY, UPDATE_PRICE, or REMOVE.",
    )
    quantity: int | None = Field(
        default=None,
        description="Quantity of items. For ADD: defaults to 1 if not stated. For REMOVE: if specified (e.g. '2 rakhi hata do'), subtracts this number; if null (e.g. 'rakhi hata do'), removes the entire line.",
    )
    rate: Decimal | None = Field(
        default=None,
        description="Selling rate spoken by user. Null if not spoken.",
    )
    mrp: Decimal | None = Field(
        default=None,
        description="MRP spoken by user. Null if not spoken.",
    )


class CartItemSnapshot(BaseModel):
    line_id: str
    product_id: str
    name: str
    quantity: int
    rate: Decimal | None
    mrp: Decimal | None
    amount: Decimal


class CartStateSnapshot(BaseModel):
    items: list[CartItemSnapshot]
    subtotal: Decimal
