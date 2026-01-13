function renderActiveTrades(trades) {
    let container = $('#pos-container');
    
    // 1. Mark existing cards to identify removals later
    container.children().addClass('to-remove');

    // 2. Iterate trades (Newest first) and Update or Create
    trades.slice().reverse().forEach((t, index) => {
        let pnl = 0;
        let pnlClass = 'text-secondary';
        let borderClass = 'border-secondary';
        
        if (t.status !== 'PENDING') {
            pnl = (t.current_ltp - t.entry_price) * t.quantity;
            pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
            borderClass = pnl >= 0 ? 'border-success' : 'border-danger';
        }
        
        let cardId = `trade-card-${t.id}`;
        let existingCard = $(`#${cardId}`);
        
        if (existingCard.length > 0) {
            // --- UPDATE EXISTING CARD ---
            existingCard.removeClass('to-remove');
            
            // Update Classes (Border Color)
            existingCard.attr('class', `card mb-2 trade-card border-start border-4 ${borderClass}`);
            
            // Update Text Values Only (Preserves Dropdowns/Buttons)
            existingCard.find('.trade-status').text(t.status);
            existingCard.find('.trade-pnl').text(`₹ ${pnl.toFixed(2)}`).attr('class', `fw-bold trade-pnl ${pnlClass}`);
            existingCard.find('.trade-ltp').text(`LTP: ${t.current_ltp}`);
            
            // Update other mutable fields
            existingCard.find('.trade-qty').text(t.quantity);
            existingCard.find('.trade-avg').text(t.entry_price.toFixed(2));
            existingCard.find('.trade-sl').text(t.sl.toFixed(2));
            
            // Ensure visual order matches data order
            let currentAtIndex = container.children().eq(index);
            if (currentAtIndex.attr('id') !== cardId) {
                if (index === 0) container.prepend(existingCard);
                else existingCard.insertAfter(container.children().eq(index - 1));
            }
            
        } else {
            // --- CREATE NEW CARD ---
            let cardHtml = `
            <div id="${cardId}" class="card mb-2 trade-card border-start border-4 ${borderClass}">
                <div class="card-body p-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <span class="badge ${t.mode === 'LIVE' ? 'bg-danger' : 'bg-secondary'} me-1">${t.mode}</span>
                            <span class="fw-bold">${t.symbol}</span>
                            <span class="badge bg-light text-dark border ms-1 trade-status">${t.status}</span>
                        </div>
                        <div class="text-end">
                            <div class="fw-bold ${pnlClass} trade-pnl">₹ ${pnl.toFixed(2)}</div>
                            <small class="text-muted trade-ltp">LTP: ${t.current_ltp}</small>
                        </div>
                    </div>
                    
                    <div class="d-flex justify-content-between mt-2 small text-muted">
                        <span>Qty: <strong class="trade-qty">${t.quantity}</strong></span>
                        <span>Avg: <strong class="trade-avg">${t.entry_price.toFixed(2)}</strong></span>
                        <span>SL: <strong class="trade-sl">${t.sl.toFixed(2)}</strong></span>
                    </div>

                    <div class="mt-2 d-flex gap-2">
                        <button class="btn btn-sm btn-outline-primary flex-grow-1" onclick="openEditModal(${t.id})">Edit Protection</button>
                        
                        <div class="dropdown">
                            <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown">
                                Manage
                            </button>
                            <ul class="dropdown-menu">
                                <li><a class="dropdown-item" href="#" onclick="managePosition(${t.id}, 'ADD')">Add Qty</a></li>
                                <li><a class="dropdown-item" href="#" onclick="managePosition(${t.id}, 'EXIT')">Partial Exit</a></li>
                                <li><hr class="dropdown-divider"></li>
                                <li><a class="dropdown-item text-info" href="#" onclick="showLogs(${t.id})">View Logs</a></li>
                                ${t.mode === 'PAPER' ? `<li><a class="dropdown-item text-warning" href="/promote/${t.id}">Promote to LIVE</a></li>` : ''}
                            </ul>
                        </div>

                        <a href="/close_trade/${t.id}" class="btn btn-sm btn-danger" onclick="return confirm('Close this trade?')">Exit</a>
                    </div>
                </div>
            </div>`;
            
            // Insert Logic
            if (index === 0) {
                container.prepend(cardHtml);
            } else {
                $(cardHtml).insertAfter(container.children().eq(index - 1));
            }
        }
    });
    
    // 3. Remove items that are not in the new list (Closed trades)
    container.find('.to-remove').remove();
}

function managePosition(id, action) {
    let lots = prompt(`How many LOTS to ${action}?`);
    if (lots != null && parseInt(lots) > 0) {
        $.ajax({
            url: '/api/manage_trade',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ id: id, action: action, lots: lots }),
            success: function(res) {
                if (res.status === 'success') {
                    alert("✅ " + res.message); 
                    // Data will auto-update via main.js loop
                } else {
                    alert("❌ ERROR: " + res.message);
                }
            },
            error: function(err) {
                alert("Server Error: " + err.responseText);
            }
        });
    }
}

function openEditModal(id) {
    $.ajax({
        url: '/api/positions',
        success: function(trades) {
            let t = trades.find(x => x.id == id);
            if (t) {
                // FIX: Updated IDs to match modals.html
                $('#edit_trade_id').val(t.id);
                $('#edit_sl').val(t.sl);
                $('#edit_trail').val(t.trailing_sl);
                
                $('#edit_t1').val(t.targets[0] || 0);
                $('#edit_t2').val(t.targets[1] || 0);
                $('#edit_t3').val(t.targets[2] || 0);

                // FIX: Updated Modal ID
                $('#editTradeModal').modal('show');
            }
        }
    });
}

function saveTradeUpdate() {
    let data = {
        // FIX: Updated ID to match input
        id: $('#edit_trade_id').val(),
        sl: $('#edit_sl').val(),
        trailing_sl: $('#edit_trail').val(),
        targets: [
            $('#edit_t1').val(),
            $('#edit_t2').val(),
            $('#edit_t3').val()
        ]
    };
    
    $.ajax({
        url: '/api/update_trade',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(data),
        success: function(res) {
            if (res.status === 'success') {
                // FIX: Updated Modal ID
                $('#editTradeModal').modal('hide');
                // Data will auto-update
            } else {
                alert("Failed: " + res.message);
            }
        }
    });
}

function showLogs(id) {
    $.ajax({
        url: '/api/positions',
        success: function(trades) {
            let t = trades.find(x => x.id == id);
            if (t) {
                let logHtml = t.logs.map(l => `<div>${l}</div>`).join('');
                let w = window.open('', 'Trade Logs', 'width=600,height=400');
                w.document.write(`<html><head><title>Logs</title></head><body style="font-family:monospace; padding:20px;"><h3>Trade Logs</h3>${logHtml}</body></html>`);
            }
        }
    });
}
