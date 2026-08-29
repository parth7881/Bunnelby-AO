# AO — Personal Desktop Assistant

Prompt 1 foundation: FastAPI + SQLite + Electron/React. No paid services are required.

## Requirements

Use these versions or newer compatible releases:

- Python 3.11 or 3.12
- Node.js 20 LTS or newer LTS
- npm 10+
- Windows PowerShell, macOS Terminal, or Linux shell

## Project structure

```text
ao/
├── apps/
│   └── desktop/
│       ├── src/
│       │   ├── App.jsx
│       │   ├── main.jsx
│       │   └── styles.css
│       ├── electron.cjs
│       ├── index.html
│       ├── package.json
│       ├── preload.cjs
│       └── vite.config.js
├── database/
│   ├── migrations/
│   │   ├── versions/
│   │   │   └── 0001_create_messages.py
│   │   ├── env.py
│   │   └── script.py.mako
│   ├── .gitkeep
│   └── alembic.ini
├── services/
│   └── api/
│       ├── app/
│       │   ├── __init__.py
│       │   ├── database.py
│       │   ├── main.py
│       │   ├── models.py
│       │   └── schemas.py
│       └── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 1. Open the project

Open a terminal in the `ao` folder.

```powershell
cd path\to\ao
```

Verify Python and Node:

```powershell
python --version
node --version
npm --version
```

Expected: Python 3.11/3.12 and Node 20+.

## 2. Backend setup

From the repository root:

```powershell
python -m venv .venv
```

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once in the same terminal and retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### macOS/Linux

```bash
source .venv/bin/activate
```

Install backend dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r services/api/requirements.txt
```

Create/update the SQLite schema using Alembic:

```powershell
python -m alembic -c database/alembic.ini upgrade head
```

Expected terminal output includes:

```text
Running upgrade  -> 0001, create messages table
```

A local file should now exist at:

```text
database/ao.db
```

Start FastAPI:

```powershell
python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000 --reload
```

Expected terminal output includes:

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete.
```

Keep this terminal open.

## 3. Verify the backend directly

Open a second terminal in the repository root.

### PowerShell

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json" `
  -Body '{"message":"hello"}'
```

Expected response:

```text
reply
-----
AO heard: hello
```

You can also open FastAPI's local API docs in a browser:

```text
http://127.0.0.1:8000/docs
```

The page should show `POST /chat`.

## 4. Desktop setup

Open a third terminal:

```powershell
cd apps/desktop
npm install
npm run dev
```

Expected terminal output includes a Vite URL similar to:

```text
Local: http://127.0.0.1:5173/
```

After Vite is ready, Electron opens an AO desktop window automatically.

The window should show:

- `AO`
- `Personal Desktop Assistant`
- `AO is ready.`
- a `Message AO...` input
- a `Send` button

## 5. End-to-end verification

With FastAPI and Electron both running:

1. Type `hello AO` in the desktop input.
2. Click `Send`.
3. The chat history should show your message.
4. AO should answer:

```text
AO heard: hello AO
```

Each request writes two rows to SQLite: one `user` row and one `assistant` row.

## 6. Verify SQLite logging

With the virtual environment active, run from the repository root:

```powershell
python -c "import sqlite3; c=sqlite3.connect('database/ao.db'); print(c.execute('SELECT id, role, content, created_at FROM messages ORDER BY id').fetchall())"
```

After sending one message, output should contain at least two rows similar to:

```text
[(1, 'user', 'hello AO', '...'), (2, 'assistant', 'AO heard: hello AO', '...')]
```

## Run AO later

You normally need two terminals.

### Terminal 1 — backend

```powershell
cd path\to\ao
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000 --reload
```

### Terminal 2 — desktop

```powershell
cd path\to\ao\apps\desktop
npm run dev
```

## Current Prompt 1 behavior

`POST /chat` accepts:

```json
{"message":"anything"}
```

and returns:

```json
{"reply":"AO heard: anything"}
```

Gemini, Gmail, Calendar, voice, file search, and terminal tools are intentionally not included yet. They belong to later prompts.
