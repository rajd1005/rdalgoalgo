function loadSettings() {
    $.get('/api/settings/load', function(data) {
        if(data) {
            settings = data;
            if(settings.exchanges) {
                $('input[name="exch_select"]').prop('checked', false);
                settings.exchanges.forEach(e => $(`#exch_${e}`).prop('checked', true));
            }
            renderWatchlist();
            
            // --- Telegram Config Load ---
            let tg = settings.telegram || {};
            $('#tg_enabled').prop('checked', tg.enabled || false);
            $('#tg_token').val(tg.bot_token || '');
            
            // 1. Load Channels First (so DOM is ready for Forwarding Rules)
            $('#tg_channels_body').empty();
            let channels = tg.channels || [];
            channels.forEach(c => addChannelRow(c.name, c.chat_id, c.limit));
            
            // 2. Load Forwarding Rules
            $('#tg_forward_body').empty();
            let fwdRules = tg.forwarding_rules || [];
            fwdRules.forEach(r => addForwardRow(r.source_id, r.dest_id, r.trigger_event, r.delay, r.trigger_value, r.template));
            
            let events = tg.events || {};
            let tmpl = tg.templates || {};
            
            ['TRADE_ADDED', 'TRADE_UPDATE', 'TRADE_ACTIVATED', 'TARGET_HIT', 'MADE_HIGH', 'CLOSE_SUMMARY'].forEach(evt => {
                $(`#tg_evt_${evt}`).prop('checked', events[evt] !== false); 
                $(`#tg_tmpl_${evt}`).val(tmpl[evt] || '');
            });
            // ----------------------------

            ['PAPER', 'LIVE', 'SIMULATOR'].forEach(m => {
                let k = m === 'SIMULATOR' ? 'sim' : m.toLowerCase();
                let s = settings.modes[m];
                $(`#${k}_qty_mult`).val(s.qty_mult);
                $(`#${k}_r1`).val(s.ratios[0]);
                $(`#${k}_r2`).val(s.ratios[1]);
                $(`#${k}_r3`).val(s.ratios[2]);
                $(`#${k}_def_trail`).val(s.trailing_sl || 0);
                $(`#${k}_order_type`).val(s.order_type || 'MARKET');
                $(`#${k}_trail_limit`).val(s.sl_to_entry || 0);
                $(`#${k}_exit_mult`).val(s.exit_multiplier || 1);

                let tgts = s.targets || [
                    {active: true, lots: 0, full: false},
                    {active: true, lots: 0, full: false},
                    {active: true, lots: 1000, full: true}
                ];
                $(`#${k}_a1`).prop('checked', tgts[0].active);
                $(`#${k}_l1`).val(tgts[0].lots > 0 && !tgts[0].full ? tgts[0].lots : '');
                $(`#${k}_f1`).prop('checked', tgts[0].full);
                
                $(`#${k}_a2`).prop('checked', tgts[1].active);
                $(`#${k}_l2`).val(tgts[1].lots > 0 && !tgts[1].full ? tgts[1].lots : '');
                $(`#${k}_f2`).prop('checked', tgts[1].full);

                $(`#${k}_a3`).prop('checked', tgts[2].active);
                $(`#${k}_l3`).val(tgts[2].lots > 0 && !tgts[2].full ? tgts[2].lots : '');
                $(`#${k}_f3`).prop('checked', tgts[2].full);

                renderSLTable(m);
            });
            if (typeof updateDisplayValues === "function") updateDisplayValues(); 
        }
    });
}

// FIX: Read from DOM to ensure dropdowns see newly added (unsaved) channels
function getChannelOptions(selectedId) {
    let opts = '';
    $('#tg_channels_body tr').each(function() {
        let name = $(this).find('.tg-name').val();
        let id = $(this).find('.tg-cid').val();
        if(name && id) {
            let sel = (id == selectedId) ? 'selected' : '';
            opts += `<option value="${id}" ${sel}>${name}</option>`;
        }
    });
    return opts;
}

function addChannelRow(name='', cid='', limit=100) {
    let row = `<tr>
        <td><input type="text" class="form-control form-control-sm tg-name" placeholder="e.g. Free" value="${name}"></td>
        <td><input type="text" class="form-control form-control-sm tg-cid" placeholder="-100..." value="${cid}"></td>
        <td><input type="number" class="form-control form-control-sm tg-limit" placeholder="Max" value="${limit}"></td>
        <td class="text-center"><button class="btn btn-sm btn-outline-danger py-0" onclick="$(this).closest('tr').remove()">×</button></td>
    </tr>`;
    $('#tg_channels_body').append(row);
}

