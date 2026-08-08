let extractionPollInterval;

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
  
  let activeFilter = 'PENDING';
  let searchTerm = '';
  let currentItemId = null;
  let currentExpectedQty = 0;
  let currentExpectedQtyString = '';
  let sheetTimeout = null;

  // Search logic
  function normalizeSearchText(text) {
    return text.replace(/\s+/g, ' ').trim().toLowerCase();
  }

  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchTerm = normalizeSearchText(e.target.value);
      renderItems();
    });
  }

  // Filter tabs logic
  filterTabs.forEach(tab => {
    tab.addEventListener('click', (e) => {
      filterTabs.forEach(t => t.classList.remove('active'));
      e.target.classList.add('active');
      activeFilter = e.target.getAttribute('data-filter');
      renderItems();
    });
  });

  function renderItems() {
    let total = 0, pending = 0, pricing = 0, issues = 0, visibleCount = 0, verifiedCount = 0;

    itemRows.forEach(row => {
      total++;
      const tally = row.getAttribute('data-tally-status');
      const familyId = row.getAttribute('data-family-id');
      const pricingStatus = row.getAttribute('data-pricing-status');
      const labelStatus = row.getAttribute('data-label-status');
      const isReceived = tally !== 'UNVERIFIED';

      if (tally === 'UNVERIFIED' || tally === 'MISMATCH') {
        pending++; // Mismatches bundle into pending
      } else if (isReceived) {
        if (pricingStatus === 'PENDING') pricing++;
        else if (labelStatus === 'FAILED' || labelStatus === 'MISSING_TEMPLATE') issues++;
      }
      
      if (isReceived && tally !== 'MISMATCH') {
          verifiedCount++;
      }

      // Filtering logic
      let visibleFilter = false;
      if (activeFilter === 'ALL') visibleFilter = true;
      else if (activeFilter === 'PENDING' && (tally === 'UNVERIFIED' || tally === 'MISMATCH')) visibleFilter = true;
      else if (activeFilter === 'NEEDS_PRICING' && tally !== 'UNVERIFIED' && tally !== 'MISMATCH' && isReceived && pricingStatus === 'PENDING') visibleFilter = true;
      else if (activeFilter === 'PRINT_ISSUES' && tally !== 'UNVERIFIED' && tally !== 'MISMATCH' && isReceived && (labelStatus === 'FAILED' || labelStatus === 'MISSING_TEMPLATE')) visibleFilter = true;


      // Search logic
      let visibleSearch = true;
      if (searchTerm) {
        const desc = normalizeSearchText(row.getAttribute('data-description') || '');
        const normDesc = normalizeSearchText(row.getAttribute('data-norm-description') || '');
        const cd = normalizeSearchText(row.getAttribute('data-code') || '');
        const mrp = normalizeSearchText(row.getAttribute('data-mrp') || '');
        const sp = normalizeSearchText(row.getAttribute('data-confirmed-selling-price') || '');
        const lp = normalizeSearchText(row.getAttribute('data-landing-price') || '');
        const pr = normalizeSearchText(row.getAttribute('data-purchase-rate') || '');
        
        if (!desc.includes(searchTerm) && !normDesc.includes(searchTerm) && !cd.includes(searchTerm) &&
            !mrp.includes(searchTerm) && !sp.includes(searchTerm) && !lp.includes(searchTerm) && !pr.includes(searchTerm)) {
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
    
    title.textContent = row.querySelector('h4') ? row.querySelector('h4').textContent : 'Unknown';
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
        if (isNaN(mrp) && !isNaN(selling)) {
            mrp = selling / (1 - parseFloat(savedDisc) / 100);
        }
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
    
    // Automatically load draft and pricing context
    loadDraftStatus();
    loadPricingContext(row);
    clearTimeout(sheetTimeout);
    sheet.hidden = false;
    backdrop.hidden = false;
    setTimeout(() => {
      sheet.style.visibility = 'visible';
      sheet.style.transform = 'translateY(0)';
      backdrop.style.opacity = '1';
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
    if (!row) return;
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
  document.getElementById('btn-receive-all')?.addEventListener('click', () => {
      inputQty.value = currentExpectedQtyString;
      updateDiffIndicator();
      submitTally(currentExpectedQtyString, true);
  });

  async function loadPricingContext(row, familyId) {
    const landing = document.getElementById('input-landing-price').value;
    const mrp = document.getElementById('input-mrp').value;
    
    const suggestionsDiv = document.getElementById('pricing-suggestions');
    if (suggestionsDiv) suggestionsDiv.innerHTML = '';
    const contextDiv = document.getElementById('pricing-context');
    if (contextDiv) contextDiv.innerHTML = 'Loading context...';
    
    try {
      const [sugRes, prevRes] = await Promise.all([
        fetch(`/receiving/items/${currentItemId}/pricing_suggestions?landing_price=${landing || ''}&mrp=${mrp || ''}`),
        fetch(`/receiving/items/${currentItemId}/previous_price`)
      ]);
      
      const suggestions = await sugRes.json();
      const prev = await prevRes.json();
      
      let ctxHtml = '';
      if (prev.mrp !== null || prev.selling_price !== null) {
        ctxHtml += `<strong>Previous:</strong> MRP ₹${prev.mrp || '-'} / Sell ₹${prev.selling_price || '-'} `;
      } else {
        ctxHtml += `<strong>Previous:</strong> None `;
      }
      
      if (suggestions.cost_rule_type) {
        ctxHtml += `| <strong>Rule:</strong> ${suggestions.cost_rule_type} ${suggestions.cost_rule_percent}% `;
      }
      if (suggestions.mrp_discount_percent) {
        ctxHtml += `| <strong>Disc Rule:</strong> ${suggestions.mrp_discount_percent}% `;
      }
      contextDiv.innerHTML = ctxHtml || 'No pricing rules found.';
      
      if (suggestions.cost_based_suggestion) {
        const btn = document.createElement('button');
        btn.className = 'button outline';
        btn.style.padding = '4px 8px';
        btn.textContent = `Cost Based: ₹${Math.round(parseFloat(suggestions.cost_based_suggestion)).toString()}`;
        btn.onclick = () => { document.getElementById('input-selling-price').value = Math.round(parseFloat(suggestions.cost_based_suggestion)).toString(); updatePricingIndicators(); };
        suggestionsDiv.appendChild(btn);
      }
      
      if (suggestions.mrp_based_suggestion) {
        const btn = document.createElement('button');
        btn.className = 'button outline';
        btn.style.padding = '4px 8px';
        btn.textContent = `MRP Based: ₹${Math.round(parseFloat(suggestions.mrp_based_suggestion)).toString()}`;
        btn.onclick = () => { document.getElementById('input-selling-price').value = Math.round(parseFloat(suggestions.mrp_based_suggestion)).toString(); updatePricingIndicators(); };
        suggestionsDiv.appendChild(btn);
      }
      
      if (!document.getElementById('input-selling-price').value && suggestions.unified_suggestion && !suggestions.is_conflict) {
        document.getElementById('input-selling-price').value = Math.round(parseFloat(suggestions.unified_suggestion)).toString();
      }
      
      updatePricingIndicators();
    } catch (e) {
      contextDiv.innerHTML = 'Error loading context.';
      console.error(e);
    }
  }

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
    
    // Keep track of coded price in the dedicated UI field
    const codeInput = document.getElementById('input-coded-price');
    if (codeInput && document.activeElement !== codeInput) {
      if (!isNaN(selling)) {
          const generated = generateCodedPrice(selling);
          const decodedTyped = decodePriceCode(codeInput.value);
          
          // Only overwrite if the manually typed code doesn't mathematically equal the current selling price
          if (decodedTyped !== selling) {
              updateCodedPriceBox(generated);
          }
      } else {
          updateCodedPriceBox('');
      }
    }
  }
  
  function generateCodedPrice(price) {


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
  }
  
  function decodePriceCode(code) {
      if (!code) return null;
      const map = window.priceCodeSettings?.code_to_digit || {};
      let priceStr = '';
      for (const char of code.toUpperCase()) {
          if (char === ' ') continue;
          const digit = map[char];
          if (digit !== undefined) {
              priceStr += digit;
          }
      }
      return priceStr ? parseFloat(priceStr) : null;
  }
  
  function getJunkPadding(deficit) {
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
  }
  
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
  
  document.getElementById('input-landing-price')?.addEventListener('input', () => { updatePricingIndicators(); if(document.getElementById('pricing-section').hidden === false) loadPricingContext(document.getElementById('item-row-' + currentItemId)); });
  document.getElementById('input-mrp')?.addEventListener('input', () => { updatePricingIndicators(); if(document.getElementById('pricing-section').hidden === false) loadPricingContext(document.getElementById('item-row-' + currentItemId)); });
  document.getElementById('input-selling-price')?.addEventListener('input', updatePricingIndicators);
  
  document.getElementById('input-coded-price')?.addEventListener('input', (e) => {
      e.target.value = e.target.value.toUpperCase(); // Force uppercase
      const raw = e.target.value;
      const decoded = decodePriceCode(raw);
      
      const previewSpan = document.getElementById('clean-code-preview');
      
      if (decoded !== null) {
          document.getElementById('input-selling-price').value = Math.round(decoded).toString();
          updatePricingIndicators();
      }
      
      const targetLen = window.codeTargetLength || 0;
      const deficit = targetLen - raw.length;
      let padded = raw;
      if (deficit > 0) {
          const junk = getJunkPadding(deficit);
          const front = Math.floor(junk.length / 2);
          padded = junk.substring(0, front) + raw + junk.substring(front);
      }
      
      if (previewSpan && raw) {
          previewSpan.textContent = `(${padded})`;
          previewSpan.style.display = 'inline';
      } else if (previewSpan) {
          previewSpan.style.display = 'none';
      }
  });
  
  document.getElementById('input-calc-margin')?.addEventListener('input', (e) => {
      const margin = parseFloat(e.target.value);
      const landing = parseFloat(document.getElementById('input-landing-price').value);
      if (!isNaN(margin) && !isNaN(landing)) {
          const selling = landing * (1 + margin / 100);
          document.getElementById('input-selling-price').value = Math.round(selling).toString();
          updatePricingIndicators('calc');
          
          const markup = parseFloat(document.getElementById('input-calc-markup').value);
          if (!isNaN(markup) && markup < 100) {
              const mrp = Math.round(selling / (1 - markup / 100));
              document.getElementById('input-mrp').value = mrp.toString();
          }
      }
      localStorage.setItem('saved_margin_pct', e.target.value);
  });

  document.getElementById('input-calc-markup')?.addEventListener('input', (e) => {
      const markup = parseFloat(e.target.value);
      const selling = parseFloat(document.getElementById('input-selling-price').value);
      if (!isNaN(markup) && !isNaN(selling) && markup < 100) {
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
    if (e.target.value) localStorage.setItem('saved_template_id', e.target.value);
    const previewBtn = document.getElementById('btn-preview-template');
    if (previewBtn) previewBtn.style.display = e.target.value ? 'inline-block' : 'none';
    updateDraft({ template_id: e.target.value ? parseInt(e.target.value) : null });
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
            if (!draft.template_id) {
                const savedTemplate = localStorage.getItem('saved_template_id');
                if (savedTemplate) {
                    select.value = savedTemplate;
                    if (previewBtn) previewBtn.style.display = 'inline-block';
                    updateDraft({ template_id: parseInt(savedTemplate) });
                    return; // updateDraft calls loadDraftStatus again
                }
            }
        }
        
        const billInput = document.getElementById('draft-billing-item');
        if (billInput) {
            billInput.value = draft.billing_item || window.currentSuggestedBilling || '';
            if (!draft.billing_item && window.currentSuggestedBilling) {
                updateDraft({ billing_item: window.currentSuggestedBilling });
            }
        }
        
        const container = document.getElementById('dynamic-fields-container');
        if (!container) return;
        container.innerHTML = '';
        
        const fieldPriority = {
            brand: 1,
            item_display_name: 2,
            design: 2,
            article: 3,
            article_no: 3,
            size: 4,
            batch_no: 5,
            expiry: 6,
            coded_price: 90,
            mrp: 91,
            selling_price: 92
        };

        draft.fields.sort((a, b) => {
            const pA = fieldPriority[a.semantic_field] || 50;
            const pB = fieldPriority[b.semantic_field] || 50;
            return pA - pB;
        });

        window.codeTargetLength = 0;
        draft.fields.forEach(field => {
            if (field.semantic_field === 'coded_price' && field.default_value) {
                window.codeTargetLength = field.default_value.length;
            }
            if (['mrp', 'selling_price', 'coded_price'].includes(field.semantic_field)) {
                return; // Hide these from dynamic fields, they belong in Pricing Section
            }
            
            const div = document.createElement('div');
            div.style.flex = "1 1 calc(50% - 0.5rem)";
            div.style.minWidth = "120px";
            const isMissing = field.missing;
            div.innerHTML = `<label style="font-size: 11px; font-weight: 600;">${field.template_field}${isMissing ? ' <span style="color:var(--danger)">*</span>' : ''}<br><input type="text" data-field="${field.semantic_field}" class="form-input draft-field-input" style="width:100%; margin-top:2px; padding:4px; ${isMissing ? 'border-color:var(--danger)' : ''}" value="${field.value || ''}"></label>`;
            container.appendChild(div);
        });
        
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

  async function confirmAndPrint(isReprint=false) {
    const landing = document.getElementById('input-landing-price').value;
    const mrp = document.getElementById('input-mrp').value;
    const selling = document.getElementById('input-selling-price').value;
    const copies = document.getElementById('input-label-copies').value;
    
    if (!selling) return showToast('Selling Price is required', 'error');
    if (copies === '') return showToast('Copies is required (0 for none)', 'error');
    
    try {
      // 1. Force save the exact padded Code into the draft so the backend doesn't overwrite it
      const previewSpan = document.getElementById('clean-code-preview');
      let coded = document.getElementById('input-coded-price').value;
      if (previewSpan && previewSpan.style.display !== 'none' && previewSpan.textContent) {
          coded = previewSpan.textContent.replace(/^\(|\)$/g, ''); 
      }
      
      if (coded !== undefined && window.currentDraft) {
          const manualOverrides = window.currentDraft.manual_overrides || {};
          manualOverrides['coded_price'] = coded.toUpperCase();
          await fetch(`/receiving/items/${currentItemId}/draft`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ manual_overrides: JSON.stringify(manualOverrides) })
          });
      }
      
      const priceRes = await fetch(`/receiving/items/${currentItemId}/price`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          landing_price: landing ? parseFloat(landing) : null,
          mrp: mrp ? parseFloat(mrp) : null,
          selling_price: parseFloat(selling)
        })
      });
      if (!priceRes.ok) throw new Error((await priceRes.json()).detail);
      
      const printRes = await fetch(`/receiving/items/${currentItemId}/print`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          copies: parseInt(copies),
          force_reprint: isReprint
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
  const scrollContent = document.querySelector('.sheet-scroll-content');
  if (scrollContent) {
      scrollContent.addEventListener('focusin', (e) => {
          if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
              setTimeout(() => {
                  e.target.scrollIntoView({ behavior: 'smooth', block: 'center' });
              }, 300); // Wait for keyboard animation
          }
      });
  }

  renderItems(); // initial
});
