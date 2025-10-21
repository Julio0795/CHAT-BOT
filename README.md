Personalized AI WhatsApp Chat Bot
<p align="center">
  <img src="https://i.imgur.com/EcxWZR7.png" alt="Project Logo">
</p>

This project is a sophisticated, conversational AI assistant designed to manage and automate WhatsApp conversations. It's built with a powerful two-part architecture: a Python Flask backend (the brain) that handles all logic and intelligence, and a Node.js script (the bridge) that connects directly to the WhatsApp network.

The bot is designed to impersonate a specific user, maintaining a consistent personality, remembering conversational history, and even pursuing long-term conversational objectives. It features a full web dashboard for management, monitoring, and manual approval of messages.

✨ Key Features
🧠 AI-Powered & Context-Aware: Uses OpenAI's GPT models to generate human-like, context-aware replies based on conversation history.
🎛️ Web Dashboard for Management: A full-featured Flask web UI to monitor conversations, define the bot's personality, manage contacts, and manually approve messages.
🔒 Manual Approval Workflow: An optional mode that holds all generated replies for your approval on the dashboard before they are sent.
💾 Persistent Memory: All conversations, contact profiles, and bot settings are saved in a memory.json file, ensuring the bot remembers everything between sessions.
🎯 Contact-Specific Personality: Tailor the bot's communication style and remember specific facts for each individual contact.
🤖 Automatic Profile Learning: The bot can periodically analyze conversations to automatically update its notes on a contact's personality and key life details.
🔄 Robust Offline Queuing: If the Python brain is offline, the Node.js bridge safely queues incoming messages and processes them once the connection is restored.

🏗️ Architecture
The system operates with a clear separation of concerns, making it robust and scalable.

[User on WhatsApp] <--> [WhatsApp Network] <--> [index.js (Node.js Bridge)] <--> [bot.py (Python Brain & Web UI)]

bot.py (The Brain): A Python Flask server that handles all decision-making, prompt generation, AI calls, and serves the web dashboard.
index.js (The Bridge): A Node.js script using whatsapp-web.js that connects to WhatsApp, listens for incoming messages, sends outgoing messages, and communicates with the Python brain via a local API.

🚀 Getting Started
Follow these steps to set up and run the project on your local machine.

**Prerequisites**
Node.js installed.
Python (version 3.8 or newer) installed.
Git installed.
**Step 1: Clone the Repository**
Open your terminal or command prompt and clone the project.

# Clone the project from GitHub
git clone https://github.com/your-username/whatshapp-bot.git

# Navigate into the project directory
cd whatshapp-bot

(Replace your-username with your actual GitHub username)

**Step 2: Set Up the Python Backend**
This will install all the necessary Python libraries inside a clean virtual environment.

# Create a Python virtual environment
python -m venv .venv

# Activate the environment
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install the required Python packages
pip install -r requirements.txt

**Step 3: Set Up the Node.js Bridge**
This will install the whatsapp-web.js library and its dependencies.

# Install the required Node.js packages
npm install


**Step 4: Configure Your API Key (Crucial!)**
The bot needs your secret OpenAI API key to function.

Find the file named config.template.json.
Make a copy of this file and rename the copy to config.json.
Open config.json with a text editor and replace "YOUR_OPENAI_API_KEY_GOES_HERE" with your actual OpenAI API key.
The final file should look like this:

{
  "openai_api_key": "sk-AbcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
}

**Step 5: Run the Application**
You need to run both the Python brain and the Node.js bridge.

Using the Run Script (Windows)
The easiest way to start is by double-clicking the run.bat file. This will automatically open two command prompt windows and start both the Python and Node.js servers for you.

Your bot is now fully operational


