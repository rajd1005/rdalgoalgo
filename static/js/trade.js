function loadDetails(symId, expId, typeSelector, qtyId, slId) {
    let s = $(symId).val(); if(!s) return;
    
    let settingsKey = normalizeSymbol(s);
    let mode = 'PAPER';
    if (symId === '#h_sym' || $('#history').is(':visible')) mode = 'SIMULATOR'; 
    else mode = $('#mode_input').val();
    
    let modeSettings = settings.modes[mode] || settings.modes.PAPER;
    let savedSL = (modeSettings.symbol_sl && modeSettings.symbol_sl[settingsKey]) || 20;
    $(slId).val(savedSL);
    
    // Apply Defaults from Global Settings
    if(mode === 'SIMULATOR') {
         // Handled in simulator.js
    } else {
        // Trade Form Specifics
        if(modeSettings.order_type) $('#ord').val(modeSettings.order_type);
        if(modeSettings.trail_limit !== undefined) $('#trail_mode').val(modeSettings.trail_limit);
        $('#trail_sl').val(modeSettings.trailing_sl || '');
        $('#exit_mult').val(modeSettings.exit_mult || 1);
        
        // Sync Ratios Display
        if(modeSettings.ratios) {
            $('#r_t1').text(modeSettings.ratios[0]);
            $('#r_t2').text(modeSettings.ratios[1]);
            $('#r_t3').text(modeSettings.ratios[2]);
        }

        // Sync Target Config (Active, Lots, Full)
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

    let mode = $('#mode_input').val(); 
    let baseRatios = settings.modes[mode].ratios;
    let sl = basePrice - p;

    // --- EXIT MULTIPLIER LOGIC ---
    let exitMult = parseInt($('#exit_mult').val()) || 1;
    let finalRatio = baseRatios[2]; 
    
    if (exitMult > 1) {
        let steps = Math.min(exitMult, 3); 
        let ratioStep = finalRatio / steps;
        let lotsPerStep = Math.floor(qty / steps); 
        let extraLots = qty % steps;

        for(let i=1; i<=3; i++) {
             if (i <= steps) {
                 let targetPrice = basePrice + (p * (ratioStep * i));
                 $(`#p_t${i}`).val(targetPrice.toFixed(2));
                 
                 let thisLots = lotsPerStep;
                 if (i === steps) thisLots += extraLots; 
                 
                 $(`#t${i}_active`).prop('checked', true);
                 $(`#t${i}_lots`).val(thisLots);
                 $(`#t${i}_full`).prop('checked', false); 
                 $(`#pnl_t${i}`).text(`₹ ${((targetPrice - basePrice) * thisLots).toFixed(0)}`);
             } else {
                 $(`#t${i}_active`).prop('checked', false);
                 $(`#t${i}_lots`).val('');
                 $(`#p_t${i}`).val('');
                 $(`#pnl_t${i}`).text('₹ 0');
             }
        }
    } else {
        // Standard Behavior
        let t1 = basePrice + p * baseRatios[0]; 
        let t2 = basePrice + p * baseRatios[1]; 
        let t3 = basePrice + p * baseRatios[2];
    
        if (!document.activeElement || !['p_t1', 'p_t2', 'p_t3'].includes(document.activeElement.id)) {
                $('#p_t1').val(t1.toFixed(2)); $('#p_t2').val(t2.toFixed(2)); $('#p_t3').val(t3.toFixed(2));
                $('#pnl_t1').text(`₹ ${((t1-basePrice)*qty).toFixed(0)}`); 
                $('#pnl_t2').text(`₹ ${((t2-basePrice)*qty).toFixed(0)}`); 
                $('#pnl_t3').text(`₹ ${((t3-basePrice)*qty).toFixed(0)}`);
        }
    }

    $('#pnl_sl').text(`₹ ${((sl-basePrice)*qty).toFixed(0)}`);

    // Handle Full Checkbox Logic
    ['t1', 't2', 't3'].forEach(k => {
        if ($(`#${k}_full`).is(':checked')) {
            $(`#${k}_lots`).val(1000).prop('readonly', true);
        } else {
            $(`#${k}_lots`).prop('readonly', false);
        }
    });
}
