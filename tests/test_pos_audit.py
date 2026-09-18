import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select, update
from app.db import SessionLocal
from app.models import PosCart, PosCartItem, ProductFamily, LabelVariant, Sale, TallyItem
from app.services.sales_service import checkout_cart, CheckoutError
from app.routes.pos import increase_pos_item, decrease_pos_item, pos_cart_version


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_checkout_failure_restores_cart_status(db_session):
    # Setup active cart with an invalid item (rate missing)
    cart = PosCart(status="active", cart_mode="normal")
    db_session.add(cart)
    db_session.commit()
    db_session.refresh(cart)

    family = ProductFamily(family_name="Test Item Lock", category="General")
    db_session.add(family)
    db_session.commit()

    unique_barcode = f"LCK_{uuid.uuid4().hex[:6].upper()}"
    variant = LabelVariant(
        family_id=family.id,
        barcode=unique_barcode,
        item_display_name="Test Item Lock",
        selling_price=None, # Missing price
        mrp=Decimal("100.00"),
    )
    db_session.add(variant)
    db_session.commit()

    cart_item = PosCartItem(
        cart_id=cart.id,
        variant_id=variant.id,
        qty=1,
        unit_price=None,
        rate_snapshot=None,
        mrp_snapshot=Decimal("100.00"),
        item_name_snapshot="Test Item Lock",
        source_type="barcode",
    )
    db_session.add(cart_item)
    db_session.commit()

    try:
        # Attempt checkout - should raise CheckoutError due to missing rate
        with pytest.raises(CheckoutError) as exc_info:
            checkout_cart(db_session, cart, payment_mode="cash")
        assert "Rate is missing" in str(exc_info.value)

        # Verify cart status was restored to 'active'
        db_session.refresh(cart)
        assert cart.status == "active", "Cart status must be restored to 'active' on checkout error"

        # Now fix the rate and verify checkout succeeds!
        cart_item.rate_snapshot = Decimal("80.00")
        cart_item.unit_price = Decimal("80.00")
        db_session.add(cart_item)
        db_session.commit()

        sale = checkout_cart(db_session, cart, payment_mode="cash")
        assert sale is not None
        assert sale.status == "completed"
        assert sale.total == Decimal("80.00")
        db_session.refresh(cart)
        assert cart.status == "checked_out"
    finally:
        # Cleanup test artifacts
        db_session.delete(variant)
        db_session.delete(family)
        db_session.commit()


def test_decrease_pos_item_deletes_when_qty_one(db_session):
    # Setup active cart with an item of qty 1
    cart = PosCart(status="active", cart_mode="normal")
    db_session.add(cart)
    db_session.commit()
    db_session.refresh(cart)

    cart_item = PosCartItem(
        cart_id=cart.id,
        variant_id=None,
        qty=1,
        unit_price=Decimal("50.00"),
        rate_snapshot=Decimal("50.00"),
        mrp_snapshot=Decimal("50.00"),
        item_name_snapshot="Decrease Test Item",
        source_type="tally_item",
        tally_stock_item_name_snapshot="Decrease Test Item",
    )
    db_session.add(cart_item)
    db_session.commit()
    db_session.refresh(cart_item)

    # Calling decrease on item with qty 1 should delete it
    decrease_pos_item(cart_item.id, db=db_session)

    # Verify item no longer exists
    deleted_item = db_session.get(PosCartItem, cart_item.id)
    assert deleted_item is None, "Item with qty 1 must be deleted on decrease"

    # Verify active cart has 0 items
    remaining_items = db_session.execute(
        select(PosCartItem).where(PosCartItem.cart_id == cart.id)
    ).scalars().all()
    assert len(remaining_items) == 0


def test_increase_pos_item_integer_arithmetic(db_session):
    cart = PosCart(status="active", cart_mode="normal")
    db_session.add(cart)
    db_session.commit()

    cart_item = PosCartItem(
        cart_id=cart.id,
        variant_id=None,
        qty=2,
        unit_price=Decimal("25.00"),
        rate_snapshot=Decimal("25.00"),
        item_name_snapshot="Increase Test Item",
        source_type="tally_item",
        tally_stock_item_name_snapshot="Increase Test Item",
    )
    db_session.add(cart_item)
    db_session.commit()
    db_session.refresh(cart_item)

    # Increase quantity
    increase_pos_item(cart_item.id, db=db_session)
    db_session.refresh(cart_item)
    assert cart_item.qty == 3
    assert isinstance(cart_item.qty, int)


def test_pos_cart_version_signature(db_session):
    # Ensure active cart
    cart = db_session.scalar(select(PosCart).where(PosCart.status == "active"))
    if not cart:
        cart = PosCart(status="active", cart_mode="normal")
        db_session.add(cart)
        db_session.commit()

    v1 = pos_cart_version(db=db_session)
    assert "version" in v1
    assert "count" in v1

    # Adding an item changes version
    item = PosCartItem(
        cart_id=cart.id,
        qty=1,
        unit_price=Decimal("10.00"),
        rate_snapshot=Decimal("10.00"),
        item_name_snapshot="Version Test Item",
        source_type="tally_item",
        tally_stock_item_name_snapshot="Version Test Item",
    )
    db_session.add(item)
    db_session.commit()

    v2 = pos_cart_version(db=db_session)
    assert v2["version"] != v1["version"], "Version must change when an item is added"

    # Cleaning up item
    db_session.delete(item)
    db_session.commit()
