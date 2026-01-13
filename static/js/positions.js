function updateData() {
    if(!document.getElementById('n_lp')) return;
    
    $.get('/api/indices', d => { 
        // 1. Zero Price Detection (Server Offline/Reconnecting)
        if (d.NIFTY === 0 || d.BANKNIFTY === 0) {
            
            // UI: Update Ticker with Loading Animation
            let spinner = '<span class="spinner-border spinner-border-sm text-warning" role="status" aria-hidden="true" style="width: 0.8rem; height: 0.8rem; border-width: 0.15em;"></span> <span class="text-warning small blink" style="font-size:0.75rem;">Wait...</span>';
            $('#n_lp').html(spinner); 
            $('#b_lp').html(spinner); 
            $('#s_lp').html(spinner);

            // UI: Update Status Badge (Waiting for Server Loop)
            if ($('#status-badge').text().trim() !== "Manual Login") {
                $('#status-badge').attr('class', 'badge bg-warning text-dark shadow-sm blink').html('<i class="fas fa-sync fa-spin"></i> Auto-Login...');
            }

            // Poll Backend Status to Check for Failure (to show Manual Button)
            $.get('/api/status', statusData => {
                if (statusData.state === 'FAILED') {
                     // UI: Show Manual Login Button in Ticker Bar (Replaces Status Badge)
                     let btnHtml = `<a href="${statusData.login_url}" class="btn btn-sm btn-danger fw-bold shadow-sm py-0" style="font-size: 0.75rem;" target="_blank"><i class="fas fa-key"></i> Manual Login</a>`;
                     
                     $('#status-badge').removeClass('bg-warning blink').addClass('bg-transparent p-0').html(btnHtml);
                }
            });

            return; // Stop processing further updates while offline
        }

        // Restore Badge if it was in error/waiting state
        if ($('#status-badge').find('.fa-sync').length > 0 || $('#status-badge').find('.fa-key').length > 0) {
             $('#status-badge').attr('class', 'badge bg-success shadow-sm').html('<i class="fas fa-wifi"></i> Connected');
        }

        $('#n_lp').text(d.NIFTY); 
        $('#b_lp').text(d.BANKNIFTY); 
        $('#s_lp').text(d.SENSEX); 
    });
    
    // Only proceed with other updates if we are online
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
        let sumLive = 0, sumPaper = 0;
        trades.forEach(t => {
            let pnl = (t.status === 'PENDING') ? 0 : (t.current_ltp - t.entry_price) * t.quantity;
            let cat = getTradeCategory(t);
            if(cat === 'LIVE') sumLive += pnl; else if(cat === 'PAPER' && !t.is_replay) sumPaper += pnl;
        });
        $('#sum_live').text("₹ " + sumLive.toFixed(2)).attr('class', sumLive >= 0 ? 'fw-bold text-success' : 'fw-bold text-danger');
        $('#sum_paper').text("₹ " + sumPaper.toFixed(2)).attr('class', sumPaper >= 0 ? 'fw-bold text-success' : 'fw-bold text-danger');

        let filtered = trades.filter(t => filterType === 'ALL' || getTradeCategory(t) === filterType);
        let html = '';
        if(filtered.length === 0) html = '<div class="text-center p-4 text-muted">No Active Trades for selected filter</div>';
        else {
            filtered.forEach(t => {
                let pnl = (t.current_ltp - t.entry_price) * t.quantity;
                let color = pnl >= 0 ? 'pnl-green' : 'pnl-red';
                if (t.status === 'PENDING') { pnl = 0; color = 'text-warning'; }
                let cat = getTradeCategory(t); 
                
                // Badge Logic: Replay vs Paper vs Live
                let badge = getMarkBadge(cat);
                if(t.is_replay) badge = '<span class="badge bg-info text-dark" style="font-size:0.7rem;">REPLAY</span>';

                let editBtn = `<button class="btn btn-xs btn-outline-primary" onclick="openEditTradeModal('${t.id}')">✏️ Edit</button>`;
                
                // --- Active Trade Status Tags (Updated) ---
                let statusTag = '';
                if(t.status === 'PENDING') statusTag = '<span class="badge bg-warning text-dark" style="font-size:0.7rem;">Pending</span>';
                else {
                    let hits = t.targets_hit_indices || [];
                    let maxHit = -1;
                    if(hits.length > 0) maxHit = Math.max(...hits);
                    
                    if(maxHit === 0) statusTag = '<span class="badge bg-success" style="font-size:0.7rem;">Target 1 Hit</span>';
                    else if(maxHit === 1) statusTag = '<span class="badge bg-success" style="font-size:0.7rem;">Target 2 Hit</span>';
                    else if(maxHit === 2) statusTag = '<span class="badge bg-success" style="font-size:0.7rem;">Target 3 Hit</span>';
                    else statusTag = '<span class="badge bg-primary" style="font-size:0.7rem;">Active</span>';
                }
                
                // Replay Time Indicator (Optional but helpful)
                let timeTag = '';
                if(t.is_replay && t.last_update_time) {
                    timeTag = `<br><span class="text-muted" style="font-size:0.65rem;">🕒 ${t.last_update_time.slice(11,19)}</span>`;
                }

                html += `<div class="trade-row">
                    <div class="trade-info">
                        <div class="d-flex align-items-center gap-2">
                            <span class="fw-bold text-dark" style="font-size:0.9rem;">${t.symbol}</span>
                            ${badge}
                            ${statusTag}
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
                        ${timeTag}
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
    $('#edit_trade_id').val(t.id);
    $('#edit_entry').val(t.entry_price);
    $('#edit_sl').val(t.sl);
    $('#edit_trail').val(t.trailing_sl || 0);
    $('#edit_trail_mode').val(t.sl_to_entry || 0);
    
    // Load Exit Multiplier (or default to 1)
    $('#edit_exit_mult').val(t.exit_multiplier || 1);
    
    // Default Controls if missing
    let defaults = [
        {enabled: true, lots: 0},
        {enabled: true, lots: 0},
        {enabled: true, lots: 1000} // Default T3 exits all
    ];
    let controls = t.target_controls || defaults;

    // T1
    $('#edit_t1').val(t.targets[0] || 0);
    $('#check_t1').prop('checked', controls[0].enabled);
    let l1 = controls[0].lots;
    $('#full_t1').prop('checked', l1 >= 1000);
    $('#lot_t1').val(l1 < 1000 && l1 > 0 ? l1 : '');
    
    // T2
    $('#edit_t2').val(t.targets[1] || 0);
    $('#check_t2').prop('checked', controls[1].enabled);
    let l2 = controls[1].lots;
    $('#full_t2').prop('checked', l2 >= 1000);
    $('#lot_t2').val(l2 < 1000 && l2 > 0 ? l2 : '');

    // T3
    $('#edit_t3').val(t.targets[2] || 0);
    $('#check_t3').prop('checked', controls[2].enabled);
    let l3 = controls[2].lots;
    $('#full_t3').prop('checked', l3 >= 1000);
    $('#lot_t3').val(l3 < 1000 && l3 > 0 ? l3 : '');
    
    // Disable target inputs if they are already hit
    let hits = t.targets_hit_indices || [];
    $('#edit_t1').prop('disabled', hits.includes(0));
    $('#edit_t2').prop('disabled', hits.includes(1));
    $('#edit_t3').prop('disabled', hits.includes(2));
    
    // Manage Position Setup
    let lot = t.lot_size || 1;
    $('#man_add_lots').attr('step', lot).attr('min', lot).val(lot).data('lot', lot);
    $('#man_exit_lots').attr('step', lot).attr('min', lot).val(lot).data('lot', lot);

    new bootstrap.Modal(document.getElementById('editTradeModal')).show();
}

function saveTradeUpdate() {
    let d = {
        id: $('#edit_trade_id').val(),
        entry_price: parseFloat($('#edit_entry').val()),
        sl: parseFloat($('#edit_sl').val()),
        trailing_sl: parseFloat($('#edit_trail').val()),
        sl_to_entry: parseInt($('#edit_trail_mode').val()) || 0,
        exit_multiplier: parseInt($('#edit_exit_mult').val()) || 1,
        targets: [
            parseFloat($('#edit_t1').val())||0,
            parseFloat($('#edit_t2').val())||0,
            parseFloat($('#edit_t3').val())||0
        ],
        target_controls: [
            { 
                enabled: $('#check_t1').is(':checked'), 
                lots: $('#full_t1').is(':checked') ? 1000 : (parseInt($('#lot_t1').val()) || 0)
            },
            { 
                enabled: $('#check_t2').is(':checked'), 
                lots: $('#full_t2').is(':checked') ? 1000 : (parseInt($('#lot_t2').val()) || 0)
            },
            { 
                enabled: $('#check_t3').is(':checked'), 
                lots: $('#full_t3').is(':checked') ? 1000 : (parseInt($('#lot_t3').val()) || 0)
            }
        ]
    };
    $.ajax({ type: "POST", url: '/api/update_trade', data: JSON.stringify(d), contentType: "application/json", success: function(r) { if(r.status==='success') { $('#editTradeModal').modal('hide'); updateData(); } else alert("Failed to update: " + r.message); } });
}

function managePos(action) {
    let inputId = (action === 'ADD') ? '#man_add_lots' : '#man_exit_lots';
    let qty = parseInt($(inputId).val());
    let lotSize = $(inputId).data('lot') || 1;
    
    if(!qty || qty <= 0 || qty % lotSize !== 0) { 
        alert(`Invalid Quantity. Must be multiple of ${lotSize}`); return; 
    }
    
    // Convert Quantity to Lots count for the backend
    let lots = qty / lotSize;
    
    if(confirm(`${action === 'ADD' ? 'Add' : 'Exit'} ${qty} Qty (${lots} Lots)?`)) {
        let d = { id: $('#edit_trade_id').val(), action: action, lots: lots };
        $.ajax({
            type: "POST", url: '/api/manage_trade', data: JSON.stringify(d), contentType: "application/json",
            success: function(r) {
                if(r.status === 'success') { $('#editTradeModal').modal('hide'); updateData(); }
                else alert("Error: " + r.message);
            }
        });
    }
}
