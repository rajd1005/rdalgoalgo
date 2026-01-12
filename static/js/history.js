function loadClosedTrades() {
    let filterDate = $('#hist_date').val(); let filterType = $('#hist_filter').val();
    $.get('/api/closed_trades', trades => {
        allClosedTrades = trades; let html = ''; 
        let dayTotal = 0;
        let totalWins = 0;
        let totalLosses = 0;
        let totalPotential = 0;

        let filtered = trades.filter(t => t.exit_time && t.exit_time.startsWith(filterDate) && (filterType === 'ALL' || getTradeCategory(t) === filterType));
        if(filtered.length === 0) html = '<div class="text-center p-4 text-muted">No History for this Date/Filter</div>';
        else {
            filtered.forEach(t => {
                dayTotal += t.pnl; 
                if(t.pnl > 0) totalWins += t.pnl;
                else totalLosses += t.pnl;

                let color = t.pnl >= 0 ? 'pnl-green' : 'pnl-red';
                let cat = getTradeCategory(t); 
                let badge = getMarkBadge(cat);
                
                // --- Logic for Potential Profit Display ---
                let potHtml = '';
                let mh = t.made_high || 0;
                let calcQty = t.initial_quantity || t.quantity; 
                
                // Condition: Show if PNL > 0 OR Booked PNL > 0 OR Targets were Hit (for SL Hit After Target)
                // Explicitly EXCLUDE 'COST_EXIT'
                let showPotential = (t.pnl > 0) || (t.booked_pnl && t.booked_pnl > 0) || (t.targets_hit_indices && t.targets_hit_indices.length > 0);
                
                if (t.status === 'COST_EXIT') showPotential = false;

                if (showPotential && mh > t.entry_price && calcQty > 0) {
                    let pot = (mh - t.entry_price) * calcQty;
                    totalPotential += pot; 
                    potHtml = `<br><span class="text-primary" style="font-size:0.75rem;">High: <b>${mh.toFixed(2)}</b></span> <span class="text-success" style="font-size:0.75rem;">Max: <b>${pot.toFixed(0)}</b></span>`;
                }

                // --- Status Tag Logic (Updated for "SL Hit After Target") ---
                let statusTag = '';
                if (t.status === 'SL_HIT') {
                     if (t.targets_hit_indices && t.targets_hit_indices.length > 0) {
                         let maxHit = Math.max(...t.targets_hit_indices);
                         // maxHit: 0=T1, 1=T2, 2=T3
                         statusTag = `<span class="badge bg-danger" style="font-size:0.7rem;">SL Hit After T${maxHit + 1}</span>`;
                     } else {
                         statusTag = '<span class="badge bg-danger" style="font-size:0.7rem;">Stop-Loss</span>';
                     }

                } else if (t.status === 'TARGET_HIT') {
                     // Check if Final Target or specific
                     let maxHit = 2; 
                     if (t.targets_hit_indices && t.targets_hit_indices.length > 0) {
                         maxHit = Math.max(...t.targets_hit_indices);
                     }
                     
                     if (maxHit === 0) statusTag = '<span class="badge bg-success" style="font-size:0.7rem;">Target 1 Hit</span>';
                     else if (maxHit === 1) statusTag = '<span class="badge bg-success" style="font-size:0.7rem;">Target 2 Hit</span>';
                     else statusTag = '<span class="badge bg-success" style="font-size:0.7rem;">Target 3 Hit</span>';

                } else if (t.status === 'COST_EXIT') {
                     statusTag = '<span class="badge bg-warning text-dark" style="font-size:0.7rem;">Cost Exit</span>';
                } else {
                     statusTag = `<span class="badge bg-secondary" style="font-size:0.7rem;">${t.status}</span>`;
                }
                // -----------------------------------------------------------

                // Action Buttons
                let editBtn = (t.order_type === 'SIMULATION') ? `<button class="btn btn-xs btn-outline-primary" onclick="editSim('${t.id}')">✏️ Edit</button>` : '';
                let delBtn = `<button class="btn btn-xs btn-outline-danger" onclick="deleteTrade('${t.id}')">🗑️</button>`;
                
                html += `<div class="trade-row">
                    <div class="trade-info">
                        <div class="d-flex align-items-center gap-2">
                            <span class="fw-bold text-dark" style="font-size:0.9rem;">${t.symbol}</span>
                            ${badge}
                            ${statusTag}
                        </div>
                        <div class="text-end">
                             <span class="fw-bold ${color}" style="font-size:1rem;">${t.pnl.toFixed(2)}</span>
                        </div>
                    </div>
                    <div class="trade-details">
                        <span class="text-uppercase fw-bold" style="font-size:0.7rem; color:#666;">${t.status}</span>
                        <span>Q: <b>${t.quantity}</b></span>
                        <span>Ent: <b>${t.entry_price.toFixed(2)}</b></span>
                        <span>Ext: <b>${t.exit_price.toFixed(2)}</b></span>
                        ${potHtml}
                    </div>
                    <div class="trade-actions">
                        <span class="text-muted me-auto" style="font-size:0.75rem;">${t.exit_time.slice(11,16)}</span>
                        ${editBtn}
                        ${delBtn}
                        <button class="btn btn-xs btn-outline-secondary" onclick="showLogs('${t.id}', 'closed')">Logs</button>
                    </div>
                </div>`;
            });
        }
        $('#hist-container').html(html); 
        
        $('#day_pnl').text("₹ " + dayTotal.toFixed(2));
        if(dayTotal >= 0) $('#day_pnl').removeClass('bg-danger').addClass('bg-success'); else $('#day_pnl').removeClass('bg-success').addClass('bg-danger');

        $('#total_wins').text("Wins: ₹ " + totalWins.toFixed(2));
        $('#total_losses').text("Loss: ₹ " + totalLosses.toFixed(2));
        
        $('#total_potential').text("Total Potential Profit: ₹ " + totalPotential.toFixed(2));
    });
}

function deleteTrade(id) { 
    if(confirm("Delete trade?")) $.post('/api/delete_trade/' + id, r => { if(r.status === 'success') loadClosedTrades(); else alert('Failed to delete'); }); 
}

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
