# Price Monitor App

Web app per monitorare i prezzi dei competitor su Google Shopping ed eBay per prodotti WooCommerce.

## Features

- 📦 Sincronizza prodotti da WooCommerce
- 🔍 Ricerca prezzi su Google Shopping (via SerpAPI)
- 🛒 Ricerca prezzi su eBay
- 📊 Dashboard con statistiche e grafici
- 📈 Storico prezzi con trend
- ⚡ Bulk add monitor per più prodotti
- 🔔 Confronto "tuo prezzo" vs competitor

## Deploy su Railway

### 1. Crea repository GitHub

```bash
cd price-monitor-app
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/TUO_USERNAME/price-monitor-app.git
git push -u origin main
```

### 2. Deploy su Railway

1. Vai su [railway.app](https://railway.app)
2. Login con GitHub
3. "New Project" → "Deploy from GitHub repo"
4. Seleziona `price-monitor-app`
5. Railway deploya automaticamente

### 3. Configura variabili d'ambiente

In Railway, vai su **Variables** e aggiungi:

```
WC_URL=https://your-store.com
WC_CONSUMER_KEY=ck_xxxxx
WC_CONSUMER_SECRET=cs_xxxxx
SERPAPI_KEY=your_serpapi_key
EBAY_CLIENT_ID=your_ebay_client_id
EBAY_CLIENT_SECRET=your_ebay_client_secret
EBAY_MARKETPLACE=EBAY_IT
SECRET_KEY=generate-a-random-string-here
```

### 4. Genera dominio

In Railway → Settings → Domains → "Generate Domain"

La tua app sarà accessibile su `https://xxx.up.railway.app`

## Sviluppo locale

```bash
# Crea virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Installa dipendenze
pip install -r requirements.txt

# Copia e configura .env
cp .env.example .env
# Modifica .env con le tue credenziali

# Avvia
python run.py
```

Apri http://localhost:5000

## Struttura

```
price-monitor-app/
├── app/
│   ├── __init__.py       # App factory
│   ├── models.py         # Database models
│   ├── routes.py         # Page routes
│   ├── api.py            # API endpoints
│   └── services/
│       ├── woocommerce.py
│       ├── serpapi.py
│       ├── ebay.py
│       └── price_collector.py
├── templates/            # HTML templates
├── static/               # CSS, JS
├── requirements.txt
├── Procfile              # Railway/Heroku
└── run.py                # Entry point
```

## API Endpoints

- `GET /api/products` - Lista prodotti WooCommerce
- `POST /api/sync-products` - Sincronizza prodotti
- `GET /api/monitors` - Lista monitor
- `POST /api/monitors` - Crea monitor
- `POST /api/monitors/bulk` - Crea monitor multipli
- `POST /api/monitors/:id/collect` - Raccogli prezzi
- `GET /api/monitors/:id/prices` - Storico prezzi
- `POST /api/test-search` - Test ricerca
- `POST /api/collect-all` - Raccogli tutti i prezzi
