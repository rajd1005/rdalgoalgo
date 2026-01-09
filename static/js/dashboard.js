let settings = { 
    exchanges: ['NSE', 'NFO', 'MCX', 'CDS', 'BSE', 'BFO'],
    watchlist: [],
    modes: {
        LIVE: {qty_mult: 1, ratios: [0.5, 1.0, 1.5], symbol_sl: {}},
        PAPER: {qty_mult: 1, ratios: [0.5, 1.0, 1.5], symbol_sl: {}},
        SIMULATOR: {qty_mult: 1, ratios: [0.5, 1.0, 1.5], symbol_sl: {}}
    }
};

let curLotSize = 1;
let symLTP = {}; 
let activeTradesList = []; 
let allClosedTrades = [];
let curLTP = 0;

// Aggressive Normalization
function normalizeSymbol(s) {
    if(!s) return "";
    s = s.toUpperCase().trim();
    if(s.includes('(')) s = s.split('(')[0].trim();
    if(s.includes(':')) s = s.split(':')[0].trim();
    
    if(['NIFTY', 'NIFTY 50', 'NIFTY50'].includes(s)) return 'NIFTY';
    if(['BANKNIFTY', 'NIFTY BANK', 'BANK NIFTY'].includes(s)) return 'BANKNIFTY';
    if(['FINNIFTY', 'NIFTY FIN SERVICE'].includes(s)) return 'FINNIFTY';
    if(['SENSEX', 'BSE SENSEX'].includes(s)) return 'SENSEX';
    return s;
}

$(document).ready(function() {
    renderWatchlist();
    loadSettings();
    
    let now = new Date(); const offset = now.getTimezoneOffset(); let localDate = new Date(now.getTime() - (offset*60*1000));
    $('#hist_date').val(localDate.toISOString().slice(0,10)); $('#h_time').val(localDate.toISOString().slice(0,16));
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
    setInterval(updateClock, 1000); updateClock();
    setInterval(updateData, 1000); updateData();
});

function loadSettings() {
    $.get('/api/settings/load', function(data) {
        if(data) {
            settings = data;
            if(settings.exchanges) {
                $('input[name="exch_select"]').prop('checked', false);
                settings.exchanges.forEach(e => $(`#exch_${e}`).prop('checked', true));
            }
            renderWatchlist();
            ['PAPER', 'LIVE', 'SIMULATOR'].forEach(m => {
                let k = m === 'SIMULATOR' ? 'sim' : m.toLowerCase();
                let s = settings.modes[m];
                $(`#${k}_qty_mult`).val(s.qty_mult);
                $(`#${k}_r1`).val(s.ratios[0]);
                $(`#${k}_r2`).val(s.ratios[1]);
                $(`#${k}_r3`).val(s.ratios[2]);
                renderSLTable(m);
            });
            updateDisplayValues(); 
        }
    });
}

function saveSettings() {
    let selectedExchanges = [];
    $('input[name="exch_select"]:checked').each(function() { selectedExchanges.push($(this).val()); });
    settings.exchanges = selectedExchanges;

    ['PAPER', 'LIVE', 'SIMULATOR'].forEach(m => {
        let k = m === 'SIMULATOR' ? 'sim' : m.toLowerCase();
        settings.modes[m].qty_mult = parseInt($(`#${k}_qty_mult`).val()) || 1;
        settings.modes[m].ratios = [parseFloat($(`#${k}_r1`).val()), parseFloat($(`#${k}_r2`).val()), parseFloat($(`#${k}_r3`).val())];
    });

    $.ajax({ type: "POST", url: '/api/settings/save', data: JSON.stringify(settings), contentType: "application/json", success: () => { $('#settingsModal').modal('hide'); loadSettings(); } });
}

function renderWatchlist() {
    let wl = settings.watchlist || [];
    let opts = '<option value="">📺 Select</option>';
    wl.forEach(w => { opts += `<option value="${w}">${w}</option>`; });
    $('#trade_watch').html(opts);
    $('#sim_watch').html(opts);
}

function addToWatchlist(inputId) {
    let val = $(inputId).val();
    if(val && val.length > 2) {
        if(val.includes('(')) val = val.split('(')[0].trim();
        else if(val.includes(':')) val = val.split(':')[0].trim();
        
        if(!settings.watchlist) settings.watchlist = [];
        if(!settings.watchlist.includes(val)) {
            settings.watchlist.push(val);
            $.ajax({ type: "POST", url: '/api/settings/save', data: JSON.stringify(settings), contentType: "application/json", success: () => { 
                renderWatchlist();
                let btn = $(inputId).next(); let originalText = btn.text(); btn.text("✅"); setTimeout(() => btn.text(originalText), 1000);
            }});
        } else { alert("Symbol already in Watchlist"); }
    }
}

