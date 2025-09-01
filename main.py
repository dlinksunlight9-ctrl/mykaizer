import aiohttp
import asyncio
import brotli
import gzip
import re
import os
from flask import Flask, jsonify, request, render_template
import threading

app = Flask(__name__)

BALANCE_URL = "https://zero-api.kaisar.io/user/balances?symbol=point"
SPIN_URL = "https://zero-api.kaisar.io/lucky/spin"
CONVERT_URL = "https://zero-api.kaisar.io/lucky/convert"

# Add your tokens directly here (comma separated)
TOKENS = [
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJfaWQiOiI2OGI1MWUwN2YzM2EyY2ZjZDk5MDE5MzkiLCJpZCI6IjY4YjUxZTA3ZjMzYTJjZmNkOTkwMTkzOSIsInJvbGUiOiJ1c2VyIiwic3RhdHVzIjoxLCJpYXQiOjE3NTY3MDAxNjcsImV4cCI6MTc4ODI1Nzc2N30.IyxBlPw9k_Zd0r-pnk6M0jEGSCPsqDkJ9yAYyACnD0U"
]

# Remove any empty tokens
TOKENS = [token.strip() for token in TOKENS if token.strip()]

# Default target points
DEFAULT_TARGET = 10000

timeout = aiohttp.ClientTimeout(total=10)

# Global variable to track if bot is running
bot_running = False
bot_thread = None

def get_headers(token):
    return {
        "accept": "*/*",
        "accept-encoding": "gzip, deflate, br",
        "authorization": f"Bearer {token.strip()}",
        "content-type": "application/json",
        "origin": "https://zero.kaisar.io",
        "referer": "https://zero.kaisar.io/",
        "user-agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Mobile Safari/537.36",
    }

async def decode_response(resp):
    raw_data = await resp.read()
    encoding = resp.headers.get("content-encoding", "")
    try:
        if "br" in encoding:
            raw_data = brotli.decompress(raw_data)
        elif "gzip" in encoding:
            raw_data = gzip.decompress(raw_data)
    except:
        pass
    return raw_data.decode("utf-8", errors="ignore")

async def is_token_valid(session, headers):
    try:
        async with session.get(BALANCE_URL, headers=headers) as resp:
            return resp.status == 200
    except:
        return False

async def check_balance(session, headers, name):
    try:
        async with session.get(BALANCE_URL, headers=headers) as resp:
            decoded = await decode_response(resp)
            match = re.search(r'"balance":"?([\d.]+)"?', decoded)
            if match:
                balance = float(match.group(1))
                print(f"[{name}] Balance: {balance}")
                return balance
            return None
    except:
        return None

async def buy_ticket(session, headers, count, name):
    try:
        for _ in range(count):
            await session.post(CONVERT_URL, headers=headers, json={})
        print(f"[{name}] Bought {count} tickets.")
    except Exception as e:
        print(f"[{name}] Ticket buying error: {e}")

async def spin(session, headers):
    try:
        async with session.post(SPIN_URL, headers=headers, json={}) as resp:
            return resp.status
    except:
        return None

