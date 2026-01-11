import requests
import settings
import threading

def get_config():
    s = settings.load_settings()
    return s.get('telegram', {})

def format_message(template, data, extra=None):
    if not template: return ""
    
    # Flatten basics
    replacements = {
        "{symbol}": data.get('symbol', 'Unknown'),
        "{type}": data.get('raw_params', {}).get('type', 'Unknown'), # For sim
        "{mode}": data.get('mode', 'PAPER'),
        "{entry}": f"{data.get('entry_price', 0):.2f}",
        "{sl}": f"{data.get('sl', 0):.2f}",
        "{qty}": str(data.get('quantity', 0)),
        "{ltp}": f"{data.get('current_ltp', 0):.2f}",
        "{pnl}": f"{((data.get('current_ltp', 0) - data.get('entry_price', 0)) * data.get('quantity', 0)):.2f}" if data.get('current_ltp') else "0",
        "{high}": f"{data.get('made_high', 0):.2f}"
    }

    # Targets formatting
    targets = data.get('targets', [])
    replacements["{targets}"] = " | ".join([f"{t:.2f}" for t in targets])
    
    # Extra data (like specific target hit index)
    if extra:
        for k, v in extra.items():
            replacements[f"{{{k}}}"] = str(v)

    # Replace all
    msg = template
    for k, v in replacements.items():
        msg = msg.replace(k, v)
    
    return msg

def send_request(token, chat_id, text, reply_to=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            return r.json().get('result', {}).get('message_id')
        else:
            print(f"Telegram Error: {r.text}")
    except Exception as e:
        print(f"Telegram Connection Fail: {e}")
    return None

def send_alert(event_type, trade_data, extra=None):
    """
    event_type: TRADE_ADDED, TRADE_UPDATE, TRADE_ACTIVATED, TARGET_HIT, MADE_HIGH, CLOSE_SUMMARY
    """
    # Run in background thread to not block trading loop
    threading.Thread(target=_process_alert, args=(event_type, trade_data, extra)).start()

def _process_alert(event_type, trade_data, extra):
    conf = get_config()
    
    # 1. Check Global Enable
    if not conf.get('enabled', False): return
    
    # 2. Check Specific Event Toggle
    events = conf.get('events', {})
    if not events.get(event_type, True): return

    # 3. Check Credentials
    token = conf.get('bot_token')
    chat_id = conf.get('chat_id')
    if not token or not chat_id: return

    # 4. Get Template
    templates = conf.get('templates', {})
    tmpl = templates.get(event_type, "")
    if not tmpl: return

    # 5. Format
    text = format_message(tmpl, trade_data, extra)
    
    # 6. Determine Threading (Reply Logic)
    # Trade Added is the root.
    reply_to = None
    if event_type == "TRADE_ADDED":
        msg_id = send_request(token, chat_id, text)
        if msg_id:
            # We need to save this ID back to the trade record in the caller function
            # usually by reference, but since we are threaded, we treat it carefully.
            # However, for TRADE_ADDED, we usually want the ID immediately.
            # Exception: we return ID here if needed, but this is threaded.
            # Strategy: Store in trade_data dict (mutable) if possible or rely on
            # the fact that strategy_manager saves the trade object after calling this.
            # BUT: Threading creates a race condition for saving 'telegram_root_id'.
            # FIX: Run TRADE_ADDED synchronously or update DB here.
            pass 
    else:
        # For updates, reply to the root
        reply_to = trade_data.get('telegram_root_id')

    # Send
    # Note: For TRADE_ADDED, we run sync to capture ID safely
    if event_type != "TRADE_ADDED":
        send_request(token, chat_id, text, reply_to)

def send_trade_added_sync(trade_data):
    """Specific sync function for adding trade to ensure we capture the Root Message ID"""
    conf = get_config()
    if not conf.get('enabled', False): return None
    if not conf.get('events', {}).get('TRADE_ADDED', True): return None
    
    token = conf.get('bot_token')
    chat_id = conf.get('chat_id')
    tmpl = conf.get('templates', {}).get('TRADE_ADDED', "")
    
    if token and chat_id and tmpl:
        text = format_message(tmpl, trade_data)
        return send_request(token, chat_id, text)
    return None
