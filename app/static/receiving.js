document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('receiving-search');
  const filterTabs = document.querySelectorAll('.filter-tab');
  const itemRows = document.querySelectorAll('.item-row');
  
  const progressVerified = document.getElementById('progress-verified');
  const progressTotal = document.getElementById('progress-total');
  const progressFill = document.getElementById('progress-fill');
  
  const countRemaining = document.getElementById('count-remaining');
  const countVerified = document.getElementById('count-verified');
  const countMismatch = document.getElementById('count-mismatch');
  const countAll = document.getElementById('count-all');
  
  const completionSummary = document.getElementById('completion-summary');
  const summaryTotal = document.getElementById('summary-total');
  const summaryVerified = document.getElementById('summary-verified');
  const summaryMismatch = document.getElementById('summary-mismatch');
  
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
  
  let activeFilter = 'REMAINING';
  let searchTerm = '';
  let currentItemId = null;
  let currentExpectedQty = 0;
  let currentExpectedQtyString = '';

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
    let total = 0, remaining = 0, match = 0, pricing = 0, issues = 0, visibleCount = 0;

    itemRows.forEach(row => {
      total++;
      const tally = row.getAttribute('data-tally-status');
      const familyId = row.getAttribute('data-family-id');
      const pricingStatus = row.getAttribute('data-pricing-status');
      const labelStatus = row.getAttribute('data-label-status');
      const recQtyText = document.getElementById(`mismatch-text-${row.getAttribute('data-item-id')}`)?.textContent || "";
      const isReceived = recQtyText.includes('Received: ') && !recQtyText.includes('Received: 0') && !recQtyText.includes('Received: 0.0');

      if (tally === 'UNVERIFIED') {
        remaining++;
      } else if (isReceived) {
        if (!familyId) match++;
        else if (pricingStatus === 'PENDING') pricing++;
        else if (labelStatus === 'FAILED' || labelStatus === 'MISSING_TEMPLATE') issues++;
      }

      // Filtering logic
      let visibleFilter = false;
      if (activeFilter === 'ALL') visibleFilter = true;
      else if (activeFilter === 'REMAINING' && tally === 'UNVERIFIED') visibleFilter = true;
      else if (activeFilter === 'NEEDS_MATCH' && tally !== 'UNVERIFIED' && isReceived && !familyId) visibleFilter = true;
      else if (activeFilter === 'NEEDS_PRICING' && tally !== 'UNVERIFIED' && isReceived && familyId && pricingStatus === 'PENDING') visibleFilter = true;
      else if (activeFilter === 'PRINT_ISSUES' && tally !== 'UNVERIFIED' && isReceived && (labelStatus === 'FAILED' || labelStatus === 'MISSING_TEMPLATE')) visibleFilter = true;

      // Search logic
      let visibleSearch = true;
      if (searchTerm) {
        const desc = normalizeSearchText(row.getAttribute('data-description') || '');
        const normDesc = normalizeSearchText(row.getAttribute('data-norm-description') || '');
        const cd = normalizeSearchText(row.getAttribute('data-code') || '');
        if (!desc.includes(searchTerm) && !normDesc.includes(searchTerm) && !cd.includes(searchTerm)) {
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

    if (document.getElementById('count-remaining')) document.getElementById('count-remaining').textContent = remaining;
    if (document.getElementById('count-match')) document.getElementById('count-match').textContent = match;
    if (document.getElementById('count-pricing')) document.getElementById('count-pricing').textContent = pricing;
    if (document.getElementById('count-issues')) document.getElementById('count-issues').textContent = issues;
    if (document.getElementById('count-all')) document.getElementById('count-all').textContent = total;

    const checked = total - remaining;
    if (progressTotal) progressTotal.textContent = total;
    if (progressVerified) progressVerified.textContent = checked;
    if (progressFill) progressFill.style.width = (total === 0 ? 0 : (checked / total) * 100) + '%';
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
    
    title.textContent = row.querySelector('h4') ? row.querySelector('h4').textContent : 'Unknown';
    code.textContent = row.querySelector('.code') ? row.querySelector('.code').textContent : '';
    
    const expectedEl = document.getElementById('expected-qty-' + currentItemId);
    const expQtyText = expectedEl ? expectedEl.textContent.trim() : '';
    const unitEl = document.getElementById('item-unit-' + currentItemId);
    unitSpan.textContent = unitEl ? unitEl.textContent : 'PCS';
    
    if (expQtyText === '—' || expQtyText === '?' || expQtyText === '') {
      currentExpectedQty = null;
      currentExpectedQtyString = '';
      expectedSpan.textContent = '—';
      document.getElementById('btn-receive-all').style.display = 'none';
      inputQty.value = '';
    } else {
      currentExpectedQtyString = expQtyText;
      currentExpectedQty = parseFloat(expQtyText);
      expectedSpan.textContent = currentExpectedQtyString;
      expectedBtnSpan.textContent = currentExpectedQtyString;
      document.getElementById('btn-receive-all').style.display = 'block';
      inputQty.value = currentExpectedQtyString;
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
    document.getElementById('input-mrp').value = row.getAttribute('data-mrp') || '';
    document.getElementById('input-selling-price').value = row.getAttribute('data-confirmed-selling-price') || row.getAttribute('data-mrp') || '';
    
    const rowData = window.itemsJson?.find(i => i.id == currentItemId);
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
    setTimeout(() => {
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

  function updateDiffIndicator() {
    let val = parseFloat(inputQty.value);
    if (isNaN(val) || currentExpectedQty === null) {
      diffIndicator.textContent = ''; return;
    }
    if (val === currentExpectedQty) {
      diffIndicator.textContent = 'EXACT MATCH'; diffIndicator.style.color = '#28a745';
    } else if (val < currentExpectedQty) {
      diffIndicator.textContent = 'SHORT BY ' + (currentExpectedQty - val); diffIndicator.style.color = '#d73a49';
    } else {
      diffIndicator.textContent = 'EXTRA ' + (val - currentExpectedQty); diffIndicator.style.color = '#ffc107';
    }
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
    row.setAttribute('data-confirmed-selling-price', itemData.confirmed_selling_price || '');

    const icon = document.getElementById('item-icon-' + itemId);
    if (icon) {
      icon.setAttribute('data-status', itemData.tally_status);
      if (itemData.tally_status === 'VERIFIED') icon.textContent = '✓';
      else if (itemData.tally_status === 'MISMATCH') icon.textContent = '⚠';
      else icon.textContent = '○';
    }

    const mismatchText = document.getElementById('mismatch-text-' + itemId);
    if (mismatchText) {
      mismatchText.style.display = itemData.tally_status !== 'UNVERIFIED' ? 'block' : 'none';
      if (itemData.tally_status === 'VERIFIED') {
        mismatchText.className = 'mismatch-text verified';
        mismatchText.textContent = `Received: ${itemData.received_qty}`;
      } else if (itemData.tally_status === 'MISMATCH') {
        mismatchText.className = 'mismatch-text';
        let diffStr = '';
        if (itemData.received_qty < itemData.expected_qty) diffStr = ` (Short ${Math.abs(itemData.expected_qty - itemData.received_qty)})`;
        else if (itemData.received_qty > itemData.expected_qty) diffStr = ` (Extra ${Math.abs(itemData.expected_qty - itemData.received_qty)})`;
        mismatchText.textContent = `Received: ${itemData.received_qty}${diffStr}`;
      }
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
    suggestionsDiv.innerHTML = '';
    const contextDiv = document.getElementById('pricing-context');
    contextDiv.innerHTML = 'Loading context...';
    
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
        btn.textContent = `Cost Based: ₹${suggestions.cost_based_suggestion}`;
        btn.onclick = () => { document.getElementById('input-selling-price').value = suggestions.cost_based_suggestion; updatePricingIndicators(); };
        suggestionsDiv.appendChild(btn);
      }
      
      if (suggestions.mrp_based_suggestion) {
        const btn = document.createElement('button');
        btn.className = 'button outline';
        btn.style.padding = '4px 8px';
        btn.textContent = `MRP Based: ₹${suggestions.mrp_based_suggestion}`;
        btn.onclick = () => { document.getElementById('input-selling-price').value = suggestions.mrp_based_suggestion; updatePricingIndicators(); };
        suggestionsDiv.appendChild(btn);
      }
      
      if (!document.getElementById('input-selling-price').value && suggestions.unified_suggestion && !suggestions.is_conflict) {
        document.getElementById('input-selling-price').value = suggestions.unified_suggestion;
      }
      
      updatePricingIndicators();
    } catch (e) {
      contextDiv.innerHTML = 'Error loading context.';
      console.error(e);
    }
  }

  function updatePricingIndicators() {
    const landing = parseFloat(document.getElementById('input-landing-price').value);
    const mrp = parseFloat(document.getElementById('input-mrp').value);
    const selling = parseFloat(document.getElementById('input-selling-price').value);
    
    let markup = '--', gm = '--', disc = '--';
    
    if (!isNaN(landing) && landing > 0 && !isNaN(selling)) {
      markup = (((selling - landing) / landing) * 100).toFixed(1);
      gm = (((selling - landing) / selling) * 100).toFixed(1);
    }
    if (!isNaN(mrp) && mrp > 0 && !isNaN(selling)) {
      disc = (((mrp - selling) / mrp) * 100).toFixed(1);
    }
    
    document.getElementById('ind-markup').textContent = markup;
    document.getElementById('ind-margin').textContent = gm;
    const discInput = document.getElementById('input-discount');
    if (discInput && document.activeElement !== discInput) {
        discInput.value = disc !== '--' ? disc : '';
    }
  }
  
  document.getElementById('input-landing-price')?.addEventListener('input', () => { updatePricingIndicators(); if(document.getElementById('pricing-section').hidden === false) loadPricingContext(document.getElementById('item-row-' + currentItemId)); });
  document.getElementById('input-mrp')?.addEventListener('input', () => { updatePricingIndicators(); if(document.getElementById('pricing-section').hidden === false) loadPricingContext(document.getElementById('item-row-' + currentItemId)); });
  document.getElementById('input-selling-price')?.addEventListener('input', updatePricingIndicators);
  
  document.getElementById('input-discount')?.addEventListener('input', async (e) => {
      const disc = parseFloat(e.target.value);
      const mrp = parseFloat(document.getElementById('input-mrp').value);
      const selling = parseFloat(document.getElementById('input-selling-price').value);
      
      if (isNaN(disc)) return;
      
      if (!isNaN(selling) && isNaN(mrp)) {
          // Derive MRP from Selling + Disc
          try {
              const res = await fetch(`/receiving/items/${currentItemId}/derive_mrp?selling_price=${selling}&discount_percent=${disc}`);
              if (res.ok) {
                  const data = await res.json();
                  if (data.mrp) {
                      document.getElementById('input-mrp').value = data.mrp;
                  }
              }
          } catch(e) {}
      } else if (!isNaN(mrp) && isNaN(selling)) {
          // Derive Selling from MRP + Disc
          try {
              const res = await fetch(`/receiving/items/${currentItemId}/derive_selling?mrp=${mrp}&discount_percent=${disc}`);
              if (res.ok) {
                  const data = await res.json();
                  if (data.selling_price) {
                      document.getElementById('input-selling-price').value = data.selling_price;
                  }
              }
          } catch(e) {}
      }
      updatePricingIndicators();
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
    updateDraft({ template_id: e.target.value ? parseInt(e.target.value) : null });
  });

  document.getElementById('draft-billing-item')?.addEventListener('change', (e) => {
      updateDraft({ billing_item: e.target.value });
  });

  async function loadDraftStatus() {
    try {
        const res = await fetch(`/receiving/items/${currentItemId}/draft_status`);
        const draft = await res.json();
        
        const select = document.getElementById('select-template');
        if (select) select.value = draft.template_id || '';
        
        const billInput = document.getElementById('draft-billing-item');
        if (billInput) billInput.value = draft.billing_item || '';
        
        const container = document.getElementById('dynamic-fields-container');
        if (!container) return;
        container.innerHTML = '';
        
        draft.fields.forEach(field => {
            const div = document.createElement('div');
            div.style.flex = "1 1 45%";
            let sourceBadge = '';
            if (field.source) {
                const color = field.source === 'MANUAL' ? '#3b82f6' : (field.source === 'AI' ? '#8b5cf6' : (field.source === 'PREVIOUS' ? '#10b981' : '#64748b'));
                sourceBadge = `<span style="font-size: 9px; padding: 2px 4px; border-radius: 4px; background: ${color}; color: white; margin-left: 4px;">${field.source}</span>`;
            }
            
            div.innerHTML = `<label style="font-size: 11px; font-weight: 600;">${field.field_name} ${sourceBadge}<br><input type="text" data-field="${field.field_name}" class="form-input draft-field-input" style="width:100%; margin-top:2px; padding:4px;" value="${field.resolved_value || ''}"></label>`;
            container.appendChild(div);
        });
        
        document.querySelectorAll('.draft-field-input').forEach(input => {
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
      
      updateRowDOM(currentItemId, await printRes.json());
      renderItems();
      closeSheet();
      showToast(isReprint ? 'Reprint requested!' : 'Saved and print requested!');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  document.getElementById('btn-confirm-print')?.addEventListener('click', () => confirmAndPrint(false));
  document.getElementById('btn-reprint')?.addEventListener('click', () => confirmAndPrint(true));

  renderItems(); // initial
});
