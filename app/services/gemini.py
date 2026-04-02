import requests
from flask import current_app
from datetime import datetime, date

class GeminiService:
    """Servizio per validazione intelligente prodotti usando Gemini AI"""
    
    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    
    # Tracking utilizzo (in memoria, reset al restart)
    _requests_today = 0
    _last_request_date = None
    _total_requests = 0
    _errors_count = 0
    
    # Limiti gratuiti Gemini 2.0 Flash
    DAILY_LIMIT = 1500  # richieste/giorno gratis
    RPM_LIMIT = 15  # richieste/minuto
    
    def __init__(self):
        self.api_key = current_app.config.get('GEMINI_API_KEY', '')
    
    def is_configured(self):
        return bool(self.api_key)
    
    def _check_daily_reset(self):
        """Reset contatore giornaliero se è un nuovo giorno"""
        today = date.today()
        if GeminiService._last_request_date != today:
            GeminiService._requests_today = 0
            GeminiService._last_request_date = today
    
    def get_usage_stats(self):
        """Ritorna statistiche di utilizzo"""
        self._check_daily_reset()
        return {
            'requests_today': GeminiService._requests_today,
            'daily_limit': self.DAILY_LIMIT,
            'remaining_today': max(0, self.DAILY_LIMIT - GeminiService._requests_today),
            'total_requests': GeminiService._total_requests,
            'errors_count': GeminiService._errors_count,
            'usage_percent': round((GeminiService._requests_today / self.DAILY_LIMIT) * 100, 1),
        }
    
    def get_usage_warning(self):
        """Ritorna un warning se i crediti sono bassi"""
        stats = self.get_usage_stats()
        remaining = stats['remaining_today']
        
        if remaining <= 0:
            return {'level': 'critical', 'message': 'Crediti Gemini esauriti per oggi!'}
        elif remaining <= 50:
            return {'level': 'danger', 'message': f'Solo {remaining} richieste Gemini rimanenti oggi!'}
        elif remaining <= 200:
            return {'level': 'warning', 'message': f'{remaining} richieste Gemini rimanenti oggi'}
        return None
    
    def can_make_request(self):
        """Verifica se possiamo fare una richiesta"""
        self._check_daily_reset()
        return GeminiService._requests_today < self.DAILY_LIMIT
    
    def _increment_counter(self):
        """Incrementa contatori dopo una richiesta"""
        self._check_daily_reset()
        GeminiService._requests_today += 1
        GeminiService._total_requests += 1
    
    def validate_product_match(self, searched_product, found_title, found_price, your_price=None):
        """
        Usa Gemini AI per validare se un prodotto trovato corrisponde a quello cercato.
        
        Returns:
            bool: True se il prodotto è valido, False altrimenti
            str: Motivo della decisione (per debug)
        """
        if not self.is_configured():
            return True, "Gemini non configurato"
        
        if not self.can_make_request():
            return True, "Limite giornaliero Gemini raggiunto"
        
        # Costruisci il prompt
        price_context = f"\nPrezzo atteso: circa €{your_price:.2f}" if your_price else ""
        
        prompt = f"""Sei un esperto di prodotti TCG (Trading Card Game) come Pokémon, Magic, Yu-Gi-Oh, Lorcana.

Devi verificare se il PRODOTTO TROVATO corrisponde ESATTAMENTE al PRODOTTO CERCATO.

PRODOTTO CERCATO: {searched_product}{price_context}
PRODOTTO TROVATO: {found_title} - €{found_price:.2f}

REGOLE IMPORTANTI:
1. Il TIPO di prodotto deve corrispondere:
   - "Display" o "Box" (36 buste) ≠ "Bundle" (6 buste) ≠ "ETB" ≠ "Tin" ≠ "Blister"
   - Verifica il NUMERO di buste/carte se indicato
2. L'ESPANSIONE/SET deve corrispondere (es. "Fiamme Spettrali" ≠ "Corona Astrale")
3. La LINGUA deve corrispondere se specificata (IT ≠ EN ≠ JP)
4. NON sono validi: carte singole, lotti, prodotti usati, accessori

Rispondi SOLO con UNA di queste opzioni:
VALIDO - se il prodotto corrisponde
NON_VALIDO:motivo breve - se non corrisponde"""

        try:
            response = requests.post(
                f"{self.API_URL}?key={self.api_key}",
                headers={'Content-Type': 'application/json'},
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "temperature": 0.1,  # Bassa temperatura = risposte più deterministiche
                        "maxOutputTokens": 50
                    }
                },
                timeout=10
            )
            
            if response.status_code != 200:
                error_detail = response.text[:500] if response.text else "No response body"
                print(f"[Gemini] API error {response.status_code}: {error_detail}")
                GeminiService._errors_count += 1
                return True, f"Errore API: {response.status_code}"
            
            # Richiesta OK - incrementa contatore
            self._increment_counter()
            
            data = response.json()
            
            # Estrai la risposta
            result_text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip()
            
            if result_text.startswith('VALIDO'):
                return True, "Validato da Gemini AI"
            elif result_text.startswith('NON_VALIDO'):
                reason = result_text.replace('NON_VALIDO:', '').replace('NON_VALIDO', '').strip()
                return False, f"Gemini: {reason}" if reason else "Gemini: prodotto non corrispondente"
            else:
                print(f"[Gemini] Risposta non chiara: {result_text}")
                return True, f"Risposta ambigua: {result_text[:50]}"
                
        except requests.Timeout:
            print("[Gemini] Timeout")
            GeminiService._errors_count += 1
            return True, "Timeout Gemini"
        except Exception as e:
            print(f"[Gemini] Error: {e}")
            GeminiService._errors_count += 1
            return True, f"Errore: {str(e)[:50]}"
    
    def batch_validate(self, searched_product, items, your_price=None, max_items=20):
        """
        Valida un batch di prodotti in una singola chiamata (più efficiente).
        
        Returns:
            dict: {index: (is_valid, reason)}
        """
        if not self.is_configured() or not items:
            return {i: (True, "Gemini non configurato") for i in range(len(items))}
        
        if not self.can_make_request():
            return {i: (True, "Limite giornaliero raggiunto") for i in range(len(items))}
        
        # Limita il numero di items per evitare prompt troppo lunghi
        items_to_check = items[:max_items]
        
        # Costruisci lista prodotti
        products_list = "\n".join([
            f"{i+1}. {item.get('title', 'N/A')} - €{item.get('price', 0):.2f}"
            for i, item in enumerate(items_to_check)
        ])
        
        price_context = f"\nPrezzo atteso: circa €{your_price:.2f}" if your_price else ""
        
        prompt = f"""Sei un esperto di prodotti TCG (Pokémon, Magic, Yu-Gi-Oh, Lorcana).

PRODOTTO CERCATO: {searched_product}{price_context}

PRODOTTI TROVATI:
{products_list}

Per OGNI prodotto, verifica se corrisponde ESATTAMENTE al prodotto cercato.
Considera: tipo prodotto (Display/Bundle/ETB/Tin), numero buste, espansione, lingua.

Rispondi con UNA RIGA per prodotto nel formato:
NUMERO:VALIDO oppure NUMERO:NON_VALIDO

Esempio:
1:VALIDO
2:NON_VALIDO
3:VALIDO"""

        try:
            response = requests.post(
                f"{self.API_URL}?key={self.api_key}",
                headers={'Content-Type': 'application/json'},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 200
                    }
                },
                timeout=15
            )
            
            if response.status_code != 200:
                print(f"[Gemini] Batch error: {response.status_code}")
                GeminiService._errors_count += 1
                return {i: (True, "Errore API") for i in range(len(items_to_check))}
            
            # Richiesta OK - incrementa contatore
            self._increment_counter()
            
            data = response.json()
            result_text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip()
            
            # Parse risultati
            results = {}
            for line in result_text.split('\n'):
                line = line.strip()
                if ':' in line:
                    parts = line.split(':')
                    try:
                        idx = int(parts[0]) - 1  # Converti a 0-indexed
                        is_valid = 'VALIDO' in parts[1].upper() and 'NON' not in parts[1].upper()
                        results[idx] = (is_valid, "Gemini AI")
                    except (ValueError, IndexError):
                        continue
            
            # Riempi i mancanti (assume valido)
            for i in range(len(items_to_check)):
                if i not in results:
                    results[i] = (True, "Non verificato")
            
            # Per items oltre il limite, assume valido
            for i in range(len(items_to_check), len(items)):
                results[i] = (True, "Oltre limite batch")
            
            return results
            
        except Exception as e:
            print(f"[Gemini] Batch error: {e}")
            GeminiService._errors_count += 1
            return {i: (True, f"Errore: {str(e)[:30]}") for i in range(len(items))}
