import streamlit as st
import requests
import pandas as pd
import time
from datetime import datetime
import pytz

# --- PAGE CONFIG ---
st.set_page_config(page_title="XAU/USD Live SMC Scanner", layout="wide")

# --- IMPROVED TIME CONVERSION ---
def get_ist_time(api_time_str=None):
    """
    Ensures the API time is treated as UTC and converted correctly to IST.
    """
    ist_tz = pytz.timezone('Asia/Kolkata')
    if api_time_str:
        # 1. Parse API string
        dt = datetime.strptime(api_time_str, '%Y-%m-%d %H:%M:%S')
        # 2. Assign UTC timezone to the raw time
        utc_dt = pytz.utc.localize(dt)
        # 3. Convert to Indian Time
        ist_dt = utc_dt.astimezone(ist_tz)
        return ist_dt.strftime('%Y-%m-%d %H:%M')
    
    # Return current time in IST
    return datetime.now(ist_tz).strftime('%Y-%m-%d %H:%M:%S')

def fetch_data(symbol, interval, api_key):
    # CRITICAL FIX: Added &timezone=UTC to the URL
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=100&timezone=UTC&apikey={api_key}"
    try:
        r = requests.get(url).json()
        if 'values' not in r:
            st.error(f"API Error: {r.get('message')}")
            return None
        df = pd.DataFrame(r['values'])
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)
        return df.iloc[::-1].reset_index(drop=True)
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None

def get_market_state(price, ema50, ema200):
    if price > ema50 > ema200: return "Strong Bullish"
    if price < ema50 < ema200: return "Strong Bearish"
    if price > ema200: return "Bullish"
    if price < ema200: return "Bearish"
    return "Sideways"

def analyze_data(df):
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rsi = 100 - (100 / (1 + (gain / loss)))
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    mkt_info = {
        "price": latest['close'],
        "change": latest['close'] - prev['close'],
        "rsi": rsi.iloc[-1],
        "state": get_market_state(latest['close'], latest['ema50'], latest['ema200']),
        "high": df['high'].max(),
        "low": df['low'].min()
    }
    
    obs = []
    for i in range(2, len(df)):
        curr, p = df.iloc[i], df.iloc[i-1]
        ob_type = None
        c_body, p_body = abs(curr['close'] - curr['open']), abs(p['close'] - p['open'])
        
        if curr['close'] > curr['open'] and p['close'] < p['open'] and c_body > (p_body * 2):
            ob_type = "BULLISH OB"
        elif curr['close'] < curr['open'] and p['close'] > p['open'] and c_body > (p_body * 2):
            ob_type = "BEARISH OB"
            
        if ob_type:
            obs.append({
                "IST_Time": get_ist_time(curr['datetime']), # Uses fixed conversion
                "Market_State": get_market_state(curr['close'], df['ema50'].iloc[i], df['ema200'].iloc[i]),
                "OB_Type": ob_type,
                "Zone_Low": round(p['low'], 2),
                "Zone_High": round(p['high'], 2),
                "Impulse": round(c_body, 2),
                "raw_time": curr['datetime']
            })
    return mkt_info, obs

# --- STREAMLIT UI ---
st.title("⚖️ XAU/USD Live SMC Dashboard")

# Sidebar
st.sidebar.header("Settings")
api_key = st.sidebar.text_input("API Key", value="f208bbc7e84a428ea03adf59947ff894", type="password")
symbol = st.sidebar.text_input("Symbol", value="XAU/USD")
interval = st.sidebar.selectbox("Interval", ["1min", "5min", "15min", "1h"], index=2)
refresh_rate = st.sidebar.slider("Refresh Rate (sec)", 30, 300, 60)

if 'ob_history' not in st.session_state:
    st.session_state.ob_history = []

df = fetch_data(symbol, interval, api_key)

if df is not None:
    mkt, current_obs = analyze_data(df)
    
    # Update History
    for ob in current_obs:
        if not any(h['raw_time'] == ob['raw_time'] for h in st.session_state.ob_history):
            st.session_state.ob_history.append(ob)

    # 1. Dashboard Metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Live Price", f"${mkt['price']:.2f}", f"{mkt['change']:+.2f}")
    col2.metric("Market State", mkt['state'])
    col3.metric("RSI (14)", f"{mkt['rsi']:.1f}")
    col4.metric("Session High/Low", f"{mkt['high']:.1f} / {mkt['low']:.1f}")

    st.markdown("---")

    # 2. Order Block History
    st.subheader("✅ Order Block (SMC) Signal History")
    if st.session_state.ob_history:
        history_df = pd.DataFrame(st.session_state.ob_history).tail(20)
        history_df = history_df[["IST_Time", "Market_State", "OB_Type", "Zone_Low", "Zone_High", "Impulse"]]
        st.dataframe(history_df, use_container_width=True)

    # 3. Chart
    st.line_chart(df.set_index('datetime')['close'])

    st.caption(f"Last updated (IST): {get_ist_time()}. Page will refresh automatically.")
    time.sleep(refresh_rate)
    st.rerun()
