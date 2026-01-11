function calcSimSL(source) {
    let entry = parseFloat($('#h_entry').val()) || 0;
    if(entry <= 0) return;
    
    // Apply Defaults for Simulator (One-time check logic using a data flag)
    let s = settings.modes.SIMULATOR;
    if (!$(document).data('sim_init_done')) {
        if (s.trailing_sl !== undefined) $('#h_trail').val(s.trailing_sl);
        if (s.trail_limit !== undefined) $('#h_sl_to_entry').val(s.trail_limit);
        if (s.exit_mult !== undefined) $('#h_exit_mult').val(s.exit_mult);
        
        // Sync Ratios Labels
        if(s.ratios) {
             $('#hr_t1').text(s.ratios[0]);
             $('#hr_t2').text(s.ratios[1]);
             $('#hr_t3').text(s.ratios[2]);
        }

        // Apply Targets
        if (s.targets) {
            ['t1', 't2', 't3'].forEach((k, i) => {
                let conf = s.targets[i];
                $(`#h_check_${k}`).prop('checked', conf.active);
                $(`#h_full_${k}`).prop('checked', conf.full);
                if(conf.full) $(`#h_lot_${k}`).val(1000);
                else $(`#h_lot_${k}`).val(conf.lots > 0 ? conf.lots : '');
            });
        }
        $(document).data('sim_init_done', true);
    }

    if(source === 'pts') {
        let pts = parseFloat($('#h_sl_pts').val()) || 0;
        $('#h_p_sl').val((entry - pts).toFixed(2));
    } else {
        let price = parseFloat($('#h_p_sl').val()) || 0;
        $('#h_sl_pts').val((entry - price).toFixed(2));
    }
    $('#h_entry').trigger('input'); 
    
    // --- EXIT MULTIPLIER LOGIC FOR SIMULATOR ---
    let qty = parseInt($('#h_qty').val()) || 1;
    let pts = parseFloat($('#h_sl_pts').val()) || 0;
    let exitMult = parseInt($('#h_exit_mult').val()) || 1;
    let baseRatios = s.ratios || [0.5, 1.0, 1.5];
    let finalRatio = baseRatios[2];

    if(exitMult > 1) {
        let steps = Math.min(exitMult, 3);
        let ratioStep = finalRatio / steps;
        let lotsPerStep = Math.floor(qty / steps);
        let extraLots = qty % steps;

        for(let i=1; i<=3; i++) {
            if(i <= steps) {
                let targetPrice = entry + (pts * (ratioStep * i));
                $(`#h_t${i}`).val(targetPrice.toFixed(2));
                
                let thisLots = lotsPerStep;
                if(i === steps) thisLots += extraLots;
                
                $(`#h_check_t${i}`).prop('checked', true);
                $(`#h_lot_t${i}`).val(thisLots);
                $(`#h_full_t${i}`).prop('checked', false);
                
                // Update PnL display
                $(`#h_pnl_t${i}`).text(`₹ ${((targetPrice - entry) * thisLots).toFixed(0)}`);
            } else {
                $(`#h_check_t${i}`).prop('checked', false);
                $(`#h_lot_t${i}`).val('');
                $(`#h_t${i}`).val('');
                $(`#h_pnl_t${i}`).text('₹ 0');
            }
        }
    }
    // -------------------------------------------

    // Handle Full Checkbox UI
    ['t1', 't2', 't3'].forEach(k => {
        if ($(`#h_full_${k}`).is(':checked')) $(`#h_lot_${k}`).val(1000).prop('readonly', true);
        else $(`#h_lot_${k}`).prop('readonly', false);
    });
}

function calcSimManual(id) { 
    let val = parseFloat($('#h_' + id).val()) || 0; 
    let qty = parseInt($('#h_qty').val()) || 1; 
    let entry = parseFloat($('#h_entry').val()) || 0; 
    if (val > 0 && entry > 0) $('#h_pnl_' + id).text(`₹ ${((val - entry) * qty).toFixed(0)}`); 
}

window.checkHistory = function() {
    let entry = $('#h_entry').val(); if(!entry) { alert("Entry Price required!"); return; }
    let sVal = $('#h_sym').val(); if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    
    let d = {
        symbol: sVal, type:$('input[name="h_type"]:checked').val(), expiry:$('#h_exp').val(), 
        strike:$('#h_str').val(), time:$('#h_time').val(), 
        sl_points:$('#h_sl_pts').val(), qty:$('#h_qty').val(),
        entry_price: entry, 
        t1: $('#h_t1').val(), t2: $('#h_t2').val(), t3: $('#h_t3').val(),
        
        // New Fields for Trailing & Targets
        trailing_sl: $('#h_trail').val(),
        sl_to_entry: $('#h_sl_to_entry').val() === "1",
        exit_mult: $('#h_exit_mult').val(),
        target_controls: [
            { 
                enabled: $('#h_check_t1').is(':checked'), 
                lots: $('#h_full_t1').is(':checked') ? 1000 : (parseInt($('#h_lot_t1').val()) || 0) 
            },
            { 
                enabled: $('#h_check_t2').is(':checked'), 
                lots: $('#h_full_t2').is(':checked') ? 1000 : (parseInt($('#h_lot_t2').val()) || 0) 
            },
            { 
                enabled: $('#h_check_t3').is(':checked'), 
                lots: $('#h_full_t3').is(':checked') ? 1000 : (parseInt($('#h_lot_t3').val()) || 0) 
            }
        ]
    };
    
    $('#h_res').show().text("Simulating...");
    $.ajax({ type: "POST", url: '/api/history_check', data: JSON.stringify(d), contentType: "application/json", success: function(r) { if(r.status==='success') { $('#h_res').html(`<b class="text-success">${r.message}</b>`); setTimeout(() => { if(r.is_active) switchTab('pos'); else switchTab('closed'); }, 1500); } else $('#h_res').text(r.message); } });
};
