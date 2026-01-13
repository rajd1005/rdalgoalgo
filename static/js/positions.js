function renderActiveTrades(trades) {
    // FIX: Changed selector to '#pos-container' to match tab_active.html
    let container = $('#pos-container');
    container.empty();
    
    // Reverse array to show newest first
    trades.slice().reverse().forEach(t => {
        let pnl = 0;
        let pnlClass = 'text-secondary';
        
        if (t.status !== 'PENDING') {
            pnl = (t.current_ltp - t.entry_price) * t.quantity;
            pnlClass = pnl >= 0 ? 'text-success' : 'text-danger';
        }
        
        let card = `
        <div class="card mb-2 trade-card border-start border-4 ${pnl >= 0 ? 'border-success' : 'border-danger'}">
            <div class="card-body p-2">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <span class="badge ${t.mode === 'LIVE' ? 'bg-danger' : 'bg-secondary'} me-1">${t.mode}</span>
                        <span class="fw-bold">${t.symbol}</span>
                        <span class="badge bg-light text-dark border ms-1">${t.status}</span>
                    </div>
                    <div class="text-end">
                        <div class="fw-bold ${pnlClass}">₹ ${pnl.toFixed(2)}</div>
                        <small class="text-muted">LTP: ${t.current_ltp}</small>
                    </div>
                </div>
                
                <div class="d-flex justify-content-between mt-2 small text-muted">
                    <span>Qty: <strong>${t.quantity}</strong></span>
                    <span>Avg: <strong>${t.entry_price.toFixed(2)}</strong></span>
                    <span>SL: <strong>${t.sl.toFixed(2)}</strong></span>
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
        </div>
        `;
        container.append(card);
    });
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
                    // Success Notification
                    alert("✅ " + res.message); 
                    updateData();
                } else {
                    // Error Notification
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
                $('#edit_id').val(t.id);
                $('#edit_sl').val(t.sl);
                $('#edit_trail').val(t.trailing_sl);
                
                $('#edit_t1').val(t.targets[0] || 0);
                $('#edit_t2').val(t.targets[1] || 0);
                $('#edit_t3').val(t.targets[2] || 0);

                $('#editModal').modal('show');
            }
        }
    });
}

function saveTradeUpdate() {
    let data = {
        id: $('#edit_id').val(),
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
                $('#editModal').modal('hide');
                updateData();
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
