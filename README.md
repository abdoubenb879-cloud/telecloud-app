# ☁️ TeleCloud: Unlimited Telegram Storage

TeleCloud is a simple Python application that turns your Telegram "Saved Messages" into an unlimited personal cloud storage. It automatically splits large files (up to 2GB) into smaller chunks and reassembles them when you download.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
Make sure you have Python 3.10 or higher installed. If you don't, download it from [python.org](https://www.python.org/).

### 2. Install Requirements
Open your terminal (Command Prompt or PowerShell) in the project folder and run:
```powershell
pip install -r requirements.txt
```

### 3. Run the App
Start the application by running:
```powershell
python -m app.main
```

### 4. First-Time Login (IMPORTANT)
When you run the app for the first time, watch your terminal! 
1. Telegram will ask for your **Phone Number** (formatted like `+1234567890`).
2. You will receive a **login code** in your Telegram app.
3. Type the code into the terminal.
4. Once logged in, the app will start the web interface.

### 5. Access the Web Interface
Open your browser and go to:
[http://localhost:5000](http://localhost:5000)

---

## 🛠️ How to Use

- **Upload**: Drag and drop any file into the portal. For files larger than 1.9GB, the app will automatically chop them into pieces.
- **Download**: Click the download icon next to any file. The app will fetch all pieces from Telegram, put them back together, and save the file to your PC.
- **Delete**: Clicking delete will remove the file records from the app and delete the messages from your Telegram history.

---

## 📁 Project Structure
- `/app`: Core Python logic (Database, Chunker, Telegram Client)
- `/templates` & `/static`: The beautiful web interface
- `/uploads`: Temporary area for splitting files
- `/downloads`: Area where files are reassembled before sending to you
- `cloud_metadata.db`: Your local database (don't delete this!)

---

## ⚠️ Security & Privacy
- Your files are stored in **Saved Messages** on Telegram.
- Only you can see them via your Telegram account.
- Your `api_id` and `api_hash` are kept safe in the `.env` file. **Never share this file.**
