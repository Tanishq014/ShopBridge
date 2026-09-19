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
    
    // Global Search & Active Row Handlers for Grid Mode (Initialized Once)
    let gridHighlightedIndex = -1;
    let lastActiveRowIndex = null;
    let lastFocusedColIndex = null;
    let autoAdvanceTimer = null;
    
    function updateActiveGridRow(tr, cell = null) {
        if (!tr) return;
        const table = document.getElementById('spreadsheet-table');
        if (!table) return;

        const allRows = table.querySelectorAll('.grid-row');
        allRows.forEach(r => {
            if (r !== tr) r.classList.remove('search-highlighted');
        });
        tr.classList.add('search-highlighted');

        const visibleRows = Array.from(allRows).filter(r => r.style.display !== 'none');
        const idx = visibleRows.indexOf(tr);
        if (idx !== -1) {
            gridHighlightedIndex = idx;
        }
    }
    window.updateActiveGridRow = updateActiveGridRow;

    function updateGridSearchHighlight(visibleRows, table) {
        if (!table) return;
        const allRows = table.querySelectorAll('.grid-row');
        allRows.forEach(r => r.classList.remove('search-highlighted'));
        
        if (gridHighlightedIndex >= 0 && gridHighlightedIndex < visibleRows.length) {
            const target = visibleRows[gridHighlightedIndex];
            target.classList.add('search-highlighted');
            target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    document.addEventListener('grid-search', (e) => {
        applyGridFilters();
    });

    const savedGridFilter = localStorage.getItem('receiving_active_filter');
    const activeTab = document.querySelector('.filter-tab.active');
    let currentGridFilter = (savedGridFilter && ['PENDING', 'NEEDS_PRICING', 'PRINT_ISSUES', 'ALL'].includes(savedGridFilter))
        ? savedGridFilter
        : (activeTab ? (activeTab.getAttribute('data-filter') || 'PENDING') : 'PENDING');
    
    document.addEventListener('grid-tab-filter', (e) => {
        const newFilter = (typeof e.detail === 'object' && e.detail !== null) ? e.detail.filter : (e.detail || 'PENDING');
        const filterChanged = (typeof e.detail === 'object' && e.detail !== null) ? !!e.detail.filterChanged : (newFilter !== currentGridFilter);
        currentGridFilter = newFilter;
        applyGridFilters(filterChanged);
    });

    function applyGridFilters(filterChanged = false) {
        const table = document.getElementById('spreadsheet-table');
        if (!table) return;

        const term = (searchInput ? searchInput.value.toLowerCase().trim() : '');
        const rows = table.querySelectorAll('.grid-row');
        const visibleRows = [];

        // Track active element before visibility changes
        const activeEl = document.activeElement;
        const activeRow = (activeEl && activeEl.closest) ? activeEl.closest('.grid-row') : null;

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

        if (filterChanged && visibleRows.length > 0) {
            // When filter changes, make top line active from billing item!
            gridHighlightedIndex = 0;
            const topRow = visibleRows[0];
            updateActiveGridRow(topRow);
            const billingInput = topRow.querySelector('input[data-field="billing_item"]') || topRow.querySelector('.code-field') || topRow.querySelector('.grid-cell');
            if (billingInput) {
                setTimeout(() => {
                    billingInput.focus();
                    if (typeof billingInput.select === 'function') billingInput.select();
                }, 30);
            }
            topRow.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        } else if (activeRow && visibleRows.includes(activeRow)) {
            // Active row is still visible, keep it highlighted and active!
            gridHighlightedIndex = visibleRows.indexOf(activeRow);
            updateActiveGridRow(activeRow, activeEl);
        } else if (activeRow && !visibleRows.includes(activeRow)) {
            // The active row was just hidden (e.g. verified on PENDING tab)!
            if (visibleRows.length > 0) {
                const targetIdx = (lastActiveRowIndex !== null && lastActiveRowIndex < visibleRows.length)
                    ? lastActiveRowIndex
                    : (visibleRows.length - 1);
                const targetRow = visibleRows[targetIdx];
                gridHighlightedIndex = targetIdx;
                updateActiveGridRow(targetRow);
                
                const focusableInTarget = Array.from(targetRow.querySelectorAll('.grid-cell, .btn-grid-print'));
                const targetCell = (lastFocusedColIndex !== null && focusableInTarget[lastFocusedColIndex])
                    ? focusableInTarget[lastFocusedColIndex]
                    : (targetRow.querySelector('.code-field') || targetRow.querySelector('.grid-cell'));
                if (targetCell) {
                    setTimeout(() => {
                        targetCell.focus();
                        if (typeof targetCell.select === 'function') targetCell.select();
                    }, 20);
                }
            } else {
                gridHighlightedIndex = -1;
                updateGridSearchHighlight(visibleRows, table);
            }
        } else if (term) {
            gridHighlightedIndex = visibleRows.length > 0 ? 0 : -1;
            updateGridSearchHighlight(visibleRows, table);
        } else if (visibleRows.length > 0) {
            if (gridHighlightedIndex < 0 || gridHighlightedIndex >= visibleRows.length) {
                gridHighlightedIndex = 0;
            }
            updateActiveGridRow(visibleRows[gridHighlightedIndex]);
        } else {
            gridHighlightedIndex = -1;
            updateGridSearchHighlight(visibleRows, table);
        }
    }

    const searchInput = document.getElementById('receiving-search');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            applyGridFilters(false);
        });

        document.addEventListener('grid-search', () => {
            applyGridFilters(false);
        });

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
            window.codeTargetLength = 0;
            spreadsheetContainer.style.display = 'none';
            itemList.style.display = 'flex';
            workspaceFilters.style.display = 'flex';
            document.querySelector('.grid-mode-toggle').style.background = 'transparent';
            return;
        }
        localStorage.setItem('grid_mode_template', tid);
        const selTmpl = (window.templatesData || []).find(t => String(t.id) === String(tid));
        window.codeTargetLength = selTmpl ? (selTmpl.code_target_length || 0) : 0;
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
            if (data.code_target_length !== undefined) {
                window.codeTargetLength = data.code_target_length || 0;
            }
            
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

    function renderTallyStatusBadge(receivedQty, expectedQty, tallyStatus) {
        const rec = (receivedQty !== null && receivedQty !== undefined && !isNaN(Number(receivedQty))) ? Number(receivedQty) : 0;
        const exp = (expectedQty !== null && expectedQty !== undefined && !isNaN(Number(expectedQty))) ? Number(expectedQty) : null;
        
        // Check if verified / done
        if (tallyStatus === 'VERIFIED' || (exp !== null && rec === exp && rec > 0)) {
            return `<span class="badge verified tally-status-badge" style="background: rgba(52,199,89,0.15); color: #15803d; font-weight: 700;">✓ Rec: ${rec} (Done)</span>`;
        }
        
        // If received exceeds expected
        if (exp !== null && rec > exp) {
            const extra = Number.isInteger(rec - exp) ? (rec - exp) : parseFloat((rec - exp).toFixed(3));
            return `<span class="badge mismatch tally-status-badge" style="background: rgba(255,59,48,0.15); color: var(--accent-red, #ff3b30); font-weight: 700;">Rec: ${rec} (Extra ${extra})</span>`;
        }
        
        // If partially received / mismatch short
        if (exp !== null && rec > 0 && rec < exp) {
            const shortQty = Number.isInteger(exp - rec) ? (exp - rec) : parseFloat((exp - rec).toFixed(3));
            return `<span class="badge mismatch short tally-status-badge" style="background: rgba(255,149,0,0.15); color: #c2410c; font-weight: 700;">Rec: ${rec} (Short ${shortQty})</span>`;
        }
        
        // If received is 0 or unverified / untouched
        if (rec === 0) {
            const pendingText = exp !== null ? `Pending ${exp}` : 'Pending';
            return `<span class="badge pending tally-status-badge" style="background: rgba(142,142,147,0.15); color: #636366; font-weight: 600;">${pendingText}</span>`;
        }
        
        // Fallback if no expected qty known but received > 0
        return `<span class="badge verified tally-status-badge" style="background: rgba(52,199,89,0.15); color: #15803d; font-weight: 700;">Rec: ${rec}</span>`;
    }
    window.renderTallyStatusBadge = renderTallyStatusBadge;

    function updateGridRowTallyBadge(gridRow, receivedQty, expectedQty, tallyStatus) {
        if (!gridRow) return;
        const rec = (receivedQty !== null && receivedQty !== undefined && !isNaN(Number(receivedQty))) ? Number(receivedQty) : 0;
        let exp = (expectedQty !== null && expectedQty !== undefined && !isNaN(Number(expectedQty))) ? Number(expectedQty) : null;
        if (exp === null) {
            const expAttr = gridRow.getAttribute('data-expected-qty');
            if (expAttr !== null && expAttr !== '' && !isNaN(Number(expAttr))) {
                exp = Number(expAttr);
            }
        }
        
        // Compute effective tally status if not explicitly provided
        let status = tallyStatus;
        if (!status) {
            if (exp !== null && rec === exp && rec > 0) status = 'VERIFIED';
            else if (rec > 0) status = 'MISMATCH';
            else status = 'UNVERIFIED';
        }
        
        gridRow.setAttribute('data-received-qty', rec);
        gridRow.setAttribute('data-tally-status', status);
        
        const tallyDisplay = gridRow.querySelector('.tally-display');
        if (tallyDisplay) {
            tallyDisplay.textContent = rec;
        }
        
        let statusContainer = gridRow.querySelector('.tally-status-container');
        if (!statusContainer) {
            const badges = gridRow.querySelector('.badges');
            if (badges) {
                statusContainer = document.createElement('span');
                statusContainer.className = 'tally-status-container';
                badges.appendChild(statusContainer);
            }
        }
        
        if (statusContainer) {
            statusContainer.innerHTML = renderTallyStatusBadge(rec, exp, status);
        }
    }
    window.updateGridRowTallyBadge = updateGridRowTallyBadge;

    function renderGrid(data) {
        if (!data || data.length === 0) {
            spreadsheetContainer.innerHTML = '<div style="padding: 2rem;">No items to display.</div>';
            return;
        }

        const isTopDown = localStorage.getItem('pricing_strategy_mode') === 'top_down';

        const dynamicCols = new Set();
        data.forEach(row => {
            Object.keys(row.dynamic_fields || {}).forEach(k => {
                if (!['mrp', 'selling_price', 'coded_price', 'family_name', 'barcode'].includes(k)) {
                    dynamicCols.add(k);
                }
            });
        });

        const fieldPriority = {
            brand: 1, item_display_name: 2, design: 2, article: 3,
            article_no: 3, size: 4, batch_no: 5, expiry: 6
        };

        const orderedDynamicCols = Array.from(dynamicCols).sort((a, b) => {
            return (fieldPriority[a] || 50) - (fieldPriority[b] || 50);
        });

        // Middle Columns Specification:
        // 'pricing_group' moves together as a single unified group.
        // Dynamic template columns can be reordered around or alongside the pricing group.
        const colDefinitions = {};

        // 1. Pricing Group Column Definition
        if (isTopDown) {
            colDefinitions['pricing_group'] = {
                key: 'pricing_group',
                headerHtml: `
                    <div class="draggable-col-header pricing-group-header" data-col-key="pricing_group" draggable="true" title="Selling Group: MRP, C Calc, Code (Drag to move together)" style="display: flex; flex-direction: row; align-items: center; gap: 0.5rem; cursor: grab;">
                        <div style="width: 70px; display: flex; align-items: center;"><span class="col-drag-handle">⠿</span>MRP</div>
                        <div style="width: 90px;">C Calc</div>
                        <div style="width: 90px;">Code</div>
                    </div>`,
                renderCell: (row) => {
                    let codeStr = row.supplier_product_code || (row.selling_price ? window.generateCodedPrice(row.selling_price) : '');
                    let decodedStr = '';
                    let sellVal = (row.selling_price && Number(row.selling_price) > 0) ? Math.round(Number(row.selling_price)) : '';
                    if (sellVal) {
                        decodedStr = `₹${sellVal}`;
                    } else if (codeStr && !/^\d+$/.test(codeStr)) {
                        const decoded = window.decodePriceCode ? window.decodePriceCode(codeStr) : null;
                        if (decoded !== null && decoded > 0) {
                            sellVal = Math.round(decoded);
                            decodedStr = `₹${sellVal}`;
                        }
                    }
                    return `
                    <div class="grid-col-cell pricing-group-row" data-col-key="pricing_group" style="display: flex; flex-direction: row; align-items: center; gap: 0.5rem;">
                        <div style="width: 70px;"><input type="number" step="1" class="grid-cell pricing-field" data-field="mrp" value="${row.mrp !== null ? row.mrp : ''}" style="width: 100%;"></div>
                        <div style="width: 90px;"><input type="text" class="grid-cell calc-field" placeholder="-200 / 50%" style="width: 100%;"></div>
                        <div style="width: 90px; position: relative;">
                            <input type="text" class="grid-cell code-field" data-field="supplier_product_code" value="${codeStr}" style="font-family: monospace; width: 100%; padding-right: 38px;">
                            <span class="grid-code-preview" style="position: absolute; top: 50%; right: 5px; transform: translateY(-50%); font-size: 0.72rem; color: var(--accent-green, #10b981); background: transparent; font-weight: 700; ${decodedStr ? 'display: block;' : 'display: none;'} pointer-events: none; white-space: nowrap; z-index: 2;">${decodedStr}</span>
                            <input type="hidden" class="pricing-field" data-field="selling_price" value="${sellVal}">
                        </div>
                    </div>`;
                }
            };
        } else {
            colDefinitions['pricing_group'] = {
                key: 'pricing_group',
                headerHtml: `
                    <div class="draggable-col-header pricing-group-header" data-col-key="pricing_group" draggable="true" title="Selling Group: Marg %, Code, Disc %, MRP (Drag to move together)" style="display: flex; flex-direction: row; align-items: center; gap: 0.5rem; cursor: grab;">
                        <div style="width: 70px; display: flex; align-items: center;"><span class="col-drag-handle">⠿</span>Marg %</div>
                        <div style="width: 90px;">Code</div>
                        <div style="width: 70px;">Disc %</div>
                        <div style="width: 70px;">MRP</div>
                    </div>`,
                renderCell: (row) => {
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
                    let sellVal = (row.selling_price && Number(row.selling_price) > 0) ? Math.round(Number(row.selling_price)) : '';
                    if (sellVal) {
                        decodedStr = `₹${sellVal}`;
                    } else if (codeStr && !/^\d+$/.test(codeStr)) {
                        const decoded = window.decodePriceCode ? window.decodePriceCode(codeStr) : null;
                        if (decoded !== null && decoded > 0) {
                            sellVal = Math.round(decoded);
                            decodedStr = `₹${sellVal}`;
                        }
                    }
                    return `
                    <div class="grid-col-cell pricing-group-row" data-col-key="pricing_group" style="display: flex; flex-direction: row; align-items: center; gap: 0.5rem;">
                        <div style="width: 70px;"><input type="number" step="0.1" class="grid-cell margin-field" placeholder="%" value="${margin}" style="width: 100%;"></div>
                        <div style="width: 90px; position: relative;">
                            <input type="text" class="grid-cell code-field" data-field="supplier_product_code" value="${codeStr}" style="font-family: monospace; width: 100%; padding-right: 38px;">
                            <span class="grid-code-preview" style="position: absolute; top: 50%; right: 5px; transform: translateY(-50%); font-size: 0.72rem; color: var(--accent-green, #10b981); background: transparent; font-weight: 700; ${decodedStr ? 'display: block;' : 'display: none;'} pointer-events: none; white-space: nowrap; z-index: 2;">${decodedStr}</span>
                            <input type="hidden" class="pricing-field" data-field="selling_price" value="${sellVal}">
                        </div>
                        <div style="width: 70px;"><input type="number" step="0.1" class="grid-cell disc-field" placeholder="%" value="${disc}" style="width: 100%;"></div>
                        <div style="width: 70px;"><input type="number" step="1" class="grid-cell pricing-field" data-field="mrp" value="${row.mrp !== null ? row.mrp : ''}" style="width: 100%;"></div>
                    </div>`;
                }
            };
        }

        // 2. Dynamic Template Column Definitions
        orderedDynamicCols.forEach(colName => {
            const key = `dyn_${colName}`;
            colDefinitions[key] = {
                key: key,
                headerHtml: `
                    <div class="draggable-col-header" data-col-key="${key}" draggable="true" title="${colName} (Drag to reposition)" style="width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; align-items: center; cursor: grab;">
                        <span class="col-drag-handle">⠿</span><span style="overflow: hidden; text-overflow: ellipsis;">${colName}</span>
                    </div>`,
                renderCell: (row) => {
                    const f = (row.dynamic_fields || {})[colName];
                    const val = f ? (f.value || '') : '';
                    const missingClass = (f && f.missing) ? 'missing-field' : '';
                    return `<div class="grid-col-cell" data-col-key="${key}" style="width: 80px;"><input type="text" class="grid-cell dynamic-cell ${missingClass}" data-dynamic-field="${colName}" value="${val}" style="width: 100%;"></div>`;
                }
            };
        });

        // 3. Resolve Column Sequence from localStorage
        const defaultOrderKeys = ['pricing_group', ...orderedDynamicCols.map(c => `dyn_${c}`)];
        const templateStorageKey = `grid_middle_cols_${isTopDown ? 'td' : 'bu'}_${currentGridTemplate || 'default'}`;
        const fallbackStorageKey = `grid_middle_cols_${isTopDown ? 'td' : 'bu'}`;
        
        let savedKeys = null;
        try {
            const raw = localStorage.getItem(templateStorageKey) || localStorage.getItem(fallbackStorageKey);
            if (raw) savedKeys = JSON.parse(raw);
        } catch (err) {}

        let finalOrderKeys = [];
        if (Array.isArray(savedKeys) && savedKeys.length > 0) {
            // Keep saved keys that are currently valid
            savedKeys.forEach(k => {
                if (colDefinitions[k] && !finalOrderKeys.includes(k)) {
                    finalOrderKeys.push(k);
                }
            });
            // Append any available keys not present in saved order
            defaultOrderKeys.forEach(k => {
                if (!finalOrderKeys.includes(k) && colDefinitions[k]) {
                    finalOrderKeys.push(k);
                }
            });
        } else {
            finalOrderKeys = defaultOrderKeys;
        }

        const middleCols = finalOrderKeys.map(k => colDefinitions[k]).filter(Boolean);

        let html = `<div class="sleek-grid" id="spreadsheet-table" style="display: flex; flex-direction: column; gap: 0.25rem; width: 100%;">
            <div class="sleek-grid-header" style="display: flex; flex-direction: row; align-items: center; justify-content: space-between; padding: 0.4rem 0.25rem; gap: 0.5rem; font-size: 0.7rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid var(--border-color); position: sticky; top: 0; z-index: 20; background: var(--bg-color, #f2f2f7); box-shadow: 0 2px 4px rgba(0,0,0,0.03);">
                <div style="flex: 1; text-align: left; padding-left: 0.25rem;">Item Description</div>
                <div style="display: flex; flex-direction: row; align-items: center; gap: 0.5rem; padding-right: 0.25rem;">
                    <!-- Fixed Left Columns -->
                    <div style="width: 80px;">Cost</div>
                    <div style="width: 120px;">Billing Item</div>
                    
                    <!-- Draggable Middle Columns Header Container -->
                    <div class="grid-middle-cols-header" style="display: flex; flex-direction: row; align-items: center; gap: 0.5rem;">
                        ${middleCols.map(col => col.headerHtml).join('')}
                    </div>

                    <!-- Fixed Right Columns -->
                    <div style="width: 60px; text-align: center;">Qty</div>
                    <div style="width: 70px; text-align: center;">Action</div>
                </div>
            </div>
            <div class="sleek-grid-body" style="display: flex; flex-direction: column; gap: 0.15rem;">
        `;

        data.forEach((row, rowIdx) => {
            const trClass = row.label_status === 'PRINTED' ? 'row-printed' : '';
            
            let costVal = '';
            if (row.landing_price !== null && row.landing_price !== undefined) costVal = row.landing_price;
            else if (row.purchase_rate !== null && row.purchase_rate !== undefined) costVal = row.purchase_rate;
            
            const rawCopies = parseInt(row.received_qty || row.expected_qty || 1, 10);
            const defaultCopies = Math.max(1, isNaN(rawCopies) ? 1 : rawCopies);

            html += `<div class="item-row grid-row ${trClass}" data-item-id="${row.id}" data-tally-status="${row.tally_status}" data-expected-qty="${row.expected_qty !== null && row.expected_qty !== undefined ? row.expected_qty : ''}" data-unit="${row.unit || 'PCS'}" data-pricing-status="${row.pricing_status}" data-label-status="${row.label_status}" data-received-qty="${row.received_qty || 0}" style="display: flex; flex-direction: row; align-items: center; justify-content: space-between; margin: 0; padding: 0.15rem 0.25rem; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 6px;">
                
                <!-- Left Side: Sleek Details -->
                <div class="item-details readonly-cell" style="padding-left: 0.25rem; flex: 1; min-width: 0; display: flex; flex-direction: row; align-items: center; justify-content: flex-start; gap: 0.5rem; overflow: hidden; white-space: nowrap;">
                    <div style="display: flex; align-items: baseline; gap: 0.5rem; overflow: hidden; text-overflow: ellipsis;">
                        ${row.source_row_number ? `<span style="font-size: 0.75rem; color: var(--accent-blue); font-weight: 600; margin-right: 0.25rem;">#${row.source_row_number}</span>` : ''}
                        <span class="item-title-text" style="font-size: 0.85rem; font-weight: 600; text-overflow: ellipsis; overflow: hidden;" title="${row.raw_description || ''}">${row.raw_description || ''}</span>
                    </div>
                    <div class="badges" style="margin-top: 0; flex-shrink: 0; display: flex; gap: 0.35rem; align-items: center;">
                        <span class="badge qty-badge" style="background: #e5e5ea; color: #3a3a3c; font-weight: 600;"><span class="tally-display">${row.received_qty || 0}</span> / ${row.expected_qty !== null && row.expected_qty !== undefined ? row.expected_qty : '—'} ${row.unit || 'PCS'}</span>
                        <span class="tally-status-container">
                            ${renderTallyStatusBadge(row.received_qty, row.expected_qty, row.tally_status)}
                        </span>
                        ${row.label_status === 'PRINTED' ? '<span class="badge verified label-printed-badge" style="font-weight: 600;">Printed</span>' : ''}
                    </div>
                </div>

                <!-- Right Side: Excel Inputs -->
                <div class="grid-inputs" style="display: flex; flex-direction: row; align-items: center; flex-shrink: 0; padding-right: 0.25rem; gap: 0.5rem;">
                    <!-- Fixed Left -->
                    <div style="width: 80px;"><input type="number" step="0.01" class="grid-cell pricing-field" data-field="purchase_rate" value="${costVal}" style="width: 100%;"></div>
                    <div style="width: 120px;"><input type="text" class="grid-cell" data-field="billing_item" value="${row.billing_item || ''}" style="width: 100%;"></div>

                    <!-- Draggable Middle Columns Row Container -->
                    <div class="grid-middle-cols-row" style="display: flex; flex-direction: row; align-items: center; gap: 0.5rem;">
                        ${middleCols.map(col => col.renderCell(row)).join('')}
                    </div>

                    <!-- Fixed Right -->
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
        
        applyGridFilters(true); // apply filters after rendering and activate top line from billing item

        setupGridInteractions();
        setupGridColumnDrag(isTopDown, currentGridTemplate);
    }

    function setupGridColumnDrag(isTopDown, currentGridTemplate) {
        const table = document.getElementById('spreadsheet-table');
        if (!table) return;

        const headerMiddle = table.querySelector('.grid-middle-cols-header');
        if (!headerMiddle) return;

        let draggedKey = null;

        const headers = headerMiddle.querySelectorAll('.draggable-col-header');
        headers.forEach(header => {
            header.addEventListener('dragstart', (e) => {
                draggedKey = header.getAttribute('data-col-key');
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', draggedKey);
                header.classList.add('col-dragging');
            });

            header.addEventListener('dragend', () => {
                header.classList.remove('col-dragging');
                headerMiddle.querySelectorAll('.draggable-col-header').forEach(h => {
                    h.classList.remove('drop-target-left', 'drop-target-right');
                });
                draggedKey = null;
            });

            header.addEventListener('dragover', (e) => {
                e.preventDefault();
                if (!draggedKey) return;
                const target = e.target.closest('.draggable-col-header');
                if (!target || target.getAttribute('data-col-key') === draggedKey) return;

                e.dataTransfer.dropEffect = 'move';
                const rect = target.getBoundingClientRect();
                const isLeft = (e.clientX - rect.left) < (rect.width / 2);
                target.classList.toggle('drop-target-left', isLeft);
                target.classList.toggle('drop-target-right', !isLeft);
            });

            header.addEventListener('dragleave', (e) => {
                const target = e.target.closest('.draggable-col-header');
                if (target && (!e.relatedTarget || !target.contains(e.relatedTarget))) {
                    target.classList.remove('drop-target-left', 'drop-target-right');
                }
            });

            header.addEventListener('drop', (e) => {
                e.preventDefault();
                const target = e.target.closest('.draggable-col-header');
                headerMiddle.querySelectorAll('.draggable-col-header').forEach(h => {
                    h.classList.remove('drop-target-left', 'drop-target-right');
                });

                if (!target || !draggedKey) return;
                const targetKey = target.getAttribute('data-col-key');
                if (targetKey === draggedKey) return;

                const rect = target.getBoundingClientRect();
                const isLeft = (e.clientX - rect.left) < (rect.width / 2);

                // Reorder header elements
                const draggedHeader = headerMiddle.querySelector(`[data-col-key="${draggedKey}"]`);
                if (!draggedHeader) return;
                if (isLeft) {
                    headerMiddle.insertBefore(draggedHeader, target);
                } else {
                    headerMiddle.insertBefore(draggedHeader, target.nextSibling);
                }

                // Reorder cells in every row
                const rows = table.querySelectorAll('.grid-row');
                rows.forEach(r => {
                    const rowMiddle = r.querySelector('.grid-middle-cols-row');
                    if (!rowMiddle) return;
                    const draggedCell = rowMiddle.querySelector(`[data-col-key="${draggedKey}"]`);
                    const targetCell = rowMiddle.querySelector(`[data-col-key="${targetKey}"]`);
                    if (draggedCell && targetCell) {
                        if (isLeft) {
                            rowMiddle.insertBefore(draggedCell, targetCell);
                        } else {
                            rowMiddle.insertBefore(draggedCell, targetCell.nextSibling);
                        }
                    }
                });

                // Persist new order to localStorage
                const newOrder = Array.from(headerMiddle.querySelectorAll('.draggable-col-header')).map(h => h.getAttribute('data-col-key'));
                const templateStorageKey = `grid_middle_cols_${isTopDown ? 'td' : 'bu'}_${currentGridTemplate || 'default'}`;
                const fallbackStorageKey = `grid_middle_cols_${isTopDown ? 'td' : 'bu'}`;
                try {
                    localStorage.setItem(templateStorageKey, JSON.stringify(newOrder));
                    localStorage.setItem(fallbackStorageKey, JSON.stringify(newOrder));
                } catch (err) {}
            });
        });
    }


    function setupGridInteractions() {
        const table = document.getElementById('spreadsheet-table');
        if (!table) return;

        const isTopDown = localStorage.getItem('pricing_strategy_mode') === 'top_down';
        let lastPrintFocusTime = 0;

        function refreshGridCodePreview(tr) {
            if (!tr) return;
            const codeInput = tr.querySelector('.code-field');
            const previewSpan = tr.querySelector('.grid-code-preview');
            const sellInput = tr.querySelector('input[data-field="selling_price"]');
            if (!codeInput || !previewSpan) return;

            const cleanCode = codeInput.value ? codeInput.value.trim().toUpperCase() : '';
            const isNumbersOnly = cleanCode && /^\d+$/.test(cleanCode);
            
            if (isNumbersOnly) {
                codeInput.classList.add('invalid-code');
                codeInput.title = "Code cannot be only numbers. Use coded letters too.";
                codeInput.setCustomValidity("Code cannot be only numbers. Use coded letters too.");
            } else {
                codeInput.classList.remove('invalid-code');
                codeInput.title = "";
                codeInput.setCustomValidity("");
            }

            let decoded = null;
            if (cleanCode && !isNumbersOnly) {
                decoded = window.decodePriceCode ? window.decodePriceCode(cleanCode) : null;
            }
            
            if (decoded !== null && Number.isFinite(decoded) && decoded > 0) {
                const rounded = Math.round(decoded);
                previewSpan.textContent = `₹${rounded}`;
                previewSpan.style.display = 'block';
                if (sellInput) {
                    sellInput.value = rounded;
                }
            } else {
                previewSpan.textContent = '';
                previewSpan.style.display = 'none';
                if (cleanCode && sellInput) {
                    sellInput.value = '';
                }
            }
        }

        let activeGridField = null;
        let activeGridOriginalValue = null;
        let activeGridDirty = false;

        function isGridFieldActuallyEditing(input = document.activeElement) {
            return Boolean(
                input &&
                input.classList &&
                input.classList.contains('grid-cell') &&
                activeGridField === input &&
                activeGridDirty &&
                input.value !== ""
            );
        }

        table.addEventListener('focusin', (e) => {
            if (e.target.classList && e.target.classList.contains('grid-cell')) {
                activeGridField = e.target;
                activeGridOriginalValue = e.target.value;
                activeGridDirty = false;
                e.target.dataset.justFocused = "true";
                
                const tr = e.target.closest('.grid-row');
                if (tr) {
                    updateActiveGridRow(tr, e.target);
                    const visibleRows = Array.from(table.querySelectorAll('.grid-row')).filter(r => r.style.display !== 'none');
                    lastActiveRowIndex = visibleRows.indexOf(tr);
                    const focusable = Array.from(tr.querySelectorAll('.grid-cell, .btn-grid-print'));
                    lastFocusedColIndex = focusable.indexOf(e.target);
                }

                if (typeof e.target.select === 'function') {
                    e.target.select();
                }
            }
        });

        table.addEventListener('mouseup', (e) => {
            if (e.target.classList && e.target.classList.contains('grid-cell')) {
                if (e.target.dataset && e.target.dataset.justFocused === "true") {
                    e.preventDefault();
                    if (typeof e.target.select === 'function') {
                        e.target.select();
                    }
                }
            }
        });

        table.addEventListener('click', (e) => {
            if (autoAdvanceTimer) {
                clearTimeout(autoAdvanceTimer);
                autoAdvanceTimer = null;
            }
            const tr = e.target.closest('.grid-row');
            if (tr) {
                updateActiveGridRow(tr);
            }
            if (e.target.classList && e.target.classList.contains('grid-cell')) {
                if (e.target.dataset && e.target.dataset.justFocused === "true") {
                    delete e.target.dataset.justFocused;
                    if (typeof e.target.select === 'function') {
                        e.target.select();
                    }
                }
            }
        });

        table.addEventListener('focusout', (e) => {
            if (e.target.classList && e.target.classList.contains('grid-cell')) {
                if (e.target.dataset) {
                    delete e.target.dataset.justFocused;
                }
            }
        });

        // PRICING LOGIC
        table.addEventListener('input', (e) => {
            if (!e.target.classList.contains('grid-cell')) return;
            
            if (activeGridField === e.target) {
                activeGridDirty = e.target.value !== activeGridOriginalValue;
            }
            
            if (e.isTrusted && e.target.dataset.autoFilled) {
                delete e.target.dataset.autoFilled;
            }

            const tr = e.target.closest('.grid-row');
            if (!tr) return;

            const rateInput = tr.querySelector('input[data-field="purchase_rate"]');
            const mrpInput = tr.querySelector('input[data-field="mrp"]');
            const sellInput = tr.querySelector('input[data-field="selling_price"]'); // hidden
            const codeInput = tr.querySelector('.code-field');
            
            if (isTopDown) {
                const calcBox = tr.querySelector('.calc-field');
                
                if (e.target === calcBox) {
                    const currentMrp = parseFloat(mrpInput.value) || 0;
                    const expr = calcBox ? calcBox.value.trim() : "";
                    if (currentMrp > 0 && expr) {
                        const calcRate = window.computeMrpCalculation(currentMrp, expr);
                        if (calcRate !== null && Number.isFinite(calcRate) && calcRate > 0) {
                            const roundedPrice = Math.max(1, Math.round(calcRate));
                            sellInput.value = roundedPrice;
                            const encoded = window.generateCodedPrice(roundedPrice);
                            if (encoded) {
                                codeInput.value = encoded;
                                codeInput.dataset.autoCalculated = 'true';
                            }
                            refreshGridCodePreview(tr);
                        }
                    }
                } else if (e.target === codeInput) {
                    delete codeInput.dataset.autoCalculated;
                    codeInput.value = codeInput.value.toUpperCase();
                    const cleanCode = codeInput.value.trim();
                    let decoded = null;
                    if (cleanCode && !/^\d+$/.test(cleanCode)) {
                        decoded = window.decodePriceCode ? window.decodePriceCode(cleanCode) : null;
                    }
                    if (decoded !== null && decoded > 0) {
                        sellInput.value = Math.round(decoded);
                    } else {
                        sellInput.value = '';
                    }
                    refreshGridCodePreview(tr);
                } else if (e.target === mrpInput) {
                    // MRP is truth. User typing MRP does not wipe or overwrite code.
                }
            } else {
                const marginInput = tr.querySelector('.margin-field');
                const discInput = tr.querySelector('.disc-field');

                const rate = parseFloat(rateInput.value);
                const mrp = parseFloat(mrpInput.value);
                const sell = parseFloat(sellInput.value);
                const margin = parseFloat(marginInput.value);
                const disc = parseFloat(discInput.value);

                if (e.target === marginInput && !isNaN(margin) && !isNaN(rate) && rate > 0) {
                    const calcSell = Math.round(rate * (1 + margin / 100));
                    sellInput.value = calcSell;
                    const encoded = window.generateCodedPrice(calcSell);
                    if (encoded) {
                        codeInput.value = encoded;
                    }
                    refreshGridCodePreview(tr);
                    
                    // If Disc % is set, calculate and put in MRP cell; otherwise update Disc % display if MRP exists
                    if (!isNaN(disc) && disc < 100) {
                        mrpInput.value = Math.round(calcSell / (1 - disc / 100));
                    } else if (!isNaN(mrp) && mrp > 0) {
                        discInput.value = (((mrp - calcSell) / mrp) * 100).toFixed(1);
                    }
                } else if (e.target === discInput && !isNaN(disc) && disc < 100 && !isNaN(sell) && sell > 0) {
                    // MRP Disc % calculates MRP from selling price and puts in the MRP cell!
                    mrpInput.value = Math.round(sell / (1 - disc / 100));
                } else if (e.target === codeInput) {
                    delete codeInput.dataset.autoCalculated;
                    codeInput.value = codeInput.value.toUpperCase();
                    const cleanCode = codeInput.value.trim();
                    let decoded = null;
                    if (cleanCode && !/^\d+$/.test(cleanCode)) {
                        decoded = window.decodePriceCode ? window.decodePriceCode(cleanCode) : null;
                    }
                    if (decoded !== null && decoded > 0) {
                        const rounded = Math.round(decoded);
                        sellInput.value = rounded;
                        // Cascade back to margin/disc calculation box indicators for user reference ONLY (NEVER touch mrpInput!)
                        if (!isNaN(rate) && rate > 0) marginInput.value = (((rounded - rate) / rate) * 100).toFixed(1);
                        if (!isNaN(mrp) && mrp > 0) discInput.value = (((mrp - rounded) / mrp) * 100).toFixed(1);
                    } else {
                        sellInput.value = '';
                    }
                    refreshGridCodePreview(tr);
                } else if (e.target === rateInput && !isNaN(rate) && rate > 0) {
                    // Changing purchase rate updates Margin % calculation box for user reference ONLY.
                    // Code and MRP are TRUTH and must NEVER be overwritten!
                    if (!isNaN(sell) && sell > 0) {
                        marginInput.value = (((sell - rate) / rate) * 100).toFixed(1);
                    }
                } else if (e.target === mrpInput && !isNaN(mrp) && mrp > 0) {
                    // Changing MRP updates Disc % calculation box for user reference ONLY.
                    // Code is TRUTH and must NEVER be overwritten!
                    if (!isNaN(sell) && sell > 0) {
                        discInput.value = (((mrp - sell) / mrp) * 100).toFixed(1);
                    }
                }
            }
        });

        // AUTO SAVE ON BLUR (Change)
        table.addEventListener('change', async (e) => {
            if (e.target.classList.contains('grid-cell')) {
                // Formatting on blur for Code
                if (e.target.classList.contains('code-field')) {
                    e.target.value = e.target.value.trim().toUpperCase();
                    const tr = e.target.closest('.grid-row');
                    refreshGridCodePreview(tr);
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
                                const nextCodeInput = nextRow.querySelector('.code-field');
                                const hasExistingCode = nextCodeInput && nextCodeInput.value.trim() && nextCodeInput.dataset.autoCalculated !== 'true';
                                
                                // Do not overwrite calculation boxes or code if user explicitly set code on nextRow
                                if (hasExistingCode) {
                                    continue;
                                }

                                if (targetInput && (!targetInput.value || targetInput.dataset.autoFilled === 'true')) { 
                                    targetInput.value = val;
                                    targetInput.dataset.autoFilled = 'true';
                                    targetInput.dispatchEvent(new Event('input', { bubbles: true }));
                                } else if (targetInput && targetInput.value) {
                                    // Stop cascading if we hit a row the user explicitly entered
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

            if (autoAdvanceTimer && ['Tab', 'Enter', 'Backspace', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
                clearTimeout(autoAdvanceTimer);
                autoAdvanceTimer = null;
            }

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
                        updateActiveGridRow(prevRow, prev);
                    }
                }
                if (prev) {
                    prev.focus();
                    if (prev.select) prev.select();
                }
                return;
            }

            if (e.key === 'Backspace' && !isGridFieldActuallyEditing(e.target)) {
                e.preventDefault();
                e.stopPropagation();
                let prev = focusable[currentIdx - 1];
                if (!prev) {
                    const prevRow = rows[rowIdx - 1];
                    if (prevRow) {
                        const prevFocusable = Array.from(prevRow.querySelectorAll('.grid-cell, .btn-grid-print'));
                        prev = prevFocusable[prevFocusable.length - 1];
                        updateActiveGridRow(prevRow, prev);
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
                                updateActiveGridRow(nextRow, nextCell);
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
                        if (next) updateActiveGridRow(nextRow, next);
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
                    const nextTarget = Array.from(prevRow.querySelectorAll('.grid-cell, .btn-grid-print'))[currentIdx] || prevRow.querySelector('.grid-cell');
                    if (nextTarget) {
                        updateActiveGridRow(prevRow, nextTarget);
                        nextTarget.focus();
                        if (nextTarget.select) nextTarget.select();
                    }
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                const nextRow = rows[rowIdx + 1];
                if (nextRow) {
                    const nextTarget = Array.from(nextRow.querySelectorAll('.grid-cell, .btn-grid-print'))[currentIdx] || nextRow.querySelector('.grid-cell');
                    if (nextTarget) {
                        updateActiveGridRow(nextRow, nextTarget);
                        nextTarget.focus();
                        if (nextTarget.select) nextTarget.select();
                    }
                }
            } else if (e.key === '+' || e.key === '-' || e.key === '=') {
                e.preventDefault();
                
                const currentQty = parseInt(tr.getAttribute('data-received-qty')) || 0;
                const expQtyStr = tr.getAttribute('data-expected-qty');
                const expQty = (expQtyStr !== null && expQtyStr !== '') ? parseFloat(expQtyStr) : null;
                let newQty = currentQty;
                
                if (e.key === '+' || e.key === '=') {
                    newQty = currentQty + 1;
                } else if (e.key === '-') {
                    if (currentQty > 0) newQty = currentQty - 1;
                }
                
                if (newQty !== currentQty) {
                    const prevStatus = tr.getAttribute('data-tally-status');
                    let optStatus = 'UNVERIFIED';
                    if (expQty !== null && newQty === expQty && newQty > 0) optStatus = 'VERIFIED';
                    else if (newQty > 0) optStatus = 'MISMATCH';
                    
                    updateGridRowTallyBadge(tr, newQty, expQty, optStatus);

                    if (typeof window.showToast === 'function') {
                        window.showToast(`Tally: ${newQty}`, 'success');
                    }
                    
                    if (autoAdvanceTimer) {
                        clearTimeout(autoAdvanceTimer);
                        autoAdvanceTimer = null;
                    }

                    // Auto-advance cursor to next line upon successful verification
                    // (Only if not in ALL filter, because in ALL filter rows don't hide and user may want to print labels immediately!)
                    if (optStatus === 'VERIFIED' && currentGridFilter !== 'ALL') {
                        autoAdvanceTimer = setTimeout(() => {
                            autoAdvanceTimer = null;
                            const currentVisible = Array.from(table.querySelectorAll('.grid-row')).filter(r => r.style.display !== 'none');
                            const cIdx = currentVisible.indexOf(tr);
                            let targetRow = null;
                            if (cIdx !== -1 && cIdx + 1 < currentVisible.length) {
                                targetRow = currentVisible[cIdx + 1];
                            } else if (cIdx > 0) {
                                targetRow = currentVisible[cIdx - 1];
                            }
                            if (targetRow) {
                                const nextFocusable = Array.from(targetRow.querySelectorAll('.grid-cell, .btn-grid-print'));
                                const targetCell = (currentIdx >= 0 && nextFocusable[currentIdx])
                                    ? nextFocusable[currentIdx]
                                    : (targetRow.querySelector('.code-field') || targetRow.querySelector('.grid-cell'));
                                if (targetCell) {
                                    updateActiveGridRow(targetRow, targetCell);
                                    targetCell.focus();
                                    if (typeof targetCell.select === 'function') targetCell.select();
                                }
                            }
                        }, 180);
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
                        updateGridRowTallyBadge(tr, data.received_qty, expQty, data.tally_status);
                        if (typeof window.updateRowDOM === 'function') {
                            window.updateRowDOM(itemId, data);
                        }
                        if (typeof window.renderItems === 'function') {
                            window.renderItems();
                        }
                    }).catch(err => {
                        if (typeof window.showToast === 'function') window.showToast(err.message, 'error');
                        updateGridRowTallyBadge(tr, currentQty, expQty, prevStatus);
                        if (typeof window.renderItems === 'function') {
                            window.renderItems();
                        }
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
                const codeInput = tr.querySelector('.code-field');
                
                let mrp = 0;
                let sell = 0;
                let cleanCode = codeInput ? String(codeInput.value || "").trim().toUpperCase() : "";
                if (codeInput && codeInput.value !== cleanCode) {
                    codeInput.value = cleanCode;
                }
                
                if (mrpInput && sellInput) {
                    mrp = parseFloat(mrpInput.value) || 0;
                    
                    if (mrp <= 0) {
                        if (typeof window.showToast === 'function') window.showToast('MRP is required', 'error');
                        tr.classList.add('error');
                        mrpInput.focus();
                        mrpInput.select();
                        return;
                    }

                    if (!cleanCode) {
                        if (typeof window.showToast === 'function') window.showToast("Price code is required.", "error");
                        tr.classList.add('error');
                        if (codeInput) {
                            codeInput.focus();
                            codeInput.select();
                        }
                        return;
                    }

                    if (/^\d+$/.test(cleanCode)) {
                        if (typeof window.showToast === 'function') window.showToast("Code cannot be only numbers. Use coded letters too.", "error");
                        tr.classList.add('error');
                        if (codeInput) {
                            codeInput.focus();
                            codeInput.select();
                        }
                        return;
                    }

                    let decoded = window.decodePriceCode ? window.decodePriceCode(cleanCode) : null;
                    if (decoded === null || decoded <= 0) {
                        if (typeof window.showToast === 'function') window.showToast("Code cannot be decoded. Ensure it contains valid price letters.", "error");
                        tr.classList.add('error');
                        if (codeInput) {
                            codeInput.focus();
                            codeInput.select();
                        }
                        return;
                    }

                    sell = Math.round(decoded);
                    sellInput.value = sell;
                    refreshGridCodePreview(tr);
                    
                    if (sell > mrp && mrp > 0) {
                        if (typeof window.showToast === 'function') window.showToast('Selling Price cannot exceed MRP', 'error');
                        tr.classList.add('error');
                        if (codeInput) {
                            codeInput.focus();
                            codeInput.select();
                        }
                        return;
                    }

                    if (sell < (mrp * 0.5) && mrp > 0) {
                        if (!window.confirm(`WARNING: Selling price (₹${sell}) is suspiciously low (less than 50% of MRP ₹${mrp}).\n\nPress OK/Enter to proceed with printing, or Cancel/Escape to abort.`)) {
                            if (codeInput) {
                                codeInput.focus();
                                codeInput.select();
                            }
                            return;
                        }
                    }
                }

                if (!sell && cleanCode && window.decodePriceCode) {
                    const dec = window.decodePriceCode(cleanCode);
                    if (dec !== null && dec > 0) {
                        sell = Math.round(dec);
                        if (sellInput) sellInput.value = sell;
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
                
                if (!cleanCode) {
                    if (typeof window.showToast === 'function') window.showToast("Price code is required.", "error");
                    tr.classList.add('error');
                    if (codeInput) {
                        codeInput.focus();
                        codeInput.select();
                    }
                    return;
                }
                
                if (/^\d+$/.test(cleanCode)) {
                    if (typeof window.showToast === 'function') window.showToast("Code cannot be only numbers. Use coded letters too.", "error");
                    tr.classList.add('error');
                    if (codeInput) {
                        codeInput.focus();
                        codeInput.select();
                    }
                    return;
                }

                // Compute padded code matching the template default text length
                const targetLen = window.codeTargetLength || 0;
                let paddedCode = cleanCode;
                const deficit = targetLen - cleanCode.length;
                if (deficit > 0) {
                    const junk = window.getJunkPadding ? window.getJunkPadding(deficit) : '';
                    if (junk) {
                        const front = Math.floor(junk.length / 2);
                        paddedCode = junk.substring(0, front) + cleanCode + junk.substring(front);
                    }
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

                    const printOverrides = {};
                    tr.querySelectorAll('.dynamic-cell').forEach(inp => {
                        printOverrides[inp.getAttribute('data-dynamic-field')] = inp.value;
                    });
                    printOverrides['coded_price'] = paddedCode.toUpperCase();

                    // Force save the exact padded Code into the draft so BarTender receives the padded code
                    const draftPayload = {
                        template_id: tid ? parseInt(tid, 10) : null,
                        billing_item: tr.querySelector('input[data-field="billing_item"]')?.value || null,
                        purchase_rate: parseFloat(tr.querySelector('input[data-field="purchase_rate"]')?.value) || null,
                        mrp: mrp > 0 ? mrp : null,
                        selling_price: sell,
                        supplier_product_code: cleanCode,
                        manual_overrides: JSON.stringify(printOverrides)
                    };
                    await fetch(`/receiving/items/${itemId}/draft`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(draftPayload)
                    });

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
                            force_reprint: true,
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
                    
                    const badgesContainer = tr.querySelector('.badges');
                    if (badgesContainer) {
                        let pb = badgesContainer.querySelector('.label-printed-badge');
                        if (!pb) {
                            pb = document.createElement('span');
                            pb.className = 'badge verified label-printed-badge';
                            pb.style.fontWeight = '600';
                            badgesContainer.appendChild(pb);
                        }
                        pb.textContent = statusText;
                    }
                    
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
                        const billingInput = nextRow.querySelector('input[data-field="billing_item"]') || nextRow.querySelector('.grid-cell');
                        if (billingInput) {
                            updateActiveGridRow(nextRow, billingInput);
                            lastPrintFocusTime = Date.now();
                            billingInput.focus();
                            billingInput.select();
                        }
                    }
                } catch (err) {
                    console.error("Print error:", err);
                    if (typeof window.showToast === 'function') window.showToast(err.message, 'error');
                    btn.disabled = false;
                    btn.textContent = origText;
                    tr.classList.add('error');
                    
                    const msg = (err.message || '').toLowerCase();
                    if (msg.includes('mrp')) {
                        if (mrpInput) mrpInput.focus();
                    } else if (msg.includes('price code') || msg.includes('coded letters') || msg.includes('valid price letters')) {
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
            // Calculation boxes are scratchpads for the operator only.
            // Core fields (Code, MRP, Rate) are the sole truth for draft persistence.
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
        
        const rawCode = tr.querySelector('.code-field')?.value?.trim()?.toUpperCase() || null;
        let sellingPrice = null;
        if (rawCode && !/^\d+$/.test(rawCode)) {
            const decoded = window.decodePriceCode ? window.decodePriceCode(rawCode) : null;
            if (decoded !== null && decoded > 0) {
                sellingPrice = Math.round(decoded);
            }
        }
        if (sellingPrice === null) {
            const fallbackSell = parseFloat(tr.querySelector('input[data-field="selling_price"]')?.value);
            sellingPrice = isNaN(fallbackSell) ? null : fallbackSell;
        }
        let printCode = rawCode;
        if (rawCode && !/^\d+$/.test(rawCode)) {
            const targetLen = window.codeTargetLength || 0;
            const deficit = targetLen - rawCode.length;
            if (deficit > 0) {
                const junk = window.getJunkPadding ? window.getJunkPadding(deficit) : '';
                if (junk) {
                    const front = Math.floor(junk.length / 2);
                    printCode = junk.substring(0, front) + rawCode + junk.substring(front);
                }
            }
        }
        if (printCode) {
            dynamicFields['coded_price'] = printCode;
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
            supplier_product_code: rawCode,
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
            
            if (data.tally_status) {
                tr.setAttribute('data-tally-status', data.tally_status);
                updateGridRowTallyBadge(tr, data.received_qty, tr.getAttribute('data-expected-qty'), data.tally_status);
            }
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

    // Global keyboard navigation fallback for arrow keys when activeElement is outside grid cells
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
        
        const spreadsheetContainer = document.getElementById('spreadsheet-container');
        if (!spreadsheetContainer || spreadsheetContainer.style.display === 'none') return;
        
        const activeEl = document.activeElement;
        if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'SELECT' || activeEl.classList.contains('grid-cell') || activeEl.closest('.grid-row'))) {
            return;
        }
        
        const tallySheet = document.getElementById('tally-sheet');
        if (tallySheet && !tallySheet.classList.contains('hidden') && tallySheet.style.display !== 'none') return;
        
        const table = document.getElementById('spreadsheet-table');
        if (!table) return;
        const visibleRows = Array.from(table.querySelectorAll('.grid-row')).filter(r => r.style.display !== 'none');
        if (visibleRows.length === 0) return;
        
        e.preventDefault();
        let targetIndex = gridHighlightedIndex;
        if (e.key === 'ArrowDown') {
            targetIndex = (targetIndex + 1 < visibleRows.length) ? targetIndex + 1 : 0;
        } else if (e.key === 'ArrowUp') {
            targetIndex = (targetIndex - 1 >= 0) ? targetIndex - 1 : visibleRows.length - 1;
        }
        
        const targetRow = visibleRows[targetIndex];
        if (targetRow) {
            updateActiveGridRow(targetRow);
            const cellToFocus = targetRow.querySelector('.code-field') || targetRow.querySelector('.grid-cell') || targetRow.querySelector('input[data-field="billing_item"]');
            if (cellToFocus) {
                cellToFocus.focus();
                if (typeof cellToFocus.select === 'function') cellToFocus.select();
            }
        }
    });
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
                    rowData.purchase_rate = parseFloat(purchaseRate.toFixed(2));
                    rowData.landing_price = parseFloat(landingPrice.toFixed(2));
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
