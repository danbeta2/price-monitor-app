// Price Monitor App JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Dashboard actions
    const btnSync = document.getElementById('btn-sync-products');
    const btnCollect = document.getElementById('btn-collect-all');
    const btnTestSearch = document.getElementById('btn-test-search');
    
    if (btnSync) {
        btnSync.addEventListener('click', syncProducts);
    }
    
    if (btnCollect) {
        btnCollect.addEventListener('click', collectAll);
    }
    
    if (btnTestSearch) {
        btnTestSearch.addEventListener('click', testSearch);
    }
});

async function syncProducts() {
    const btn = document.getElementById('btn-sync-products');
    const resultDiv = document.getElementById('action-result');
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Sincronizzazione...';
    
    try {
        const res = await fetch('/api/sync-products', { method: 'POST' });
        const data = await res.json();
        
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-success';
        resultDiv.innerHTML = `<i class="bi bi-check-circle"></i> Sincronizzati ${data.synced} prodotti`;
    } catch (e) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-danger';
        resultDiv.innerHTML = `<i class="bi bi-x-circle"></i> Errore: ${e.message}`;
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Sincronizza Prodotti da WooCommerce';
}

async function collectAll() {
    const btn = document.getElementById('btn-collect-all');
    const resultDiv = document.getElementById('action-result');
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Raccolta in corso...';
    
    try {
        const res = await fetch('/api/collect-all', { method: 'POST' });
        const data = await res.json();
        
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-success';
        resultDiv.innerHTML = `<i class="bi bi-check-circle"></i> Processati: ${data.processed}, Successo: ${data.successful}, Falliti: ${data.failed}`;
    } catch (e) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-danger';
        resultDiv.innerHTML = `<i class="bi bi-x-circle"></i> Errore: ${e.message}`;
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-collection"></i> Raccogli Prezzi (Tutti i Monitor)';
}

async function testSearch() {
    const btn = document.getElementById('btn-test-search');
    const source = document.getElementById('test-source').value;
    const query = document.getElementById('test-query').value;
    const resultsDiv = document.getElementById('test-results');
    
    if (!query) {
        alert('Inserisci una query di ricerca');
        return;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Ricerca...';
    resultsDiv.style.display = 'block';
    resultsDiv.innerHTML = '<div class="text-center py-3"><span class="spinner-border"></span></div>';
    
    try {
        const res = await fetch('/api/test-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source, query })
        });
        const data = await res.json();
        
        if (data.error) {
            resultsDiv.innerHTML = `<div class="alert alert-danger">${data.error}</div>`;
        } else if (data.results.length === 0) {
            resultsDiv.innerHTML = '<div class="alert alert-warning">Nessun risultato trovato</div>';
        } else {
            resultsDiv.innerHTML = `
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Titolo</th>
                                <th>Prezzo</th>
                                <th>Venditore</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.results.map(r => `
                                <tr>
                                    <td><a href="${r.url}" target="_blank">${escapeHtml(r.title.substring(0, 50))}...</a></td>
                                    <td><strong>€${r.price.toFixed(2)}</strong></td>
                                    <td>${escapeHtml(r.seller_name || '-')}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
                <small class="text-muted">Trovati ${data.results.length} risultati</small>
            `;
        }
    } catch (e) {
        resultsDiv.innerHTML = `<div class="alert alert-danger">Errore: ${e.message}</div>`;
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-search"></i> Cerca';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
