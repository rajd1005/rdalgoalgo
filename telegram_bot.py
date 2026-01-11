import requests
import settings
import threading
import time
import json
from database import db, ActiveTrade 
from flask import current_app

def get_config():
    s = settings.load_settings()
    return s.get('telegram', {})

def format_message(template, data, extra=None):
    if not template: return ""
    
    replacements = {
        "{symbol}": data.get('symbol', 'Unknown'),
        "{type}": data.get('raw_params', {}).get('type', 'Unknown'),
        "{mode}": data.get('mode', 'PAPER'),
        "{entry}": f"{data.get('entry_price', 0):.2f}",
        "{sl}": f"{data.get('sl', 0):.2f}",
        "{qty}": str(data.get('quantity', 0)),
        "{ltp}": f"{data.get('current_ltp', 0):.2f}",
        "{pnl}": f"{((data.get('current_ltp', 0) - data.get('entry_price', 0)) * data.get('quantity', 0)):.2f}" if data.get('current_ltp') else "0",
        "{high}": f"{data.get('made_high', 0):.2f}"
    }

    targets = data.get('targets', [])
    replacements["{targets}"] = " | ".join([f"{t:.2f}" for t in targets])
    
    if extra:
        for k, v in extra.items():
            replacements[f"{{{k}}}"] = str(v)

    msg = template
    for k, v in replacements.items():
        msg = msg.replace(k, v)
    
    return msg

def send_request(token, chat_id, text, reply_to=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = { "chat_id": chat_id, "text": text, "parse_mode": "HTML" }
    if reply_to: payload["reply_to_message_id"] = reply_to
        
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            return r.json().get('result', {}).get('message_id')
        else:
            print(f"Telegram Error ({chat_id}): {r.text}")
    except Exception as e:
        print(f"Telegram Connection Fail: {e}")
    return None

def send_alert(event_type, trade_data, extra=None):
    app = current_app._get_current_object()
    threading.Thread(target=_process_alert, args=(app, event_type, trade_data, extra)).start()

def _process_alert(app, event_type, trade_data, extra):
    with app.app_context():
        conf = get_config()
        if not conf.get('enabled', False): return
        if not conf.get('events', {}).get(event_type, True): return

        token = conf.get('bot_token')
        if not token: return

        # Standard Template for this event (used for regular updates)
        std_tmpl = conf.get('templates', {}).get(event_type, "")
        
        # 1. Get Existing Recipients
        sent_map = trade_data.get('telegram_msg_ids', {})
        
        # 2. Process Forwarding Rules
        forwarding_rules = conf.get('forwarding_rules', [])
        new_recipients = {}
        
        # Check if trade exists in map (source check) OR if we allow forwarding unmapped trades (logic below assumes mapped)
        if sent_map:
            for rule in forwarding_rules:
                src = str(rule.get('source_id'))
                dest = str(rule.get('dest_id'))
                trigger = rule.get('trigger_event')
                delay = int(rule.get('delay', 0))
                trigger_val = str(rule.get('trigger_value', 'ANY')) 
                
                # Rule Matches if: 
                # 1. Source Channel has this trade
                # 2. Event Type matches Trigger
                # 3. Destination Channel does NOT have this trade yet
                if src in sent_map and event_type == trigger and dest not in sent_map:
                    
                    # Specific Trigger Value Check (e.g., Target 1 vs 2)
                    if event_type == 'TARGET_HIT' and trigger_val != 'ANY':
                        hit_idx = str(extra.get('index', 0))
                        if hit_idx != trigger_val:
                            continue # Skip if target mismatch
                    
                    if delay > 0: time.sleep(delay)
                    
                    # USE CUSTOM TEMPLATE for the First Message to Destination
                    fwd_tmpl = rule.get('template', '').strip()
                    if not fwd_tmpl: fwd_tmpl = std_tmpl 
                    
                    fwd_text = format_message(fwd_tmpl, trade_data, extra)
                    
                    # Send as NEW Root Message
                    new_id = send_request(token, dest, fwd_text, reply_to=None)
                    if new_id:
                        new_recipients[dest] = new_id
                        print(f"➡️ Forwarded {event_type} to {dest} (Source: {src})")

        # 3. Send to Existing Recipients (and newly forwarded ones? No, new ones got custom msg)
        std_text = format_message(std_tmpl, trade_data, extra)
        
        for chat_id, root_msg_id in sent_map.items():
            # If we just forwarded to this channel, we sent the Custom Template.
            # Do NOT send the Standard Template immediately for the same event.
            if chat_id in new_recipients:
                continue 
            
            # Send standard update as reply
            send_request(token, chat_id, std_text, reply_to=root_msg_id)

        # 4. Update Database with New Recipients (for future threading)
        if new_recipients:
            try:
                sent_map.update(new_recipients)
                # Important: Update the trade object in memory AND db
                trade_data['telegram_msg_ids'] = sent_map 
                
                t_record = ActiveTrade.query.filter_by(id=trade_data['id']).first()
                if t_record:
                    curr_data = json.loads(t_record.data)
                    curr_data['telegram_msg_ids'] = sent_map
                    t_record.data = json.dumps(curr_data)
                    db.session.commit()
            except Exception as e:
                print(f"DB Update Error (Forwarding): {e}")

def send_trade_added_sync(trade_data, target_channels):
    conf = get_config()
    if not conf.get('enabled', False): return {}
    if not conf.get('events', {}).get('TRADE_ADDED', True): return {}
    
    token = conf.get('bot_token')
    tmpl = conf.get('templates', {}).get('TRADE_ADDED', "")
    if not token or not tmpl: return {}
    
    text = format_message(tmpl, trade_data)
    results = {}
    
    for ch in target_channels:
        cid = ch.get('chat_id')
        if cid:
            msg_id = send_request(token, cid, text)
            if msg_id:
                results[cid] = msg_id
                
    return results