async def worker(token, target, name):
    headers = get_headers(token)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if not await is_token_valid(session, headers):
            print(f"[{name}] Invalid token. Skipping.")
            return

        while bot_running:
            balance = await check_balance(session, headers, name)
            if balance is None:
                print(f"[{name}] Failed to fetch balance. Retry...")
                await asyncio.sleep(5)
                continue

            if balance >= target:
                print(f"[{name}] Target reached! Done.")
                break

            if balance >= 300:
                tickets = int(balance // 300)
                await buy_ticket(session, headers, min(tickets, 1), name)
            else:
                print(f"[{name}] Not enough for ticket. Waiting...")
                await asyncio.sleep(5)
                continue

            results = await asyncio.gather(*[spin(session, headers) for _ in range(500)])
            spins = sum(1 for r in results if r == 200)
            print(f"[{name}] Spins success: {spins}")
            await asyncio.sleep(1)

async def run_workers(tokens, target):
    tasks = [
        worker(token, target, f"Acc{i+1}")
        for i, token in enumerate(tokens)
    ]
    
    try:
        await asyncio.gather(*tasks)
    except Exception as e:
        print(f"Error in bot execution: {e}")
    
    global bot_running
    bot_running = False
    print("Bot has stopped")

def run_bot_async(tokens, target):
    """Run the bot in a separate thread with its own event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_workers(tokens, target))
    finally:
        loop.close()

@app.route('/')
def home():
    return render_template('index.html', tokens=TOKENS, target=DEFAULT_TARGET, running=bot_running)

@app.route('/run', methods=['POST'])
def run_bot():
    global bot_running, bot_thread
    
    if bot_running:
        return jsonify({"error": "Bot is already running"}), 400
    
    # Get target from form or use default
    target = request.form.get('target', DEFAULT_TARGET)
    try:
        target = float(target)
    except:
        target = DEFAULT_TARGET
    
    if not TOKENS:
        return jsonify({"error": "No tokens provided"}), 400
    
    # Run the bot in a separate thread
    bot_running = True
    bot_thread = threading.Thread(target=run_bot_async, args=(TOKENS, target))
    bot_thread.daemon = True
    bot_thread.start()
    
    return jsonify({
        "status": "started",
        "accounts": len(TOKENS),
        "target": target
    })

@app.route('/status')
def status():
    return jsonify({
        "running": bot_running,
        "accounts": len(TOKENS),
        "tokens": [f"Token {i+1}" for i in range(len(TOKENS))]
    })

@app.route('/stop', methods=['POST'])
def stop_bot():
    global bot_running
    bot_running = False
    return jsonify({"status": "stopping", "message": "Bot will stop after current operations"})

if __name__ == "__main__":
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Create a simple HTML interface
    with open('templates/index.html', 'w') as f:
        f.write('''
<!DOCTYPE html>
<html>
<head>
    <title>Kaisar Zero Point Bot</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .card { border: 1px solid #ddd; border-radius: 5px; padding: 20px; margin-bottom: 20px; }
        .success { background-color: #d4edda; }
        .error { background-color: #f8d7da; }
        .info { background-color: #d1ecf1; }
        button { background-color: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
        button:disabled { background-color: #6c757d; }
    </style>
</head>
<body>
    <h1>Kaisar Zero Point Bot</h1>
    
    <div class="card info">
        <h2>Configuration</h2>
        <p><strong>Tokens configured:</strong> {{ tokens|length }}</p>
        <p><strong>Default target:</strong> {{ target }} points</p>
    </div>
    
    <div class="card">
        <h2>Control Panel</h2>
        <div id="statusMessage"></div>
        <form id="runForm" action="/run" method="post">
            <label for="target">Target Points:</label>
            <input type="number" id="target" name="target" value="{{ target }}" min="300" step="100">
            <br><br>
            <button type="submit" id="runButton" {% if running %}disabled{% endif %}>Start Bot</button>
            <button type="button" id="stopButton" {% if not running %}disabled{% endif %}>Stop Bot</button>
        </form>
    </div>
    
    <div class="card">
        <h2>How to Use</h2>
        <p>1. Add your tokens directly in the TOKENS list in the Python code</p>
        <p>2. Set your target points (minimum 300)</p>
        <p>3. Click "Start Bot" to begin automated spinning</p>
        <p>4. Check Render logs to see the bot output</p>
    </div>
    
    <script>
        document.getElementById('runForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            const response = await fetch('/run', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (response.ok) {
                showMessage('Bot started successfully! Check logs for output.', 'success');
                document.getElementById('runButton').disabled = true;
                document.getElementById('stopButton').disabled = false;
            } else {
                showMessage('Error: ' + data.error, 'error');
            }
        });
        
        document.getElementById('stopButton').addEventListener('click', async function() {
            const response = await fetch('/stop', {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (response.ok) {
                showMessage('Bot stopping...', 'info');
                document.getElementById('runButton').disabled = false;
                document.getElementById('stopButton').disabled = true;
            }
        });
        
        function showMessage(message, type) {
            const messageDiv = document.getElementById('statusMessage');
            messageDiv.textContent = message;
            messageDiv.className = 'card ' + type;
        }
    </script>
</body>
</html>
        ''')
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
