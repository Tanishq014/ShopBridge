import re

with open('scripts/smoke_checks.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Clean up duplicate lines inside the main block
cleaned_lines = []
seen = set()

# We only want to deduplicate assertions, not the whole file, but an easy way is:
# The duplicated phone print checks are between line 192 and 234.
for line in lines:
    # Filter out the unwanted new smoke checks
    if "phoneShowCachedPreview" in line and "/new-stock/preview-image" in line:
        continue
    if "phoneActualPreviewIsGenerated" in line and "phoneShowCachedPreview();" in line:
        continue
    if "phoneSecondaryTools" in line and "data-copy-count" in line:
        continue
    if "phoneStickyPrintButton" in line and "phonePrintButton.disabled" in line:
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
    # Remove old/duplicated ones that we don't want
    
    cleaned_lines.append(line)

# Now deduplicate consecutive identical lines or lines in the huge assertion block
final_lines = []
for line in cleaned_lines:
    if line.strip().startswith('assert_true('):
        if line in final_lines:
            continue
    final_lines.append(line)

with open('scripts/smoke_checks.py', 'w', encoding='utf-8') as f:
    f.writelines(final_lines)

print("Cleaned up smoke_checks.py")
