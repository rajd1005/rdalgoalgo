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
                let cat = getTradeCategory(t); let badge = getMarkBadge(cat);
                let editBtn = (cat !== 'SIMULATOR') ? `<span class="action-btn text-primary" onclick="openEditTradeModal('${t.id}')">✏️</span>` : '';

                html += `<div class="card mb-3 border shadow-sm"><div class="card-body p-2">
                    <div class="d-flex justify-content-between mb-2 align-items-center">
                        <div style="font-size:0.9rem; font-weight:700;">${t.symbol} <span class="badge bg-light text-dark border">Q:${t.quantity}</span></div>
                        <div>${editBtn} ${badge}</div>
                    </div>
                    <div class="text-center py-2 bg-light rounded mb-2">
                        <small class="text-muted fw-bold" style="font-size:0.7rem;">P&L</small>
                        <h4 class="mb-0 fw-bold ${color}">${t.status==='PENDING'?'PENDING':pnl.toFixed(2)}</h4>
                    </div>
                    <div class="row text-center mb-2 g-0">
                        <div class="col-6 border-end"><div class="pos-grid-label">Entry</div><div class="pos-grid-val">${t.entry_price.toFixed(2)}</div></div>
                        <div class="col-6"><div class="pos-grid-label">LTP</div><div class="pos-grid-val text-primary">${t.current_ltp.toFixed(2)}</div></div>
                    </div>
                    <div class="row text-center border-top pt-2 g-1">
                        <div class="col-3 px-1"><div class="pos-grid-label text-danger">SL</div><small class="fw-bold" style="font-size:0.8rem;">${t.sl.toFixed(1)}</small></div>
                        <div class="col-3 px-1"><div class="pos-grid-label text-success">T1</div><small class="fw-bold" style="font-size:0.8rem;">${t.targets[0].toFixed(1)}</small></div>
                        <div class="col-3 px-1"><div class="pos-grid-label text-success">T2</div><small class="fw-bold" style="font-size:0.8rem;">${t.targets[1].toFixed(1)}</small></div>
                        <div class="col-3 px-1"><div class="pos-grid-label text-success">T3</div><small class="fw-bold" style="font-size:0.8rem;">${t.targets[2].toFixed(1)}</small></div>
                    </div>
                    <div class="mt-2 text-center"><button class="btn btn-sm btn-outline-secondary w-100" onclick="showLogs('${t.id}', 'active')">📄 Logs</button></div>
                    <div class="mt-2 d-flex justify-content-between gap-2"><a href="/close_trade/${t.id}" class="btn btn-sm btn-dark flex-grow-1 fw-bold">${t.status==='PENDING'?'Cancel':'Exit'}</a>${t.mode=='PAPER' ? `<a href="/promote/${t.id}" class="btn btn-sm btn-outline-danger fw-bold">Live</a>` : ''}</div>
                </div></div>`;
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
