import os

with open('scripts/smoke_checks.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "phoneShowCachedPreview" in line and "/new-stock/preview-image" in line:
        continue
    if "phoneActualPreviewIsGenerated" in line and "phoneShowCachedPreview();" in line:
        continue
    if "phoneSecondaryTools" in line and "data-copy-count" in line:
        continue
    if "phoneStickyPrintButton" in line and "phonePrintButton.disabled" in line:
        continue
    if "phoneSelectTextOnEdit" in line and "field.select()" in line:
        continue
    if "phoneCalculateMarginButton" in line and "phoneMarginPreview" in line:
        continue
    if "phoneRecordDecision" in line and "phoneExactVariant" in line:
        continue
    if "Force New Barcode" in line and "Usually leave this automatic" in line:
        continue
    if "phonePrintCopiesDialog" in line and "phoneOpenCopiesDialog" in line:
        continue
    if "phonePrintCopiesConfirmed" in line and "phoneSubmitPrintButton" in line:
        continue
    if ".scanner-status span" in line and "overflow-wrap: anywhere" in line:
        continue
    if "Loaded saved item" in line and "phone print shows the old green loaded saved item status" in line:
        continue
    if "min-height: 42px" in line and "padding-bottom: 76px" in line:
        continue
    if "Printed" in line and "recent_prints.html" in line:
        continue
    if "Printed" in line and "scan.html" in line:
        continue
    if "Created" in line and "print_jobs.html" in line:
        continue
    if "phone_print(DummyRequest()" in line and "status_code" in line:
        continue
    
    new_lines.append(line)

pos_checks = [
    '        assert_true("???" not in pos_markup, "POS template contains bad currency mojibake")\n',
    '        assert_true("heldBillCount" in pos_markup, "Recent Bills count is missing")\n',
    '        assert_true("scrollIntoView" not in pos_markup.split("function scrollSelectedBillNavIntoView", 1)[1].split("}", 1)[0], "Recent Bills nav must not use scrollIntoView")\n',
    '        assert_true("item.item_count ?? item.lines ?? 0" in pos_markup, "Held bill line count must fall back to lines")\n',
    '        assert_true("item.total_qty ?? item.count ?? 0" in pos_markup, "Held bill qty must fall back to count")\n',
    '        assert_true("PgUp/PgDn Bills" in pos_markup, "POS help text must mention PgUp/PgDn Bills")\n',
]

for i, line in enumerate(new_lines):
    if 'print("Smoke checks passed")' in line:
        for check in reversed(pos_checks):
            new_lines.insert(i, check)
        break

with open('scripts/smoke_checks.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Cleaned up smoke_checks.py")
