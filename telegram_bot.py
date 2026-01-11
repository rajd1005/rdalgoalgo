import requests
import settings
import threading

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
    threading.Thread(target=_process_alert, args=(event_type, trade_data, extra)).start()

def _process_alert(event_type, trade_data, extra):
    conf = get_config()
    if not conf.get('enabled', False): return
    if not conf.get('events', {}).get(event_type, True): return

    token = conf.get('bot_token')
    if not token: return

    tmpl = conf.get('templates', {}).get(event_type, "")
    if not tmpl: return

    text = format_message(tmpl, trade_data, extra)
    
    # Retrieve stored message IDs for channels this trade was sent to
    # Structure: { "chat_id_1": msg_id, "chat_id_2": msg_id }
    sent_map = trade_data.get('telegram_msg_ids', {})
    
    # If it's a legacy trade without map, or specific logic needed, handle here.
    # We only update channels where the initial trade was sent.
    if sent_map:
        for chat_id, root_msg_id in sent_map.items():
            # For TRADE_ADDED, we usually don't use send_alert (we use send_trade_added_sync)
            # For others, we reply to root
            send_request(token, chat_id, text, reply_to=root_msg_id)

def send_trade_added_sync(trade_data, target_channels):
    """
    Synchronous sending for TRADE_ADDED to capture Message IDs per channel.
    target_channels: List of channel config dicts {chat_id, ...} allowed by limits.
    """
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
