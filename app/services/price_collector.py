import re
from datetime import datetime
from app import db
from app.models import Monitor, PriceRecord
from app.services.serpapi import SerpAPIService
from app.services.ebay import EbayService
from app.services.gemini import GeminiService

class PriceCollector:
    
    # Keywords che indicano prodotti NON desiderati
    NEGATIVE_KEYWORDS = [
        # Lotti e multipli
        'lot ', ' lot', 'lotto', 'lotti',
        '2x', '3x', '4x', '5x', '6x', '10x',
        'x2 ', 'x3 ', 'x4 ', 'x5 ', 'x6 ', 'x10',
        
        # Usato/aperto/danneggiato
        'empty', 'vuoto', 'vuota', 'no cards', 'senza carte',
        'opened', 'aperto', 'aperta', 'used', 'usato', 'usata',
        'damaged', 'danneggiato', 'danneggiata',
        
        # Falsi/custom
        'fake', 'replica', 'proxy', 'custom', 'unofficial', 'fan made',
        
        # Repacked
        'repack', 'repacked', 'resealed', 'riconfezionato',
        
        # Carte singole / gradate
        'singola', 'singolo', 'single',
        'raw', 'psa ', 'bgs ', 'cgc ', 'graded', 'gradato',
        
        # Accessori
        'sleeves', 'bustine protettive', 'deck box', 'playmat', 'tappetino',
    ]
    
    # Keywords per lingua straniera (da escludere se lingua='it' o 'en')
    FOREIGN_LANGUAGE_KEYWORDS = {
        'ja': ['japanese', 'japan', 'jap ', 'giapponese', 'giapp', '日本語', 'jp'],
        'ko': ['korean', 'coreano', 'corea', '한국어', 'kr'],
        'zh': ['chinese', 'cinese', 'cina', '中文', 'cn', 'taiwan'],
        'de': ['german', 'tedesco', 'deutsch'],
        'fr': ['french', 'francese', 'français'],
        'es': ['spanish', 'spagnolo', 'español'],
        'pt': ['portuguese', 'portoghese', 'português'],
    }
    
    # Parole da ignorare nel matching
    IGNORE_WORDS = {
        'di', 'del', 'della', 'dei', 'degli', 'delle', 
        'e', 'o', 'a', 'da', 'in', 'con', 'su', 'per', 'tra', 'fra',
        'the', 'an', 'of', 'and', 'or', 'for', 'to', 'with',
        '-', '–', ':', '(', ')', '[', ']', '|',
        'pokemon', 'pokémon', 'tcg', 'card', 'cards', 'carte',
        'yu', 'gi', 'oh', 'yugioh',
        'magic', 'mtg', 'gathering',
        'sealed', 'sigillato', 'sigillata', 'new', 'nuovo', 'nuova',
    }
    
    # Keywords importanti che DEVONO matchare se presenti
    PRODUCT_TYPE_KEYWORDS = {
        'booster', 'box', 'display', 'bundle', 'etb', 'elite', 'trainer',
        'blister', 'pack', 'tin', 'collection', 'premium', 'ultra',
        'starter', 'deck', 'theme', 'structure',
        '36', '24', '18', '12', '10', '6', '3',
    }
    
    # Toggle globale per validazione AI (può essere disabilitato se finiscono crediti)
    _use_ai_validation = True
    
    def __init__(self):
        self.serpapi = SerpAPIService()
        self.ebay = EbayService()
        self.gemini = GeminiService()
    
    @classmethod
    def set_ai_validation(cls, enabled):
        """Abilita/disabilita validazione AI"""
        cls._use_ai_validation = enabled
        print(f"[PriceCollector] AI validation: {'ENABLED' if enabled else 'DISABLED'}")
    
    @classmethod
    def is_ai_validation_enabled(cls):
        return cls._use_ai_validation
    
    @classmethod
    def build_smart_queries(cls, product_name):
        """
        Genera query di ricerca ottimizzate dal nome prodotto.
        Strategia: espansione + quantità (es. "Caos Nascente 36 buste").
        Ritorna una lista di query da eseguire (IT + EN).
        """
        name_lower = product_name.lower()

        # 1. Rileva il gioco (Pokemon, Magic, etc.)
        game = ''
        for g in ['pokemon', 'pokémon', 'magic', 'mtg', 'yugioh', 'yu-gi-oh', 'lorcana', 'one piece', 'digimon', 'dragon ball', 'altered', 'flesh and blood']:
            if g in name_lower:
                game = g.replace('pokémon', 'pokemon').replace('yu-gi-oh', 'yugioh')
                break

        # 2. Estrai quantità + unità (es. "36 buste", "6 buste", "10 carte")
        quantity_match = re.search(r'(\d+)\s*(buste|bustine|booster|pack|packs|carte|cards|busta)', name_lower)
        quantity_str = quantity_match.group(0).strip() if quantity_match else ''

        # 3. Rileva espansione IT e traduci in EN
        expansion_it = ''
        expansion_en = ''
        sorted_expansions = sorted(cls.EXPANSION_IT_TO_EN.items(), key=lambda x: len(x[0]), reverse=True)
        for it_name, en_name in sorted_expansions:
            if it_name in name_lower:
                expansion_it = it_name
                expansion_en = en_name
                break

        # Se non trovata in mappa, prova a estrarre l'espansione rimuovendo parti note
        if not expansion_it:
            clean = name_lower
            for remove in [game, 'display', 'booster', 'box', 'bundle', 'etb', 'elite trainer',
                          'set allenatore', 'allenatore fuoriclasse', 'collezione', 'collection',
                          'tin', 'latta', 'blister', 'buste', 'busta', 'bustine', 'pack', 'packs',
                          'sealed', 'sigillato', 'tcg', 'gcc', '(it)', '(en)', '(jp)', '–', '-',
                          'mega evoluzione', 'megaevoluzione']:
                clean = clean.replace(remove, ' ')
            clean = re.sub(r'\b\d+\b', '', clean)
            clean = re.sub(r'\s+', ' ', clean).strip()
            if len(clean) > 2:
                expansion_it = clean

        # 4. Rileva tipo prodotto per query EN (solo per traduzione, non per query IT)
        product_type_en = ''
        sorted_types = sorted(cls.PRODUCT_TYPE_IT_TO_EN.items(), key=lambda x: len(x[0]), reverse=True)
        for it_type, en_type in sorted_types:
            if it_type in name_lower:
                product_type_en = en_type
                break

        # 5. Costruisci le query — SEMPLICI: espansione + quantità
        queries = []

        # Query IT: espansione + quantità (es. "Caos Nascente 36 buste")
        if expansion_it and quantity_str:
            q_it = f"{expansion_it} {quantity_str}".strip()
            q_it = re.sub(r'\s+', ' ', q_it)
            queries.append(q_it)
        elif expansion_it:
            # Nessuna quantità: usa espansione + tipo prodotto generico
            q_it = f"{expansion_it}".strip()
            queries.append(q_it)

        # Query EN: espansione tradotta + tipo prodotto EN
        if expansion_en:
            q_en = f"{expansion_en} {product_type_en}".strip()
            q_en = re.sub(r'\s+', ' ', q_en)
            if q_en not in queries:
                queries.append(q_en)

        # Query con gioco + espansione (per risultati Google più mirati)
        if game and expansion_it:
            q_game = f"{game} {expansion_it} {quantity_str}".strip()
            q_game = re.sub(r'\s+', ' ', q_game)
            if q_game not in queries:
                queries.append(q_game)

        # Fallback: query originale se nessuna generata
        if not queries:
            queries.append(product_name)

        print(f"[SmartQuery] '{product_name[:60]}' -> {queries}")
        return queries

    def collect_for_monitor(self, monitor):
        """Raccoglie prezzi da tutte le fonti configurate per un monitor"""
        results = {
            'total_results': 0,
            'saved': 0,
            'valid': 0,
            'skipped_duplicates': 0,
            'sources': {}
        }

        your_price = monitor.product.price if monitor.product else None
        language = getattr(monitor, 'language', 'it') or 'it'
        source = getattr(monitor, 'source', 'all') or 'all'

        # Determina quali fonti usare
        sources_to_use = []
        if source == 'all':
            sources_to_use = ['google_shopping', 'google_web', 'ebay']
        elif source == 'both':  # Legacy: google_shopping + ebay
            sources_to_use = ['google_shopping', 'ebay']
        elif source == 'google':  # Entrambi i Google
            sources_to_use = ['google_shopping', 'google_web']
        else:
            sources_to_use = [source]

        # Genera query smart (IT + EN) dal nome prodotto
        product_name = monitor.product.name if monitor.product else monitor.search_query
        smart_queries = self.build_smart_queries(product_name)
        # Includi anche la search_query originale se diversa
        original_query = monitor.search_query
        all_queries = list(dict.fromkeys(smart_queries + [original_query]))  # deduplica mantenendo ordine

        all_items = []
        seen_titles = set()  # dedup tra query diverse

        # Raccogli da ogni fonte PER OGNI QUERY
        for query in all_queries:
            for src in sources_to_use:
                if src == 'google_shopping' and self.serpapi.is_configured():
                    result = self.serpapi.search(query, num_results=30)
                    for item in result.get('results', []):
                        title_key = item.get('title', '').lower().strip()
                        if title_key not in seen_titles:
                            seen_titles.add(title_key)
                            item['source'] = 'google_shopping'
                            all_items.append(item)
                    results['sources']['google_shopping'] = results['sources'].get('google_shopping', 0) + len(result.get('results', []))

                elif src == 'google_web' and self.serpapi.is_configured():
                    result = self.serpapi.search_web(query, num_results=20)
                    for item in result.get('results', []):
                        title_key = item.get('title', '').lower().strip()
                        if title_key not in seen_titles:
                            seen_titles.add(title_key)
                            item['source'] = 'google_web'
                            all_items.append(item)
                    results['sources']['google_web'] = results['sources'].get('google_web', 0) + len(result.get('results', []))

                elif src == 'ebay' and self.ebay.is_configured():
                    result = self.ebay.search(query, num_results=30)
                    for item in result.get('results', []):
                        title_key = item.get('title', '').lower().strip()
                        if title_key not in seen_titles:
                            seen_titles.add(title_key)
                            item['source'] = 'ebay'
                            all_items.append(item)
                    results['sources']['ebay'] = results['sources'].get('ebay', 0) + len(result.get('results', []))
        
        if not all_items:
            return {'error': 'Nessuna fonte configurata o nessun risultato', **results}
        
        results['total_results'] = len(all_items)
        results['ai_validated'] = 0
        results['ai_rejected'] = 0
        today = datetime.utcnow().date()
        
        # STEP 1: Pre-filtra con regole base (prezzo, keywords negativi)
        # Ogni item riceve un indice globale per tracciamento AI
        for idx, item in enumerate(all_items):
            item['_global_idx'] = idx
            item['_basic_valid'] = self._validate_result(
                item, your_price, monitor.price_tolerance,
                monitor.search_query, language
            )

        # STEP 2: Validazione AI con Gemini (solo se abilitato e configurato)
        items_for_ai = [item for item in all_items if item['_basic_valid']]

        # Mappa: global_idx -> (is_valid, reason) da Gemini
        ai_decision = {}
        use_ai = PriceCollector._use_ai_validation and self.gemini.is_configured() and self.gemini.can_make_request()

        if items_for_ai and use_ai:
            print(f"[Gemini] Validating {len(items_for_ai)} items for: {monitor.search_query[:50]}...")
            batch_results = self.gemini.batch_validate(
                monitor.search_query,
                items_for_ai,
                your_price,
                max_items=20
            )
            # Mappa i risultati batch (indice locale) -> indice globale
            for local_idx, (is_valid, reason) in batch_results.items():
                if local_idx < len(items_for_ai):
                    global_idx = items_for_ai[local_idx]['_global_idx']
                    ai_decision[global_idx] = (is_valid, reason)
        elif items_for_ai and not use_ai:
            print(f"[PriceCollector] AI validation skipped (disabled or no credits)")

        # STEP 3: Salva risultati
        for item in all_items:
            basic_valid = item.pop('_basic_valid', True)
            global_idx = item.pop('_global_idx', -1)

            # Determina validità finale
            if not basic_valid:
                is_valid = False
            elif global_idx in ai_decision:
                is_valid, reason = ai_decision[global_idx]
                if is_valid:
                    results['ai_validated'] += 1
                else:
                    results['ai_rejected'] += 1
                    print(f"[Gemini] Rejected: {item.get('title', '')[:60]}... - {reason}")
            else:
                is_valid = basic_valid
            
            if is_valid:
                results['valid'] += 1
            
            seller_name = item.get('seller_name', '')[:255] if item.get('seller_name') else None
            item_source = item.get('source', 'unknown')
            
            # Evita duplicati: stesso monitor + stesso venditore + stessa fonte + stesso giorno
            existing = PriceRecord.query.filter(
                PriceRecord.monitor_id == monitor.id,
                PriceRecord.seller_name == seller_name,
                PriceRecord.source == item_source,
                db.func.date(PriceRecord.fetched_at) == today
            ).first()
            
            if existing:
                if existing.price != item['price']:
                    existing.price = item['price']
                    existing.is_valid = is_valid
                    existing.fetched_at = datetime.utcnow()
                results['skipped_duplicates'] += 1
                continue
            
            record = PriceRecord(
                monitor_id=monitor.id,
                title=item['title'][:500],
                price=item['price'],
                currency=item.get('currency', 'EUR'),
                seller_name=seller_name,
                seller_rating=item.get('seller_rating'),
                url=item.get('url', '')[:2000],
                source=item_source,
                is_valid=is_valid,
                fetched_at=datetime.utcnow(),
            )
            
            db.session.add(record)
            results['saved'] += 1
        
        monitor.last_run_at = datetime.utcnow()
        db.session.commit()
        
        return results
    
    # Domini del proprio negozio da escludere dai competitor
    OWN_STORE_DOMAINS = None

    @classmethod
    def _get_own_domains(cls):
        """Estrae i domini del proprio negozio da WC_URL (cached)"""
        if cls.OWN_STORE_DOMAINS is None:
            from flask import current_app
            wc_url = current_app.config.get('WC_URL', '')
            domains = set()
            if wc_url:
                # Estrai dominio da URL (es. "https://scimmia.it" -> "scimmia.it", "scimmia")
                import re
                match = re.search(r'://(?:www\.)?([^/]+)', wc_url)
                if match:
                    full_domain = match.group(1).lower()
                    domains.add(full_domain)                    # es. "scimmia.it"
                    domains.add(full_domain.split('.')[0])       # es. "scimmia"
            cls.OWN_STORE_DOMAINS = domains
        return cls.OWN_STORE_DOMAINS

    def _validate_result(self, item, your_price, tolerance, search_query, language='it'):
        """Valida un risultato con logica intelligente per TCG sealed products"""
        title = item.get('title', '')
        title_lower = title.lower()
        query_lower = search_query.lower()
        price = item.get('price', 0)

        # ========== 0. ESCLUDI IL PROPRIO NEGOZIO ==========
        own_domains = self._get_own_domains()
        if own_domains:
            seller = (item.get('seller_name') or '').lower()
            url = (item.get('url') or '').lower()
            for domain in own_domains:
                if domain in seller or domain in url:
                    return False

        # ========== 1. FILTRO PREZZO (usa tolerance del monitor) ==========
        tolerance_pct = tolerance if tolerance and tolerance > 0 else 40
        if your_price and your_price > 0:
            min_price = your_price * (1 - tolerance_pct / 100)
            max_price = your_price * (1 + tolerance_pct / 100)
            if not (min_price <= price <= max_price):
                return False
        else:
            # Senza prezzo di riferimento, rifiuta prezzi assurdi (< €1 o > €5000)
            if price < 1 or price > 5000:
                return False
        
        # ========== 2. KEYWORDS NEGATIVE (esclusione immediata) ==========
        critical_negatives = [
            # Lotti/multipli
            'lot ', ' lot', 'lotto', 'lotti', 'bundle of', 'set of', 'x2', 'x3', 'x4', 'x5',
            # Usato/aperto
            'empty', 'vuoto', 'vuota', 'no cards', 'senza carte', 'opened', 'aperto',
            # Falsi
            'fake', 'replica', 'proxy', 'custom', 'unofficial', 'fan made',
            # Repacked
            'repack', 'repacked', 'resealed', 'riconfezionato',
            # Gradate
            'psa ', 'bgs ', 'cgc ', 'graded', 'gradato', 'gem mint',
            # Accessori - prodotti
            'sleeves', 'bustine protettive', 'deck box', 'playmat', 'tappetino',
            'binder', 'album foto', 'portfolio', 'raccoglitore',
            'toploader', 'top loader', 'card saver', 'one touch',
            'inner sleeve', 'penny sleeve', 'bustina protettiva',
            # Accessori - brand (non producono carte/sealed)
            'ultra pro', 'ultimate guard', 'dragon shield', 'gamegenic',
            'arkhive', 'xenoskin', 'alcove', 'vault x', 'bcw ',
            'sideloading', 'matte sleeve',
            # Carte singole
            'singola', 'singolo', 'single card', 'holo rare', 'full art', 'secret rare',
            # Carte singole - pattern prezzo basso
            'common', 'uncommon', 'rare holo', 'reverse holo',
        ]
        for keyword in critical_negatives:
            if keyword in title_lower:
                return False
        
        # ========== 3. FILTRO PRODOTTI NON-TCG ==========
        # Se il titolo non contiene NESSUN termine TCG, probabilmente è un accessorio
        tcg_indicators = [
            'pokemon', 'pokémon', 'magic', 'mtg', 'yugioh', 'yu-gi-oh',
            'lorcana', 'one piece', 'digimon', 'dragon ball', 'flesh and blood',
            'altered', 'weiss schwarz', 'cardfight', 'union arena',
            'booster', 'display', 'bundle', 'etb', 'blister', 'tin ',
            'buste', 'busta', 'espansione', 'expansion', 'collection',
            'scarlet', 'violet', 'scarlatto', 'violetto',
            'prismatic', 'obsidian', 'paldea', 'temporal', 'stellar',
            'surging', 'twilight', 'shrouded', 'sword', 'shield',
            'sealed', 'sigillato',
        ]
        has_tcg_term = any(term in title_lower for term in tcg_indicators)
        if not has_tcg_term:
            return False

        # ========== 4. MATCH TIPO PRODOTTO (critico!) ==========
        # Se cerco "Display 36" non voglio "Bundle 6" o "Blister 3"
        if not self._match_product_type_strict(query_lower, title_lower):
            return False
        
        # ========== 5. MATCH ESPANSIONE/SET ==========
        # Le parole chiave dell'espansione devono corrispondere
        if not self._match_expansion(query_lower, title_lower):
            return False

        # ========== 6. LINGUA ==========
        if language == 'it':
            foreign_keywords = ['japanese', 'giapponese', 'japan', 'korean', 'coreano', 
                               'chinese', 'cinese', 'china', 'german', 'tedesco']
            for kw in foreign_keywords:
                if kw in title_lower and kw not in query_lower:
                    return False
        
        return True
    
    def _match_product_type_strict(self, query, title):
        """Verifica STRETTAMENTE che il tipo di prodotto corrisponda"""

        # Categorie in ordine di PRIORITA (piu specifiche prima)
        # Ordine: upc > etb > collection > gift > case > booster_single > display > bundle > blister > tin
        product_categories = [
            ('upc', ['upc', 'ultra premium collection', 'ultra premium']),
            ('etb', ['etb', 'elite trainer', 'trainer box', 'set allenatore', 'allenatore fuoriclasse', 'collezione allenatore']),
            ('collection', ['collection box', 'collezione premium', 'premium collection', 'album collection', 'poster collection', 'binder collection', 'mini tin collection']),
            ('gift', ['gift set', 'gift box', 'set regalo']),
            ('case', ['case 6', 'case 10', 'case 12', ' case ', 'cassa']),
            ('booster_single', ['busta singola', 'bustina ', 'singola busta', 'single pack', 'single booster']),
            ('display', ['display', 'box 36', '36 buste', '36 booster', 'booster box', '36 pack', '24 buste', '24 booster', '24 pack']),
            ('bundle', ['bundle', '6 buste', '6 booster', '6 pack']),
            ('blister', ['blister', '3 buste', '3 booster', '3 pack', '2 buste', '2 booster', '2 pack', '1 busta', '1 booster', 'checklane']),
            ('tin', ['tin ', ' tin', 'latta']),
        ]

        def find_category(text):
            """Trova la categoria piu specifica (prima in ordine di priorita)"""
            for cat, keywords in product_categories:
                for kw in keywords:
                    if kw in text:
                        return cat
            return None

        query_category = find_category(query)

        if not query_category:
            return True  # Non riusciamo a determinare, passa

        title_category = find_category(title)

        # Se il titolo ha una categoria diversa -> INVALIDO
        if title_category and title_category != query_category:
            return False

        # Controlla numeri di buste/pack (regex ampliato per piu formati)
        num_pattern = r'(\d+)\s*[-]?\s*(?:buste|bustine|booster|pack|packs)'
        query_numbers = re.findall(num_pattern, query)
        title_numbers = re.findall(num_pattern, title)

        if query_numbers and title_numbers:
            # Confronta tutti i numeri trovati, non solo il primo
            q_set = set(query_numbers)
            t_set = set(title_numbers)
            # Se nessun numero in comune -> mismatch
            if not q_set & t_set:
                return False

        return True
    
    # Traduzione nomi espansioni IT -> EN (e viceversa) per matching e query
    EXPANSION_IT_TO_EN = {
        # Scarlet & Violet era
        'scarlatto e violetto': 'scarlet violet', 'scarlatto': 'scarlet', 'violetto': 'violet',
        'fiamme ossidiana': 'obsidian flames',
        'evoluzioni a paldea': 'paldea evolved',
        'forze temporali': 'temporal forces',
        'destino di paldea': 'paldean fates',
        'corona astrale': 'stellar crown',
        'scontro paradosso': 'paradox rift',
        'nebbie prismatiche': 'prismatic evolutions',
        'supercarica energetica': 'surging sparks',
        'crepuscolo mascherato': 'twilight masquerade',
        'scintille folgoranti': 'sparkling zero',
        'rivali predestinati': 'fated rivals',
        # Sword & Shield era
        'spada e scudo': 'sword shield',
        'stelle lucenti': 'brilliant stars',
        'tempesta argentata': 'silver tempest',
        'destini brillanti': 'shining fates',
        'voltaggio vivido': 'vivid voltage',
        'regno glaciale': 'chilling reign',
        'alleati evoluti': 'evolving skies',
        'celebrazioni': 'celebrations',
        'colpo fusione': 'fusion strike',
        'origine perduta': 'lost origin',
        'astri lucenti': 'astral radiance',
        'fiamme spettrali': 'phantom forces',
        # Sun & Moon era
        'sole e luna': 'sun moon',
        'ombre infuocate': 'burning shadows',
        'invasione scarlatta': 'crimson invasion',
        'ultraprisma': 'ultra prism',
        'tempesta celestiale': 'celestial storm',
        'tuoni perduti': 'lost thunder',
        'legami inossidabili': 'unbroken bonds',
        'eclissi cosmica': 'cosmic eclipse',
        'destino nascosto': 'hidden fates',
        # XY era
        'mega evoluzione': 'mega evolution',
        'megaevoluzione': 'mega evolution',
        'caos nascente': 'ancient origins',
        'furie volanti': 'roaring skies',
        'duello primordiale': 'primal clash',
        'origini antiche': 'ancient origins',
        'punto di rottura': 'breakpoint',
        'turbine spettrale': 'phantom forces',
        'vapori accesi': 'steam siege',
        'destini incrociati': 'fates collide',
        'generazioni': 'generations',
        'evoluzioni': 'evolutions',
        # Black & White era
        'nero e bianco': 'black white',
        'confini varcati': 'boundaries crossed',
        'glaciazione plasmatica': 'plasma freeze',
        # Diamond & Pearl / misc
        'diamante e perla': 'diamond pearl',
        # One Piece
        'mare di azzurrite': 'azurite sea',
        'sussurri nel pozzo': 'whispers in the well',
        # Lorcana
        'nelle terre d\'inchiostro': 'into the inklands',
        'lucentezza siderale': 'shimmering skies',
        'il ritorno di ursula': 'ursula\'s return',
        'cieli scintillanti': 'shimmering skies',
        'le terre d\'inchiostro': 'into the inklands',
    }

    # Tipo prodotto IT -> EN per query
    PRODUCT_TYPE_IT_TO_EN = {
        'display': 'booster box', 'booster box': 'booster box',
        'box 36 buste': 'booster box 36', 'box 24 buste': 'booster box 24',
        'bundle': 'bundle', 'etb': 'elite trainer box',
        'set allenatore fuoriclasse': 'elite trainer box',
        'set allenatore': 'elite trainer box',
        'collezione allenatore': 'elite trainer box',
        'tin': 'tin', 'latta': 'tin',
        'blister': 'blister', 'collection': 'collection',
        'album collection': 'album collection',
        'upc': 'ultra premium collection',
        'starter deck': 'starter deck', 'mazzo': 'starter deck',
    }

    def _match_expansion(self, query, title):
        """Verifica che l'espansione/set corrisponda (con traduzione IT->EN)"""

        # Parole comuni da ignorare nel matching
        common_words = {
            'pokemon', 'pokémon', 'tcg', 'card', 'cards', 'carte', 'box', 'display',
            'booster', 'bundle', 'pack', 'buste', 'busta', 'set', 'collection', 'collezione',
            'ita', 'ital', 'italiano', 'italiana', 'eng', 'english', 'inglese',
            'sealed', 'sigillato', 'new', 'nuovo', 'nuova', 'the', 'a', 'di', 'del',
            'della', 'e', 'and', 'or', 'with', 'con', 'per', 'for', 'in', 'da',
            'promo', 'carta', 'con', 'ultra', 'premium', 'mega', 'ex', 'gx', 'vmax',
            'vstar', 'tin', 'latta', 'elite', 'trainer', 'allenatore',
            'magic', 'mtg', 'gathering', 'yugioh', 'lorcana',
        }

        # Parole che indicano tipo prodotto (non espansione)
        type_words = {
            'display', 'box', 'booster', 'bundle', 'pack', 'buste', 'busta',
            'blister', 'tin', 'latta', 'etb', 'elite', 'trainer', 'collection',
            'collezione', 'upc', 'case', 'gift', 'starter', 'deck', 'theme',
            'structure', 'checklane', 'allenatore', 'fuoriclasse',
        }

        # Traduci la query IT -> EN per matchare titoli inglesi
        translated_query = query
        for it_name, en_name in self.EXPANSION_IT_TO_EN.items():
            if it_name in query:
                translated_query = translated_query.replace(it_name, en_name)

        # Estrai parole significative (lettere 3+ E numeri che sono nomi, es "151")
        query_words = set(re.findall(r'[a-zA-ZàèéìòùÀÈÉÌÒÙ]{3,}', query))
        translated_words = set(re.findall(r'[a-zA-ZàèéìòùÀÈÉÌÒÙ]{3,}', translated_query))
        # Aggiungi numeri significativi (nomi di espansioni come "151")
        query_numbers = set(re.findall(r'\b(\d{2,4})\b', query))
        # Filtra numeri generici di buste (36, 24, 6, 3, 10, 12, 18)
        pack_numbers = {'36', '24', '18', '12', '10', '6', '3', '1', '2'}
        significant_numbers = query_numbers - pack_numbers

        all_query_words = query_words | translated_words
        significant_query_words = [w for w in all_query_words if w not in common_words and w not in type_words]
        # Aggiungi numeri significativi come "parole" da matchare
        significant_query_words.extend(significant_numbers)

        if not significant_query_words:
            return True

        # Estrai parole dal titolo per word-boundary matching (no substring)
        title_words = set(re.findall(r'[a-zA-ZàèéìòùÀÈÉÌÒÙ]{3,}', title))
        title_words_lower = {w.lower() for w in title_words}
        # Aggiungi anche numeri dal titolo
        title_numbers = set(re.findall(r'\b(\d{2,4})\b', title))
        title_all = title_words_lower | title_numbers

        # Match: parola query deve essere ESATTAMENTE presente come parola nel titolo
        matches = sum(1 for w in significant_query_words if w.lower() in title_all)
        required = max(1, int(len(significant_query_words) * 0.75))

        return matches >= required
    
    def _match_product_type(self, search_query, title):
        """Verifica che il tipo di prodotto corrisponda"""
        query_lower = search_query.lower()
        
        # Trova quali tipi di prodotto sono nella query
        query_types = []
        for keyword in self.PRODUCT_TYPE_KEYWORDS:
            if keyword in query_lower:
                query_types.append(keyword)
        
        if not query_types:
            return True
        
        # Verifica che almeno uno dei tipi sia nel titolo
        for pt in query_types:
            if pt in title:
                continue
            # Se la query ha "box" ma il titolo ha "bundle" -> INVALID
            if pt in ['box', 'display'] and ('bundle' in title or 'tin' in title or 'blister' in title):
                return False
            if pt == 'bundle' and ('box' in title and 'display' in title):
                return False
            if pt == 'etb' and 'etb' not in title and 'elite trainer' not in title:
                return False
        
        # Verifica che il titolo non abbia tipi diversi non richiesti
        title_types = [k for k in self.PRODUCT_TYPE_KEYWORDS if k in title]
        for tt in title_types:
            if tt not in query_types:
                # Il titolo ha un tipo non richiesto
                if tt in ['bundle', 'etb', 'tin', 'blister', 'starter', 'deck', 'theme', 'structure']:
                    # Questi sono tipi specifici, se non richiesti -> invalid
                    if tt not in query_lower:
                        return False
        
        return True
    
    def _match_main_keywords(self, search_query, title):
        """Verifica che le parole chiave principali siano presenti - più permissivo"""
        query_words = re.findall(r'\w+', search_query.lower())
        
        # Filtra parole da ignorare
        significant_words = [
            w for w in query_words 
            if w not in self.IGNORE_WORDS 
            and w not in self.PRODUCT_TYPE_KEYWORDS
            and len(w) > 2
        ]
        
        if not significant_words:
            return True
        
        # Per carte singole (contengono numeri tipo 001/191), basta match parziale
        has_card_number = any(c.isdigit() for c in search_query)
        
        # Conta match
        matches = sum(1 for word in significant_words if word in title)
        
        # Per carte: basta 1 match. Per prodotti sealed: 40% match
        if has_card_number:
            required = 1
        else:
            required = max(1, int(len(significant_words) * 0.4))
        
        return matches >= required
    
    def _filter_results(self, results, search_query, your_price=None, tolerance=40, language='it'):
        """Filtra una lista di risultati"""
        valid_results = []
        for item in results:
            is_valid = self._validate_result(item, your_price, tolerance, search_query, language)
            item['is_valid'] = is_valid
            if is_valid:
                valid_results.append(item)
        return valid_results
    
    def test_search(self, source, query, filter_results=True, language='it'):
        """Test di ricerca su una o più fonti"""
        all_results = []
        total_raw = 0
        errors = {}
        
        # Mappa source a lista di fonti
        if source == 'all':
            sources = ['google_shopping', 'google_web', 'ebay']
        elif source == 'both':  # Legacy
            sources = ['google_shopping', 'ebay']
        elif source == 'google':
            sources = ['google_shopping', 'google_web']
        else:
            sources = [source]
        
        for src in sources:
            if src == 'google_shopping':
                if not self.serpapi.is_configured():
                    errors['google_shopping'] = 'Non configurato'
                    continue
                result = self.serpapi.search(query, num_results=30)
                for item in result.get('results', []):
                    item['source'] = 'google_shopping'
                    all_results.append(item)
                total_raw += len(result.get('results', []))
                if result.get('error'):
                    errors['google_shopping'] = result['error']
            
            elif src == 'google_web':
                if not self.serpapi.is_configured():
                    errors['google_web'] = 'Non configurato'
                    continue
                result = self.serpapi.search_web(query, num_results=20)
                for item in result.get('results', []):
                    item['source'] = 'google_web'
                    all_results.append(item)
                total_raw += len(result.get('results', []))
                if result.get('error'):
                    errors['google_web'] = result['error']
                    
            elif src == 'ebay':
                if not self.ebay.is_configured():
                    errors['ebay'] = 'Non configurato'
                    continue
                result = self.ebay.search(query, num_results=30)
                for item in result.get('results', []):
                    item['source'] = 'ebay'
                    all_results.append(item)
                total_raw += len(result.get('results', []))
                if result.get('error'):
                    errors['ebay'] = result['error']
        
        if filter_results:
            valid_results = self._filter_results(all_results, query, language=language)
            valid_results.sort(key=lambda x: x.get('price', 999999))
            return {
                'results': valid_results,
                'total': len(valid_results),
                'total_raw': total_raw,
                'filtered_out': total_raw - len(valid_results),
                'google_shopping_count': len([r for r in valid_results if r.get('source') == 'google_shopping']),
                'google_web_count': len([r for r in valid_results if r.get('source') == 'google_web']),
                'ebay_count': len([r for r in valid_results if r.get('source') == 'ebay']),
                'errors': errors if errors else None,
            }
        
        all_results.sort(key=lambda x: x.get('price', 999999))
        return {
            'results': all_results,
            'total': len(all_results),
            'total_raw': total_raw,
            'errors': errors if errors else None,
        }
