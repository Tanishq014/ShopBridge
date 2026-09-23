"""Unit tests for voice billing in-memory cart service."""
from decimal import Decimal
import pytest

from app.schemas_voice import CartAction
from app.services.in_memory_cart_service import (
    InMemoryCartService,
    get_or_create_cart,
    clear_cart_session,
    reset_cart_registry,
)


def test_add_with_rate_no_mrp():
    """Verify '2 rakhi 20 wali' sets rate=20, mrp=None, amount=40."""
    service = InMemoryCartService()
    action = CartAction(
        action_type="ADD",
        product_id="P001",
        quantity=2,
        rate=Decimal("20.00"),
        mrp=None,
    )
    snapshot = service.execute_action(action)

    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert item.line_id == "L001"
    assert item.product_id == "P001"
    assert item.name == "Rakhi"
    assert item.quantity == 2
    assert item.rate == Decimal("20.00")
    assert item.mrp is None
    assert item.amount == Decimal("40.00")
    assert snapshot.subtotal == Decimal("40.00")


def test_add_with_mrp_and_rate():
    """Verify '3 hand soap MRP 60 rate 55' sets mrp=60, rate=55, amount=165."""
    service = InMemoryCartService()
    action = CartAction(
        action_type="ADD",
        product_id="P003",
        quantity=3,
        rate=Decimal("55.00"),
        mrp=Decimal("60.00"),
    )
    snapshot = service.execute_action(action)

    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert item.product_id == "P003"
    assert item.quantity == 3
    assert item.mrp == Decimal("60.00")
    assert item.rate == Decimal("55.00")
    assert item.amount == Decimal("165.00")
    assert snapshot.subtotal == Decimal("165.00")


def test_multi_rate_coexistence():
    """Verify distinct rates for the same product (2 @ 20 and 3 @ 25) do NOT merge."""
    service = InMemoryCartService()

    # 1. 2 Rakhi @ 20
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )
    # 2. 3 Rakhi @ 25
    snapshot = service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=3, rate=Decimal("25.00"))
    )

    assert len(snapshot.items) == 2
    assert snapshot.items[0].line_id == "L001"
    assert snapshot.items[0].quantity == 2
    assert snapshot.items[0].rate == Decimal("20.00")
    assert snapshot.items[0].amount == Decimal("40.00")

    assert snapshot.items[1].line_id == "L002"
    assert snapshot.items[1].quantity == 3
    assert snapshot.items[1].rate == Decimal("25.00")
    assert snapshot.items[1].amount == Decimal("75.00")

    assert snapshot.subtotal == Decimal("115.00")


def test_compatible_rate_merge():
    """Verify items with identical product_id AND rate merge into the same line."""
    service = InMemoryCartService()

    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )
    snapshot = service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=3, rate=Decimal("20.00"))
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].line_id == "L001"
    assert snapshot.items[0].quantity == 5
    assert snapshot.items[0].rate == Decimal("20.00")
    assert snapshot.items[0].amount == Decimal("100.00")
    assert snapshot.subtotal == Decimal("100.00")


def test_set_quantity_single_line():
    """Verify 'nahi rakhi 5 kar do' when only 1 line exists updates cleanly."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )

    snapshot = service.execute_action(
        CartAction(action_type="SET_QUANTITY", product_id="P001", quantity=5)
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].quantity == 5
    assert snapshot.items[0].amount == Decimal("100.00")
    assert snapshot.subtotal == Decimal("100.00")


def test_set_quantity_disambiguation_error():
    """Verify SET_QUANTITY raises ValueError when multiple lines of the same product exist."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=3, rate=Decimal("25.00"))
    )

    with pytest.raises(ValueError, match="Multiple lines exist for product P001"):
        service.execute_action(
            CartAction(action_type="SET_QUANTITY", product_id="P001", quantity=5)
        )


def test_set_quantity_by_line_id():
    """Verify SET_QUANTITY targeting a specific line_id works even with multi-rate coexistence."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=3, rate=Decimal("25.00"))
    )

    # Modify L001 to qty 5
    snapshot = service.execute_action(
        CartAction(action_type="SET_QUANTITY", line_id="L001", quantity=5)
    )

    assert snapshot.items[0].line_id == "L001"
    assert snapshot.items[0].quantity == 5
    assert snapshot.items[0].amount == Decimal("100.00")

    assert snapshot.items[1].line_id == "L002"
    assert snapshot.items[1].quantity == 3
    assert snapshot.items[1].amount == Decimal("75.00")

    assert snapshot.subtotal == Decimal("175.00")


def test_reject_unknown_product_id():
    """Verify adding an uncatalogued product raises ValueError."""
    service = InMemoryCartService()
    with pytest.raises(ValueError, match="Unknown productId: 'P999'"):
        service.execute_action(
            CartAction(action_type="ADD", product_id="P999", quantity=1, rate=Decimal("10.00"))
        )


def test_pos_voice_page_route():
    """Verify GET /pos/voice returns 200 OK and contains the voice billing UI."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/pos/voice")
    assert response.status_code == 200
    assert "Voice POS Billing" in response.text
    assert "Current Cart" in response.text
    assert "Live Conversation" in response.text
    assert "voiceSelect" in response.text
    assert "continuousMicCheck" in response.text


