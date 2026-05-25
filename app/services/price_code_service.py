from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


# Edit this mapping later if the shop wants a different private price code.
PRICE_CODE_DIGITS = {
    "0": "Z",
    "1": "A",
    "2": "B",
    "3": "C",
    "4": "D",
    "5": "E",
    "6": "F",
    "7": "G",
    "8": "H",
    "9": "J",
}


def generate_coded_price(price: Decimal | float | int | str | None) -> str:
    if price in (None, ""):
        return ""

    try:
        amount = Decimal(str(price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return ""

    if amount < 0:
        return ""

    digits = str(int(amount))
    return "".join(PRICE_CODE_DIGITS[digit] for digit in digits)

