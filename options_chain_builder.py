import logging
import json
import os
from datetime import datetime
from config import INDICES_CONFIG

class DynamicOptionsChainBuilder:
    def __init__(self, index_name="NIFTY", smart_api=None):
        self.index_name = index_name.upper()
        self.smart_api = smart_api
        self.nfo_contracts = []
        self.scrip_master_data = []

    def load_scrip_master(self, scrip_data=None):
        try:
            if scrip_data:
                self.scrip_master_data = scrip_data
            elif os.path.exists('scrip_master.json'):
                with open('scrip_master.json', 'r', encoding='utf-8') as f:
                    self.scrip_master_data = json.load(f)
            
            self.nfo_contracts = []
            for item in self.scrip_master_data:
                sym = item.get('symbol', '').upper()
                if self.index_name in sym and item.get('instrumenttype', '') in ['OPTIDX', 'OPTSTK']:
                    self.nfo_contracts.append(item)
                    
            logging.info(f"🔗 [ChainBuilder-{self.index_name}] Loaded {len(self.nfo_contracts)} derivative contracts from master.")
        except Exception as e:
            logging.error(f"❌ Error loading scrip master for {self.index_name}: {e}")

    def get_nearest_expiry_contract(self, spot_price, instrument_type="CE"):
        """Finds the nearest ATM option contract with strict liquidity and bid-ask spread validation."""
        try:
            if not self.nfo_contracts:
                self.load_scrip_master()
                if not self.nfo_contracts:
                    return None

            valid_contracts = []
            today = datetime.now()
            
            for c in self.nfo_contracts:
                exp_str = c.get('expiry')
                if not exp_str: continue
                
                parsed_date = None
                for fmt in ('%d-%b-%Y', '%d%b%Y', '%Y-%m-%d', '%d-%b-%y'):
                    try:
                        parsed_date = datetime.strptime(exp_str, fmt)
                        break
                    except ValueError:
                        continue
                
                if parsed_date and parsed_date >= today.replace(hour=0, minute=0, second=0, microsecond=0):
                    c['parsed_expiry_date'] = parsed_date
                    valid_contracts.append(c)

            if not valid_contracts:
                return None

            earliest_expiry_date = min(valid_contracts, key=lambda x: x['parsed_expiry_date'])['parsed_expiry_date']
            
            matching_contracts = []
            for c in valid_contracts:
                if c['parsed_expiry_date'] == earliest_expiry_date:
                    sym = c.get('symbol', '').upper()
                    if sym.endswith(instrument_type.upper()):
                        try:
                            raw_strike = float(c.get('strike', 0))
                            actual_strike = raw_strike / 100.0 if raw_strike > 100000 else raw_strike
                            c['parsed_strike'] = actual_strike
                            matching_contracts.append(c)
                        except ValueError:
                            continue

            if not matching_contracts:
                return None

            sorted_candidates = sorted(matching_contracts, key=lambda x: abs(x['parsed_strike'] - spot_price))

            for candidate in sorted_candidates[:5]:
                contract_symbol = candidate.get('symbol')
                contract_token = candidate.get('token') or candidate.get('symboltoken')
                
                if not self.smart_api:
                    return {
                        'symbol': contract_symbol,
                        'token': contract_token,
                        'strike': candidate['parsed_strike'],
                        'expiry': earliest_expiry_date.strftime('%d%b%Y').upper()
                    }

                try:
                    # ✅ FIXED: Strict exchange routing for Options (NFO for Nifty, BFO for Sensex)
                    exchange = "BFO" if self.index_name == "SENSEX" else "NFO"
                    
                    resp = self.smart_api.ltpData(exchange, contract_symbol, contract_token)
                    if resp and resp.get('status'):
                        data = resp.get('data', {})
                        ltp = float(data.get('ltp', 0) if hasattr(data, 'get') else 0)
                        
                        q_resp = self.smart_api.getMarketData(mode="FULL", exchangeTokens={exchange: [contract_token]})
                        if q_resp and q_resp.get('status'):
                            q_data = q_resp['data'].get('fetched', [{}])[0]
                            volume = float(q_data.get('tradeVolume', 10000))
                            best_bid = float(q_data.get('bestBidPrice', ltp * 0.99))
                            best_ask = float(q_data.get('bestAskPrice', ltp * 1.01))
                            
                            spread_pct = ((best_ask - best_bid) / ltp) * 100 if ltp > 0 else 0.0
                            
                            if volume >= 500 and spread_pct <= 1.5:
                                logging.info(f"✅ [LIQUIDITY PASSED] {contract_symbol} | Vol: {volume} | Spread: {spread_pct:.2f}%")
                                return {
                                    'symbol': contract_symbol,
                                    'token': contract_token,
                                    'strike': candidate['parsed_strike'],
                                    'expiry': earliest_expiry_date.strftime('%d%b%Y').upper()
                                }
                            else:
                                logging.warning(f"⚠️ [LIQUIDITY REJECTED] {contract_symbol} (Vol: {volume}, Spread: {spread_pct:.2f}%) -> Skipping strike.")
                except Exception as ex:
                    logging.warning(f"⚠️ Could not verify live depth for {contract_symbol}: {ex}")
                    return {
                        'symbol': contract_symbol,
                        'token': contract_token,
                        'strike': candidate['parsed_strike'],
                        'expiry': earliest_expiry_date.strftime('%d%b%Y').upper()
                    }

            fallback = sorted_candidates[0]
            return {
                'symbol': fallback.get('symbol'),
                'token': fallback.get('token') or fallback.get('symboltoken'),
                'strike': fallback['parsed_strike'],
                'expiry': earliest_expiry_date.strftime('%d%b%Y').upper()
            }
        except Exception as e:
            logging.error(f"❌ Error getting validated liquidity contract for {self.index_name}: {e}")
            return None
