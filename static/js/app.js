// Price Monitor App JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Dashboard actions
    const btnSync = document.getElementById('btn-sync-products');
    const btnCollect = document.getElementById('btn-collect-all');
    const btnTestSearch = document.getElementById('btn-test-search');
    const btnMonitorAll = document.getElementById('btn-monitor-all');
    const btnCleanupSingles = document.getElementById('btn-cleanup-singles');
    
    if (btnSync) {
        btnSync.addEventListener('click', syncProducts);
    }
    
    if (btnCollect) {
        btnCollect.addEventListener('click', collectAll);
    }
    
    if (btnTestSearch) {
        btnTestSearch.addEventListener('click', testSearch);
    }
    
    if (btnMonitorAll) {
        btnMonitorAll.addEventListener('click', createMonitorsForAll);
    }
    
    if (btnCleanupSingles) {
        btnCleanupSingles.addEventListener('click', cleanupSingleCards);
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
        
        if (data.error) {
            resultDiv.className = 'alert alert-danger';
            resultDiv.innerHTML = `<i class="bi bi-x-circle"></i> <strong>${data.error}</strong><br><small>${data.details || ''}</small>`;
        } else if (data.synced === 0) {
            resultDiv.className = 'alert alert-warning';
            resultDiv.innerHTML = `<i class="bi bi-exclamation-triangle"></i> ${data.message || 'Nessun prodotto trovato'}`;
        } else {
            resultDiv.className = 'alert alert-success';
            let msg = `<i class="bi bi-check-circle"></i> Sincronizzati ${data.synced} prodotti sealed`;
            if (data.skipped_single_cards > 0) {
                msg += ` <small class="text-muted">(ignorate ${data.skipped_single_cards} carte singole)</small>`;
            }
            if (data.removed > 0) {
                msg += `<br><small>Rimossi ${data.removed} prodotti obsoleti</small>`;
            }
            resultDiv.innerHTML = msg;
        }
    } catch (e) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-danger';
        resultDiv.innerHTML = `<i class="bi bi-x-circle"></i> Errore di rete: ${e.message}`;
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-arrow-repeat"></i> Sincronizza Prodotti da WooCommerce';
}

