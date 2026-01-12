$(document).ready(function() {
    renderWatchlist();
    loadSettings();
    
    let now = new Date(); const offset = now.getTimezoneOffset(); let localDate = new Date(now.getTime() - (offset*60*1000));
    $('#hist_date').val(localDate.toISOString().slice(0,10)); 
    
    // Global Bindings
    $('#hist_date, #hist_filter').change(loadClosedTrades);
    $('#active_filter').change(fetchPositions);
    
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
    }, 4000);

    // Loops
    setInterval(updateClock, 1000); updateClock();
    setInterval(fetchPositions, 1000); 
    setInterval(fetchMarketData, 2000); fetchMarketData(); // Added Ticker Loop
});

// --- 1. TICKER UPDATE ---
function fetchMarketData() {
    $.get('/api/market_status', function(data) {
        if(data.NIFTY > 0) {
            $('#n_lp').text(data.NIFTY.toFixed(2));
            $('#n_lp').removeClass('text-warning').addClass('text-success');
        }
        if(data.BANKNIFTY > 0) {
            $('#b_lp').text(data.BANKNIFTY.toFixed(2));
            $('#b_lp').removeClass('text-warning').addClass('text-success');
        }
    });
}

// --- 2. POSITIONS UPDATE ---
function fetchPositions() {
    $.get('/api/positions', function(trades) {
        if(typeof updateActiveTab === "function") {
            updateActiveTab(trades);
        }
    });
}

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
