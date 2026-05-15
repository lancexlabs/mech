/**
 * MechTrack — WhatsApp Bridge (FIXED - Proper reconnect)
 * Port: 4322
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const express = require('express');
const qrcode = require('qrcode');
const qrcodeTerminal = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(express.json());

const PORT = 4322;
const SESSION_PATH = path.join(__dirname, 'whatsapp-session');

let client = null;
let currentQr = null;
let currentQrUrl = null;
let isReady = false;
let isConnecting = false;

function log(icon, msg) {
    const ts = new Date().toLocaleTimeString('en-IN');
    console.log(`[${ts}] ${icon}  ${msg}`);
}

function clearSession() {
    if (fs.existsSync(SESSION_PATH)) {
        fs.rmSync(SESSION_PATH, { recursive: true, force: true });
        log('🗑️', 'Session cleared');
    }
}

async function destroyClient() {
    if (client) {
        try {
            await client.destroy();
        } catch(e) {}
        client = null;
    }
    isReady = false;
    currentQr = null;
    currentQrUrl = null;
    isConnecting = false;
}

async function initializeClient() {
    if (isConnecting) {
        log('⏳', 'Already connecting, please wait...');
        return;
    }
    
    isConnecting = true;
    log('🚀', 'Initializing WhatsApp client...');
    
    await destroyClient();
    
    client = new Client({
        authStrategy: new LocalAuth({ dataPath: SESSION_PATH }),
        puppeteer: {
            headless: true,
            args: [
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--disable-gpu'
            ],
        },
    });

    client.on('qr', (qr) => {
        currentQr = qr;
        isReady = false;
        currentQrUrl = null;
        
        console.log('\n' + '='.repeat(60));
        log('📱', 'SCAN THIS QR CODE WITH WHATSAPP');
        console.log('='.repeat(60));
        qrcodeTerminal.generate(qr, { small: true });
        console.log('-'.repeat(60));
        console.log('1. Open WhatsApp on your phone');
        console.log('2. Tap Menu (⋮) → Linked Devices');
        console.log('3. Tap "Link a Device"');
        console.log('4. Scan the QR code above');
        console.log('='.repeat(60) + '\n');
        
        qrcode.toDataURL(qr, { margin: 2, width: 300 }, (err, url) => {
            if (!err) currentQrUrl = url;
        });
    });

    client.on('authenticated', () => {
        log('✅', 'Authenticated successfully');
    });

    client.on('ready', () => {
        isReady = true;
        currentQr = null;
        currentQrUrl = null;
        isConnecting = false;
        console.log('\n' + '='.repeat(60));
        log('✅', 'WHATSAPP IS READY!');
        console.log('='.repeat(60) + '\n');
    });

    client.on('auth_failure', (msg) => {
        log('❌', `Auth failed: ${msg}`);
        isReady = false;
        isConnecting = false;
    });

    client.on('disconnected', (reason) => {
        log('❌', `Disconnected: ${reason}`);
        isReady = false;
        currentQr = null;
        currentQrUrl = null;
        isConnecting = false;
        log('🔄', 'Use /reset endpoint to reconnect');
    });

    client.initialize();
}

// ============================================
// EXPRESS ENDPOINTS
// ============================================

app.get('/health', (req, res) => {
    res.json({
        status: 'ok',
        ready: isReady,
        connected: isReady,
        session_exists: fs.existsSync(SESSION_PATH),
        initialized: !!client
    });
});

app.get('/qr', async (req, res) => {
    if (isReady) {
        return res.json({ qr: null, ready: true, message: 'Already connected' });
    }
    
    if (!currentQr) {
        return res.json({ qr: null, ready: false, message: 'Waiting for QR code... Please wait a few seconds' });
    }
    
    try {
        if (currentQrUrl) {
            return res.json({ qr: currentQrUrl, ready: false, message: 'Scan QR code with WhatsApp' });
        }
        
        const url = await qrcode.toDataURL(currentQr, {
            margin: 2,
            width: 300,
            color: { dark: '#000000', light: '#FFFFFF' }
        });
        return res.json({ qr: url, ready: false, message: 'Scan QR code with WhatsApp' });
    } catch (err) {
        return res.status(500).json({ qr: null, ready: false, error: err.message });
    }
});

app.post('/send-message', async (req, res) => {
    const { phone, message } = req.body;
    
    if (!phone || !message) {
        return res.status(400).json({ error: 'Phone and message are required' });
    }
    
    if (!isReady || !client) {
        return res.status(503).json({ error: 'WhatsApp not ready. Please connect first.' });
    }
    
    let clean = phone.replace(/\D/g, '');
    if (clean.length === 10) clean = '91' + clean;
    if (!clean.startsWith('91')) clean = '91' + clean;
    
    const chatId = `${clean}@c.us`;
    log('📤', `Sending to ${chatId}`);
    
    try {
        const numberDetails = await client.getNumberId(chatId);
        if (!numberDetails) {
            return res.status(400).json({ error: 'Number not registered on WhatsApp' });
        }
        
        const sent = await client.sendMessage(chatId, message);
        if (sent && sent.id) {
            log('✅', `Message sent: ${sent.id.id}`);
            return res.json({ success: true, messageId: sent.id.id });
        }
        
        return res.status(500).json({ error: 'Failed to send message' });
    } catch (err) {
        log('❌', `Send error: ${err.message}`);
        return res.status(500).json({ error: err.message });
    }
});

app.post('/disconnect', async (req, res) => {
    try {
        await destroyClient();
        clearSession();
        log('🔌', 'Disconnected and session cleared');
        res.json({ success: true, message: 'Disconnected. Use /reset to reconnect.' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/reset', async (req, res) => {
    try {
        log('🔄', 'Resetting connection...');
        await destroyClient();
        clearSession();
        setTimeout(() => {
            initializeClient();
        }, 1000);
        res.json({ success: true, message: 'Reset complete. New QR will appear in a few seconds.' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.listen(PORT, () => {
    console.log('\n' + '='.repeat(60));
    log('🚀', `WhatsApp Bridge running on http://localhost:${PORT}`);
    console.log('='.repeat(60));
    console.log('  GET  /health       - Check status');
    console.log('  GET  /qr           - Get QR code');
    console.log('  POST /send-message - Send message');
    console.log('  POST /disconnect   - Disconnect');
    console.log('  POST /reset        - Reset & get new QR');
    console.log('='.repeat(60) + '\n');
    
    initializeClient();
});

process.on('SIGINT', async () => {
    log('🛑', 'Shutting down...');
    await destroyClient();
    process.exit(0);
});