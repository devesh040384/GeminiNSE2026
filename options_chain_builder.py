import datetime
import logging

class DynamicOptionsChainBuilder:
    def __init__(self, smart_api=None, index_name=None, **kwargs):
        self.smart_api = smart_api
        self.index_name = index_name
        self.scrip_master_data = []

    def load_scrip_master(self):
        """Loads or fetches scrip master data if required during initialization."""
        try:
            logging.info(f"📁 Scrip master loader initialized for {self.index_name}")
            return True
        except Exception as e:
            logging.error(f"❌ Failed to load scrip master: {e}")
            return False

    def get_nearest_expiry_contract(self, scrip_master_data, symbol, option_type, target_strike):
        """
        Filters the scrip master for valid option contracts matching the symbol, 
        option type (CE/PE), and strike, ensuring the expiry date is >= Today.
        """
        if not scrip_master_data:
            logging.error(f"❌ Scrip master data is empty or None for {symbol}. Cannot fetch options.")
            return None

        today = datetime.date.today()
        matching_contracts = []

        for scrip in scrip_master_data:
            if scrip.get('exch_seg') == 'NFO' or scrip.get('exch_seg') == 'BFO':
                scrip_symbol = str(scrip.get('symbol', ''))
                
                if symbol in scrip_symbol and scrip_symbol.endswith(option_type):
                    expiry_str = scrip.get('expiry')
                    
                    if expiry_str:
                        try:
                            expiry_date = self._parse_expiry_date(expiry_str)
                            
                            if expiry_date:
                                # 🛡️ STRICT FIX: Exclude expired contracts (Expiry Date < Current Date)
                                if expiry_date >= today:
                                    strike_val = float(scrip.get('strike', 0.0)) / 100.0
                                    
                                    matching_contracts.append({
                                        'token': scrip.get('token'),
                                        'symbol': scrip_symbol,
                                        'expiry_date': expiry_date,
                                        'strike': strike_val,
                                        'lotsize': scrip.get('lotsize', 1)
                                    })
                        except Exception:
                            continue

        if not matching_contracts:
            logging.error(f"❌ No valid unexpired options found for {symbol} {option_type}")
            return None

        # Sort by nearest future expiry date first
        matching_contracts.sort(key=lambda x: x['expiry_date'])
        nearest_expiry = matching_contracts[0]['expiry_date']
        expiry_filtered = [c for c in matching_contracts if c['expiry_date'] == nearest_expiry]
        
        # Find closest strike
        best_contract = min(expiry_filtered, key=lambda x: abs(x['strike'] - float(target_strike)))
        
        logging.info(f"✅ Selected Valid Contract: {best_contract['symbol']} | Expiry: {best_contract['expiry_date']} | Strike: {best_contract['strike']}")
        return best_contract

    def _parse_expiry_date(self, expiry_str):
        """Helper to safely parse various broker date formats into a datetime.date object."""
        for fmt in ('%d%b%Y', '%d-%b-%Y', '%Y-%m-%d', '%d%m%Y'):
            try:
                return datetime.datetime.strptime(expiry_str.strip(), fmt).date()
            except ValueError:
                continue
        return None

# Alias to maintain compatibility if anything imports OptionsChainBuilder directly
OptionsChainBuilder = DynamicOptionsChainBuilder
