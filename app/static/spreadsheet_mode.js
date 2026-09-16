document.addEventListener('DOMContentLoaded', () => {
    const gridSelect = document.getElementById('grid-template-select');
    const spreadsheetContainer = document.getElementById('spreadsheet-container');
    const itemList = document.getElementById('item-list');
    const workspaceFilters = document.querySelector('.workspace-filters');
    const modeToggle = document.getElementById('grid-toggle-pricing-mode');
    
    // Inject sleek grid cell styles
    if (!document.getElementById('sleek-grid-styles')) {
        const style = document.createElement('style');
        style.id = 'sleek-grid-styles';
        style.textContent = `
            .sleek-grid .grid-cell {
                width: 100%;
                box-sizing: border-box;
                padding: 0.1rem 0.25rem;
                border: 1px solid rgba(0,0,0,0.15);
                background: #fff;
                border-radius: 6px;
                font-size: 0.85rem;
                font-family: inherit;
                outline: none;
                color: var(--text-main);
                transition: all 0.2s cubic-bezier(0.1, 0.7, 0.1, 1);
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }
            .sleek-grid .grid-cell:hover {
                border-color: #c7c7cc;
            }
            .sleek-grid .grid-cell:focus {
                background: #fff;
                border-color: var(--accent-blue);
                box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
            }
            .sleek-grid .grid-cell.saving {
                background: rgba(255, 149, 0, 0.05);
                border-color: var(--accent-orange);
            }
            .sleek-grid .grid-cell.error {
                background: rgba(255, 59, 48, 0.05);
                border-color: var(--accent-red);
            }
            .sleek-grid .grid-cell.missing-field {
                border-color: var(--accent-red);
                background: rgba(255, 59, 48, 0.02);
            }
        `;
        document.head.appendChild(style);
    }
    
    // Global Search Handlers for Grid Mode (Initialized Once)
    let gridHighlightedIndex = -1;
    
    function updateGridSearchHighlight(visibleRows, table) {
        if (!table) return;
        const allRows = table.querySelectorAll('.grid-row');
        allRows.forEach(r => r.classList.remove('search-highlighted'));
        
        if (gridHighlightedIndex >= 0 && gridHighlightedIndex < visibleRows.length) {
            const target = visibleRows[gridHighlightedIndex];
            target.classList.add('search-highlighted');
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    document.addEventListener('grid-search', (e) => {
        applyGridFilters();
    });

    const activeTab = document.querySelector('.filter-tab.active');
    let currentGridFilter = activeTab ? (activeTab.getAttribute('data-filter') || 'PENDING') : 'PENDING';
    
    document.addEventListener('grid-tab-filter', (e) => {
        currentGridFilter = e.detail || 'PENDING';
        applyGridFilters();
    });

    function applyGridFilters() {
        const table = document.getElementById('spreadsheet-table');
        if (!table) return;

        const term = (searchInput ? searchInput.value.toLowerCase().trim() : '');
        const rows = table.querySelectorAll('.grid-row');
        const visibleRows = [];

        rows.forEach(row => {
            // Check text search
            let textMatch = true;
            if (term) {
                let textContent = '';
                row.querySelectorAll('.readonly-cell').forEach(cell => {
                    textContent += ' ' + (cell.textContent || '');
                });
                row.querySelectorAll('input').forEach(input => {
                    if (input.type === 'text' || input.type === 'number') {
                        textContent += ' ' + (input.value || '');
                    }
                });
                if (!textContent.toLowerCase().includes(term)) {
                    textMatch = false;
                }
            }

            // Check tab filter
            let tabMatch = true;
            const tallyStatus = row.getAttribute('data-tally-status');
            const pricingStatus = row.getAttribute('data-pricing-status');
            const labelStatus = row.getAttribute('data-label-status');

            if (currentGridFilter === 'PENDING') {
                tabMatch = tallyStatus === 'UNVERIFIED' || tallyStatus === 'MISMATCH';
            } else if (currentGridFilter === 'NEEDS_PRICING') {
                tabMatch = tallyStatus !== 'UNVERIFIED' && tallyStatus !== 'MISMATCH' && pricingStatus === 'PENDING';
            } else if (currentGridFilter === 'PRINT_ISSUES') {
                tabMatch = tallyStatus !== 'UNVERIFIED' && tallyStatus !== 'MISMATCH' && (labelStatus === 'FAILED' || labelStatus === 'MISSING_TEMPLATE');
            }

            if (textMatch && tabMatch) {
                row.style.display = 'flex';
                visibleRows.push(row);
            } else {
                row.style.display = 'none';
            }
        });

        gridHighlightedIndex = visibleRows.length > 0 ? 0 : -1;
        updateGridSearchHighlight(visibleRows, table);
    }

    const searchInput = document.getElementById('receiving-search');
    if (searchInput) {
        searchInput.addEventListener('keydown', (e) => {
            const itemListVisible = document.getElementById('item-list')?.style.display !== 'none';
            if (itemListVisible) return; // List mode handles its own
            
            const table = document.getElementById('spreadsheet-table');
            if (!table) return;

            const rows = Array.from(table.querySelectorAll('.grid-row'));
            const visibleRows = rows.filter(r => r.style.display !== 'none');
            if (visibleRows.length === 0) return;
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                gridHighlightedIndex = (gridHighlightedIndex + 1) % visibleRows.length;
                updateGridSearchHighlight(visibleRows, table);
                
                const billingInput = visibleRows[gridHighlightedIndex].querySelector('input[data-field="billing_item"]');
                if (billingInput) {
                    billingInput.focus();
                    billingInput.select();
                } else {
                    const firstInput = visibleRows[gridHighlightedIndex].querySelector('.grid-cell');
                    if (firstInput) {
                        firstInput.focus();
                        firstInput.select();
                    }
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                gridHighlightedIndex = (gridHighlightedIndex - 1 + visibleRows.length) % visibleRows.length;
                updateGridSearchHighlight(visibleRows, table);
                
                const billingInput = visibleRows[gridHighlightedIndex].querySelector('input[data-field="billing_item"]');
                if (billingInput) {
                    billingInput.focus();
                    billingInput.select();
                } else {
                    const firstInput = visibleRows[gridHighlightedIndex].querySelector('.grid-cell');
                    if (firstInput) {
                        firstInput.focus();
                        firstInput.select();
                    }
                }
            } else if (e.key === 'Enter') {
                e.preventDefault();
                const targetIndex = gridHighlightedIndex >= 0 ? gridHighlightedIndex : 0;
                if (visibleRows[targetIndex]) {
                    const billingInput = visibleRows[targetIndex].querySelector('input[data-field="billing_item"]');
                    if (billingInput) {
                        billingInput.focus();
                        billingInput.select();
                    } else {
                        const firstInput = visibleRows[targetIndex].querySelector('.grid-cell');
                        if (firstInput) {
                            firstInput.focus();
                            firstInput.select();
                        }
                    }
                }
            }
        });
    }

    let currentGridData = [];
    let currentGridTemplate = null;

    if (!gridSelect || !spreadsheetContainer) return;

    if (modeToggle) {
        modeToggle.checked = localStorage.getItem('pricing_strategy_mode') === 'top_down';
        modeToggle.addEventListener('change', (e) => {
            localStorage.setItem('pricing_strategy_mode', e.target.checked ? 'top_down' : 'bottom_up');
            
            // Sync with List Mode toggle
            const listToggle = document.getElementById('toggle-pricing-mode');
            if (listToggle && listToggle.checked !== e.target.checked) {
                listToggle.checked = e.target.checked;
                listToggle.dispatchEvent(new Event('change'));
            }

            if (currentGridData.length > 0) {
                renderGrid(currentGridData);
            }
        });
    }

    gridSelect.addEventListener('change', async (e) => {
        const tid = e.target.value;
        if (!tid) {
            localStorage.removeItem('grid_mode_template');
            spreadsheetContainer.style.display = 'none';
            itemList.style.display = 'flex';
            workspaceFilters.style.display = 'flex';
            document.querySelector('.grid-mode-toggle').style.background = 'transparent';
            return;
        }
        localStorage.setItem('grid_mode_template', tid);
        spreadsheetContainer.style.display = 'block';
        itemList.style.display = 'none';
        // workspaceFilters.style.display = 'none'; // Keep filters visible in grid mode
        spreadsheetContainer.innerHTML = '<div style="padding: 2rem; text-align: center;">Loading grid...</div>';
        
        const pathParts = window.location.pathname.split('/');
        const sessionId = pathParts[pathParts.length - 1].split('?')[0];
        
        try {
            const res = await fetch(`/receiving/${sessionId}/grid_data?template_id=${tid}`);
            if (!res.ok) throw new Error("Failed to load grid data");
            const data = await res.json();
            currentGridData = data.items || [];
            currentGridTemplate = tid;
            
            // Populate Global Adjustments UI
            const panel = document.getElementById('global-adjustments-panel');
            const toggleBtn = document.getElementById('btn-toggle-global-adjustments');
            if (panel) {
                panel.style.display = 'none'; // Keep hidden by default
                
                if (data.global_discounts && data.global_discounts.length > 0) {
                    document.getElementById('global-discounts-input').value = data.global_discounts.join(', ');
                }
                if (data.global_taxes && data.global_taxes.length > 0) {
                    document.getElementById('global-taxes-input').value = data.global_taxes.join(', ');
                }
                
                // Highlight the button if AI found global pricing
                if (toggleBtn) {
                    const hasAdjustments = (data.global_discounts && data.global_discounts.length > 0) || 
                                         (data.global_taxes && data.global_taxes.length > 0);
                    if (hasAdjustments) {
                        toggleBtn.classList.remove('outline');
                        toggleBtn.classList.add('primary');
                        if (!toggleBtn.innerHTML.includes('✨')) {
                            toggleBtn.innerHTML = '% Global Pricing <span title="AI Extracted">✨</span>';
                        }
                    } else {
                        toggleBtn.classList.add('outline');
                        toggleBtn.classList.remove('primary');
                        toggleBtn.innerHTML = '% Global Pricing';
                    }
                }
            }
            currentGridTemplate = tid;
            renderGrid(currentGridData);

            gridSelect.blur();
            const table = document.getElementById('spreadsheet-table');
            if (table) {
                const firstInput = table.querySelector('.grid-row:not([style*="display: none"]) .grid-cell');
                if (firstInput) {
                    firstInput.focus();
                    firstInput.select();
                }
            }
        } catch (err) {
            spreadsheetContainer.innerHTML = `<div style="color: red; padding: 2rem;">Error: ${err.message}</div>`;
        }
    });
    
    // Load saved template on initial load
    setTimeout(() => {
        const savedTemplate = localStorage.getItem('grid_mode_template');
        if (savedTemplate && gridSelect && Array.from(gridSelect.options).some(o => o.value === savedTemplate)) {
            gridSelect.value = savedTemplate;
            gridSelect.dispatchEvent(new Event('change'));
        }
    }, 50);

    function renderGrid(data) {
        if (!data || data.length === 0) {
            spreadsheetContainer.innerHTML = '<div style="padding: 2rem;">No items to display.</div>';
            return;
        }

        const isTopDown = localStorage.getItem('pricing_strategy_mode') === 'top_down';

        const dynamicCols = new Set();
        data.forEach(row => {
            Object.keys(row.dynamic_fields || {}).forEach(k => {
                if (!['mrp', 'selling_price', 'coded_price', 'family_name'].includes(k)) {
                    dynamicCols.add(k);
                }
            });
        });

        const fieldPriority = {
            brand: 1, item_display_name: 2, design: 2, article: 3,
            article_no: 3, size: 4, batch_no: 5, expiry: 6
        };

        const orderedCols = Array.from(dynamicCols).sort((a, b) => {
            return (fieldPriority[a] || 50) - (fieldPriority[b] || 50);
        });

        let html = `<div class="sleek-grid" id="spreadsheet-table" style="display: flex; flex-direction: column; gap: 0.5rem; width: 100%;">
            <div style="display: flex; flex-direction: row; align-items: center; justify-content: flex-end; padding-right: 0.75rem; gap: 0.5rem; font-size: 0.7rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border-color); padding-bottom: 0.5rem; margin-bottom: 0.25rem;">
                <div style="width: 80px;">Cost</div>
                <div style="width: 120px;">Billing Item</div>`;
        
        if (isTopDown) {
            html += `
                <div style="width: 70px;">MRP</div>
                <div style="width: 90px;">C Calc</div>
                <div style="width: 90px;">Code</div>`;
        } else {
            html += `
                <div style="width: 70px;">Marg %</div>
                <div style="width: 90px;">Code</div>
                <div style="width: 70px;">Disc %</div>
                <div style="width: 70px;">MRP</div>`;
        }

        html += `
                ${orderedCols.map(c => `<div style="width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${c}</div>`).join('')}
                <div style="width: 60px;">Qty</div>
                <div style="width: 70px; text-align: center;">Action</div>
            </div>
            <div class="sleek-grid-body" style="display: flex; flex-direction: column; gap: 0.15rem;">
        `;

        data.forEach((row, rowIdx) => {
            const trClass = row.label_status === 'PRINTED' ? 'row-printed' : '';
            
            // Calculate initial margins/discounts for display
            let margin = '';
            let disc = '';
            if (row.landing_price > 0 && row.selling_price > 0) {
                margin = (((row.selling_price - row.landing_price) / row.landing_price) * 100).toFixed(1);
            }
            if (row.selling_price > 0 && row.mrp > 0) {
                disc = (((row.mrp - row.selling_price) / row.mrp) * 100).toFixed(1);
            }

            let codeStr = row.supplier_product_code || (row.selling_price ? window.generateCodedPrice(row.selling_price) : '');
            
            let decodedStr = '';
            let targetLen = window.codeTargetLength || 0;
            if (codeStr) {
                let previewParts = [];
                let deficit = targetLen - codeStr.length;
                if (deficit > 0) {
                    const junk = window.getJunkPadding ? window.getJunkPadding(deficit) : 'XXXXXX'.substring(0, deficit);
                    const front = Math.floor(junk.length / 2);
                    previewParts.push(junk.substring(0, front) + codeStr + junk.substring(front));
                }
                if (row.selling_price) {
                    previewParts.push(`₹${row.selling_price}`);
                } else {
                    const decoded = window.decodePriceCode ? window.decodePriceCode(codeStr) : null;
                    if (decoded !== null) previewParts.push(`₹${Math.round(decoded)}`);
                }
                decodedStr = previewParts.join(' ');
            }
            
            let costVal = '';
            if (row.landing_price !== null && row.landing_price !== undefined) costVal = row.landing_price;
            else if (row.purchase_rate !== null && row.purchase_rate !== undefined) costVal = row.purchase_rate;
            
            html += `<div class="item-row grid-row ${trClass}" data-item-id="${row.id}" data-tally-status="${row.tally_status}" data-pricing-status="${row.pricing_status}" data-label-status="${row.label_status}" data-received-qty="${row.received_qty || 0}" style="display: flex; flex-direction: row; align-items: center; justify-content: space-between; margin: 0; padding: 0.15rem 0.25rem; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 6px;">
                
                <!-- Left Side: Sleek Details -->
                <div class="item-details readonly-cell" style="padding-left: 0.25rem; flex: 1; min-width: 0; display: flex; flex-direction: row; align-items: center; justify-content: flex-start; gap: 0.5rem; overflow: hidden; white-space: nowrap;">
                    <div style="display: flex; align-items: baseline; gap: 0.5rem; overflow: hidden; text-overflow: ellipsis;">
                        ${row.source_row_number ? `<span style="font-size: 0.75rem; color: var(--accent-blue); font-weight: 600; margin-right: 0.25rem;">#${row.source_row_number}</span>` : ''}
                        <span style="font-size: 0.85rem; font-weight: 600; text-overflow: ellipsis; overflow: hidden;" title="${row.raw_description || ''}">${row.raw_description || ''}</span>
                    </div>
                    <div class="badges" style="margin-top: 0; flex-shrink: 0;">
                        <span class="badge qty-badge" style="background: var(--bg-body); border-color: transparent;"><span class="tally-display">${row.received_qty || 0}</span> / ${row.expected_qty || '—'} ${row.unit || 'PCS'}</span>
                        ${row.label_status === 'PRINTED' ? '<span class="badge verified">Printed</span>' : ''}
                    </div>
                </div>

                <!-- Right Side: Excel Inputs -->
                <div class="grid-inputs" style="display: flex; flex-direction: row; align-items: center; flex-shrink: 0; padding-right: 0.25rem; gap: 0.5rem;">
                    
                    <div style="width: 80px;"><input type="number" step="0.01" class="grid-cell pricing-field" data-field="purchase_rate" value="${costVal}" style="width: 100%;"></div>
                    <div style="width: 120px;"><input type="text" class="grid-cell" data-field="billing_item" value="${row.billing_item || ''}" style="width: 100%;"></div>`;

            if (isTopDown) {
                html += `
                    <div style="width: 70px;"><input type="number" step="1" class="grid-cell pricing-field" data-field="mrp" value="${row.mrp !== null ? row.mrp : ''}" style="width: 100%;"></div>
                    <div style="width: 90px;"><input type="text" class="grid-cell calc-field" placeholder="-200 / 50%" style="width: 100%;"></div>
                    <div style="width: 90px; position: relative;">
                        <input type="text" class="grid-cell code-field" data-field="supplier_product_code" value="${codeStr}" style="font-family: monospace; width: 100%; padding-right: 4px;">
                        <span class="grid-code-preview" style="position: absolute; top: 50%; right: 4px; transform: translateY(-50%); font-size: 0.75rem; color: var(--accent-green, #10b981); background: transparent; font-weight: 600; ${decodedStr ? 'display: block;' : 'display: none;'} pointer-events: none; white-space: nowrap;">${decodedStr}</span>
                        <input type="hidden" class="pricing-field" data-field="selling_price" value="${row.selling_price || ''}">
                    </div>`;
            } else {
                html += `
                    <div style="width: 70px;"><input type="number" step="0.1" class="grid-cell margin-field" placeholder="%" value="${margin}" style="width: 100%;"></div>
                    <div style="width: 90px; position: relative;">
                        <input type="text" class="grid-cell code-field" data-field="supplier_product_code" value="${codeStr}" style="font-family: monospace; width: 100%; padding-right: 4px;">
                        <span class="grid-code-preview" style="position: absolute; top: 50%; right: 4px; transform: translateY(-50%); font-size: 0.75rem; color: var(--accent-green, #10b981); background: transparent; font-weight: 600; ${decodedStr ? 'display: block;' : 'display: none;'} pointer-events: none; white-space: nowrap;">${decodedStr}</span>
                        <input type="hidden" class="pricing-field" data-field="selling_price" value="${row.selling_price || ''}">
                    </div>
                    <div style="width: 70px;"><input type="number" step="0.1" class="grid-cell disc-field" placeholder="%" value="${disc}" style="width: 100%;"></div>
                    <div style="width: 70px;"><input type="number" step="1" class="grid-cell pricing-field" data-field="mrp" value="${row.mrp !== null ? row.mrp : ''}" style="width: 100%;"></div>`;
            }

            orderedCols.forEach(col => {
                const f = row.dynamic_fields[col];
                const val = f ? (f.value || '') : '';
                const missingClass = (f && f.missing) ? 'missing-field' : '';
                html += `<div style="width: 80px;"><input type="text" class="grid-cell dynamic-cell ${missingClass}" data-dynamic-field="${col}" value="${val}" style="width: 100%;"></div>`;
            });

            const rawCopies = parseInt(row.received_qty || row.expected_qty || 1, 10);
            const defaultCopies = Math.max(1, isNaN(rawCopies) ? 1 : rawCopies);

            html += `
                    <div style="width: 60px;"><input type="number" class="grid-cell" data-field="copies" value="${defaultCopies}" min="1" max="1000" style="width: 100%; text-align: center;"></div>
                    <div style="width: 70px; text-align: center;">
                        <button class="button primary btn-grid-print" style="margin: 0; width: 100%; padding: 0.2rem 0.25rem; font-size: 0.75rem; border-radius: 4px;" ${row.label_status === 'PRINTED' ? 'disabled' : ''}>
                            ${row.label_status === 'PRINTED' ? 'Printed' : 'Print'}
                        </button>
                    </div>
                </div>
            </div>`;
        });

        html += `</div></div>`;
        spreadsheetContainer.innerHTML = html;
        
        applyGridFilters(); // apply filters after rendering

        setupGridInteractions();
    }

    function setupGridInteractions() {
        const table = document.getElementById('spreadsheet-table');
        if (!table) return;

        const isTopDown = localStorage.getItem('pricing_strategy_mode') === 'top_down';
        let lastPrintFocusTime = 0;

        // PRICING LOGIC
        table.addEventListener('input', (e) => {
            if (!e.target.classList.contains('grid-cell')) return;
            
            if (e.isTrusted && e.target.dataset.autoFilled) {
                delete e.target.dataset.autoFilled;
            }

            const tr = e.target.closest('.grid-row');
            if (!tr) return;

            const rateInput = tr.querySelector('input[data-field="purchase_rate"]');
            const mrpInput = tr.querySelector('input[data-field="mrp"]');
            const sellInput = tr.querySelector('input[data-field="selling_price"]'); // hidden
            const codeInput = tr.querySelector('.code-field');
            
            function refreshPreview() {
                const previewSpan = tr.querySelector('.grid-code-preview');
                if (!previewSpan) return;
                const cleanCode = codeInput.value;
                const decoded = window.decodePriceCode(cleanCode);
                const targetLen = window.codeTargetLength || 0;
                const deficit = targetLen - cleanCode.length;
                let previewParts = [];
                
                if (deficit > 0 && cleanCode.length > 0) {
                    const junk = window.getJunkPadding ? window.getJunkPadding(deficit) : 'XXXXXX'.substring(0, deficit);
                    const front = Math.floor(junk.length / 2);
                    previewParts.push(junk.substring(0, front) + cleanCode + junk.substring(front));
                }
                
                if (decoded !== null) {
                    previewParts.push(`₹${Math.round(decoded)}`);
                }
                
                const finalStr = previewParts.join(' ');
                if (finalStr) {
                    previewSpan.textContent = finalStr;
                    previewSpan.style.display = 'block';
                } else {
                    previewSpan.style.display = 'none';
                }
            }

            if (isTopDown) {
                const calcBox = tr.querySelector('.calc-field');
                
                if (e.target === calcBox || e.target === mrpInput) {
                    const currentMrp = parseFloat(mrpInput.value) || 0;
                    const expr = calcBox ? calcBox.value.trim() : "";
                    if (currentMrp > 0 && expr) {
                        const calcRate = window.computeMrpCalculation(currentMrp, expr);
                        if (calcRate !== null && Number.isFinite(calcRate) && calcRate > 0) {
                            const roundedPrice = Math.max(1, Math.round(calcRate));
                            sellInput.value = roundedPrice;
                            const encoded = window.generateCodedPrice(roundedPrice);
                            codeInput.value = encoded || String(roundedPrice);
                            refreshPreview();
                        }
                    } else if (currentMrp <= 0) {
                        sellInput.value = '';
                        codeInput.value = '';
                        refreshPreview();
                    }
                } else if (e.target === codeInput) {
                    codeInput.value = codeInput.value.toUpperCase();
                    refreshPreview();
                    
                    const decoded = window.decodePriceCode(codeInput.value);
                    if (decoded !== null) {
                        sellInput.value = Math.round(decoded);
                    }
                }
            } else {
                const marginInput = tr.querySelector('.margin-field');
                const discInput = tr.querySelector('.disc-field');

                const rate = parseFloat(rateInput.value);
                const mrp = parseFloat(mrpInput.value);
                const sell = parseFloat(sellInput.value);
                const margin = parseFloat(marginInput.value);
                const disc = parseFloat(discInput.value);

                if (e.target === marginInput && !isNaN(margin) && !isNaN(rate)) {
                    const calcSell = rate * (1 + margin / 100);
                    sellInput.value = Math.round(calcSell);
                    codeInput.value = window.generateCodedPrice(calcSell) || String(Math.round(calcSell));
                    refreshPreview();
                    
                    // Cascade to MRP
                    if (!isNaN(disc) && disc < 100 && mrpInput) {
                        mrpInput.value = Math.round(calcSell / (1 - disc / 100));
                    }
                } else if (e.target === discInput && !isNaN(disc) && disc < 100 && !isNaN(sell)) {
                    if (mrpInput) mrpInput.value = Math.round(sell / (1 - disc / 100));
                } else if (e.target === codeInput) {
                    codeInput.value = codeInput.value.toUpperCase();
                    refreshPreview();
                    
                    const decoded = window.decodePriceCode(codeInput.value);
                    if (decoded !== null) {
                        sellInput.value = Math.round(decoded);
                        // Cascade back to margin/disc
                        if (!isNaN(rate) && rate > 0) marginInput.value = (((decoded - rate) / rate) * 100).toFixed(1);
                        if (!isNaN(mrp) && mrp > 0) discInput.value = (((mrp - decoded) / mrp) * 100).toFixed(1);
                    }
                } else if (e.target === rateInput && !isNaN(rate) && rate > 0 && !isNaN(sell)) {
                    marginInput.value = (((sell - rate) / rate) * 100).toFixed(1);
                } else if (e.target === mrpInput && !isNaN(mrp) && mrp > 0 && !isNaN(sell)) {
                    discInput.value = (((mrp - sell) / mrp) * 100).toFixed(1);
                }
            }
        });

        // AUTO SAVE ON BLUR (Change)
        table.addEventListener('change', async (e) => {
            if (e.target.classList.contains('grid-cell')) {
                // Formatting on blur for Code
                if (e.target.classList.contains('code-field')) {
                    const previewSpan = e.target.parentElement.querySelector('.grid-code-preview');
                    if (previewSpan) previewSpan.style.display = 'none';
                    
                    const targetLen = window.codeTargetLength || 0;
                    const cleanCode = e.target.value;
                    const deficit = targetLen - cleanCode.length;
                    if (deficit > 0) {
                        const junk = window.getJunkPadding(deficit);
                        const front = Math.floor(junk.length / 2);
                        e.target.value = junk.substring(0, front) + cleanCode + junk.substring(front);
                    }
                }
                await saveCell(e.target);
                
                // Sticky Fill-Down Logic
                const isPricingField = e.target.classList.contains('margin-field') || 
                                       e.target.classList.contains('disc-field') || 
                                       e.target.classList.contains('calc-field');
                
                if (isPricingField && e.target.value) {
                    const currentTr = e.target.closest('.grid-row');
                    const allRows = Array.from(table.querySelectorAll('.grid-row'));
                    const currentIndex = allRows.indexOf(currentTr);
                    
                    const val = e.target.value;
                    let fieldSelector = '';
                    if (e.target.dataset.field) {
                        fieldSelector = `[data-field="${e.target.dataset.field}"]`;
                    } else {
                        const specificClass = Array.from(e.target.classList).find(c => c.endsWith('-field'));
                        if (specificClass) fieldSelector = `.${specificClass}`;
                    }
                    
                    if (fieldSelector) {
                        for (let i = currentIndex + 1; i < allRows.length; i++) {
                            const nextRow = allRows[i];
                            if (nextRow.dataset.pricingStatus === 'PENDING') {
                                const targetInput = nextRow.querySelector(fieldSelector);
                                if (targetInput && (!targetInput.value || targetInput.dataset.autoFilled === 'true')) { 
                                    targetInput.value = val;
                                    targetInput.dataset.autoFilled = 'true';
                                    targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                                } else if (targetInput && targetInput.value) {
                                    // Stop cascading if we hit a row the user explicitly priced
                                    break;
                                }
                            }
                        }
                    }
                }
            }
        });

        // NAVIGATION
        table.addEventListener('keydown', (e) => {
            if (!e.target.classList.contains('grid-cell') && !e.target.classList.contains('btn-grid-print')) return;

            if ((e.key === 'Enter' || e.key === 'Tab') && (Date.now() - lastPrintFocusTime < 350)) {
                e.preventDefault();
                return;
            }

            const tr = e.target.closest('.grid-row');
            if (!tr) return;

            // Only navigate through currently visible rows!
            const rows = Array.from(table.querySelectorAll('.grid-row')).filter(r => r.style.display !== 'none');
            const rowIdx = rows.indexOf(tr);
            if (rowIdx === -1) return;

            const focusable = Array.from(tr.querySelectorAll('.grid-cell, .btn-grid-print'));
            const currentIdx = focusable.indexOf(e.target);

            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const printBtn = tr.querySelector('.btn-grid-print');
                if (printBtn && !printBtn.disabled) {
                    printBtn.click();
                }
                return;
            }

            if (e.key === 'Tab' && e.shiftKey) {
                e.preventDefault();
                let prev = focusable[currentIdx - 1];
                if (!prev) {
                    const prevRow = rows[rowIdx - 1];
                    if (prevRow) {
                        const prevFocusable = Array.from(prevRow.querySelectorAll('.grid-cell, .btn-grid-print'));
                        prev = prevFocusable[prevFocusable.length - 1];
                    }
                }
                if (prev) {
                    prev.focus();
                    if (prev.select) prev.select();
                }
                return;
            }

            if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                
                if (e.target.classList.contains('btn-grid-print')) {
                    if (e.key === 'Enter') {
                        e.target.click();
                    } else if (e.key === 'Tab') {
                        const nextRow = rows[rowIdx + 1];
                        if (nextRow) {
                            const nextCell = nextRow.querySelector('.grid-cell');
                            if (nextCell) {
                                nextCell.focus();
                                if (nextCell.select) nextCell.select();
                            }
                        }
                    }
                    return;
                }

                let next = focusable[currentIdx + 1];
                if (!next) {
                    const nextRow = rows[rowIdx + 1];
                    if (nextRow) {
                        next = nextRow.querySelector('.grid-cell');
                    }
                }
                
                if (next) {
                    next.focus();
                    if (next.select) next.select();
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prevRow = rows[rowIdx - 1];
                if (prevRow) {
                    const nextTarget = Array.from(prevRow.querySelectorAll('.grid-cell, .btn-grid-print'))[currentIdx];
                    if (nextTarget) {
                        nextTarget.focus();
                        if (nextTarget.select) nextTarget.select();
                    }
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                const nextRow = rows[rowIdx + 1];
                if (nextRow) {
                    const nextTarget = Array.from(nextRow.querySelectorAll('.grid-cell, .btn-grid-print'))[currentIdx];
                    if (nextTarget) {
                        nextTarget.focus();
                        if (nextTarget.select) nextTarget.select();
                    }
                }
            } else if (e.key === '+' || e.key === '-' || e.key === '=') {
                e.preventDefault();
                
                const currentQty = parseInt(tr.getAttribute('data-received-qty')) || 0;
                let newQty = currentQty;
                
                if (e.key === '+' || e.key === '=') {
                    newQty = currentQty + 1;
                } else if (e.key === '-') {
                    if (currentQty > 0) newQty = currentQty - 1;
                }
                
                if (newQty !== currentQty) {
                    tr.setAttribute('data-received-qty', newQty);
                    
                    const tallyDisplay = tr.querySelector('.tally-display');
                    if (tallyDisplay) {
                        tallyDisplay.textContent = newQty;
                    }

                    if (typeof window.showToast === 'function') {
                        window.showToast(`Tally: ${newQty}`, 'success');
                    }
                    
                    const itemId = tr.getAttribute('data-item-id');
                    const isDraftSession = (window.SESSION_STATUS === 'DRAFT');
                    const url = isDraftSession ? `/receiving/items/${itemId}/draft` : `/receiving/items/${itemId}/tally`;
                    const method = isDraftSession ? 'PUT' : 'POST';
                    const body = isDraftSession ? JSON.stringify({ received_qty: newQty }) : JSON.stringify({ received_qty: newQty.toString() });

                    fetch(url, {
                        method: method,
                        headers: { 'Content-Type': 'application/json' },
                        body: body
                    }).then(res => {
                        if(res.ok) return res.json();
                        throw new Error('Failed to save tally');
                    }).then(data => {
                        tr.setAttribute('data-tally-status', data.tally_status);
                        if (typeof window.updateRowDOM === 'function') {
                            window.updateRowDOM(itemId, data);
                        }
                    }).catch(err => {
                        if (typeof window.showToast === 'function') window.showToast(err.message, 'error');
                        tr.setAttribute('data-received-qty', currentQty);
                    });
                }
            } else if (e.key === 'ArrowLeft') {
                let atStart = false;
                try {
                    atStart = (e.target.type === 'number') ? true : (e.target.selectionStart === 0 && e.target.selectionEnd === 0);
                } catch (err) { atStart = true; }
                
                if (atStart) {
                    e.preventDefault();
                    let prev = focusable[currentIdx - 1];
                    if (!prev) {
                        const prevRow = rows[rowIdx - 1];
                        if (prevRow) {
                            const prevFocusable = Array.from(prevRow.querySelectorAll('.grid-cell, .btn-grid-print'));
                            prev = prevFocusable[prevFocusable.length - 1];
                        }
                    }
                    if (prev) {
                        prev.focus();
                        if (prev.select) prev.select();
                    }
                }
            } else if (e.key === 'ArrowRight') {
                let atEnd = false;
                try {
                    atEnd = (e.target.type === 'number') ? true : (e.target.selectionStart === e.target.value.length && e.target.selectionEnd === e.target.value.length);
                } catch (err) { atEnd = true; }
                
                if (atEnd) {
                    e.preventDefault();
                    let next = focusable[currentIdx + 1];
                    if (!next) {
                        const nextRow = rows[rowIdx + 1];
                        if (nextRow) {
                            next = nextRow.querySelector('.grid-cell');
                        }
                    }
                    if (next) {
                        next.focus();
                        if (next.select) next.select();
                    }
                }
            }
        });
        
        // PRINTING
        table.addEventListener('click', async (e) => {
            if (e.target.classList.contains('btn-grid-print')) {
                const btn = e.target;
                if (btn.disabled) return;
                
                const tr = btn.closest('.grid-row');
                
                const mrpInput = tr.querySelector('input[data-field="mrp"]');
                const sellInput = tr.querySelector('input[data-field="selling_price"]');
                
                let mrp = 0;
                let sell = 0;
                
                if (mrpInput && sellInput) {
                    mrp = parseFloat(mrpInput.value) || 0;
                    sell = parseFloat(sellInput.value) || 0;
                    
                    if (mrpInput && mrp <= 0) {
                        if (typeof window.showToast === 'function') window.showToast('MRP is required', 'error');
                        tr.classList.add('error');
                        mrpInput.focus();
                        mrpInput.select();
                        return;
                    }

                    // If sell is not yet computed but MRP & C CALC exist, calculate now
                    if (sell <= 0 && mrp > 0) {
                        const calcBox = tr.querySelector('.calc-field');
                        const expr = calcBox ? calcBox.value.trim() : "";
                        if (expr) {
                            const calcRate = window.computeMrpCalculation(mrp, expr);
                            if (calcRate !== null && Number.isFinite(calcRate) && calcRate > 0) {
                                sell = Math.max(1, Math.round(calcRate));
                                sellInput.value = sell;
                                const encoded = window.generateCodedPrice(sell);
                                const codeInput = tr.querySelector('.code-field');
                                if (codeInput) codeInput.value = encoded || String(sell);
                            }
                        }
                    }
                    
                    if (sell <= 0) {
                        if (typeof window.showToast === 'function') window.showToast('Selling Price is required', 'error');
                        tr.classList.add('error');
                        if (sellInput.type === 'hidden') {
                            const calcBox = tr.querySelector('.calc-field');
                            if (calcBox && !calcBox.value.trim()) {
                                calcBox.focus();
                            } else if (mrp <= 0) {
                                mrpInput.focus();
                            } else if (calcBox) {
                                calcBox.focus();
                            }
                        } else {
                            sellInput.focus();
                        }
                        return;
                    }
                    
                    if (sell > mrp && mrp > 0) {
                        if (typeof window.showToast === 'function') window.showToast('Selling Price cannot exceed MRP', 'error');
                        tr.classList.add('error');
                        if (sellInput.type === 'hidden') {
                            const calcBox = tr.querySelector('.calc-field');
                            if (calcBox) calcBox.focus();
                        } else {
                            sellInput.focus();
                        }
                        return;
                    }
                    if (sell < (mrp * 0.5) && mrp > 0) {
                        if (!window.confirm(`WARNING: Selling price (₹${sell}) is suspiciously low (less than 50% of MRP ₹${mrp}).\n\nPress OK/Enter to proceed with printing, or Cancel/Escape to abort.`)) {
                            if (sellInput.type === 'hidden') {
                                const calcBox = tr.querySelector('.calc-field');
                                if (calcBox) calcBox.focus();
                            } else {
                                sellInput.focus();
                            }
                            return;
                        }
                    }
                }
                
                const itemId = tr.getAttribute('data-item-id');
                const copiesInput = tr.querySelector('input[data-field="copies"]');
                let copies = parseInt(copiesInput.value);
                if (isNaN(copies) || copies < 1) {
                    copies = 1;
                    copiesInput.value = 1;
                }
                
                if (copies > 1000) {
                    if (typeof window.showToast === 'function') window.showToast("Maximum print quantity is 1000.", "error");
                    tr.classList.add('error');
                    copiesInput.focus();
                    return;
                }
                
                if (copies > 24) {
                    const itemName = tr.querySelector('.cell-product')?.textContent?.trim() || '';
                    const confirmed = await window.confirmLargeQuantityPrint(copies, itemName);
                    if (!confirmed) {
                        copiesInput.focus();
                        return;
                    }
                }
                
                const codeInput = tr.querySelector('.code-field');
                const cleanCode = codeInput ? String(codeInput.value || "").trim() : "";
                
                if (!cleanCode) {
                    if (typeof window.showToast === 'function') window.showToast("Price code is required.", "error");
                    tr.classList.add('error');
                    if (codeInput) codeInput.focus();
                    return;
                }
                
                if (/^\d+$/.test(cleanCode)) {
                    if (typeof window.showToast === 'function') window.showToast("Code cannot be only numbers. Use coded letters too.", "error");
                    tr.classList.add('error');
                    if (codeInput) codeInput.focus();
                    return;
                }

                const missingDynamicCell = tr.querySelector('.dynamic-cell.missing-field');
                if (missingDynamicCell && !missingDynamicCell.value.trim()) {
                    const fieldName = missingDynamicCell.getAttribute('data-dynamic-field') || 'Required field';
                    if (typeof window.showToast === 'function') {
                        window.showToast(`"${fieldName}" is required for this template.`, "error");
                    }
                    tr.classList.add('error');
                    missingDynamicCell.focus();
                    missingDynamicCell.select();
                    return;
                }
                
                btn.disabled = true;
                const origText = btn.textContent;
                btn.textContent = '...';
                
                try {
                    if (document.activeElement && tr.contains(document.activeElement)) {
                        document.activeElement.blur();
                    }

                    if (window.gridPendingSaves && window.gridPendingSaves.has(itemId)) {
                        btn.textContent = 'Sync...';
                        await window.gridPendingSaves.get(itemId);
                        btn.textContent = '...';
                    }
                    
                    const tid = document.getElementById('grid-template-select')?.value;

                    const priceRes = await fetch(`/receiving/items/${itemId}/price`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                          landing_price: tr.querySelector('input[data-field="purchase_rate"]')?.value ? parseFloat(tr.querySelector('input[data-field="purchase_rate"]').value) : null,
                          mrp: mrp > 0 ? mrp : null,
                          selling_price: sell,
                          template_id: tid ? parseInt(tid, 10) : null
                        })
                    });
                    
                    if (!priceRes.ok) {
                        const err = await priceRes.json();
                        throw new Error(err.detail || "Pricing confirmation failed");
                    }
                    
                    const res = await fetch(`/receiving/items/${itemId}/print`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                            copies: copies,
                            template_id: tid ? parseInt(tid, 10) : null 
                        })
                    });
                    
                    if (!res.ok) {
                        const err = await res.json();
                        throw new Error(err.detail || "Print failed");
                    }
                    const printedItem = await res.json();
                    
                    if (printedItem.label_status === 'MISSING_TEMPLATE') {
                        throw new Error("Missing template. Please select a template before printing.");
                    } else if (printedItem.label_status === 'FAILED') {
                        throw new Error("Print failed. Check BarTender connection.");
                    }
                    
                    const statusText = printedItem.label_status === 'QUEUED' ? 'Queued' : 'Printed';
                    
                    if (typeof window.showToast === 'function') window.showToast(statusText, 'success');
                    btn.textContent = statusText;
                    tr.classList.remove('error');
                    tr.classList.add('row-printed');
                    tr.setAttribute('data-label-status', printedItem.label_status);
                    
                    const listModeRow = document.getElementById('item-row-' + itemId);
                    if (listModeRow) {
                        listModeRow.setAttribute('data-label-status', printedItem.label_status);
                    }
                    
                    if (typeof window.renderItems === 'function') {
                        window.renderItems();
                    }
                    
                    const rows = Array.from(table.querySelectorAll('.grid-row')).filter(r => r.style.display !== 'none');
                    const rowIdx = rows.indexOf(tr);
                    let nextRow = null;
                    if (rowIdx !== -1) {
                        nextRow = rows[rowIdx + 1];
                    } else if (rows.length > 0) {
                        // tr was filtered out (e.g. in Pending filter), so the row that slid up into position is rows[0]
                        nextRow = rows[0];
                    }
                    if (nextRow) {
                        const billingInput = nextRow.querySelector('input[data-field="billing_item"]');
                        if (billingInput) {
                            lastPrintFocusTime = Date.now();
                            billingInput.focus();
                            billingInput.select();
                        }
                    }
                } catch (err) {
                    if (typeof window.showToast === 'function') window.showToast(err.message, 'error');
                    btn.disabled = false;
                    btn.textContent = origText;
                    tr.classList.add('error');
                    
                    if (err.message.toLowerCase().includes('mrp')) {
                        if (mrpInput) mrpInput.focus();
                    } else if (err.message.toLowerCase().includes('code')) {
                        const codeInput = tr.querySelector('.code-field');
                        if (codeInput) codeInput.focus();
                    }
                }
            }
        });

        // COLUMN RESIZING
        const resizers = table.querySelectorAll('.col-resizer');
        let x, w, currentCol;

        const mouseDownHandler = function(e) {
            currentCol = e.target.parentElement;
            x = e.clientX;
            const styles = window.getComputedStyle(currentCol);
            w = parseInt(styles.width, 10);
            
            document.addEventListener('mousemove', mouseMoveHandler);
            document.addEventListener('mouseup', mouseUpHandler);
            currentCol.classList.add('resizing');
        };

        const mouseMoveHandler = function(e) {
            const dx = e.clientX - x;
            currentCol.style.width = `${w + dx}px`;
            currentCol.style.minWidth = `${w + dx}px`;
            currentCol.style.maxWidth = `${w + dx}px`;
        };

        const mouseUpHandler = function() {
            document.removeEventListener('mousemove', mouseMoveHandler);
            document.removeEventListener('mouseup', mouseUpHandler);
            currentCol.classList.remove('resizing');
        };

        resizers.forEach(resizer => {
            resizer.addEventListener('mousedown', mouseDownHandler);
        });

    }

    async function saveCell(input) {
        if (input.classList.contains('calc-field') || input.classList.contains('margin-field') || input.classList.contains('disc-field')) {
            // Derived fields don't save themselves, they just wait for the core fields to save.
        }

        input.classList.add('saving');
        input.classList.remove('error');

        const tr = input.closest('.grid-row');
        const itemId = tr.getAttribute('data-item-id');

        const dynamicFields = {};
        tr.querySelectorAll('.dynamic-cell').forEach(inp => {
            dynamicFields[inp.getAttribute('data-dynamic-field')] = inp.value;
        });

        const billingItem = tr.querySelector('input[data-field="billing_item"]')?.value || null;
        
        let purchaseRate = parseFloat(tr.querySelector('input[data-field="purchase_rate"]')?.value);
        purchaseRate = isNaN(purchaseRate) ? null : purchaseRate;
        
        let mrp = parseFloat(tr.querySelector('input[data-field="mrp"]')?.value);
        mrp = isNaN(mrp) ? null : mrp;
        
        let sellingPrice = parseFloat(tr.querySelector('input[data-field="selling_price"]')?.value);
        sellingPrice = isNaN(sellingPrice) ? null : sellingPrice;
        
        const codedPrice = tr.querySelector('.code-field')?.value || null;
        if (codedPrice && codedPrice.trim()) {
            dynamicFields['coded_price'] = codedPrice.trim().toUpperCase();
        }
        const copies = parseInt(tr.querySelector('input[data-field="copies"]')?.value) || 1;
        const tid = document.getElementById('grid-template-select')?.value;

        const payload = {
            template_id: tid ? parseInt(tid, 10) : null,
            manual_overrides: Object.keys(dynamicFields).length > 0 ? JSON.stringify(dynamicFields) : null,
            billing_item: billingItem,
            purchase_rate: purchaseRate,
            mrp: mrp,
            selling_price: sellingPrice,
            supplier_product_code: codedPrice,
            landing_price: purchaseRate // Note: usually updated via global discounts, but keeping sync
        };

        window.gridPendingSaves = window.gridPendingSaves || new Map();
        
        const savePromise = fetch(`/receiving/items/${itemId}/draft`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(async res => {
            if (!res.ok) throw new Error();
            input.classList.remove('saving');
            const data = await res.json();
            
            if (data.tally_status) tr.setAttribute('data-tally-status', data.tally_status);
            if (data.pricing_status) tr.setAttribute('data-pricing-status', data.pricing_status);

            tr.querySelectorAll('.dynamic-cell').forEach(inp => {
                const fName = inp.getAttribute('data-dynamic-field');
                if (data.dynamic_fields && data.dynamic_fields[fName] && data.dynamic_fields[fName].missing) {
                    inp.classList.add('missing-field');
                } else {
                    inp.classList.remove('missing-field');
                }
            });
        }).catch(err => {
            input.classList.remove('saving');
            input.classList.add('error');
            if (typeof window.showToast === 'function') window.showToast('Save failed', 'error');
        });
        
        window.gridPendingSaves.set(itemId, savePromise);
        try {
            await savePromise;
        } finally {
            if (window.gridPendingSaves.get(itemId) === savePromise) {
                window.gridPendingSaves.delete(itemId);
            }
        }
    }
});
// ==========================================
// Global Pricing Adjustments Logic
// ==========================================
window.applyGlobalAdjustments = async function() {
    const btn = document.querySelector('#global-adjustments-panel button');
    if (btn) {
        btn.disabled = true;
        btn.innerText = "Applying...";
    }
    
    try {
        const discountsInput = document.getElementById('global-discounts-input').value;
        const taxesInput = document.getElementById('global-taxes-input').value;
        
        // Parse commas separated strings to arrays of floats
        const parseList = (str) => str.split(',').map(s => parseFloat(s.trim())).filter(n => !isNaN(n));
        
        const discounts = parseList(discountsInput);
        const taxes = parseList(taxesInput);
        
        if (discounts.length === 0 && taxes.length === 0) {
            alert("Please enter at least one global discount or tax percentage.");
            return;
        }
        
        let updatedCount = 0;
        
        const rows = document.querySelectorAll('.grid-row');
        for (const tr of Array.from(rows)) {
            const itemId = parseInt(tr.getAttribute('data-item-id'));
            if (isNaN(itemId)) continue;
            
            const mrpInput = tr.querySelector('input[data-field="mrp"]');
            const rateInput = tr.querySelector('input[data-field="purchase_rate"]');
            const discInput = tr.querySelector('.disc-field');
            
            if (!mrpInput || !rateInput) continue;
            
            const mrp = parseFloat(mrpInput.value) || 0;
            if (mrp <= 0) continue;
            
            let currentPrice = mrp;
            
            // Line level discount (if exists)
            const lineDisc = discInput ? (parseFloat(discInput.value) || 0) : 0;
            if (lineDisc > 0) {
                currentPrice = currentPrice * (1 - (lineDisc / 100));
            }
            
            // Global discounts sequentially
            discounts.forEach(d => {
                currentPrice = currentPrice * (1 - (d / 100));
            });
            
            const purchaseRate = currentPrice;
            
            // Global taxes
            let taxMultiplier = 1;
            taxes.forEach(t => {
                taxMultiplier += (t / 100);
            });
            
            const landingPrice = purchaseRate * taxMultiplier;
            
            // Update DOM visually
            rateInput.value = landingPrice.toFixed(2);
            
            const marginInput = tr.querySelector('.margin-field');
            const sellInput = tr.querySelector('input[data-field="selling_price"]');
            const sell = parseFloat(sellInput?.value);
            if (marginInput && !isNaN(sell) && sell > 0 && landingPrice > 0) {
                marginInput.value = (((sell - landingPrice) / landingPrice) * 100).toFixed(1);
            }
            
            // Update backing data array
            if (typeof currentGridData !== 'undefined') {
                const rowData = currentGridData.find(r => r.id === itemId);
                if (rowData) {
                    rowData.mrp = mrp;
                    rowData.purchase_rate = purchaseRate.toFixed(2);
                    rowData.landing_price = landingPrice.toFixed(2);
                }
            }
            
            updatedCount++;
            
            const tid = document.getElementById('grid-template-select')?.value;
            // Auto-save sequentially to avoid DB locks
            const payload = {
                template_id: tid ? parseInt(tid, 10) : null,
                mrp: mrp,
                purchase_rate: purchaseRate,
                landing_price: landingPrice
            };
            
            try {
                const res = await fetch(`/receiving/items/${itemId}/draft`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) throw new Error("Status " + res.status);
            } catch (err) {
                console.error("Failed to save global adjustment for row", itemId, err);
            }
        }
        
        if (updatedCount > 0) {
            alert(`Successfully recalculated prices for ${updatedCount} rows!`);
        } else {
            alert('No rows with MRP found to apply discounts to.');
        }
    } catch (err) {
        console.error(err);
        alert("An error occurred while applying global adjustments.");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = "Apply to All Rows";
        }
    }
};
