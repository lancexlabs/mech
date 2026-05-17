/**
 * Bridge Manager - Controls WhatsApp bridge lifecycle
 * Starts bridge on demand, stops after authentication
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

let bridgeProcess = null;
let isConnecting = false;
let connectionPromise = null;

function log(icon, msg) {
    const ts = new Date().toLocaleTimeString('en-IN');
    console.log(`[${ts}] ${icon}  ${msg}`);
}

function waitForBridgeReady(timeout = 30000) {
    return new Promise((resolve, reject) => {
        const startTime = Date.now();
        const checkInterval = setInterval(() => {
            const req = http.get('http://localhost:4322/health', (res) => {
                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    try {
                        const json = JSON.parse(data);
                        if (res.statusCode === 200) {
                            clearInterval(checkInterval);
                            resolve(json);
                        }
                    } catch (e) {}
                });
            });
            req.on('error', () => {});
            req.end();
            
            if (Date.now() - startTime > timeout) {
                clearInterval(checkInterval);
                reject(new Error('Bridge startup timeout'));
            }
        }, 500);
    });
}

async function startBridgeAndConnect() {
    if (isConnecting) {
        log('⏳', 'Already connecting, please wait...');
        return connectionPromise;
    }
    
    isConnecting = true;
    
    // Kill existing bridge if running
    if (bridgeProcess) {
        log('🔄', 'Stopping existing bridge...');
        bridgeProcess.kill();
        await new Promise(resolve => setTimeout(resolve, 2000));
        bridgeProcess = null;
    }
    
    // Clean up old session files
    const sessionPath = path.join(__dirname, 'whatsapp-session');
    const publicPath = path.join(__dirname, 'public');
    try {
        if (fs.existsSync(sessionPath)) {
            fs.rmSync(sessionPath, { recursive: true, force: true });
            log('🗑️', 'Cleaned old session');
        }
        if (fs.existsSync(publicPath)) {
            const files = fs.readdirSync(publicPath);
            files.forEach(file => {
                if (file.includes('qr') || file.includes('connected')) {
                    fs.unlinkSync(path.join(publicPath, file));
                }
            });
        }
    } catch (e) {}
    
    connectionPromise = new Promise(async (resolve, reject) => {
        // Start new bridge process
        log('🚀', 'Starting WhatsApp bridge...');
        bridgeProcess = spawn('node', [path.join(__dirname, 'whatsapp-bridge.js')], {
            stdio: 'inherit',
            detached: false
        });
        
        bridgeProcess.on('error', (err) => {
            log('❌', `Bridge process error: ${err.message}`);
            reject(err);
            isConnecting = false;
        });
        
        bridgeProcess.on('exit', (code) => {
            log('📢', `Bridge process exited with code ${code}`);
            bridgeProcess = null;
        });
        
        try {
            // Wait for bridge to be ready
            await waitForBridgeReady(30000);
            log('✅', 'Bridge is ready');
            
            // Now wait for authentication
            let authCompleted = false;
            let authTimeout = setTimeout(() => {
                if (!authCompleted) {
                    reject(new Error('Authentication timeout (90s)'));
                    isConnecting = false;
                }
            }, 90000);
            
            // Poll for connection status
            const pollInterval = setInterval(async () => {
                try {
                    const req = http.get('http://localhost:4322/health', (res) => {
                        let data = '';
                        res.on('data', chunk => data += chunk);
                        res.on('end', () => {
                            try {
                                const json = JSON.parse(data);
                                if (json.ready === true || json.connected === true) {
                                    authCompleted = true;
                                    clearInterval(pollInterval);
                                    clearTimeout(authTimeout);
                                    log('🎉', 'WhatsApp connected successfully!');
                                    resolve({ success: true, message: 'Connected' });
                                    isConnecting = false;
                                    
                                    // Stop bridge after 5 seconds (connection confirmed)
                                    setTimeout(() => {
                                        if (bridgeProcess) {
                                            log('🛑', 'Stopping bridge (connection complete)');
                                            bridgeProcess.kill();
                                            bridgeProcess = null;
                                        }
                                    }, 5000);
                                }
                            } catch (e) {}
                        });
                    });
                    req.on('error', () => {});
                    req.end();
                } catch (e) {}
            }, 1000);
            
        } catch (err) {
            reject(err);
            isConnecting = false;
        }
    });
    
    return connectionPromise;
}

async function disconnectBridge() {
    if (bridgeProcess) {
        bridgeProcess.kill();
        bridgeProcess = null;
    }
    isConnecting = false;
    connectionPromise = null;
    log('🔌', 'Disconnected');
    return { success: true };
}

module.exports = { startBridgeAndConnect, disconnectBridge };