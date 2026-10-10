from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'processed' / 'fund_lens.sqlite'
API = 'https://api.mfapi.in/mf'
AMFI = 'https://portal.amfiindia.com/spages/NAVAll.txt'
# Purposefully narrow, declared watchlist; not a ranked or exhaustive universe.
FUNDS = {
    119063: ('HDFC Nifty 50', 'Nifty 50'),
    120716: ('UTI Nifty 50', 'Nifty 50'),
    118482: ('Bandhan Nifty 50', 'Nifty 50'),
    120684: ('ICICI Nifty Next 50', 'Nifty Next 50'),
    143341: ('UTI Nifty Next 50', 'Nifty Next 50'),
    141877: ('DSP Nifty 50 Equal Weight', 'Nifty 50 Equal Weight'),
}
