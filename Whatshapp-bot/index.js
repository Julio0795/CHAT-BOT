// NEW: Import the necessary classes from whatsapp-web.js
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const axios = require('axios');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');

const QUEUE_PATH = path.join(__dirname, 'pending.json');
const IMAGES_DIR = path.join(__dirname, 'images');

// --- Your queue logic remains exactly the same ---
let pending = [];
try {
    const raw = fs.readFileSync(QUEUE_PATH, 'utf-8');
    const parsed = JSON.parse(raw);
    pending = Array.isArray(parsed) ? parsed : [];
} catch {
    pending = [];
}

function saveQueue() {
    try {
        fs.writeFileSync(QUEUE_PATH, JSON.stringify(pending, null, 2));
    } catch {}
}

// --- The core logic functions are updated for the new client ---

// The `sock` object is now a `client` object
async function processQueue(client) {
    for (let i = 0; i < pending.length; ) {
        const { from, text } = pending[i];
        try {
            const { data } = await axios.post('http://127.0.0.1:5001/reply', {
                sender: from,
                message: text,
            });

            if (Array.isArray(data.images)) {
                for (const img of data.images) {
                    const p = path.join(IMAGES_DIR, img);
                    if (fs.existsSync(p)) {
                        // NEW: Sending media is done with the MessageMedia class
                        const media = MessageMedia.fromFilePath(p);
                        await client.sendMessage(from, media);
                    } else {
                        console.warn('[processQueue] image not found:', p);
                    }
                }
            }
            if (data.reply) {
                // NEW: Sending text is simpler
                await client.sendMessage(from, data.reply);
            }

            pending.splice(i, 1);
            saveQueue();
        } catch (e) {
            break; // Server still down, stop trying
        }
    }
}

async function sendOrQueue(client, from, text) {
    try {
        const { data } = await axios.post('http://127.0.0.1:5001/reply', {
            sender: from,
            message: text,
        });

        if (Array.isArray(data.images)) {
            for (const img of data.images) {
                const p = path.join(IMAGES_DIR, img);
                if (fs.existsSync(p)) {
                    const media = MessageMedia.fromFilePath(p);
                    await client.sendMessage(from, media);
                } else {
                    console.warn('[sendOrQueue] image not found:', p);
                }
            }
        }
        if (data.reply) {
            await client.sendMessage(from, data.reply);
        }

        await processQueue(client);
    } catch (e) {
        pending.push({ from, text });
        saveQueue();
    }
}

// --- Main connection logic using whatsapp-web.js ---

console.log('Initializing WhatsApp client...');

// NEW: Use LocalAuth to save session and avoid re-scanning the QR code every time
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true, // Run in the background
        args: ['--no-sandbox', '--disable-setuid-sandbox'], // Required for some environments
    },
});

// NEW: Event for QR code generation
client.on('qr', (qr) => {
    console.log('QR Code received, scan it with your phone.');
    qrcode.generate(qr, { small: true });
});

// NEW: Event for when the client is authenticated and ready
client.on('ready', async () => {
    console.log('✅ Client is ready and connected!');
    // Process the local queue once connected
    await processQueue(client);
});

// NEW: Event for incoming messages
client.on('message', async (msg) => {
    // Ignore our own messages and status updates
    if (msg.fromMe || msg.isStatus) {
        return;
    }

    // `msg.from` is the JID (e.g., '15551234567@c.us')
    const from = msg.from;

    // Ignore group messages
    if (msg.isGroup) {
        return;
    }

    // `msg.body` contains the text of the message
    const text = msg.body;
    if (!text || !text.trim()) {
        return; // Ignore empty messages (e.g., just an image with no caption)
    }

    console.log(`Message from ${from}: ${text}`);
    
    // Your logic to get contact name (if available) and update Flask backend
    try {
        const contact = await msg.getContact();
        const assignedName = contact.name || contact.pushname;
        if (assignedName) {
            const params = new URLSearchParams();
            params.append('jid', from);
            params.append('name', assignedName);
            axios.post('http://127.0.0.1:5001/update_contact_name', params)
                 .catch(() => {});
        }
    } catch (e) {
        console.warn('Could not get contact details for', from);
    }


    await sendOrQueue(client, from, text);
});

// Start the client
client.initialize();

// --- Polling for approved replies remains exactly the same ---
setInterval(async () => {
    try {
        const { data } = await axios.get('http://127.0.0.1:5001/approved_batch');
        const items = Array.isArray(data?.items) ? data.items : [];
        for (const item of items) {
            if (!item?.jid) continue;

            if (Array.isArray(item.images) && item.images.length) {
                for (const img of item.images) {
                    const p = path.join(IMAGES_DIR, img);
                    if (fs.existsSync(p)) {
                        const media = MessageMedia.fromFilePath(p);
                        await client.sendMessage(item.jid, media);
                    } else {
                        console.warn('[approved_batch] image not found:', p);
                    }
                }
            }

            if (item.reply) {
                await client.sendMessage(item.jid, item.reply);
            }
        }
    } catch (err) {
        // swallow; will try again next tick
    }
}, 2000);