function loadClosedTrades() {
    let filterDate = $('#hist_date').val(); let filterType = $('#hist_filter').val();
    $.get('/api/closed_trades', trades => {
        allClosedTrades = trades; let html = ''; let dayTotal = 0;
        let filtered = trades.filter(t => t.exit_time && t.exit_time.startsWith(filterDate) && (filterType === 'ALL' || getTradeCategory(t) === filterType));
        if(filtered.length === 0) html = '<div class="text-center p-4 text-muted">No History for this Date/Filter</div>';
        else {
            filtered.forEach(t => {
                dayTotal += t.pnl; let color = t.pnl >= 0 ? 'pnl-green' : 'pnl-red';
                let cat = getTradeCategory(t); let badge = getMarkBadge(cat);
                let editBtn = (t.order_type === 'SIMULATION') ? `<span class="action-btn text-primary" onclick="editSim('${t.id}')">✏️</span>` : '';
                let delBtn = `<span class="action-btn text-danger" onclick="deleteTrade('${t.id}')">🗑️</span>`;
                let ltpBadge = t.current_ltp ? `<span class="badge bg-light text-dark border ms-1" style="font-size:0.7rem;">LTP:${t.current_ltp.toFixed(2)}</span>` : '';
                html += `<div class="card mb-3 border shadow-sm"><div class="card-body p-2">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <h6 class="fw-bold mb-0" style="font-size:0.9rem;">${t.symbol}</h6> <div>${editBtn}${delBtn}${badge}<span class="badge bg-secondary ms-1" style="font-size:0.7rem;">${t.status}</span></div>
                    </div>
                    <div class="d-flex justify-content-between mt-1"><small>Entry: <b>${t.entry_price.toFixed(2)}</b></small><small>Exit: <b>${t.exit_price.toFixed(2)}</b>${ltpBadge}</small></div>
                    <div class="d-flex justify-content-between mt-1 align-items-center"><small class="text-muted" style="font-size:0.7rem;">${t.exit_time.slice(11,16)}</small><h5 class="mb-0 fw-bold ${color}">${t.pnl.toFixed(2)}</h5></div>
                    <div class="mt-2 text-center"><button class="btn btn-sm btn-outline-secondary w-100" onclick="showLogs('${t.id}', 'closed')">📄 Logs</button></div>
                </div></div>`;
            });
        }
        $('#hist-container').html(html); $('#day_pnl').text("₹ " + dayTotal.toFixed(2));
        if(dayTotal >= 0) $('#day_pnl').removeClass('bg-danger').addClass('bg-success'); else $('#day_pnl').removeClass('bg-success').addClass('bg-danger');
    });
}

function deleteTrade(id) { 
    if(confirm("Delete trade?")) $.post('/api/delete_trade/' + id, r => { if(r.status === 'success') loadClosedTrades(); else alert('Failed to delete'); }); 
}

function editSim(id) {
    let t = allClosedTrades.find(x => x.id == id); if(!t) return;
    $('.dashboard-tab').hide(); $('#history').show(); $('.nav-btn').removeClass('active'); $('.nav-btn').last().addClass('active');
    if(t.raw_params) {
        $('#h_sym').val(t.raw_params.symbol); $('#h_entry').val(t.entry_price); $('#h_qty').val(t.quantity); $('#h_time').val(t.raw_params.time);
        $(`input[name="h_type"][value="${t.raw_params.type}"]`).prop('checked', true);
        loadDetails('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_qty', '#h_sl_pts');
        setTimeout(() => { $('#h_exp').val(t.raw_params.expiry).change(); setTimeout(() => { $('#h_str').val(t.raw_params.strike).change(); }, 500); }, 800);
    } else alert("Old trade format.");
}
