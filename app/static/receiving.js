let extractionPollInterval;

window.confirmLargeQuantityPrint = function(copies, itemName) {
  return new Promise((resolve) => {
    const dialog = document.getElementById("printQuantityWarningDialog");
    const msg = document.getElementById("printQuantityWarningDialogMessage");
    const confirmBtn = document.getElementById("confirmPrintQuantityWarningButton");
    const cancelBtn = document.getElementById("cancelPrintQuantityWarningButton");
    const backdrop = document.getElementById("printQuantityWarningDialogBackdrop");

    if (!dialog) {
      resolve(window.confirm(`Warning: You are about to print ${copies} labels${itemName ? ` for "${itemName}"` : ''}.\n\nPress OK to confirm, or Cancel to abort.`));
      return;
    }

    if (msg) {
      msg.textContent = `You are about to print ${copies} labels${itemName ? ` for "${itemName}"` : ''}. Are you sure?`;
    }

    dialog.hidden = false;
    setTimeout(() => {
      confirmBtn?.focus();
    }, 50);

    let isDone = false;

    function cleanup() {
      if (isDone) return;
      isDone = true;
      dialog.hidden = true;
      document.removeEventListener("keydown", onKeyDown, true);
      confirmBtn?.removeEventListener("click", onConfirm);
      cancelBtn?.removeEventListener("click", onCancel);
      backdrop?.removeEventListener("click", onCancel);
    }

    function onConfirm(e) {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      cleanup();
      resolve(true);
    }

    function onCancel(e) {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      cleanup();
      resolve(false);
    }

    function onKeyDown(e) {
      if (dialog.hidden) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onCancel(e);
      } else if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        onConfirm(e);
      }
    }

    confirmBtn?.addEventListener("click", onConfirm);
    cancelBtn?.addEventListener("click", onCancel);
    backdrop?.addEventListener("click", onCancel);
    setTimeout(() => {
      if (!isDone) {
        document.addEventListener("keydown", onKeyDown, true);
      }
    }, 10);
  });
};

let stagedFiles = [];
let dragSourceIndex = null;

function stageFiles(event) {
    const files = Array.from(event.target.files);
    if (files.length === 0) return;
    
    stagedFiles = files;
    renderStagedFiles();
    document.getElementById('upload-staging-area').style.display = 'block';
    
    // Hide buttons
    document.getElementById('btn-ai-extract').style.display = 'none';
    document.getElementById('btn-toggle-draft-form').style.display = 'none';
}

function renderStagedFiles() {
    const list = document.getElementById('staged-files-list');
    list.innerHTML = '';
    
    stagedFiles.forEach((file, index) => {
        const li = document.createElement('li');
        li.draggable = true;
        li.style.padding = '0.5rem';
        li.style.border = '1px solid #ddd';
        li.style.marginBottom = '0.25rem';
        li.style.borderRadius = '4px';
        li.style.background = '#f9fafb';
        li.style.display = 'flex';
        li.style.justifyContent = 'space-between';
        
        li.innerHTML = `<span><strong style="margin-right: 0.5rem; color: var(--accent-blue);">Page ${index + 1}</strong> ${file.name}</span> <span style="color: #999;">☰</span>`;
        
        li.addEventListener('dragstart', (e) => {
            dragSourceIndex = index;
            e.dataTransfer.effectAllowed = 'move';
        });
        
        li.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
        });
        
        li.addEventListener('drop', (e) => {
            e.preventDefault();
            if (dragSourceIndex === null) return;
            const targetIndex = index;
            
            const draggedItem = stagedFiles[dragSourceIndex];
            stagedFiles.splice(dragSourceIndex, 1);
            stagedFiles.splice(targetIndex, 0, draggedItem);
            
            dragSourceIndex = null;
            renderStagedFiles();
        });
        
        list.appendChild(li);
    });
}

function cancelUpload() {
    stagedFiles = [];
    document.getElementById('file-upload').value = '';
    document.getElementById('upload-staging-area').style.display = 'none';
    document.getElementById('btn-ai-extract').style.display = 'block';
    document.getElementById('btn-toggle-draft-form').style.display = 'block';
}

async function confirmUpload(sessionId) {
    if (stagedFiles.length === 0) return;
    
    const extractBtn = document.getElementById('btn-ai-extract');
    const originalText = extractBtn.innerHTML;
    document.getElementById('upload-staging-area').style.display = 'none';
    extractBtn.style.display = 'block';
    extractBtn.innerHTML = '⏳ Uploading...';
    extractBtn.disabled = true;

    const formData = new FormData();
    stagedFiles.forEach(file => {
        formData.append('files', file);
    });

    try {
        const response = await fetch(`/receiving/${sessionId}/extract`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error("Upload failed");
        }

        const data = await response.json();
        
        extractBtn.innerHTML = '⏳ Extracting AI...';
        pollExtractionStatus(sessionId, extractBtn, originalText);
        
    } catch (e) {
        alert("Extraction request failed: " + e.message);
        if (extractBtn) {
            extractBtn.innerHTML = originalText;
            extractBtn.disabled = false;
        }
    }
}

async function pollExtractionStatus(sessionId, extractBtn, originalText) {
    extractionPollInterval = setInterval(async () => {
        try {
            const response = await fetch(`/receiving/${sessionId}/extraction_status`);
            if (!response.ok) return;
            const data = await response.json();
            
            if (data.status === 'COMPLETED') {
                clearInterval(extractionPollInterval);
                extractBtn.innerHTML = '✅ Done! Reloading...';
                setTimeout(() => window.location.reload(), 500);
            } else if (data.status === 'FAILED') {
                clearInterval(extractionPollInterval);
                alert("AI Extraction failed: " + (data.error || "Unknown error"));
                extractBtn.innerHTML = originalText;
                extractBtn.disabled = false;
            }
        } catch (e) {
            console.error("Polling error", e);
        }
    }, 2000);
}

