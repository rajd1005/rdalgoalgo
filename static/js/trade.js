function loadDetails(symId, expId, typeSelector, qtyId, slId) {
    let s = $(symId).val(); if(!s) return;
    
    let settingsKey = normalizeSymbol(s);
    let mode = 'PAPER'; // Default
    
    // Determine context
    if (symId === '#h_sym' || $('#history').is(':visible')) mode = 'SIMULATOR'; 
    else if (symId === '#imp_sym') mode = 'PAPER'; // FORCE PAPER FOR IMPORT
    else mode = $('#mode_input').val();
    
    let modeSettings = settings.modes[mode] || settings.modes.PAPER;
    
    // Auto-fill SL if field exists
    if(slId) {
        let savedSL = (modeSettings.symbol_sl && modeSettings.symbol_sl[settingsKey]) || 20;
        $(slId).val(savedSL);
    }
    
    // Auto-fill Settings (Trailing, Order Type, Exit Mult)
    if(mode === 'SIMULATOR') {
        // Simulator specific logic if any
    } else {
        let prefix = (symId === '#imp_sym') ? '#imp_' : '#'; // Detect import modal prefix
        let trailVal = modeSettings.trailing_sl || '';
        
        // Handle Prefixing for shared IDs or unique Import IDs
        if(prefix === '#imp_') {
             $('#imp_trail_sl').val(trailVal);
             $('#imp_trail_limit').val(modeSettings.sl_to_entry || 0);
             $('#imp_exit_mult').val(modeSettings.exit_multiplier || 1);
             
             // Populate Import Target Controls (Active/Full/Lots)
             if(modeSettings.targets) {
                ['t1', 't2', 't3'].forEach((k, i) => {
                    let conf = modeSettings.targets[i];
                    $(`#imp_${k}_active`).prop('checked', conf.active);
                    $(`#imp_${k}_full`).prop('checked', conf.full);
                    if(conf.full) $(`#imp_${k}_lots`).val(1000);
                    else $(`#imp_${k}_lots`).val(conf.lots > 0 ? conf.lots : '');
                });
             }
        } else {
             // Standard Trade Tab
             $('#trail_sl').val(trailVal);
             $('#ord').val(modeSettings.order_type || 'MARKET').trigger('change');
             $('select[name="sl_to_entry"]').val(modeSettings.sl_to_entry || 0);
             $('#exit_mult').val(modeSettings.exit_multiplier || 1);
             
             if(modeSettings.targets) {
                ['t1', 't2', 't3'].forEach((k, i) => {
                    let conf = modeSettings.targets[i];
                    $(`#${k}_active`).prop('checked', conf.active);
                    $(`#${k}_full`).prop('checked', conf.full);
                    if(conf.full) $(`#${k}_lots`).val(1000);
                    else $(`#${k}_lots`).val(conf.lots > 0 ? conf.lots : '');
                });
             }
        }
    }
    
    if(mode === 'SIMULATOR') calcSimSL('pts'); 
    else if (symId !== '#imp_sym') calcRisk(); // Only calc risk on main tab immediately

    $.get('/api/details?symbol='+s, d => { 
        symLTP[symId] = d.ltp; 
        if(d.lot_size > 0) {
            curLotSize = d.lot_size;
            if(symId !== '#imp_sym') $('#lot').text(curLotSize); 
            
            let mult = parseInt(modeSettings.qty_mult) || 1;
            $(qtyId).val(curLotSize * mult).attr('step', curLotSize).attr('min', curLotSize);
        }
        window[symId+'_fut'] = d.fut_expiries; window[symId+'_opt'] = d.opt_expiries;
        
        let typeVal = $(typeSelector).val();
        if (typeVal) {
            fillExp(expId, typeSelector, symId);
        } else {
            $(expId).empty();
            let strId = (expId === '#exp') ? '#str' : (expId === '#imp_exp' ? '#imp_str' : '#h_str');
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

function fillExp(expId, typeSelector, symId) { 
    let typeVal = $(typeSelector).val();
    let l = typeVal=='FUT' ? window[symId+'_fut'] : window[symId+'_opt']; 
    let $e = $(expId).empty(); if(l) l.forEach(d => $e.append(`<option value="${d}">${d}</option>`)); 
    if(expId === '#exp') fillChain('#sym', '#exp', 'input[name="type"]:checked', '#str');
    if(expId === '#h_exp') fillChain('#h_sym', '#h_exp', 'input[name="h_type"]:checked', '#h_str');
    if(expId === '#imp_exp') fillChain('#imp_sym', '#imp_exp', 'input[name="imp_type"]:checked', '#imp_str');
}

function fillChain(sym, exp, typeSelector, str) {
    let spot = symLTP[sym] || 0; let sVal = $(sym).val(); if(sVal.includes(':')) sVal = sVal.split(':')[0].trim();
    $.get(`/api/chain?symbol=${sVal}&expiry=${$(exp).val()}&type=${$(typeSelector).val()}&ltp=${spot}`, d => {
        let $s = $(str).empty(); 
        d.forEach(r => { let mark = r.label.includes('ATM') ? '🔴' : ''; let style = r.label.includes('ATM') ? 'style="color:red; font-weight:bold;"' : ''; let selected = r.label.includes('ATM') ? 'selected' : ''; $s.append(`<option value="${r.strike}" ${selected} ${style}>${mark} ${r.strike} ${r.label}</option>`); });
        // For import modal, we might want to trigger a price fetch or risk calc here
    });
}

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

function calcPnl(id) { 
    let val = parseFloat($('#p_' + id).val()) || 0; 
    let qty = parseInt($('#qty').val()) || 1; 
    let basePrice = ($('#ord').val() === 'LIMIT' && $('#lim_pr').val() > 0) ? parseFloat($('#lim_pr').val()) : curLTP; 
    if (val > 0) $('#pnl_' + id).text(`₹ ${((val - basePrice) * qty).toFixed(0)}`); 
}

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

    ['t1', 't2', 't3'].forEach(k => {
        if ($(`#${k}_full`).is(':checked')) {
            $(`#${k}_lots`).val(1000).prop('readonly', true);
        } else {
            $(`#${k}_lots`).prop('readonly', false);
        }
    });
}