async function collectAll() {
    const btn = document.getElementById('btn-collect-all');
    const resultDiv = document.getElementById('action-result');
    
    btn.disabled = true;
    resultDiv.style.display = 'block';
    resultDiv.className = 'alert alert-info';
    
    let totalProcessed = 0;
    let totalSuccess = 0;
    let totalFailed = 0;
    let offset = 0;
    const batchSize = 5;  // 5 monitor alla volta per evitare timeout
    
    try {
        while (true) {
            btn.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Raccolta batch ${Math.floor(offset/batchSize) + 1}...`;
            resultDiv.innerHTML = `<i class="bi bi-hourglass-split"></i> Processati: ${totalProcessed} | In corso...`;
            
            const res = await fetch('/api/collect-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_size: batchSize, offset: offset })
            });
            
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }
            
            const data = await res.json();
            
            totalProcessed += data.processed;
            totalSuccess += data.successful;
            totalFailed += data.failed;
            
            // Aggiorna progress
            resultDiv.innerHTML = `<i class="bi bi-hourglass-split"></i> Processati: ${totalProcessed}/${data.total} | Successo: ${totalSuccess} | Falliti: ${totalFailed}`;
            
            // Se non ci sono più monitor da processare, esci
            if (data.remaining === 0 || data.processed === 0) {
                break;
            }
            
            offset = data.next_offset;
            
            // Piccola pausa tra batch per non sovraccaricare
            await new Promise(r => setTimeout(r, 500));
        }
        
        resultDiv.className = 'alert alert-success';
        resultDiv.innerHTML = `<i class="bi bi-check-circle"></i> Completato! Processati: ${totalProcessed}, Successo: ${totalSuccess}, Falliti: ${totalFailed}`;
        
    } catch (e) {
        resultDiv.className = 'alert alert-danger';
        resultDiv.innerHTML = `<i class="bi bi-x-circle"></i> Errore: ${e.message} (Processati fin qui: ${totalProcessed})`;
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
            // Funzione per ottenere il badge della fonte
            const getSourceBadge = (src) => {
                if (src === 'google_shopping') {
                    return '<span class="badge bg-primary">Google</span>';
                } else if (src === 'ebay') {
                    return '<span class="badge bg-warning text-dark">eBay</span>';
                }
                return '<span class="badge bg-secondary">?</span>';
            };
            
            // Header con riepilogo fonti e filtri
            let summaryHtml = '';
            const filteredOut = data.filtered_out || 0;
            const totalRaw = data.total_raw || data.total;
            
            if (source === 'both' && data.google_count !== undefined) {
                summaryHtml = `
                    <div class="mb-3">
                        <span class="badge bg-primary me-2">Google: ${data.google_count}</span>
                        <span class="badge bg-warning text-dark me-2">eBay: ${data.ebay_count}</span>
                        <span class="badge bg-success">Validi: ${data.total}</span>
                        ${filteredOut > 0 ? `<span class="badge bg-secondary ms-2">Filtrati: ${filteredOut}</span>` : ''}
                        ${data.errors?.google ? `<br><small class="text-danger">Errore Google: ${data.errors.google}</small>` : ''}
                        ${data.errors?.ebay ? `<br><small class="text-danger">Errore eBay: ${data.errors.ebay}</small>` : ''}
                    </div>
                `;
            } else if (filteredOut > 0) {
                summaryHtml = `
                    <div class="mb-3">
                        <span class="badge bg-success">Validi: ${data.results.length}</span>
                        <span class="badge bg-secondary ms-2">Filtrati: ${filteredOut}</span>
                        <small class="text-muted ms-2">(rimossi: bundle, lotti, bustine singole, ecc.)</small>
                    </div>
                `;
            }
            
            resultsDiv.innerHTML = `
                ${summaryHtml}
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Fonte</th>
                                <th>Titolo</th>
                                <th>Prezzo</th>
                                <th>Venditore</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${data.results.map(r => `
                                <tr>
                                    <td>${getSourceBadge(r.source)}</td>
                                    <td><a href="${r.url}" target="_blank">${escapeHtml((r.title || '').substring(0, 50))}...</a></td>
                                    <td><strong>€${(r.price || 0).toFixed(2)}</strong></td>
                                    <td>${escapeHtml(r.seller_name || '-')}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
                <small class="text-muted">Trovati ${data.results.length} risultati${source !== 'both' ? '' : ' (ordinati per prezzo)'}</small>
            `;
        }
    } catch (e) {
        resultsDiv.innerHTML = `<div class="alert alert-danger">Errore: ${e.message}</div>`;
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-search"></i> Cerca';
}

async function createMonitorsForAll() {
    const btn = document.getElementById('btn-monitor-all');
    const resultDiv = document.getElementById('action-result');
    
    const confirmed = confirm(
        'Vuoi creare monitor per i prodotti SEALED?\n\n' +
        '✅ Esclude automaticamente carte singole (001/191, etc.)\n' +
        '✅ Ogni monitor cerca su Google + eBay insieme\n' +
        '✅ Risparmio crediti API\n\n' +
        '⚠️ Limiti API:\n' +
        '   • SerpAPI (Google): 100/mese (free)\n' +
        '   • eBay: 5000/giorno (free)\n\n' +
        'Continuare?'
    );
    
    if (!confirmed) return;
    
    btn.disabled = true;
    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
    
    try {
        const res = await fetch('/api/monitors/create-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ price_tolerance: 50, language: 'it' })
        });
        const data = await res.json();
        
        resultDiv.style.display = 'block';
        
        if (data.error) {
            resultDiv.className = 'alert alert-warning';
            resultDiv.innerHTML = `<i class="bi bi-exclamation-triangle"></i> ${data.error}<br><small>${data.message || ''}</small>`;
        } else {
            resultDiv.className = 'alert alert-success';
            let msg = `<i class="bi bi-check-circle"></i> <strong>${data.created} monitor creati!</strong><br>`;
            if (data.skipped_single_cards > 0) {
                msg += `<small class="text-warning">Escluse ${data.skipped_single_cards} carte singole</small><br>`;
            }
            msg += `<small>${data.skipped} già esistenti</small>`;
            msg += `<div class="mt-2"><a href="/monitors" class="btn btn-sm btn-success">Vai ai Monitor</a></div>`;
            resultDiv.innerHTML = msg;
        }
    } catch (e) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-danger';
        resultDiv.innerHTML = `<i class="bi bi-x-circle"></i> Errore: ${e.message}`;
    }
    
    btn.disabled = false;
    btn.innerHTML = originalHtml;
}

async function cleanupSingleCards() {
    const confirmed = confirm(
        'ELIMINARE DEFINITIVAMENTE tutte le carte singole?\n\n' +
        'Verranno eliminati:\n' +
        '• PRODOTTI (dal database locale)\n' +
        '• MONITOR associati\n' +
        '• PREZZI raccolti\n\n' +
        'Pattern eliminati: 001/191, 204/182, etc.\n\n' +
        '✅ Risparmierai crediti API\n' +
        '✅ I prodotti sealed rimarranno\n\n' +
        'Questa operazione è irreversibile. Continuare?'
    );
    
    if (!confirmed) return;
    
    const btn = document.getElementById('btn-cleanup-singles');
    const resultDiv = document.getElementById('action-result');
    
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Eliminazione...';
    
    try {
        const res = await fetch('/api/monitors/cleanup-single-cards', { method: 'POST' });
        const data = await res.json();
        
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-success';
        let msg = `<i class="bi bi-check-circle"></i> <strong>Pulizia completata</strong><br>`;
        msg += `🗑️ ${data.deleted_products || 0} prodotti eliminati<br>`;
        msg += `📊 ${data.deleted_monitors || 0} monitor eliminati<br>`;
        msg += `💰 ${data.deleted_records || 0} record prezzi eliminati`;
        resultDiv.innerHTML = msg;
    } catch (e) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'alert alert-danger';
        resultDiv.innerHTML = `<i class="bi bi-x-circle"></i> Errore: ${e.message}`;
    }
    
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-trash"></i> Pulisci Carte Singole';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
