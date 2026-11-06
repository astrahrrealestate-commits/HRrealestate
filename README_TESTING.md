# EstateOS QA Testing Package

Welcome to the EstateOS QA Testing Build.  
This package is fully self-contained: it includes the frontend, backend, background AI workers, and the database with all API keys and migrations pre-configured.

You do **not** need Node.js, Python, or PostgreSQL installed on your computer.

---

## ⚡ Prerequisites
* Make sure **Docker Desktop** is installed and **running** on your computer.

---

## 🚀 How to Run

### Option A: On Windows
1. Make sure all files (`estateos-bundle.tar`, `compose.test.yml`, `start-test.bat`) are in the **same folder**.
2. **Double-click `start-test.bat`**.
3. Wait ~30–45 seconds while it loads the images and starts the containers.
4. Open your browser and go to:  
   👉 **http://localhost:3000**

---

### Option B: On Mac / Linux
Make sure all files (`estateos-bundle.tar`, `compose.test.yml`, `start-test.command`, `start-test.sh`) are in the **same folder**.

#### Method 1 (Double-Click):
* **Double-click `start-test.command`** in Finder.  
*(Terminal will open automatically, load images, and start the app).*

#### Method 2 (Via Terminal):
1. Open the **Terminal** app.
2. Navigate to this folder:
   ```bash
   cd /path/to/folder
   ```
   *(Tip: type `cd ` and drag the folder from Finder into Terminal, then press Enter)*.
3. Run:
   ```bash
   chmod +x start-test.sh && ./start-test.sh
   ```
4. Open your browser and go to:  
   👉 **http://localhost:3000**

---

## 🧪 Testing Checklist

1. **Sign In**:
   * On `http://localhost:3000`, click **"Sign in with Google"**.
   * Use your authorized email (`chandan.p@fwc.co.in`, `aditya@seedicon.com`, `sambit.b@fwc.co.in`, `avinash.p@fwc.co.in`, etc.).
2. **Connect Google Workspace**:
   * In the left sidebar, click the **Connections** (🔌 plug icon).
   * Click **"Connect"** next to Gmail, Google Calendar, or Google Drive to link your account.
3. **Live Sync & AI Triage**:
   * Click **Sync / Refresh** to pull your real emails into the triage inbox.
   * View tenant cases, inspect maintenance tickets, and test 1-click AI draft generation and approval!

---

## 🛑 How to Stop
* In the terminal window, press **`Ctrl + C`**.
* Or open a terminal in the folder and run:
  ```bash
  docker compose -f compose.test.yml down
  ```
