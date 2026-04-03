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
    
    # Limiti gratuiti Gemini 1.5 Flash
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
    
    def generate_search_query(self, product_name, product_price=None):
        """
        Genera una query di ricerca ottimizzata per trovare il prodotto corretto.
        Usa Gemini per capire il tipo di prodotto e creare una query precisa.
        """
        if not self.is_configured():
            return product_name, "Gemini non configurato"
        
        if not self.can_make_request():
            return product_name, "Limite giornaliero raggiunto"
        
        price_hint = f"\nPrezzo: €{product_price:.2f}" if product_price else ""
        
        prompt = f"""Sei un esperto di prodotti TCG (Pokémon, Magic, Yu-Gi-Oh, Lorcana, One Piece).

COMPITO: Genera una QUERY DI RICERCA ottimizzata per Google Shopping/eBay per trovare ESATTAMENTE questo prodotto.

NOME PRODOTTO: {product_name}{price_hint}

REGOLE:
1. Identifica il TIPO di prodotto (Display/Box, Bundle, ETB, Tin, Blister, Collection, Booster Pack)
2. Identifica l'ESPANSIONE/SET (es. "Scarlatto e Violetto", "151", "Fiamme Ossidiana")
3. Identifica eventuali VARIANTI (es. "Charizard", "Pikachu", "Mid Autumn")
4. Includi il NUMERO DI BUSTE se rilevante (36, 24, 6, 3)
5. Specifica la LINGUA se indicata (ITA, ENG, JAP)
6. RIMUOVI parole inutili come "TCG", "Trading Card Game", "(CHN)", codici interni

FORMATO RISPOSTA:
QUERY: [la query ottimizzata]
TIPO: [tipo prodotto]
NOTE: [breve spiegazione]

Esempio:
Input: "151 Charizard Travel Gift Box – Set da Viaggio (CHN)"
Output:
QUERY: Pokemon 151 Charizard Gift Box Set Viaggio
TIPO: Gift Box
NOTE: Gift Box speciale 151 con Charizard"""

        try:
            response = requests.post(
                f"{self.API_URL}?key={self.api_key}",
                headers={'Content-Type': 'application/json'},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 150
                    }
                },
                timeout=15
            )
            
            if response.status_code != 200:
                print(f"[Gemini] Query generation error: {response.status_code}")
                return product_name, f"Errore API: {response.status_code}"
            
            self._increment_counter()
            
            data = response.json()
            result_text = data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '').strip()
            
            # Estrai la query dalla risposta
            query = product_name  # default
            product_type = "unknown"
            
            for line in result_text.split('\n'):
                line = line.strip()
                if line.startswith('QUERY:'):
                    query = line.replace('QUERY:', '').strip()
                elif line.startswith('TIPO:'):
                    product_type = line.replace('TIPO:', '').strip()
            
            print(f"[Gemini] Generated query: '{query}' (type: {product_type})")
            return query, product_type
            
        except Exception as e:
            print(f"[Gemini] Query generation error: {e}")
            return product_name, f"Errore: {str(e)[:50]}"
    
    def _get_feedback_examples(self, search_query, limit=6):
        """Recupera esempi di feedback per few-shot learning"""
        try:
            from app.models import ProductFeedback
            
            # Prendi gli ultimi N feedback (metà corretti, metà errati)
            correct = ProductFeedback.query.filter_by(is_correct_match=True)\
                .order_by(ProductFeedback.created_at.desc()).limit(limit // 2).all()
            incorrect = ProductFeedback.query.filter_by(is_correct_match=False)\
                .order_by(ProductFeedback.created_at.desc()).limit(limit // 2).all()
            
            examples = []
            
            if correct:
                examples.append("\nESEMPI DI MATCH CORRETTI (validati dall'utente):")
                for fb in correct:
                    examples.append(f"✅ Query: \"{fb.search_query[:50]}\" → \"{fb.found_title[:60]}\" €{fb.found_price:.2f}")
            
            if incorrect:
                examples.append("\nESEMPI DI MATCH ERRATI (rifiutati dall'utente):")
                for fb in incorrect:
                    examples.append(f"❌ Query: \"{fb.search_query[:50]}\" → \"{fb.found_title[:60]}\" €{fb.found_price:.2f}")
            
            return "\n".join(examples) if examples else ""
        except Exception as e:
            print(f"[Gemini] Error getting feedback: {e}")
            return ""
    
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
        
        # Aggiungi esempi dal feedback utente (few-shot learning)
        feedback_examples = self._get_feedback_examples(searched_product)
        
        prompt = f"""Sei un esperto di prodotti TCG sealed (Pokémon, Magic, Yu-Gi-Oh, Lorcana).

COMPITO: Verifica se il PRODOTTO TROVATO è ESATTAMENTE lo stesso del PRODOTTO CERCATO.

CERCATO: {searched_product}{price_context}
TROVATO: {found_title} - €{found_price:.2f}

CRITERI DI VALIDITÀ (TUTTI devono essere soddisfatti):

1. TIPO PRODOTTO IDENTICO:
   - Display/Box (36 buste) ≠ Bundle (6 buste) ≠ ETB ≠ Tin ≠ Blister (3 buste) ≠ Collection
   - Il NUMERO di buste DEVE corrispondere esattamente

2. ESPANSIONE/SET IDENTICO:
   - "Scarlatto e Violetto" ≠ "Fiamme Ossidiana" ≠ "Destini di Paldea"
   - "151" si riferisce SOLO all'espansione 151, non altri set

3. PERSONAGGIO/VARIANTE (se specificato):
   - "Charizard" ≠ "Pikachu" ≠ "Mewtwo"
   - Se il nome cerca "Charizard", il trovato DEVE contenere Charizard

4. ESCLUSIONI AUTOMATICHE:
   - Carte singole, buste singole, lotti, usati, accessori → NON_VALIDO
{feedback_examples}

Rispondi SOLO:
VALIDO
oppure
NON_VALIDO:motivo"""

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
        
        # Aggiungi esempi dal feedback utente
        feedback_examples = self._get_feedback_examples(searched_product)
        
        prompt = f"""Sei un esperto di prodotti TCG sealed (Pokémon, Magic, Yu-Gi-Oh, Lorcana).

PRODOTTO CERCATO: {searched_product}{price_context}

PRODOTTI DA VERIFICARE:
{products_list}

CRITERI STRETTI - Un prodotto è VALIDO SOLO se soddisfa TUTTI questi criteri:

1. STESSO TIPO PRODOTTO ESATTO:
   - Display/Box 36 buste ≠ Bundle 6 buste ≠ ETB ≠ Tin ≠ Blister ≠ Collection ≠ UPC
   - Il numero di buste DEVE corrispondere esattamente

2. STESSA ESPANSIONE/SET:
   - "Ascesa Eroica" ≠ "Fiamme Ossidiana" ≠ "Scarlatto e Violetto" ≠ "151"
   - Anche nomi tradotti (es. "Chilling Reign" = "Regno Glaciale") sono la STESSA espansione

3. STESSO PERSONAGGIO/VARIANTE (se specificato nel prodotto cercato):
   - Se cerca "Charizard", DEVE contenere Charizard

NON_VALIDO AUTOMATICO se il prodotto trovato è:
- Carta singola, busta singola, lotto, usato, aperto
- Accessorio (sleeves, deck box, album, binder, playmat, toploader)
- Brand accessori (Ultra Pro, Ultimate Guard, Dragon Shield, Gamegenic)
- Espansione/set DIVERSO da quello cercato
- Tipo prodotto diverso (es. cerca Display, trova Bundle)
{feedback_examples}

Rispondi con UNA RIGA per prodotto, NIENT'ALTRO:
1:VALIDO oppure 1:NON_VALIDO
2:VALIDO oppure 2:NON_VALIDO
..."""

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
