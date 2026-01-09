function updateData() {
    if(!document.getElementById('n_lp')) return;
    $.get('/api/indices', d => { $('#n_lp').text(d.NIFTY); $('#b_lp').text(d.BANKNIFTY); $('#s_lp').text(d.SENSEX); });
    
    let currentSym = $('#sym').val();
    if(currentSym && $('#trade').is(':visible')) {
            let tVal = $('input[name="type"]:checked').val();
            if(tVal) {
                $.get(`/api/specific_ltp?symbol=${currentSym}&expiry=${$('#exp').val()}&strike=${$('#str').val()}&type=${tVal}`, d => {
                curLTP=d.ltp; $('#inst_ltp').text("LTP: "+curLTP);
                if (document.activeElement.id !== 'p_sl') calcSLPriceFromPts('#sl_pts', '#p_sl');
                });
            }
    }
    if ($('#closed').is(':visible')) loadClosedTrades();
    
    let filterType = $('#active_filter').val();
    $.get('/api/positions', trades => {
        activeTradesList = trades; 
        let sumLive = 0, sumPaper = 0, sumSim = 0;
        trades.forEach(t => {
            let pnl = (t.status === 'PENDING') ? 0 : (t.current_ltp - t.entry_price) * t.quantity;
            let cat = getTradeCategory(t);
            if(cat === 'LIVE') sumLive += pnl; else if(cat === 'PAPER') sumPaper += pnl; else if(cat === 'SIMULATOR') sumSim += pnl;
        });
        $('#sum_live').text("₹ " + sumLive.toFixed(2)).attr('class', sumLive >= 0 ? 'fw-bold text-success' : 'fw-bold text-danger');
        $('#sum_paper').text("₹ " + sumPaper.toFixed(2)).attr('class', sumPaper >= 0 ? 'fw-bold text-success' : 'fw-bold text-danger');
        $('#sum_sim').text("₹ " + sumSim.toFixed(2)).attr('class', sumSim >= 0 ? 'fw-bold text-success' : 'fw-bold text-danger');

        let filtered = trades.filter(t => filterType === 'ALL' || getTradeCategory(t) === filterType);
        let html = '';
        if(filtered.length === 0) html = '<div class="text-center p-4 text-muted">No Active Trades for selected filter</div>';
        else {
            filtered.forEach(t => {
                let pnl = (t.current_ltp - t.entry_price) * t.quantity;
                let color = pnl >= 0 ? 'pnl-green' : 'pnl-red';
                if (t.status === 'PENDING') { pnl = 0; color = 'text-warning'; }
                let cat = getTradeCategory(t); 
                let badge = getMarkBadge(cat);
                let editBtn = (cat !== 'SIMULATOR') ? `<button class="btn btn-xs btn-outline-primary" onclick="openEditTradeModal('${t.id}')">✏️ Edit</button>` : '';

                html += `<div class="trade-row">
                    <div class="trade-info">
                        <div class="d-flex align-items-center gap-2">
                            <span class="fw-bold text-dark" style="font-size:0.9rem;">${t.symbol}</span>
                            ${badge}
                        </div>
                        <div class="text-end">
                             <span class="fw-bold ${color}" style="font-size:1rem;">${t.status==='PENDING'?'PENDING':pnl.toFixed(2)}</span>
                        </div>
                    </div>
                    <div class="trade-details">
                        <span>Qty: <b class="text-dark">${t.quantity}</b></span>
                        <span>Ent: <b>${t.entry_price.toFixed(2)}</b></span>
                        <span>LTP: <b class="text-primary">${t.current_ltp.toFixed(2)}</b></span>
                        <span class="text-danger">SL: <b>${t.sl.toFixed(1)}</b></span>
                    </div>
                    <div class="trade-actions">
                        ${editBtn}
                        <button class="btn btn-xs btn-outline-secondary" onclick="showLogs('${t.id}', 'active')">Logs</button>
                        <a href="/close_trade/${t.id}" class="btn btn-xs btn-dark fw-bold">${t.status==='PENDING'?'Cancel':'Exit'}</a>
                    </div>
                </div>`;
            });
        }
        $('#pos-container').html(html);
    });
}

function openEditTradeModal(id) {
    let t = activeTradesList.find(x => x.id == id); if(!t) return;
    $('#edit_trade_id').val(t.id); $('#edit_sl').val(t.sl); $('#edit_trail').val(t.trailing_sl || 0);
    $('#edit_t1').val(t.targets[0] || 0); $('#edit_t2').val(t.targets[1] || 0); $('#edit_t3').val(t.targets[2] || 0);
    new bootstrap.Modal(document.getElementById('editTradeModal')).show();
}

function saveTradeUpdate() {
    let d = { id: $('#edit_trade_id').val(), sl: parseFloat($('#edit_sl').val()), trailing_sl: parseFloat($('#edit_trail').val()), targets: [parseFloat($('#edit_t1').val())||0, parseFloat($('#edit_t2').val())||0, parseFloat($('#edit_t3').val())||0] };
    $.ajax({ type: "POST", url: '/api/update_trade', data: JSON.stringify(d), contentType: "application/json", success: function(r) { if(r.status==='success') { $('#editTradeModal').modal('hide'); updateData(); } else alert("Failed to update: " + r.message); } });
}
