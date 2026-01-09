$(document).ready(function() {
    renderWatchlist();
    loadSettings();
    
    let now = new Date(); const offset = now.getTimezoneOffset(); let localDate = new Date(now.getTime() - (offset*60*1000));
    $('#hist_date').val(localDate.toISOString().slice(0,10)); $('#h_time').val(localDate.toISOString().slice(0,16));
    
    // Global Bindings
    $('#hist_date, #hist_filter').change(loadClosedTrades);
    $('#active_filter').change(updateData);
    
    $('input[name="type"]').change(function() {
        let s = $('#sym').val();
        if(s) loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts');
    });
    $('input[name="h_type"]').change(function() {
        let s = $('#h_sym').val();
        if(s) loadDetails('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_qty', '#h_sl_pts');
    });
    
    $('#sl_pts, #qty, #lim_pr, #ord').on('input change', calcRisk);
    
    // Bind Search Logic
    bindSearch('#sym', '#sym_list'); 
    bindSearch('#h_sym', '#h_sym_list');
    
    // Simulator Real-time calc
    $('#h_entry, #h_sl_pts, #h_qty').on('input', function() {
        let entry = parseFloat($('#h_entry').val()) || 0; let pts = parseFloat($('#h_sl_pts').val()) || 0; let qty = parseInt($('#h_qty').val()) || 1; let ratios = settings.modes.SIMULATOR.ratios;
        if(entry > 0) {
            let sl = entry - pts; $('#h_pnl_sl').text(`₹ ${((sl-entry)*qty).toFixed(0)}`);
            if (!document.activeElement || !['h_t1', 'h_t2', 'h_t3'].includes(document.activeElement.id)) {
                let t1 = entry + pts * ratios[0]; let t2 = entry + pts * ratios[1]; let t3 = entry + pts * ratios[2];
                $('#h_t1').val(t1.toFixed(2)); $('#h_t2').val(t2.toFixed(2)); $('#h_t3').val(t3.toFixed(2));
                $('#h_pnl_t1').text(`₹ ${((t1-entry)*qty).toFixed(0)}`); $('#h_pnl_t2').text(`₹ ${((t2-entry)*qty).toFixed(0)}`); $('#h_pnl_t3').text(`₹ ${((t3-entry)*qty).toFixed(0)}`);
            }
        }
    });
    
    // Chain & input Bindings
    $('#sym').change(() => loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'));
    $('#h_sym').change(() => loadDetails('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_qty', '#h_sl_pts'));
    $('#exp').change(() => fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str'));
    $('#h_exp').change(() => fillChain('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_str'));
    $('#ord').change(function() { if($(this).val() === 'LIMIT') $('#lim_box').show(); else $('#lim_box').hide(); });
    $('#str').change(fetchLTP);

    // Loops
    setInterval(updateClock, 1000); updateClock();
    setInterval(updateData, 1000); updateData();
});

function updateDisplayValues() {
    let mode = 'PAPER';
    if ($('#history').is(':visible')) mode = 'SIMULATOR';
    else mode = $('#mode_input').val(); 
    
    let s = settings.modes[mode]; if(!s) return;
    $('#qty_mult_disp').text(s.qty_mult); $('#h_qty_mult').text(settings.modes.SIMULATOR.qty_mult);
    $('#r_t1').text(s.ratios[0]); $('#hr_t1').text(settings.modes.SIMULATOR.ratios[0]);
    $('#r_t2').text(s.ratios[1]); $('#hr_t2').text(settings.modes.SIMULATOR.ratios[1]);
    $('#r_t3').text(s.ratios[2]); $('#hr_t3').text(settings.modes.SIMULATOR.ratios[2]);
    
    if(typeof calcRisk === "function") calcRisk();
    
    if ($('#history').is(':visible')) { let entry = parseFloat($('#h_entry').val()) || 0; if (entry > 0) $('#h_entry').trigger('input'); }
}

function switchTab(id) { 
    $('.dashboard-tab').hide(); $(`#${id}`).show(); 
    $('.nav-btn').removeClass('active'); $(event.target).addClass('active'); 
    if(id==='closed') loadClosedTrades(); 
    updateDisplayValues(); 
    if(id === 'trade') $('.sticky-footer').show(); else $('.sticky-footer').hide();
}

function setMode(el, mode) { 
    $('#mode_input').val(mode); 
    $(el).parent().find('.btn').removeClass('active'); 
    $(el).addClass('active'); 
    updateDisplayValues(); 
    loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'); 
}