function addForwardRow(src='', dest='', trig='TRADE_ACTIVATED', delay=0, trigVal='ANY', tmpl='') {
    let chOpts = getChannelOptions(null); // Get fresh options from DOM
    let evtOpts = ['TRADE_ACTIVATED', 'TARGET_HIT', 'MADE_HIGH', 'CLOSE_SUMMARY'].map(e => `<option value="${e}" ${e===trig?'selected':''}>${e}</option>`).join('');
    
    let valOpts = `
        <option value="ANY" ${trigVal==='ANY'?'selected':''}>Any</option>
        <option value="1" ${trigVal==='1'?'selected':''}>Target 1</option>
        <option value="2" ${trigVal==='2'?'selected':''}>Target 2</option>
        <option value="3" ${trigVal==='3'?'selected':''}>Target 3</option>
    `;

    // Inject selection manually if IDs match
    let srcOpts = chOpts.replace(`value="${src}"`, `value="${src}" selected`);
    let destOpts = chOpts.replace(`value="${dest}"`, `value="${dest}" selected`);

    let row = `<tr>
        <td><select class="form-select form-select-sm tg-fwd-src">${srcOpts}</select></td>
        <td><select class="form-select form-select-sm tg-fwd-trig">${evtOpts}</select></td>
        <td><select class="form-select form-select-sm tg-fwd-val">${valOpts}</select></td>
        <td><select class="form-select form-select-sm tg-fwd-dest">${destOpts}</select></td>
        <td><textarea class="form-control form-control-sm tg-fwd-tmpl" rows="1" placeholder="Custom Msg...">${tmpl}</textarea></td>
        <td><input type="number" class="form-control form-control-sm tg-fwd-delay" value="${delay}" min="0" style="width:60px;"></td>
        <td class="text-center"><button class="btn btn-sm btn-outline-danger py-0" onclick="$(this).closest('tr').remove()">×</button></td>
    </tr>`;
    $('#tg_forward_body').append(row);
}

function saveSettings() {
    let selectedExchanges = [];
    $('input[name="exch_select"]:checked').each(function() { selectedExchanges.push($(this).val()); });
    settings.exchanges = selectedExchanges;

    // --- Telegram Config Save ---
    
    // 1. Capture Channels
    let channels = [];
    $('#tg_channels_body tr').each(function() {
        let name = $(this).find('.tg-name').val();
        let cid = $(this).find('.tg-cid').val();
        let limit = parseInt($(this).find('.tg-limit').val()) || 100;
        if(cid) channels.push({name: name, chat_id: cid, limit: limit});
    });

    // 2. Capture Forwarding Rules
    let rules = [];
    $('#tg_forward_body tr').each(function() {
        let src = $(this).find('.tg-fwd-src').val();
        let trig = $(this).find('.tg-fwd-trig').val();
        let trigVal = $(this).find('.tg-fwd-val').val();
        let dest = $(this).find('.tg-fwd-dest').val();
        let tmpl = $(this).find('.tg-fwd-tmpl').val();
        let delay = parseInt($(this).find('.tg-fwd-delay').val()) || 0;
        
        if(src && dest && src !== dest) {
            rules.push({
                source_id: src, 
                dest_id: dest, 
                trigger_event: trig, 
                trigger_value: trigVal,
                template: tmpl,
                delay: delay
            });
        }
    });

    if (!settings.telegram) settings.telegram = {};
    settings.telegram.enabled = $('#tg_enabled').is(':checked');
    settings.telegram.bot_token = $('#tg_token').val().trim();
    settings.telegram.channels = channels;
    settings.telegram.forwarding_rules = rules;
    
    if(!settings.telegram.events) settings.telegram.events = {};
    if(!settings.telegram.templates) settings.telegram.templates = {};

    ['TRADE_ADDED', 'TRADE_UPDATE', 'TRADE_ACTIVATED', 'TARGET_HIT', 'MADE_HIGH', 'CLOSE_SUMMARY'].forEach(evt => {
        settings.telegram.events[evt] = $(`#tg_evt_${evt}`).is(':checked');
        settings.telegram.templates[evt] = $(`#tg_tmpl_${evt}`).val();
    });
    // ----------------------------

    ['PAPER', 'LIVE', 'SIMULATOR'].forEach(m => {
        let k = m === 'SIMULATOR' ? 'sim' : m.toLowerCase();
        let s = settings.modes[m];
        
        s.qty_mult = parseInt($(`#${k}_qty_mult`).val()) || 1;
        s.ratios = [parseFloat($(`#${k}_r1`).val()), parseFloat($(`#${k}_r2`).val()), parseFloat($(`#${k}_r3`).val())];
        s.trailing_sl = parseFloat($(`#${k}_def_trail`).val()) || 0;
        s.order_type = $(`#${k}_order_type`).val();
        s.sl_to_entry = parseInt($(`#${k}_trail_limit`).val()) || 0;
        s.exit_multiplier = parseInt($(`#${k}_exit_mult`).val()) || 1;
        s.targets = [
            {
                active: $(`#${k}_a1`).is(':checked'),
                full: $(`#${k}_f1`).is(':checked'),
                lots: $(`#${k}_f1`).is(':checked') ? 1000 : (parseInt($(`#${k}_l1`).val()) || 0)
            },
            {
                active: $(`#${k}_a2`).is(':checked'),
                full: $(`#${k}_f2`).is(':checked'),
                lots: $(`#${k}_f2`).is(':checked') ? 1000 : (parseInt($(`#${k}_l2`).val()) || 0)
            },
            {
                active: $(`#${k}_a3`).is(':checked'),
                full: $(`#${k}_f3`).is(':checked'),
                lots: $(`#${k}_f3`).is(':checked') ? 1000 : (parseInt($(`#${k}_l3`).val()) || 0)
            }
        ];
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