function removeFromWatchlist(selectId) {
    let val = $('#' + selectId).val();
    if(val) {
        if(confirm("Remove " + val + " from watchlist?")) {
            settings.watchlist = settings.watchlist.filter(item => item !== val);
            $.ajax({ type: "POST", url: '/api/settings/save', data: JSON.stringify(settings), contentType: "application/json", success: () => { 
                renderWatchlist();
            }});
        }
    }
}

function loadWatchlist(selectId, inputId) {
    let val = $('#' + selectId).val();
    if(val) {
        $(inputId).val(val).trigger('change');
        $(inputId).trigger('input'); 
    }
}

function applyBulkSL(mode) {
    let k = mode === 'SIMULATOR' ? 'sim' : mode.toLowerCase();
    let text = $(`#${k}_bulk_sl`).val();
    if(!text) { alert("Please enter SYMBOL|SL"); return; }
    let lines = text.split('\n'); let count = 0;
    if(!settings.modes[mode].symbol_sl) settings.modes[mode].symbol_sl = {};
    lines.forEach(l => {
        let parts = l.split('|');
        if(parts.length === 2) {
            let s = normalizeSymbol(parts[0]); let v = parseInt(parts[1].trim());
            if(s && v > 0) { settings.modes[mode].symbol_sl[s] = v; count++; }
        }
    });
    renderSLTable(mode); $(`#${k}_bulk_sl`).val('');
    alert(`Successfully updated ${count} symbols for ${mode}. Click Save Changes.`);
}

function renderSLTable(mode) {
    let k = mode === 'SIMULATOR' ? 'sim' : mode.toLowerCase();
    let tbody = $(`#${k}_sl_table_body`).empty();
    let slMap = settings.modes[mode].symbol_sl || {};
    Object.keys(slMap).forEach(sym => {
        tbody.append(`<tr><td class="fw-bold">${sym}</td><td>${slMap[sym]}</td><td><button class="btn btn-sm btn-outline-secondary py-0" onclick="editSymSL('${mode}', '${sym}')">✏️</button> <button class="btn btn-sm btn-outline-danger py-0" onclick="deleteSymSL('${mode}', '${sym}')">🗑️</button></td></tr>`);
    });
}

function saveSymSL(mode) {
    let k = mode === 'SIMULATOR' ? 'sim' : mode.toLowerCase();
    let s = normalizeSymbol($(`#${k}_set_sym`).val());
    let p = parseInt($(`#${k}_set_sl`).val());
    if(s && p) {
        if(!settings.modes[mode].symbol_sl) settings.modes[mode].symbol_sl = {};
        settings.modes[mode].symbol_sl[s] = p;
        renderSLTable(mode);
        $(`#${k}_set_sym`).val(''); $(`#${k}_set_sl`).val('');
    }
}
function editSymSL(mode, sym) { let k = mode === 'SIMULATOR' ? 'sim' : mode.toLowerCase(); $(`#${k}_set_sym`).val(sym); $(`#${k}_set_sl`).val(settings.modes[mode].symbol_sl[sym]); }
function deleteSymSL(mode, sym) { delete settings.modes[mode].symbol_sl[sym]; renderSLTable(mode); }

function updateDisplayValues() {
    let mode = 'PAPER';
    if ($('#history').is(':visible')) mode = 'SIMULATOR';
    else mode = $('#mode_input').val(); 
    
    let s = settings.modes[mode]; if(!s) return;
    $('#qty_mult_disp').text(s.qty_mult); $('#h_qty_mult').text(settings.modes.SIMULATOR.qty_mult);
    $('#r_t1').text(s.ratios[0]); $('#hr_t1').text(settings.modes.SIMULATOR.ratios[0]);
    $('#r_t2').text(s.ratios[1]); $('#hr_t2').text(settings.modes.SIMULATOR.ratios[1]);
    $('#r_t3').text(s.ratios[2]); $('#hr_t3').text(settings.modes.SIMULATOR.ratios[2]);
    calcRisk();
    if ($('#history').is(':visible')) { let entry = parseFloat($('#h_entry').val()) || 0; if (entry > 0) $('#h_entry').trigger('input'); }
}

function switchTab(id) { 
    $('.dashboard-tab').hide(); $(`#${id}`).show(); 
    $('.nav-btn').removeClass('active'); $(event.target).addClass('active'); 
    if(id==='closed') loadClosedTrades(); 
    updateDisplayValues(); 
    if(id === 'trade') $('.sticky-footer').show(); else $('.sticky-footer').hide();
}

