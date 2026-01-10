function calcSimSL(source) {
    let entry = parseFloat($('#h_entry').val()) || 0;
    if(entry <= 0) return;
    
    if(source === 'pts') {
        let pts = parseFloat($('#h_sl_pts').val()) || 0;
        $('#h_p_sl').val((entry - pts).toFixed(2));
    } else {
        let price = parseFloat($('#h_p_sl').val()) || 0;
        $('#h_sl_pts').val((entry - price).toFixed(2));
    }
    $('#h_entry').trigger('input'); 
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
        target_controls: [
            { enabled: $('#h_check_t1').is(':checked'), lots: parseInt($('#h_lot_t1').val()) || 0 },
            { enabled: $('#h_check_t2').is(':checked'), lots: parseInt($('#h_lot_t2').val()) || 0 },
            { enabled: $('#h_check_t3').is(':checked'), lots: parseInt($('#h_lot_t3').val()) || 1000 } // Default T3 exits all (1000)
        ]
    };
    
    $('#h_res').show().text("Simulating...");
    $.ajax({ type: "POST", url: '/api/history_check', data: JSON.stringify(d), contentType: "application/json", success: function(r) { if(r.status==='success') { $('#h_res').html(`<b class="text-success">${r.message}</b>`); setTimeout(() => { if(r.is_active) switchTab('pos'); else switchTab('closed'); }, 1500); } else $('#h_res').text(r.message); } });
};
