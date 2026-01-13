$(document).ready(function() {
    renderWatchlist();
    loadSettings();
    
    let now = new Date(); const offset = now.getTimezoneOffset(); let localDate = new Date(now.getTime() - (offset*60*1000));
    $('#hist_date').val(localDate.toISOString().slice(0,10)); 
    
    // Global Bindings
    $('#hist_date, #hist_filter').change(loadClosedTrades);
    $('#active_filter').change(updateData);
    
    $('input[name="type"]').change(function() {
        let s = $('#sym').val();
        if(s) loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts');
    });
    
    $('#sl_pts, #qty, #lim_pr, #ord').on('input change', calcRisk);
    
    // Bind Search Logic
    bindSearch('#sym', '#sym_list'); 
    
    // Chain & input Bindings
    $('#sym').change(() => loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'));
    $('#exp').change(() => fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str'));
    $('#ord').change(function() { if($(this).val() === 'LIMIT') $('#lim_box').show(); else $('#lim_box').hide(); });
    
    $('#str').change(fetchLTP);

    // Auto-Remove Floating Notifications
    setTimeout(function() {
        $('.floating-alert').fadeOut('slow', function() {
            $(this).remove();
        });
    }, 4000); // 4 seconds before auto removal

    // Loops
    setInterval(updateClock, 1000); updateClock();
    setInterval(updateData, 1000); updateData();
});

function updateDisplayValues() {
    let mode = $('#mode_input').val(); 
    
    let s = settings.modes[mode]; if(!s) return;
    $('#qty_mult_disp').text(s.qty_mult); 
    $('#r_t1').text(s.ratios[0]); 
    $('#r_t2').text(s.ratios[1]); 
    $('#r_t3').text(s.ratios[2]); 
    
    if(typeof calcRisk === "function") calcRisk();
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

// --- NEW FUNCTION: PANIC TRIGGER ---
function triggerPanic() {
    if(confirm("🚨 ARE YOU SURE? \n\nThis will CLOSE ALL ACTIVE POSITIONS and CANCEL ALL PENDING ORDERS immediately.")) {
        $.post('/api/panic_squareoff', function(res) {
            if(res.status === 'success') {
                alert("✅ SUCCESS: All positions have been squared off.");
                location.reload();
            } else {
                alert("❌ Error: " + res.message);
            }
        });
    }
}

// --- RESTORED FUNCTION: Update Data Loop ---
function updateData() {
    // 1. Fetch Indices
    $.get('/api/indices', function(data) {
        $('#n_lp').text(data.NIFTY.toFixed(2));
        $('#b_lp').text(data.BANKNIFTY.toFixed(2));
        $('#s_lp').text(data.SENSEX.toFixed(2));
    });

    // 2. Fetch and Render Positions
    $.get('/api/positions', function(trades) {
        activeTradesList = trades; // Update global variable

        let liveTotal = 0; 
        let paperTotal = 0;
        
        trades.forEach(t => {
            let pnl = 0;
            if(t.current_ltp > 0) {
                 pnl = (t.current_ltp - t.entry_price) * t.quantity;
            }
            if(t.mode === 'LIVE') liveTotal += pnl;
            else paperTotal += pnl;
        });

        // Update P&L Cards
        $('#sum_live').text("₹ " + liveTotal.toFixed(2));
        if(liveTotal >= 0) $('#sum_live').removeClass('text-danger').addClass('text-success');
        else $('#sum_live').removeClass('text-success').addClass('text-danger');

        $('#sum_paper').text("₹ " + paperTotal.toFixed(2));
        if(paperTotal >= 0) $('#sum_paper').removeClass('text-danger').addClass('text-success');
        else $('#sum_paper').removeClass('text-success').addClass('text-danger');

        // Apply Filter and Render
        let filter = $('#active_filter').val();
        let filteredTrades = trades.filter(t => filter === 'ALL' || t.mode === filter);
        
        if(typeof renderActiveTrades === 'function') {
            renderActiveTrades(filteredTrades);
        }
    });

    // 3. Status Check
    $.get('/api/status', function(res) {
        if (!res.active) {
            console.log("Session expired, reloading...");
            location.reload(); 
        }
    });
}