def test_catalogue_loads_shop_inventory_and_kajal():
    """Verify InMemoryCartService loads real Tally items including Kajal and Cosmetics."""
    service = InMemoryCartService()
    items = service.get_catalogue_list()
    # Must have both default items and tally items (>500 items)
    assert len(items) > 500

    # Find Kajal
    kajal = next((p for p in items if "kajal" in p.name.lower()), None)
    assert kajal is not None, "Kajal should be present in loaded shop inventory"

    # Add Kajal with MRP 160 and selling price 100
    snapshot = service.execute_action(
        CartAction(
            action_type="ADD",
            product_id=kajal.product_id,
            quantity=1,
            rate=Decimal("100.00"),
            mrp=Decimal("160.00"),
        )
    )
    assert len(snapshot.items) == 1
    assert snapshot.items[0].product_id == kajal.product_id
    assert snapshot.items[0].name == kajal.name
    assert snapshot.items[0].quantity == 1
    assert snapshot.items[0].mrp == Decimal("160.00")
    assert snapshot.items[0].rate == Decimal("100.00")
    assert snapshot.items[0].amount == Decimal("100.00")
    assert snapshot.subtotal == Decimal("100.00")


def test_multi_mrp_coexistence():
    """Verify same product with same rate but different MRPs do NOT merge (different batches)."""
    service = InMemoryCartService()

    # Rakhi x2 @ ₹20 MRP ₹30
    service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=2,
            rate=Decimal("20.00"),
            mrp=Decimal("30.00"),
        )
    )
    # Rakhi x3 @ ₹20 MRP ₹25
    snapshot = service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=3,
            rate=Decimal("20.00"),
            mrp=Decimal("25.00"),
        )
    )

    assert len(snapshot.items) == 2
    assert snapshot.items[0].line_id == "L001"
    assert snapshot.items[0].quantity == 2
    assert snapshot.items[0].rate == Decimal("20.00")
    assert snapshot.items[0].mrp == Decimal("30.00")
    assert snapshot.items[0].amount == Decimal("40.00")

    assert snapshot.items[1].line_id == "L002"
    assert snapshot.items[1].quantity == 3
    assert snapshot.items[1].rate == Decimal("20.00")
    assert snapshot.items[1].mrp == Decimal("25.00")
    assert snapshot.items[1].amount == Decimal("60.00")

    assert snapshot.subtotal == Decimal("100.00")


def test_compatible_rate_and_mrp_merge():
    """Verify items with identical product_id, rate, AND mrp merge into the same line."""
    service = InMemoryCartService()

    service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=2,
            rate=Decimal("20.00"),
            mrp=Decimal("30.00"),
        )
    )
    snapshot = service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=3,
            rate=Decimal("20.00"),
            mrp=Decimal("30.00"),
        )
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].line_id == "L001"
    assert snapshot.items[0].quantity == 5
    assert snapshot.items[0].rate == Decimal("20.00")
    assert snapshot.items[0].mrp == Decimal("30.00")
    assert snapshot.items[0].amount == Decimal("100.00")
    assert snapshot.subtotal == Decimal("100.00")


def test_remove_quantity_subtraction():
    """Verify '2 rakhi hata do' subtracts 2 from an existing line of 5."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=5,
            rate=Decimal("20.00"),
        )
    )

    # Subtract 2
    snapshot = service.execute_action(
        CartAction(
            action_type="REMOVE",
            product_id="P001",
            quantity=2,
        )
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].quantity == 3
    assert snapshot.items[0].amount == Decimal("60.00")
    assert snapshot.subtotal == Decimal("60.00")


def test_remove_quantity_equal_or_greater_removes_line():
    """Verify removing quantity >= current line quantity removes the entire line."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=3,
            rate=Decimal("20.00"),
        )
    )

    snapshot = service.execute_action(
        CartAction(
            action_type="REMOVE",
            product_id="P001",
            quantity=3,
        )
    )
    assert len(snapshot.items) == 0
    assert snapshot.subtotal == Decimal("0.0")


