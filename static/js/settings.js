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
            if (typeof updateDisplayValues === "function") updateDisplayValues(); 
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

    $.ajax({ 
        type: "POST", 
        url: '/api/settings/save', 
        data: JSON.stringify(settings), 
        contentType: "application/json", 
        success: () => { $('#settingsModal').modal('hide'); loadSettings(); } 
    });
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
            $.ajax({ 
                type: "POST", 
                url: '/api/settings/save', 
                data: JSON.stringify(settings), 
                contentType: "application/json", 
                success: () => { 
                    renderWatchlist();
                    let btn = $(inputId).next(); let originalText = btn.text(); btn.text("✅"); setTimeout(() => btn.text(originalText), 1000);
                }
            });
        } else { alert("Symbol already in Watchlist"); }
    }
}

function removeFromWatchlist(selectId) {
    let val = $('#' + selectId).val();
    if(val) {
        if(confirm("Remove " + val + " from watchlist?")) {
            settings.watchlist = settings.watchlist.filter(item => item !== val);
            $.ajax({ type: "POST", url: '/api/settings/save', data: JSON.stringify(settings), contentType: "application/json", success: () => { renderWatchlist(); }});
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
