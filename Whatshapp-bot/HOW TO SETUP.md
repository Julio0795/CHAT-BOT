# How to Set Up and Run This Project

This project consists of two main parts that must be run simultaneously: a Python backend (the "brain") and a Node.js script (the "WhatsApp bridge").



Prerequisites

* Node.js installed.
* Python (version 3.8 or newer) installed.
* Git installed.





### **Step 1: Clone the Repository**



\# Clone the project from GitHub

git clone https://github.com/your-username/whatshapp-bot.git



\# Navigate into the project directory

cd whatshapp-bot





### **Step 2: Set Up the Python Backend**



This will install all the necessary Python libraries inside a clean virtual environment.



\# Create a Python virtual environment

python -m venv .venv



\# Activate the environment

\# On Windows:

.venv\\Scripts\\activate

\# On macOS/Linux:

source .venv/bin/activate



\# Install the required Python packages

pip install -r requirements.txt







### **Step 3: Set Up the Node.js Bridge**

This will install the whatsapp-web.js library and its dependencies.





\# Install the required Node.js packages

npm install





### **Step 4: Configure Your API Key (Crucial!)**

The bot needs your secret OpenAI API key to function.



1. Find the file named config.template.json in the project folder.
2. Make a copy of this file and rename the copy to config.json.
3. Open config.json with a text editor and replace "YOUR\_OPENAI\_API\_KEY\_GOES\_HERE" with your actual OpenAI API key. The file should look like this:

{

&nbsp; "openai\_api\_key": "sk-AbcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"

}





### **Step 5: Run the Application**



-Double click the bat file named run





-You need your WhatsApp account with phone number to approve login when running the bot you will be requested to scan QR code for login







