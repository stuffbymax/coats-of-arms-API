# CSS made by AI
# Coats of Arms API repository — Flask + SQLite

A web app to collect, browse, and manage coats of arms for towns and countries.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000

## Features

- **Browse** all entries in a visual grid
- **Search** by name
- **Detail view** with image, description, colors, symbols, motto
- **Add** new entries via form
- **Edit** existing entries
- **Delete** entries
- **REST API** at `/api/items` and `/api/items/<id>`

## Database

SQLite file `coats_of_arms.db` is auto-created on first run.  
On first run, `data.json` is seeded into the database automatically.

## Schema

```
coats_of_arms
├── id                      INTEGER PK AUTOINCREMENT
├── name                    TEXT
├── motto_latin             TEXT
├── motto_english           TEXT
├── motto_other             TEXT  (JSON: other language keys)
├── colors                  TEXT  (JSON array)
├── symbols                 TEXT  (JSON array)
├── shield_shape            TEXT
├── created_at              TEXT
├── designer                TEXT
├── image                   TEXT  (URL)
├── description             TEXT
├── usage_official_documents INTEGER (0/1)
├── usage_flags             INTEGER (0/1)
└── usage_seal              INTEGER (0/1)
```

## API

- `GET /api/items` — list all entries
- `GET /api/items/<id>` — single entry detail