def test_remove_null_quantity_removes_entire_line():
    """Verify 'rakhi hata do' (quantity=None) removes the entire line."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=5,
            rate=Decimal("20.00"),
        )
    )

    snapshot = service.execute_action(
        CartAction(
            action_type="REMOVE",
            product_id="P001",
            quantity=None,
        )
    )
    assert len(snapshot.items) == 0
    assert snapshot.subtotal == Decimal("0.0")


def test_remove_with_disambiguation_by_rate():
    """Verify removing a specific rate line when multiple lines exist for the product."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=3, rate=Decimal("25.00"))
    )

    # Remove the ₹20 line
    snapshot = service.execute_action(
        CartAction(
            action_type="REMOVE",
            product_id="P001",
            rate=Decimal("20.00"),
        )
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].line_id == "L002"
    assert snapshot.items[0].quantity == 3
    assert snapshot.items[0].rate == Decimal("25.00")
    assert snapshot.subtotal == Decimal("75.00")


def test_session_continuity_and_summary_text():
    """Verify get_or_create_cart retains state across reconnections and produces summary text."""
    reset_cart_registry()

    sess_id = "test_dad_bill_001"
    resolved_id, cart1 = get_or_create_cart(sess_id)
    assert resolved_id == sess_id

    # Add items to first session
    cart1.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P001",
            quantity=2,
            rate=Decimal("20.00"),
            mrp=Decimal("25.00"),
        )
    )
    cart1.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P002",
            quantity=1,
            rate=Decimal("50.00"),
        )
    )

    # Simulate WebSocket reconnect with same session_id
    reconn_id, cart2 = get_or_create_cart(sess_id)
    assert reconn_id == sess_id
    assert cart1 is cart2
    assert len(cart2.items) == 2
    assert cart2.get_snapshot().subtotal == Decimal("90.00")

    # Verify summary text generation for LLM system prompt injection
    summary = cart2.get_cart_summary_text()
    assert "Line L001: Rakhi (ID: P001) x2 @ ₹20.00 (MRP ₹25.00) = ₹40.00" in summary
    assert "Line L002: Cotton Hanky (ID: P002) x1 @ ₹50.00 = ₹50.00" in summary
    assert "Subtotal: ₹90.00" in summary

    # Verify clear_cart_session
    clear_cart_session(sess_id)
    assert len(cart2.items) == 0
    assert cart2.get_snapshot().subtotal == Decimal("0.0")

    reset_cart_registry()


def test_update_price_by_product_id():
    """Verify price negotiation / discount updates rate and recalculates amount cleanly."""
    service = InMemoryCartService()
    # Add Kajal @ 100
    service.execute_action(
        CartAction(
            action_type="ADD",
            product_id="P003",
            quantity=2,
            rate=Decimal("100.00"),
            mrp=Decimal("120.00"),
        )
    )

    # Dad agrees on discount: 'kajal 90 ka kar do'
    snapshot = service.execute_action(
        CartAction(
            action_type="UPDATE_PRICE",
            product_id="P003",
            rate=Decimal("90.00"),
        )
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].product_id == "P003"
    assert snapshot.items[0].quantity == 2
    assert snapshot.items[0].rate == Decimal("90.00")
    assert snapshot.items[0].mrp == Decimal("120.00")
    assert snapshot.items[0].amount == Decimal("180.00")
    assert snapshot.subtotal == Decimal("180.00")


def test_update_price_by_line_id():
    """Verify price update targets specific line when multiple lines exist for the product."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=3, rate=Decimal("25.00"))
    )

    # Update L001 from 20 to 18
    snapshot = service.execute_action(
        CartAction(
            action_type="UPDATE_PRICE",
            line_id="L001",
            rate=Decimal("18.00"),
        )
    )

    assert snapshot.items[0].line_id == "L001"
    assert snapshot.items[0].rate == Decimal("18.00")
    assert snapshot.items[0].amount == Decimal("36.00")

    assert snapshot.items[1].line_id == "L002"
    assert snapshot.items[1].rate == Decimal("25.00")
    assert snapshot.items[1].amount == Decimal("75.00")

    assert snapshot.subtotal == Decimal("111.00")


def test_set_quantity_with_rate_override():
    """Verify SET_QUANTITY updates both quantity and rate if rate is specified (e.g. bulk discount)."""
    service = InMemoryCartService()
    service.execute_action(
        CartAction(action_type="ADD", product_id="P001", quantity=2, rate=Decimal("20.00"))
    )

    # 'rakhi 5 kar do 18 ke rate se'
    snapshot = service.execute_action(
        CartAction(
            action_type="SET_QUANTITY",
            product_id="P001",
            quantity=5,
            rate=Decimal("18.00"),
        )
    )

    assert len(snapshot.items) == 1
    assert snapshot.items[0].quantity == 5
    assert snapshot.items[0].rate == Decimal("18.00")
    assert snapshot.items[0].amount == Decimal("90.00")
    assert snapshot.subtotal == Decimal("90.00")