document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('receiving-search');
  const filterTabs = document.querySelectorAll('.filter-tab');
  const itemRows = document.querySelectorAll('.item-row');
  
  // Ctrl+F override
  document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
          if (searchInput) {
              e.preventDefault();
              if (document.activeElement !== searchInput) {
                  searchInput.focus();
                  searchInput.select();
              }
          }
      }
  });

  const progressVerified = document.getElementById('progress-verified');
  const progressTotal = document.getElementById('progress-total');
  const progressFill = document.getElementById('progress-fill');
  
  const countPending = document.getElementById('count-pending');
  const countPricing = document.getElementById('count-pricing');
  const countIssues = document.getElementById('count-issues');
  const countAll = document.getElementById('count-all');
  
  const completionSummary = document.getElementById('completion-summary');
  const summaryTotal = document.getElementById('summary-total');
  const summaryVerified = document.getElementById('summary-verified');
  
  // Sheet DOM
  const sheet = document.getElementById('tally-sheet');
  const backdrop = document.getElementById('tally-sheet-backdrop');
  const title = document.getElementById('sheet-title');
  const code = document.getElementById('sheet-code');
  const expectedSpan = document.getElementById('sheet-expected');
  const expectedBtnSpan = document.getElementById('sheet-expected-btn');
  const unitSpan = document.getElementById('sheet-unit');
  const inputQty = document.getElementById('input-receive-qty');
  const diffIndicator = document.getElementById('diff-indicator');
  
  const savedFilter = localStorage.getItem('receiving_active_filter');
  let activeFilter = (savedFilter && ['PENDING', 'NEEDS_PRICING', 'PRINT_ISSUES', 'ALL'].includes(savedFilter))
    ? savedFilter
    : 'PENDING';

  const initialTab = Array.from(filterTabs).find(t => t.getAttribute('data-filter') === activeFilter);
  if (initialTab) {
    filterTabs.forEach(t => t.classList.remove('active'));
    initialTab.classList.add('active');
  }
  let searchTerm = '';
  let currentItemId = null;
  let currentExpectedQty = 0;
  let currentExpectedQtyString = '';
  let sheetTimeout = null;
  let highlightedIndex = -1;

  // Search logic
  function normalizeSearchText(text) {
    return text.replace(/\s+/g, ' ').trim().toLowerCase();
  }
  
  function updateSearchHighlight() {
      const itemListVisible = document.getElementById('item-list')?.style.display !== 'none';
      if (!itemListVisible) return;

      const visibleRows = Array.from(itemRows).filter(r => !r.classList.contains('hidden'));
      itemRows.forEach(r => r.classList.remove('search-highlighted'));
      
      if (highlightedIndex >= 0 && highlightedIndex < visibleRows.length) {
          const target = visibleRows[highlightedIndex];
          target.classList.add('search-highlighted');
          target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
  }

  function selectRow(row, index) {
      if (!row) return;
      if (row.classList.contains('grid-row')) {
          // If in grid mode, don't open the bottom sheet, just focus the row natively.
          window.gridHighlightedIndex = window.visibleItems ? window.visibleItems.indexOf(row) : 0;
          row.scrollIntoView({ behavior: 'smooth', block: 'center' });
          
          const billingInput = row.querySelector('input[data-field="billing_item"]');
          if (billingInput) {
              billingInput.focus();
              billingInput.select();
          } else {
              const firstInput = row.querySelector('.grid-cell');
              if (firstInput) {
                  firstInput.focus();
                  firstInput.select();
              }
          }
          return;
      }
      openSheet(row);
      highlightedIndex = index;
      updateSearchHighlight();
  }

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchTerm = normalizeSearchText(e.target.value);
      renderItems();
      
      const itemListVisible = document.getElementById('item-list')?.style.display !== 'none';
      if (itemListVisible) {
          const visibleRows = Array.from(itemRows).filter(r => !r.classList.contains('hidden'));
          highlightedIndex = visibleRows.length > 0 ? 0 : -1;
          updateSearchHighlight();
      } else {
          // If in grid mode, we should probably dispatch an event or handle grid filtering here
          // For now, just trigger a custom event that spreadsheet_mode.js can listen to
          document.dispatchEvent(new CustomEvent('grid-search', { detail: searchTerm }));
      }
    });
    
    searchInput.addEventListener('keydown', (e) => {
        const itemListVisible = document.getElementById('item-list')?.style.display !== 'none';
        if (!itemListVisible) return; // Grid mode handles its own keyboard navigation

        const visibleRows = Array.from(itemRows).filter(r => !r.classList.contains('hidden'));
        if (visibleRows.length === 0) return;
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            highlightedIndex = (highlightedIndex + 1) % visibleRows.length;
            updateSearchHighlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            highlightedIndex = (highlightedIndex - 1 + visibleRows.length) % visibleRows.length;
            updateSearchHighlight();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const targetIndex = highlightedIndex >= 0 ? highlightedIndex : 0;
            if (visibleRows[targetIndex]) {
                visibleRows[targetIndex].click();
                searchInput.blur();
            }
        }
    });
  }

  // Filter tabs logic
  filterTabs.forEach(tab => {
    tab.addEventListener('click', (e) => {
      const targetBtn = e.target.closest('.filter-tab') || e.target;
      filterTabs.forEach(t => t.classList.remove('active'));
      targetBtn.classList.add('active');
      activeFilter = targetBtn.getAttribute('data-filter');
      localStorage.setItem('receiving_active_filter', activeFilter);
      renderItems(true);
    });
  });

  function renderItems(filterChanged = false) {
    document.dispatchEvent(new CustomEvent('grid-tab-filter', { detail: { filter: activeFilter, filterChanged: filterChanged } }));
    let total = 0, pending = 0, pricing = 0, issues = 0, visibleCount = 0, verifiedCount = 0;

    itemRows.forEach(row => {
      total++;
      const tally = row.getAttribute('data-tally-status');
      const familyId = row.getAttribute('data-family-id');
      const pricingStatus = row.getAttribute('data-pricing-status');
      const labelStatus = row.getAttribute('data-label-status');
      const isReceived = tally !== 'UNVERIFIED';

      if (tally === 'UNVERIFIED' || tally === 'MISMATCH' || labelStatus !== 'PRINTED') {
        pending++; // Untallied, mismatch, or tallied but not yet printed stay in pending
      }
      if (isReceived && labelStatus !== 'PRINTED') {
        if (pricingStatus === 'PENDING') pricing++;
        else if (labelStatus === 'FAILED' || labelStatus === 'MISSING_TEMPLATE') issues++;
      }
      
      if (isReceived && tally !== 'MISMATCH') {
          verifiedCount++;
      }

      // Filtering logic
      let visibleFilter = false;
      if (activeFilter === 'ALL') visibleFilter = true;
      else if (activeFilter === 'PENDING' && (tally === 'UNVERIFIED' || tally === 'MISMATCH' || labelStatus !== 'PRINTED')) visibleFilter = true;
      else if (activeFilter === 'NEEDS_PRICING' && labelStatus !== 'PRINTED' && pricingStatus === 'PENDING') visibleFilter = true;
      else if (activeFilter === 'PRINT_ISSUES' && (labelStatus === 'FAILED' || labelStatus === 'MISSING_TEMPLATE')) visibleFilter = true;


      // Search logic
      let visibleSearch = true;
      if (searchTerm) {
        let desc = '', normDesc = '', cd = '', mrp = '', sp = '', lp = '', pr = '';
        
        if (row.classList.contains('grid-row')) {
            desc = normalizeSearchText(row.querySelector('span[title]')?.getAttribute('title') || '');
            cd = normalizeSearchText(row.querySelector('.code-field')?.value || '');
            mrp = normalizeSearchText(row.querySelector('input[data-field="mrp"]')?.value || '');
            sp = normalizeSearchText(row.querySelector('input[data-field="selling_price"]')?.value || '');
            lp = normalizeSearchText(row.querySelector('input[data-field="purchase_rate"]')?.value || '');
        } else {
            desc = normalizeSearchText(row.getAttribute('data-description') || '');
            normDesc = normalizeSearchText(row.getAttribute('data-norm-description') || '');
            cd = normalizeSearchText(row.getAttribute('data-code') || '');
            mrp = normalizeSearchText(row.getAttribute('data-mrp') || '');
            sp = normalizeSearchText(row.getAttribute('data-confirmed-selling-price') || '');
            lp = normalizeSearchText(row.getAttribute('data-landing-price') || '');
            pr = normalizeSearchText(row.getAttribute('data-purchase-rate') || '');
        }
        
        const rowText = normalizeSearchText(row.textContent || '');
        
        if (!desc.includes(searchTerm) && !normDesc.includes(searchTerm) && !cd.includes(searchTerm) &&
            !mrp.includes(searchTerm) && !sp.includes(searchTerm) && !lp.includes(searchTerm) && !pr.includes(searchTerm) &&
            !rowText.includes(searchTerm)) {
          visibleSearch = false;
        }
      }

      if (visibleFilter && visibleSearch) {
        row.classList.remove('hidden');
        visibleCount++;
      } else {
        row.classList.add('hidden');
      }
    });

    let emptyStateEl = document.getElementById('empty-state-msg');
    if (visibleCount === 0 && total > 0) {
      if (!emptyStateEl) {
        emptyStateEl = document.createElement('div');
        emptyStateEl.id = 'empty-state-msg';
        emptyStateEl.className = 'empty-state';
        emptyStateEl.textContent = 'No items found.';
        document.getElementById('item-list').appendChild(emptyStateEl);
      }
      emptyStateEl.style.display = 'block';
    } else if (emptyStateEl) {
      emptyStateEl.style.display = 'none';
    }

    if (document.getElementById('count-pending')) document.getElementById('count-pending').textContent = pending;
    if (document.getElementById('count-pricing')) document.getElementById('count-pricing').textContent = pricing;
    if (document.getElementById('count-issues')) document.getElementById('count-issues').textContent = issues;
    if (document.getElementById('count-all')) document.getElementById('count-all').textContent = total;

    const checked = verifiedCount;
    if (progressTotal) progressTotal.textContent = total;
    if (progressVerified) progressVerified.textContent = checked;
    if (progressFill) progressFill.style.width = (total === 0 ? 0 : (checked / total) * 100) + '%';
    
    if (completionSummary) {
        if (pending === 0 && total > 0 && window.SESSION_STATUS === 'RECEIVING') {
            completionSummary.hidden = false;
            if (summaryTotal) summaryTotal.textContent = total;
            if (summaryVerified) summaryVerified.textContent = checked;
            document.querySelector('.workspace-filters').style.display = 'none';
        } else {
            completionSummary.hidden = true;
            document.querySelector('.workspace-filters').style.display = 'flex';
        }
    }
  }

  // Toast UI
  function showToast(message, type = 'success') {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { if (container.contains(toast)) container.removeChild(toast); }, 3000);
  }

  function openSheet(row) {
    if (window.SESSION_STATUS !== 'RECEIVING') {
      showToast('Session is ' + window.SESSION_STATUS + '. Tallying is disabled.', 'error');
      return;
    }
    currentItemId = row.getAttribute('data-item-id');
    window.codeTargetLength = 0; // Reset to avoid flickering padding from previous item
    
    const titleSpan = row.querySelector('.item-title-text') || row.querySelector('h4');
    title.textContent = titleSpan ? (titleSpan.textContent || '').trim() : (row.getAttribute('data-description') || 'Unknown');
    code.textContent = row.querySelector('.code') ? row.querySelector('.code').textContent : '';
    
    // Reset AI marks
    document.querySelectorAll('.ai-mark').forEach(el => el.style.display = 'none');
    
    window.currentSuggestedBilling = '';
    const rowData = window.itemsJson?.find(i => i.id == currentItemId);
    if (rowData && rowData.extracted_payload) {
      try {
        const payload = JSON.parse(rowData.extracted_payload);
        
        // Dynamically toggle AI marks based on payload keys
        for (const key of Object.keys(payload)) {
            const markEl = document.querySelector(`.ai-mark[data-ai-key="${key}"]`);
            if (markEl && payload[key] !== null) {
                // If it's an object with a value property, check that. Otherwise assume it's a raw string.
                const hasValue = typeof payload[key] === 'object' && payload[key] !== null ? payload[key].value !== null : true;
                if (hasValue) {
                    markEl.style.display = 'inline-block';
                }
            }
        }
        
        if (payload.suggested_billing_item) {
            window.currentSuggestedBilling = typeof payload.suggested_billing_item === 'object' ? payload.suggested_billing_item.value : payload.suggested_billing_item;
            // Also light up title mark if suggested_billing_item is present but raw_description is not
            const titleMark = document.querySelector('.ai-mark[data-ai-key="raw_description"]');
            if (titleMark) titleMark.style.display = 'inline-block';
        }
      } catch (e) {
        console.warn("Failed to parse extracted_payload", e);
      }
    }
    
    const expectedEl = document.getElementById('expected-qty-' + currentItemId);
    const expQtyText = expectedEl ? expectedEl.textContent.trim() : '';
    const unitEl = document.getElementById('item-unit-' + currentItemId);
    unitSpan.textContent = unitEl ? unitEl.textContent : 'PCS';
    
    if (expQtyText === '—' || expQtyText === '?' || expQtyText === '') {
      currentExpectedQty = null;
      currentExpectedQtyString = '';
      expectedSpan.textContent = '—';
      document.getElementById('btn-receive-all').style.display = 'none';
    } else {
      currentExpectedQtyString = expQtyText;
      currentExpectedQty = parseFloat(expQtyText);
      expectedSpan.textContent = currentExpectedQtyString;
      if (expectedBtnSpan) expectedBtnSpan.textContent = currentExpectedQtyString;
      document.getElementById('btn-receive-all').style.display = 'block';
    }

    const receivedQty = parseFloat(row.getAttribute('data-received-qty'));
    if (!isNaN(receivedQty)) {
      inputQty.value = receivedQty;
    } else {
      inputQty.value = 0;
    }
    if (row.getAttribute('data-label-status') === 'PRINTED' || row.getAttribute('data-label-status') === 'QUEUED') {
        document.getElementById('btn-confirm-print').style.display = 'none';
        document.getElementById('btn-reprint').style.display = 'block';
    } else {
        document.getElementById('btn-confirm-print').style.display = 'block';
        document.getElementById('btn-reprint').style.display = 'none';
    }

    // Populate pricing fields from data attrs
    document.getElementById('draft-billing-item').value = row.getAttribute('data-billing-item') || '';
    document.getElementById('input-landing-price').value = row.getAttribute('data-landing-price') || row.getAttribute('data-purchase-rate') || '';
    let mrp = parseFloat(row.getAttribute('data-mrp'));
    let selling = parseFloat(row.getAttribute('data-confirmed-selling-price') || row.getAttribute('data-mrp'));
    
    // Restore calculator preferences
    const savedMargin = localStorage.getItem('saved_margin_pct');
    if (savedMargin) {
        document.getElementById('input-calc-margin').value = savedMargin;
        if (isNaN(selling)) {
            const landing = parseFloat(document.getElementById('input-landing-price').value);
            if (!isNaN(landing) && landing > 0) {
                selling = landing * (1 + parseFloat(savedMargin) / 100);
            }
        }
    }
    
    const savedDisc = localStorage.getItem('saved_disc_pct');
    if (savedDisc) {
        document.getElementById('input-calc-markup').value = savedDisc;
    }

    // Set final UI values
    document.getElementById('input-mrp').value = !isNaN(mrp) ? Math.round(mrp).toString() : '';
    document.getElementById('input-selling-price').value = !isNaN(selling) ? Math.round(selling).toString() : '';
    
    // Initialize Code
    if (!isNaN(selling)) {
        updateCodedPriceBox(generateCodedPrice(selling));
    } else {
        updateCodedPriceBox('');
    }
    
    const suggestedCopies = rowData ? rowData.suggested_label_copies : (currentExpectedQty !== null ? Math.ceil(currentExpectedQty) : null);
    
    if (suggestedCopies !== null) {
      document.getElementById('input-label-copies').value = suggestedCopies;
    } else {
      document.getElementById('input-label-copies').value = '';
    }

    updateDiffIndicator();
    
    // Automatically load draft
    loadDraftStatus();
    clearTimeout(sheetTimeout);
    sheet.hidden = false;
    backdrop.hidden = false;
    setTimeout(() => {
      sheet.style.visibility = 'visible';
      sheet.style.transform = 'translateY(0)';
      backdrop.style.opacity = '1';
      
      // Auto-focus first empty field
      setTimeout(() => {
          const active = document.activeElement;
          if (active && sheet.contains(active) && (active.tagName === 'INPUT' || active.tagName === 'SELECT')) {
              return; // User already clicked into a field manually, don't steal focus
          }
          const billingInput = document.getElementById('draft-billing-item');
          const landingInput = document.getElementById('input-landing-price');
          
          let targetInput = null;
          if (billingInput && !billingInput.value) {
              targetInput = billingInput;
          } else if (landingInput && !landingInput.value) {
              targetInput = landingInput;
          } else {
              const isMode2 = document.getElementById('toggle-pricing-mode')?.checked;
              targetInput = isMode2 ? document.getElementById('input-mrp') : document.getElementById('input-calc-margin');
          }
          
          if (targetInput && targetInput.offsetParent !== null) {
              targetInput.focus();
              if (typeof targetInput.select === 'function') targetInput.select();
          }
      }, 200); // Wait for transition and layout
    }, 10);
  }

  function closeSheet() {
    sheet.style.transform = 'translateY(100%)';
    backdrop.style.opacity = '0';
    clearTimeout(sheetTimeout);
    sheetTimeout = setTimeout(() => {
      sheet.hidden = true;
      sheet.style.visibility = 'hidden';
      backdrop.hidden = true;
      currentItemId = null;
    }, 300);
  }

  itemRows.forEach(row => {
    row.addEventListener('click', () => openSheet(row));
  });

  document.getElementById('btn-close-sheet')?.addEventListener('click', closeSheet);
  backdrop?.addEventListener('click', closeSheet);

  document.getElementById('btn-qty-dec')?.addEventListener('click', () => {
    let val = parseFloat(inputQty.value) || 0;
    if (val > 0) { inputQty.value = val - 1; updateDiffIndicator(); submitTally(inputQty.value, true); }
  });

  document.getElementById('btn-qty-inc')?.addEventListener('click', () => {
    let val = parseFloat(inputQty.value) || 0;
    inputQty.value = val + 1; updateDiffIndicator(); submitTally(inputQty.value, true);
  });

  inputQty?.addEventListener('change', () => {
    updateDiffIndicator();
    if (inputQty.value !== '') submitTally(inputQty.value, true);
  });
  
  inputQty?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
          e.preventDefault();
          updateDiffIndicator();
          if (inputQty.value !== '') submitTally(inputQty.value, false); // close on enter
      }
  });

  function updateDiffIndicator() {
      // Diff indicator text removed per user request
      if (diffIndicator) diffIndicator.style.display = 'none';
  }

  async function submitTally(qty, skipClose = false) {
    if (!currentItemId) return;
    try {
      const response = await fetch(`/receiving/items/${currentItemId}/tally`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ received_qty: qty.toString() })
      });
      if (!response.ok) throw new Error((await response.json()).detail || 'Failed to tally');
      updateRowDOM(currentItemId, await response.json());
      renderItems();
      if (!skipClose) closeSheet();
      showToast('Tally saved');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function updateRowDOM(itemId, itemData) {
    const row = document.getElementById('item-row-' + itemId);
    if (row) {
      row.setAttribute('data-tally-status', itemData.tally_status);
      row.setAttribute('data-family-id', itemData.family_id || '');
      row.setAttribute('data-pricing-status', itemData.pricing_status || '');
      row.setAttribute('data-label-status', itemData.label_status || '');
      row.setAttribute('data-landing-price', itemData.landing_price || '');
      row.setAttribute('data-mrp', itemData.mrp || '');
      row.setAttribute('data-confirmed-selling-price', itemData.confirmed_selling_price || '');
      row.setAttribute('data-received-qty', itemData.received_qty);

      const mismatchBadge = document.getElementById('mismatch-badge-' + itemId);
      const verifiedBadge = document.getElementById('verified-badge-' + itemId);
      
      if (mismatchBadge && verifiedBadge) {
        if (itemData.tally_status === 'VERIFIED') {
          mismatchBadge.style.display = 'none';
          verifiedBadge.style.display = 'flex';
          verifiedBadge.textContent = `Rec: ${itemData.received_qty}`;
        } else if (itemData.tally_status === 'MISMATCH') {
          verifiedBadge.style.display = 'none';
          mismatchBadge.style.display = 'flex';
          let diffStr = '';
          if (itemData.received_qty < itemData.expected_qty) diffStr = `(Short ${Math.abs(itemData.expected_qty - itemData.received_qty)})`;
          else if (itemData.received_qty > itemData.expected_qty) diffStr = `(Extra ${Math.abs(itemData.expected_qty - itemData.received_qty)})`;
          mismatchBadge.textContent = `Rec: ${itemData.received_qty} ${diffStr}`;
        } else {
          mismatchBadge.style.display = 'none';
          verifiedBadge.style.display = 'none';
        }
      }
      
      const codeSpan = row.querySelector('.code');
      if (codeSpan && itemData.coded_price) {
          codeSpan.textContent = itemData.coded_price;
      }
    }

    const gridRow = document.querySelector(`.grid-row[data-item-id="${itemId}"]`);
    if (gridRow && typeof window.updateGridRowTallyBadge === 'function') {
      const expQty = itemData.expected_qty !== undefined ? itemData.expected_qty : (parseFloat(gridRow.getAttribute('data-expected-qty')) || null);
      window.updateGridRowTallyBadge(gridRow, itemData.received_qty, expQty, itemData.tally_status);
      if (itemData.label_status) {
        gridRow.setAttribute('data-label-status', itemData.label_status);
        if (itemData.label_status === 'PRINTED') {
          gridRow.classList.add('row-printed');
          const badges = gridRow.querySelector('.badges');
          if (badges && !badges.querySelector('.label-printed-badge')) {
            const pb = document.createElement('span');
            pb.className = 'badge verified label-printed-badge';
            pb.style.fontWeight = '600';
            pb.textContent = 'Printed';
            badges.appendChild(pb);
          }
        }
      }
    }
  }
  document.getElementById('btn-receive-all')?.addEventListener('click', () => {
      inputQty.value = currentExpectedQtyString;
      updateDiffIndicator();
      submitTally(currentExpectedQtyString, true);
  });

  function updatePricingIndicators(source = 'prices') {
    const landing = parseFloat(document.getElementById('input-landing-price').value);
    const mrp = parseFloat(document.getElementById('input-mrp').value);
    const selling = parseFloat(document.getElementById('input-selling-price').value);
    const marginInput = document.getElementById('input-calc-margin');
    const markupInput = document.getElementById('input-calc-markup');
    
    if (source === 'prices') {
        if (!isNaN(landing) && landing > 0 && !isNaN(selling)) {
            const margin = ((selling - landing) / landing) * 100;
            if (marginInput && document.activeElement !== marginInput) marginInput.value = margin.toFixed(1);
        } else if (marginInput && document.activeElement !== marginInput) {
            marginInput.value = '';
        }
        
        if (!isNaN(selling) && selling > 0 && !isNaN(mrp)) {
            const markup = ((mrp - selling) / mrp) * 100;
            if (markupInput && document.activeElement !== markupInput) markupInput.value = markup.toFixed(1);
        } else if (markupInput && document.activeElement !== markupInput) {
            markupInput.value = '';
        }
    }
    
    const liveSellingPreview = document.getElementById('live-selling-price-preview');
    if (liveSellingPreview) {
        if (!isNaN(selling)) {
            liveSellingPreview.textContent = Math.round(selling);
            liveSellingPreview.style.display = 'inline';
        } else {
            liveSellingPreview.style.display = 'none';
        }
    }
    
    // Keep track of coded price in the dedicated UI field
    const codeInput = document.getElementById('input-coded-price');
    if (codeInput && document.activeElement !== codeInput && source === 'calc') {
      if (!isNaN(selling) && selling > 0) {
          const generated = window.generateCodedPrice(selling);
          const decodedTyped = window.decodePriceCode(codeInput.value);
          
          // Only overwrite if the manually typed code doesn't mathematically equal the current selling price
          if (decodedTyped !== selling) {
              updateCodedPriceBox(generated);
          }
      } else {
          updateCodedPriceBox('');
      }
    }
  }
  
  // --- Multi-Mode Layout Logic ---
  
  function applyPricingMode(isMode2) {
      const fieldMargin = document.getElementById('field-margin');
      const fieldDisc = document.getElementById('field-disc');
      const fieldMrp = document.getElementById('field-mrp');
      const fieldCalcBox = document.getElementById('field-calc-box');
      
      const fieldCode = document.getElementById('field-code');
      const pricingSection = document.getElementById('pricing-section');
      if (!fieldMargin || !fieldDisc || !fieldMrp || !fieldCalcBox || !fieldCode || !pricingSection) return;
      
      if (isMode2) {
          // Top-Down Pricing (Mode 2)
          fieldMargin.style.display = 'none';
          fieldDisc.style.display = 'none';
          fieldCalcBox.style.display = 'block';
          
          // Physically reorder DOM nodes for native Tab flow
          pricingSection.appendChild(fieldMrp);
          pricingSection.appendChild(fieldCalcBox);
          pricingSection.appendChild(fieldCode);
          
          fieldMrp.style.order = '1';
          fieldCalcBox.style.order = '2';
          fieldCode.style.order = '3';
      } else {
          // Bottom-Up Pricing (Mode 1)
          fieldMargin.style.display = 'block';
          fieldDisc.style.display = 'block';
          fieldCalcBox.style.display = 'none';
          
          // Physically reorder DOM nodes for native Tab flow
          pricingSection.appendChild(fieldMargin);
          pricingSection.appendChild(fieldCode);
          pricingSection.appendChild(fieldDisc);
          pricingSection.appendChild(fieldMrp);
          
          fieldMargin.style.order = '1';
          fieldCode.style.order = '2';
          fieldDisc.style.order = '3';
          fieldMrp.style.order = '4';
      }
      localStorage.setItem('pricing_strategy_mode', isMode2 ? 'top_down' : 'bottom_up');
  }
  
  window.computeMrpCalculation = function(currentMrp, expr) {
      if (!expr || !Number.isFinite(currentMrp) || currentMrp <= 0) return null;

      let isPercentage = expr.endsWith("%");
      let cleanExpr = isPercentage ? expr.slice(0, -1).trim() : expr;

      let op = "";
      if (["+", "-", "*", "/"].includes(cleanExpr[0])) {
        op = cleanExpr[0];
        cleanExpr = cleanExpr.slice(1).trim();
      }

      let val = parseFloat(cleanExpr);
      if (isNaN(val)) return null;

      if (op === "" && !isPercentage) {
        isPercentage = true;
        if (val < 100) {
          op = "-";
        } else {
          op = "/";
        }
      }

      let newRate = currentMrp;
      if (isPercentage) {
        if (op === "-" || op === "+") {
          val = (currentMrp * val) / 100;
        } else if (op === "/" || op === "*") {
          val = val / 100;
        }
      }

      if (op === "-") newRate = currentMrp - val;
      else if (op === "+") newRate = currentMrp + val;
      else if (op === "*") newRate = currentMrp * val;
      else if (op === "/") newRate = currentMrp / val;
      else newRate = val;

      return newRate;
  };
  
  window.generateCodedPrice = function(price) {
    if (isNaN(price) || price < 0 || price === null || price === '') return '';
    const rounded = Math.round(price).toString();
    const map = window.priceCodeSettings?.digit_to_code || {};
    let code = '';
    for (const char of rounded) {
      const alias = map[char];
      if (!alias) return '';
      code += alias.split(',')[0].trim().toUpperCase();
    }
    return code;
  };
  
  window.decodePriceCode = function(code) {
      if (!code) return null;
      const clean = String(code).trim().toUpperCase();
      if (!clean) return null;
      const map = window.priceCodeSettings?.code_to_digit || {};
      let priceStr = '';
      for (const char of clean) {
          if (char === ' ') continue;
          const digit = map[char];
          if (digit !== undefined) {
              priceStr += digit;
          }
      }
      if (priceStr) {
          const val = parseFloat(priceStr);
          if (!isNaN(val) && val > 0) return val;
      }
      return null;
  };
  
  window.getJunkPadding = function(deficit) {
      if (deficit <= 0) return '';
      const cipherMap = window.priceCodeSettings?.code_to_digit || {};
      const cipherLetters = Object.keys(cipherMap).map(k => k.toUpperCase());
      const allLetters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
      const safeLetters = allLetters.split('').filter(c => !cipherLetters.includes(c));
      
      let junk = '';
      for (let i = 0; i < deficit; i++) {
          junk += safeLetters[Math.floor(Math.random() * safeLetters.length)] || 'X';
      }
      return junk;
  };
  
  function updateCodedPriceBox(cleanCode) {
      const codeInput = document.getElementById('input-coded-price');
      const previewSpan = document.getElementById('clean-code-preview');
      if (!codeInput) return;
      
      if (!cleanCode) {
          codeInput.value = '';
          if (previewSpan) previewSpan.style.display = 'none';
          return;
      }
      
      const targetLen = window.codeTargetLength || 0;
      
      let padded = cleanCode;
      const deficit = targetLen - cleanCode.length;
      if (deficit > 0) {
          const junk = getJunkPadding(deficit);
          const front = Math.floor(junk.length / 2);
          padded = junk.substring(0, front) + cleanCode + junk.substring(front);
      }
      
      codeInput.value = cleanCode;
      
      if (previewSpan) {
          previewSpan.textContent = `(${padded})`;
          previewSpan.style.display = 'inline';
      }
  }
  
  const modeToggle = document.getElementById('toggle-pricing-mode');
  if (modeToggle) {
      modeToggle.checked = localStorage.getItem('pricing_strategy_mode') === 'top_down';
      applyPricingMode(modeToggle.checked);
      modeToggle.addEventListener('change', (e) => {
          applyPricingMode(e.target.checked);
          
          // Sync with Grid Mode toggle
          const gridToggle = document.getElementById('grid-toggle-pricing-mode');
          if (gridToggle && gridToggle.checked !== e.target.checked) {
              gridToggle.checked = e.target.checked;
              gridToggle.dispatchEvent(new Event('change'));
          }
      });
  }
  
  const calcBox = document.getElementById('input-calc-box');
  if (calcBox) {
      calcBox.addEventListener('input', (e) => {
          const expr = e.target.value.trim();
          if (!expr) return;
          const currentMrp = parseFloat(document.getElementById('input-mrp').value) || 0;
          if (currentMrp <= 0) return;
          
          const calcRate = window.computeMrpCalculation(currentMrp, expr);
          if (calcRate !== null && Number.isFinite(calcRate) && calcRate > 0) {
              const roundedPrice = Math.max(1, Math.round(calcRate));
              document.getElementById('input-selling-price').value = String(roundedPrice);
              
              const encoded = window.generateCodedPrice(roundedPrice);
              const codeInput = document.getElementById('input-coded-price');
              if (encoded && codeInput && codeInput.value !== encoded) {
                  codeInput.value = encoded;
                  codeInput.dispatchEvent(new Event("input", { bubbles: true }));
              }
          }
      });
  }
  
  document.getElementById('input-landing-price')?.addEventListener('input', () => { updatePricingIndicators(); });
  document.getElementById('input-mrp')?.addEventListener('input', () => { updatePricingIndicators(); });
  document.getElementById('input-selling-price')?.addEventListener('input', updatePricingIndicators);
  
  // Auto-save core pricing fields to draft
  document.getElementById('draft-billing-item')?.addEventListener('change', (e) => {
      updateDraft({ billing_item: e.target.value });
  });
  
  document.getElementById('pricing-section')?.addEventListener('change', (e) => {
      if (e.target.tagName === 'INPUT') {
          const landing = parseFloat(document.getElementById('input-landing-price').value);
          const mrp = parseFloat(document.getElementById('input-mrp').value);
          const rawCode = document.getElementById('input-coded-price')?.value?.trim()?.toUpperCase();
          
          let selling = null;
          if (rawCode && !/^\d+$/.test(rawCode)) {
              const decoded = window.decodePriceCode ? window.decodePriceCode(rawCode) : null;
              if (decoded !== null && decoded > 0) {
                  selling = Math.round(decoded);
              }
          }
          if (selling === null) {
              const fallbackSell = parseFloat(document.getElementById('input-selling-price').value);
              selling = isNaN(fallbackSell) ? null : fallbackSell;
          }
          
          updateDraft({
              purchase_rate: isNaN(landing) ? null : landing,
              mrp: isNaN(mrp) ? null : mrp,
              selling_price: isNaN(selling) ? null : selling,
              supplier_product_code: rawCode || null
          });
      }
  });
  
  document.getElementById('input-coded-price')?.addEventListener('input', (e) => {
      e.target.value = e.target.value.toUpperCase(); // Force uppercase
      const raw = e.target.value.trim();
      const isNumbersOnly = raw && /^\d+$/.test(raw);
      
      if (isNumbersOnly) {
          e.target.classList.add('invalid-code');
          e.target.title = "Code cannot be only numbers. Use coded letters too.";
          e.target.setCustomValidity("Code cannot be only numbers. Use coded letters too.");
      } else {
          e.target.classList.remove('invalid-code');
          e.target.title = "";
          e.target.setCustomValidity("");
      }

      let decoded = null;
      if (raw && !isNumbersOnly) {
          decoded = window.decodePriceCode(raw);
      }
      
      const previewSpan = document.getElementById('clean-code-preview');
      
      if (decoded !== null && decoded > 0) {
          document.getElementById('input-selling-price').value = Math.round(decoded).toString();
          updatePricingIndicators();
      } else if (!raw) {
          document.getElementById('input-selling-price').value = '';
          updatePricingIndicators();
      }
      
      const targetLen = window.codeTargetLength || 0;
      const deficit = targetLen - raw.length;
      let padded = raw;
      if (deficit > 0 && !isNumbersOnly) {
          const junk = getJunkPadding(deficit);
          const front = Math.floor(junk.length / 2);
          padded = junk.substring(0, front) + raw + junk.substring(front);
      }
      
      if (previewSpan && raw && !isNumbersOnly && decoded !== null && decoded > 0) {
          previewSpan.textContent = `(${padded})`;
          previewSpan.style.display = 'inline';
      } else if (previewSpan) {
          previewSpan.style.display = 'none';
      }
  });
  
  document.getElementById('input-calc-margin')?.addEventListener('input', (e) => {
      const margin = parseFloat(e.target.value);
      const landing = parseFloat(document.getElementById('input-landing-price').value);
      if (!isNaN(margin) && !isNaN(landing) && landing > 0) {
          const selling = Math.round(landing * (1 + margin / 100));
          document.getElementById('input-selling-price').value = selling.toString();
          updatePricingIndicators('calc');
          
          const markup = parseFloat(document.getElementById('input-calc-markup').value);
          if (!isNaN(markup) && markup < 100) {
              const mrp = Math.round(selling / (1 - markup / 100));
              document.getElementById('input-mrp').value = mrp.toString();
          } else {
              const mrp = parseFloat(document.getElementById('input-mrp').value);
              if (!isNaN(mrp) && mrp > 0) {
                  const disc = (((mrp - selling) / mrp) * 100).toFixed(1);
                  document.getElementById('input-calc-markup').value = disc;
              }
          }
      }
      localStorage.setItem('saved_margin_pct', e.target.value);
  });

  document.getElementById('input-calc-markup')?.addEventListener('input', (e) => {
      const markup = parseFloat(e.target.value);
      const selling = parseFloat(document.getElementById('input-selling-price').value);
      if (!isNaN(markup) && !isNaN(selling) && markup < 100 && selling > 0) {
          const mrp = Math.round(selling / (1 - markup / 100));
          document.getElementById('input-mrp').value = mrp.toString();
          updatePricingIndicators('calc');
      }
      localStorage.setItem('saved_disc_pct', e.target.value);
  });

  async function updateDraft(payload) {
    try {
        await fetch(`/receiving/items/${currentItemId}/draft`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        loadDraftStatus();
    } catch(err) {
        showToast('Failed to update draft', 'error');
    }
  }

  document.getElementById('select-template')?.addEventListener('change', (e) => {
    const tid = e.target.value ? parseInt(e.target.value, 10) : null;
    if (tid) localStorage.setItem('saved_template_id', tid.toString());
    const previewBtn = document.getElementById('btn-preview-template');
    if (previewBtn) previewBtn.style.display = tid ? 'inline-block' : 'none';
    
    if (window.templatesData && tid) {
        const tmpl = window.templatesData.find(t => t.id === tid);
        window.codeTargetLength = tmpl ? (tmpl.code_target_length || 0) : 0;
    } else if (!tid) {
        window.codeTargetLength = 0;
    }
    
    updateDraft({ template_id: tid });
    const codeInput = document.getElementById('input-coded-price');
    if (codeInput && codeInput.value) {
        updateCodedPriceBox(codeInput.value.trim());
    }
  });

  document.getElementById('btn-preview-template')?.addEventListener('click', () => {
      const templateId = document.getElementById('select-template').value;
      if (!templateId) return;
      
      let overlay = document.getElementById('template-preview-overlay');
      if (!overlay) {
          overlay = document.createElement('div');
          overlay.id = 'template-preview-overlay';
          Object.assign(overlay.style, {
              position: 'fixed', top: '0', left: '0', width: '100vw', height: '100vh',
              backgroundColor: 'rgba(0,0,0,0.8)', zIndex: '9999',
              display: 'flex', justifyContent: 'center', alignItems: 'center',
              cursor: 'pointer'
          });
          
          const img = document.createElement('img');
          img.id = 'template-preview-image';
          Object.assign(img.style, {
              maxWidth: '90%', maxHeight: '90%', objectFit: 'contain',
              backgroundColor: 'white', padding: '1rem', borderRadius: '8px'
          });
          
          overlay.appendChild(img);
          document.body.appendChild(overlay);
          
          overlay.addEventListener('click', () => { overlay.style.display = 'none'; });
      }
      
      const img = document.getElementById('template-preview-image');
      img.src = `/new-stock/template-preview/${templateId}`;
      overlay.style.display = 'flex';
  });

  document.getElementById('draft-billing-item')?.addEventListener('change', (e) => {
      updateDraft({ billing_item: e.target.value });
  });

  async function loadDraftStatus() {
    try {
        const res = await fetch(`/receiving/items/${currentItemId}/draft_status`);
        const draft = await res.json();
        window.currentDraft = draft;
        
        const select = document.getElementById('select-template');
        const previewBtn = document.getElementById('btn-preview-template');
        if (select) {
            select.value = draft.template_id || '';
            if (previewBtn) previewBtn.style.display = select.value ? 'inline-block' : 'none';
            const savedTemplate = localStorage.getItem('saved_template_id');
            if (savedTemplate && parseInt(savedTemplate) !== draft.template_id) {
                select.value = savedTemplate;
                if (previewBtn) previewBtn.style.display = 'inline-block';
                updateDraft({ template_id: parseInt(savedTemplate) });
                return; // updateDraft calls loadDraftStatus again
            }
        }
        
        const billInput = document.getElementById('draft-billing-item');
        if (billInput) {
            if (document.activeElement !== billInput) {
                billInput.value = draft.billing_item || window.currentSuggestedBilling || '';
            }
            if (!draft.billing_item && window.currentSuggestedBilling) {
                updateDraft({ billing_item: window.currentSuggestedBilling });
            }
        }
        
        const container = document.getElementById('dynamic-fields-container');
        if (!container) return;
        const newFields = draft.fields.filter(f => !['mrp', 'selling_price', 'coded_price', 'family_name'].includes(f.semantic_field));
        
        const fieldPriority = {
            brand: 1,
            item_display_name: 2,
            design: 2,
            article: 3,
            article_no: 3,
            size: 4,
            batch_no: 5,
            expiry: 6
        };

        newFields.sort((a, b) => {
            const pA = fieldPriority[a.semantic_field] || 50;
            const pB = fieldPriority[b.semantic_field] || 50;
            return pA - pB;
        });

        window.codeTargetLength = 0;
        draft.fields.forEach(field => {
            if (field.semantic_field === 'coded_price' && field.default_value) {
                window.codeTargetLength = field.default_value.length;
            }
        });
        
        const existingInputs = Array.from(container.querySelectorAll('.draft-field-input'));
        const existingSemanticFields = existingInputs.map(input => input.getAttribute('data-field'));
        const newSemanticFields = newFields.map(f => f.semantic_field);
        
        const schemaChanged = JSON.stringify(existingSemanticFields) !== JSON.stringify(newSemanticFields);
        
        if (schemaChanged) {
            container.innerHTML = '';
            newFields.forEach(field => {
                const div = document.createElement('div');
                div.style.flex = "1 1 calc(50% - 0.5rem)";
                div.style.minWidth = "120px";
                const isMissing = field.missing;
                div.innerHTML = `<label style="font-size: 11px; font-weight: 600;">${field.template_field}${isMissing ? ' <span class="missing-star" style="color:var(--danger)">*</span>' : ''}<br><input type="text" data-field="${field.semantic_field}" class="form-input draft-field-input" style="width:100%; margin-top:2px; padding:4px; ${isMissing ? 'border-color:var(--danger)' : ''}" value="${field.value || ''}"></label>`;
                container.appendChild(div);
            });
        } else {
            newFields.forEach(field => {
                const input = container.querySelector(`.draft-field-input[data-field="${field.semantic_field}"]`);
                if (input) {
                    if (document.activeElement !== input) {
                        input.value = field.value || '';
                    }
                    if (field.missing) {
                        input.style.borderColor = 'var(--danger)';
                        const star = input.parentElement.querySelector('.missing-star');
                        if (!star) input.parentElement.innerHTML = input.parentElement.innerHTML.replace('<br>', ' <span class="missing-star" style="color:var(--danger)">*</span><br>');
                    } else {
                        input.style.borderColor = '';
                        const star = input.parentElement.querySelector('.missing-star');
                        if (star) star.remove();
                    }
                }
            });
        }
        
        if (schemaChanged) {
            document.querySelectorAll('.draft-field-input').forEach(input => {
                input.addEventListener('input', (e) => {
                    // Capitalize Billing Item or Code fields if they are dynamically rendered
                    const fieldName = e.target.getAttribute('data-field');
                    if (fieldName === 'billing_item' || fieldName === 'supplier_product_code') {
                        e.target.value = e.target.value.toUpperCase();
                    }
                });
                input.addEventListener('change', (e) => {
                    const fieldName = e.target.getAttribute('data-field');
                    const val = e.target.value;
                    const manualOverrides = draft.manual_overrides || {};
                    manualOverrides[fieldName] = val;
                    updateDraft({ manual_overrides: JSON.stringify(manualOverrides) });
                });
            });
        }
        
        if (!draft.ready) {
            document.getElementById('btn-confirm-print').disabled = true;
            document.getElementById('btn-confirm-print').textContent = '[ FILL REQUIRED FIELDS ]';
        } else {
            document.getElementById('btn-confirm-print').disabled = false;
            document.getElementById('btn-confirm-print').textContent = '[ CONFIRM & PRINT ]';
        }
        
        // Re-pad the code badge in case the target length changed from switching templates
        const codeInput = document.getElementById('input-coded-price');
        if (codeInput) {
            updateCodedPriceBox(codeInput.value);
        }
        
    } catch(err) {
        console.error("Draft error", err);
    }
  }
  
  let isPrinting = false;

  async function confirmAndPrint(isReprint=false) {
    if (isPrinting) return;
    
    const landing = document.getElementById('input-landing-price').value;
    const mrp = document.getElementById('input-mrp').value;
    const selling = document.getElementById('input-selling-price').value;
    const copies = document.getElementById('input-label-copies').value;
    const code = document.getElementById('input-coded-price').value;
    
    if (!copies || isNaN(copies) || parseInt(copies, 10) < 1) {
        showToast("Must be at least 1 copy to print.", "error");
        return;
    }
    const copyCount = parseInt(copies, 10);
    if (copyCount > 1000) {
        showToast("Maximum print quantity is 1000.", "error");
        return;
    }
    if (copyCount > 24) {
        const currentItem = items.find(i => i.id === currentItemId);
        const itemName = currentItem ? (currentItem.product_family_name || currentItem.billing_item_name || currentItem.raw_billing_name) : '';
        const confirmed = await window.confirmLargeQuantityPrint(copyCount, itemName);
        if (!confirmed) {
            return;
        }
    }
    
    if (!isReprint) {
        const cleanCode = String(code || "").trim();
        if (!cleanCode) {
            showToast("Price code is required.", "error");
            return;
        }
        if (/^\d+$/.test(cleanCode)) {
            showToast("Code cannot be only numbers. Use coded letters too.", "error");
            return;
        }
    }
    
    if (!selling || isNaN(parseFloat(selling)) || parseFloat(selling) <= 0) {
        showToast('Valid Selling Price / Decodable Code is required.', 'error');
        document.getElementById('input-coded-price')?.focus();
        document.getElementById('input-coded-price')?.select();
        return;
    }
    
    if (mrp && selling && parseFloat(selling) < (parseFloat(mrp) * 0.5)) {
        if (!window.confirm(`WARNING: Selling price (₹${selling}) is suspiciously low (less than 50% of MRP ₹${mrp}).\n\nPress OK/Enter to proceed with printing, or Cancel/Escape to abort.`)) {
            return;
        }
    }
    
    isPrinting = true;
    const btnPrint = document.getElementById('btn-confirm-print');
    const originalText = btnPrint ? btnPrint.textContent : 'CONFIRM & PRINT';
    if (btnPrint) {
        btnPrint.disabled = true;
        btnPrint.textContent = 'PRINTING...';
    }
    
    try {
      const tidVal = document.getElementById('select-template')?.value;
      const parsedTid = tidVal ? parseInt(tidVal, 10) : null;
      
      // 1. Force save the exact padded Code into the draft so the backend doesn't overwrite it
      const previewSpan = document.getElementById('clean-code-preview');
      const rawCode = document.getElementById('input-coded-price')?.value?.trim()?.toUpperCase() || "";
      let coded = rawCode;
      if (previewSpan && previewSpan.style.display !== 'none' && previewSpan.textContent) {
          coded = previewSpan.textContent.replace(/^\(|\)$/g, ''); 
      }
      
      const manualOverrides = (window.currentDraft && window.currentDraft.manual_overrides) ? { ...window.currentDraft.manual_overrides } : {};
      if (coded) {
          manualOverrides['coded_price'] = coded.toUpperCase();
      }
      
      await fetch(`/receiving/items/${currentItemId}/draft`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
              template_id: parsedTid,
              supplier_product_code: rawCode || null,
              manual_overrides: JSON.stringify(manualOverrides) 
          })
      });
      
      const priceRes = await fetch(`/receiving/items/${currentItemId}/price`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          landing_price: landing ? parseFloat(landing) : null,
          mrp: mrp ? parseFloat(mrp) : null,
          selling_price: parseFloat(selling),
          template_id: parsedTid
        })
      });
      if (!priceRes.ok) throw new Error((await priceRes.json()).detail);
      
      const printRes = await fetch(`/receiving/items/${currentItemId}/print`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          copies: parseInt(copies),
          force_reprint: isReprint,
          template_id: parsedTid
        })
      });
      if (!printRes.ok) throw new Error((await printRes.json()).detail);
      const itemData = await printRes.json();
      itemData.coded_price = (coded !== undefined) ? coded.toUpperCase() : '';
      updateRowDOM(currentItemId, itemData);
      
      renderItems();
      closeSheet();
      showToast(isReprint ? 'Reprint requested!' : 'Saved and print requested!');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      isPrinting = false;
      if (btnPrint) {
          btnPrint.disabled = false;
          btnPrint.textContent = originalText;
      }
    }
  }

  document.getElementById('btn-confirm-print')?.addEventListener('click', () => confirmAndPrint(false));
  document.getElementById('btn-reprint')?.addEventListener('click', () => confirmAndPrint(true));

  // Toggle Draft Form
  document.getElementById('btn-toggle-draft-form')?.addEventListener('click', (e) => {
      const form = document.getElementById('draft-form-container');
      if (form) {
          form.classList.toggle('open');
          e.target.textContent = form.classList.contains('open') ? 'Hide Form' : '+ Add Row';
      }
  });

  // Review Mismatches
  document.getElementById('btn-review-mismatches')?.addEventListener('click', () => {
      activeFilter = 'MISMATCHES';
      filterTabs.forEach(t => t.classList.remove('active'));
      renderItems();
  });

  // Session Info Modal
  document.getElementById('btn-session-info')?.addEventListener('click', () => {
      if (window.SESSION_INFO) {
          alert(`Invoice: ${window.SESSION_INFO.invoice}\nDate: ${window.SESSION_INFO.date}\nStatus: ${window.SESSION_INFO.status}\nCreated: ${window.SESSION_INFO.created}`);
      }
  });

  // Force uppercase on draft billing item form field
  const mainBillingInput = document.getElementById('draft-billing-item');
  if (mainBillingInput) {
      mainBillingInput.addEventListener('input', (e) => e.target.value = e.target.value.toUpperCase());
  }
  
  // Select all text on focus
  document.querySelectorAll('input[type="number"], input[type="text"]').forEach(input => {
      input.addEventListener('focus', function() {
          this.select();
      });
  });
  
  // Ensure focused inputs remain visible when mobile keyboard appears
  // (Removed custom scrollIntoView logic as it conflicts with modern browser native keyboard scroll)

  // Keyboard navigation for Tally Sheet (like stock print page)
  const tallySheet = document.getElementById('tally-sheet');
  if (tallySheet) {
      tallySheet.addEventListener('keydown', (e) => {
          if (['Enter', 'ArrowDown', 'ArrowUp'].includes(e.key)) {
              const active = document.activeElement;
              if (active && (active.tagName === 'INPUT' || active.tagName === 'SELECT') && !active.readOnly && !active.disabled) {
                  if (e.key === 'Enter' && active.id === 'input-label-copies') {
                      e.preventDefault();
                      confirmAndPrint(false);
                      return;
                  }
                  
                  let elements = Array.from(tallySheet.querySelectorAll('input:not([disabled]):not([readonly]), select:not([disabled])'))
                      .filter(el => el.offsetParent !== null && el.type !== 'hidden')
                      .map((el, i) => ({ el, i }));
                  
                  elements.sort((a, b) => {
                      const parentA = a.el.closest('.form-field')?.parentElement;
                      const parentB = b.el.closest('.form-field')?.parentElement;
                      if (parentA && parentB && parentA === parentB && window.getComputedStyle(parentA).display.includes('flex')) {
                          const orderA = parseInt(window.getComputedStyle(a.el.closest('.form-field')).order) || 0;
                          const orderB = parseInt(window.getComputedStyle(b.el.closest('.form-field')).order) || 0;
                          if (orderA !== orderB) return orderA - orderB;
                      }
                      return a.i - b.i;
                  });
                  
                  elements = elements.map(x => x.el);
                  const index = elements.indexOf(active);
                  if (index > -1) {
                      e.preventDefault();
                      const dir = e.key === 'ArrowUp' ? -1 : 1;
                      const next = elements[index + dir];
                      if (next) {
                          next.focus();
                          if (typeof next.select === 'function') next.select();
                      } else if (e.key === 'Enter') {
                          // If at the end (e.g. qty or print btn), try to submit or print
                          if (active.id === 'input-print-copies') {
                              document.getElementById('btn-confirm-print')?.click();
                          }
                      }
                  }
              }
          }
      });
  }

  // Auto-select text on first click for all receiving text & number inputs
  document.addEventListener('focusin', (e) => {
    const input = e.target;
    if (input && input.tagName === 'INPUT' && (input.type === 'text' || input.type === 'number' || !input.type)) {
      input.dataset.justFocused = "true";
      if (typeof input.select === 'function') input.select();
    }
  });

  document.addEventListener('mouseup', (e) => {
    const input = e.target;
    if (input && input.tagName === 'INPUT' && input.dataset?.justFocused === "true") {
      e.preventDefault();
      if (typeof input.select === 'function') input.select();
    }
  });

  document.addEventListener('click', (e) => {
    const input = e.target;
    if (input && input.tagName === 'INPUT' && input.dataset?.justFocused === "true") {
      delete input.dataset.justFocused;
      if (typeof input.select === 'function') input.select();
    }
  });

  document.addEventListener('focusout', (e) => {
    if (e.target && e.target.dataset) {
      delete e.target.dataset.justFocused;
    }
  });

  window.renderItems = renderItems;
  window.updateRowDOM = updateRowDOM;
  renderItems(); // initial
});
// Spreadsheet Grid Logic