function setMode(el, mode) { $('#mode_input').val(mode); $(el).parent().find('.btn').removeClass('active'); $(el).addClass('active'); updateDisplayValues(); loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'); }

function getTradeCategory(t) { if (t.order_type === 'SIMULATION') return 'SIMULATOR'; if (t.mode === 'LIVE') return 'LIVE'; return 'PAPER'; }
function getMarkBadge(category) { if (category === 'SIMULATOR') return '<span class="badge bg-info text-dark" style="font-size:0.7rem;">SIM</span>'; if (category === 'LIVE') return '<span class="badge bg-danger" style="font-size:0.7rem;">LIVE</span>'; return '<span class="badge bg-warning text-dark" style="font-size:0.7rem;">PAPER</span>'; }

// --- Active Trades Logic ---
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

function updateClock() { $('#live_clock').text(new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true })); }

function showLogs(tradeId, type) {
    let trade = (type === 'active') ? activeTradesList.find(x => x.id == tradeId) : allClosedTrades.find(x => x.id == tradeId);
    if (trade && trade.logs) { $('#logModalBody').html(trade.logs.map(l => `<div class="log-entry">${l}</div>`).join('')); new bootstrap.Modal(document.getElementById('logModal')).show(); } else alert("No logs available.");
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

// --- Closed Trades Logic ---
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

function deleteTrade(id) { if(confirm("Delete trade?")) $.post('/api/delete_trade/' + id, r => { if(r.status === 'success') loadClosedTrades(); else alert('Failed to delete'); }); }
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

function bindSearch(id, listId) { $(id).on('input', function() { if(this.value.length>1) $.get('/api/search?q='+this.value, d => { $(listId).empty(); d.forEach(s=>$(listId).append(`<option value="${s}">`)) }); }); }
bindSearch('#sym', '#sym_list'); bindSearch('#h_sym', '#h_sym_list');

function loadDetails(symId, expId, typeSelector, qtyId, slId) {
    let s = $(symId).val(); if(!s) return;
    
    let settingsKey = normalizeSymbol(s);
    let mode = 'PAPER';
    if (symId === '#h_sym' || $('#history').is(':visible')) mode = 'SIMULATOR'; 
    else mode = $('#mode_input').val();
    
    let modeSettings = settings.modes[mode] || settings.modes.PAPER;
    let savedSL = (modeSettings.symbol_sl && modeSettings.symbol_sl[settingsKey]) || 20;
    $(slId).val(savedSL);
    
    if(mode === 'SIMULATOR') calcSimSL('pts'); 
    else calcRisk();

    $.get('/api/details?symbol='+s, d => { 
        symLTP[symId] = d.ltp; 
        if(d.lot_size > 0) {
            curLotSize = d.lot_size;
            $('#lot').text(curLotSize); 
            let mult = parseInt(modeSettings.qty_mult) || 1;
            $(qtyId).val(curLotSize * mult).attr('step', curLotSize).attr('min', curLotSize);
        }
        window[symId+'_fut'] = d.fut_expiries; window[symId+'_opt'] = d.opt_expiries;
        
        let typeVal = $(typeSelector).val();
        if (typeVal) {
            fillExp(expId, typeSelector, symId);
        } else {
            $(expId).empty();
            let strId = (expId === '#exp') ? '#str' : '#h_str';
            $(strId).empty().append('<option>Select Type First</option>');
        }
    });
}

function adjQty(inputId, dir) {
    let val = parseInt($(inputId).val()) || curLotSize;
    let step = curLotSize;
    let newVal = val + (dir * step);
    if(newVal >= step) {
        $(inputId).val(newVal).trigger('input');
    }
}

$('#sym').change(() => loadDetails('#sym', '#exp', 'input[name="type"]:checked', '#qty', '#sl_pts'));
$('#h_sym').change(() => loadDetails('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_qty', '#h_sl_pts'));

function fillExp(expId, typeSelector, symId) { 
    let typeVal = $(typeSelector).val();
    let l = typeVal=='FUT' ? window[symId+'_fut'] : window[symId+'_opt']; 
    let $e = $(expId).empty(); if(l) l.forEach(d => $e.append(`<option value="${d}">${d}</option>`)); 
    if(expId === '#exp') fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str');
    if(expId === '#h_exp') fillChain('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_str');
}

function fillChain(sym, exp, typeSelector, str) {
    let spot = symLTP[sym] || 0; let sVal = $(sym).val(); if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    $.get(`/api/chain?symbol=${sVal}&expiry=${$(exp).val()}&type=${$(typeSelector).val()}&ltp=${spot}`, d => {
        let $s = $(str).empty(); 
        d.forEach(r => { let mark = r.label.includes('ATM') ? '🔴' : ''; let style = r.label.includes('ATM') ? 'style="color:red; font-weight:bold;"' : ''; let selected = r.label.includes('ATM') ? 'selected' : ''; $s.append(`<option value="${r.strike}" ${selected} ${style}>${mark} ${r.strike} ${r.label}</option>`); });
        if(str === '#str') fetchLTP();
    });
}
$('#exp').change(() => fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str'));
$('#h_exp').change(() => fillChain('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_str'));
$('#ord').change(function() { if($(this).val() === 'LIMIT') $('#lim_box').show(); else $('#lim_box').hide(); });
$('#str').change(fetchLTP);

function fetchLTP() {
    let sVal = $('#sym').val(); if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    $.get(`/api/specific_ltp?symbol=${sVal}&expiry=${$('#exp').val()}&strike=${$('#str').val()}&type=${$('input[name="type"]:checked').val()}`, d => {
        curLTP=d.ltp; $('#inst_ltp').text("LTP: "+curLTP); if ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() == "") $('#lim_pr').val(curLTP);
        calcRisk();
    });
}

function calcSLPriceFromPts(ptsId, priceId) {
    let pts = parseFloat($(ptsId).val()) || 0;
    let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP;
    if(basePrice > 0) {
        let price = basePrice - pts;
        $(priceId).val(price.toFixed(2));
        calcRisk();
    }
}

function calcSLPtsFromPrice(priceId, ptsId) {
    let price = parseFloat($(priceId).val()) || 0;
    let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP;
    if(basePrice > 0 && price > 0) {
        let pts = basePrice - price;
        $(ptsId).val(pts.toFixed(2));
        calcRisk();
    }
}

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

function calcPnl(id) { let val = parseFloat($('#p_' + id).val()) || 0; let qty = parseInt($('#qty').val()) || 1; let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP; if (val > 0) $('#pnl_' + id).text(`₹ ${((val - basePrice) * qty).toFixed(0)}`); }
function calcSimManual(id) { let val = parseFloat($('#h_' + id).val()) || 0; let qty = parseInt($('#h_qty').val()) || 1; let entry = parseFloat($('#h_entry').val()) || 0; if (val > 0 && entry > 0) $('#h_pnl_' + id).text(`₹ ${((val - entry) * qty).toFixed(0)}`); }

function calcRisk() {
    let p = parseFloat($('#sl_pts').val())||0; let qty = parseInt($('#qty').val())||1;
    let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP;
    
    if (document.activeElement.id !== 'p_sl') {
            let calculatedPrice = basePrice - p;
            if(basePrice > 0) $('#p_sl').val(calculatedPrice.toFixed(2));
    }

    let mode = $('#mode_input').val(); let ratios = settings.modes[mode].ratios;
    let sl = basePrice - p;
    let t1 = basePrice + p * ratios[0]; let t2 = basePrice + p * ratios[1]; let t3 = basePrice + p * ratios[2];

    if (!document.activeElement || !['p_t1', 'p_t2', 'p_t3'].includes(document.activeElement.id)) {
            $('#p_t1').val(t1.toFixed(2)); $('#p_t2').val(t2.toFixed(2)); $('#p_t3').val(t3.toFixed(2));
            $('#pnl_t1').text(`₹ ${((t1-basePrice)*qty).toFixed(0)}`); $('#pnl_t2').text(`₹ ${((t2-basePrice)*qty).toFixed(0)}`); $('#pnl_t3').text(`₹ ${((t3-basePrice)*qty).toFixed(0)}`);
    }
    $('#pnl_sl').text(`₹ ${((sl-basePrice)*qty).toFixed(0)}`);
}

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

window.checkHistory = function() {
    let entry = $('#h_entry').val(); if(!entry) { alert("Entry Price required!"); return; }
    let sVal = $('#h_sym').val(); if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    let d = {
        symbol: sVal, type:$('input[name="h_type"]:checked').val(), expiry:$('#h_exp').val(), 
        strike:$('#h_str').val(), time:$('#h_time').val(), 
        sl_points:$('#h_sl_pts').val(), qty:$('#h_qty').val(),
        entry_price: entry, t1: $('#h_t1').val(), t2: $('#h_t2').val(), t3: $('#h_t3').val()
    };
    $('#h_res').show().text("Simulating...");
    $.ajax({ type: "POST", url: '/api/history_check', data: JSON.stringify(d), contentType: "application/json", success: function(r) { if(r.status==='success') { $('#h_res').html(`<b class="text-success">${r.message}</b>`); setTimeout(() => { if(r.is_active) switchTab('pos'); else switchTab('closed'); }, 1500); } else $('#h_res').text(r.message); } });
};
