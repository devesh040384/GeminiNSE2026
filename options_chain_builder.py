import logging
from datetime import datetime

class DynamicOptionsChainBuilder:
    def __init__(self, scrip_master_data=None, base_symbol="NIFTY", index_name=None, smart_api=None, **kwargs):
        """
        Initializes the options builder.
        Supports index_name, base_symbol, smart_api, and arbitrary kwargs from main.py.
        """
        self.base_symbol = index_name if index_name else base_symbol
        
        if scrip_master_data is None:
            scrip_master_data = kwargs.get('scrip_data') or kwargs.get('master_data') or kwargs.get('scrip_master')
            
        self.scrip_master_data = scrip_master_data
        self.smart_api = smart_api
        self.nfo_contracts = []
        
        if self.scrip_master_data:
            self.nfo_contracts = self._filter_nfo_contracts()

    def load_scrip_master(self, scrip_master_data):
        """
        Method called by main.py to load or reload the scrip master data 
        after the builder has been initialized.
        """
        self.scrip_master_data = scrip_master_data
        if self.scrip_master_data:
            self.nfo_contracts = self._filter_nfo_contracts()
            logging.info(f"✅ Loaded {len(self.nfo_contracts)} NFO contracts for {self.base_symbol}.")

    def _filter_nfo_contracts(self):
        """Filters the master scrip data down to relevant NFO index/stock option contracts."""
        if not self.scrip_master_data:
            return []
        contracts = []
        for scrip in self.scrip_master_data:
            if (scrip.get('exch_seg') == 'NFO' and 
                scrip.get('name') == self.base_symbol and 
                scrip.get('instrumenttype') in ['OPTIDX', 'OPTSTK']):
                contracts.append(scrip)
        return contracts

    def get_nearest_expiry_contract(self, spot_price=None, instrument_type="CE", **kwargs):
        """
        Finds the closest At-The-Money (ATM) contract for the specified instrument type.
        """
        # Handle alternate keyword arguments
        if spot_price is None:
            spot_price = kwargs.get('spot') or kwargs.get('price') or kwargs.get('entry_spot')
            
        opt_type = kwargs.get('option_type') or kwargs.get('type') or kwargs.get('opt_type') or instrument_type
        instrument_type = str(opt_type).upper()

        try:
            spot_price = float(spot_price)
        except (ValueError, TypeError):
            logging.error(f"❌ Invalid spot price passed to Options Builder: {spot_price}")
            return None

        if instrument_type not in ["CE", "PE"]:
            logging.error(f"❌ Invalid instrument type: {instrument_type}. Must be 'CE' or 'PE'.")
            return None

        # Re-filter contracts if list is empty but scrip_master_data is available
        if not self.nfo_contracts and self.scrip_master_data:
            self.nfo_contracts = self._filter_nfo_contracts()

        # 1. Filter by Instrument Type (symbol ends with CE or PE)
        type_filtered = [
            c for c in self.nfo_contracts 
            if c.get('symbol', '').endswith(instrument_type)
        ]
        
        if not type_filtered:
            logging.error(f"❌ No {instrument_type} contracts found for {self.base_symbol} in scrip master.")
            return None

        # 2. Extract and Parse Valid Future Expiry Dates
        valid_expiries = set()
        for c in type_filtered:
            expiry_str = c.get('expiry')
            if expiry_str:
                try:
                    expiry_date = datetime.strptime(expiry_str, '%d%b%Y').date()
                    valid_expiries.add((expiry_date, expiry_str))
                except ValueError:
                    continue

        if not valid_expiries:
            logging.error("❌ Could not parse expiry dates from scrip master.")
            return None

        # Select the closest non-expired date
        today = datetime.now().date()
        future_expiries = sorted([e for e in valid_expiries if e[0] >= today], key=lambda x: x[0])
        
        if not future_expiries:
            logging.error("❌ No valid future expiries found in scrip master.")
            return None
            
        nearest_expiry_str = future_expiries[0][1]

        # 3. Filter Contracts by Nearest Expiry
        expiry_filtered = [c for c in type_filtered if c.get('expiry') == nearest_expiry_str]

        # 4. Find the At-The-Money (ATM) Strike
        atm_contract = None
        min_diff = float('inf')

        for contract in expiry_filtered:
            try:
                raw_strike = float(contract.get('strike', 0))
                # Scale strike if multiplied by 100 in master data
                actual_strike = raw_strike / 100.0 if raw_strike > 100000 else raw_strike
            except (ValueError, TypeError):
                continue
            
            diff = abs(actual_strike - spot_price)
            if diff < min_diff:
                min_diff = diff
                atm_contract = contract
                atm_contract['parsed_strike'] = actual_strike

        if atm_contract:
            return {
                'symbol': atm_contract.get('symbol'),
                'token': atm_contract.get('token'),
                'strike': atm_contract.get('parsed_strike'),
                'expiry': nearest_expiry_str
            }
            
        logging.error(f"❌ Failed to locate ATM contract for {self.base_symbol} {instrument_type} @ {spot_price}")
        return None

    def build_options_chain(self, spot_price=None, instrument_type="CE", **kwargs):
        """Alias method for backward compatibility."""
        return self.get_nearest_expiry_contract(spot_price, instrument_type, **kwargs)

    def get_atm_contract(self, spot_price=None, instrument_type="CE", **kwargs):
        """Alias method for backward compatibility."""
        return self.get_nearest_expiry_contract(spot_price, instrument_type, **kwargs)

# Backward-compatibility alias
OptionsBuilder = DynamicOptionsChainBuilder
