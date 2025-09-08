import os, time, requests, pandas as pd, streamlit as st
from typing import Set, Tuple

API_BASE = "https://pro-api.solscan.io/v2.0"

def get_holders(api_key: str, mint: str, min_amount: str|None=None, sleep=0.2) -> Tuple[Set[str], int]:
    session = requests.Session()
    session.headers.update({"accept":"application/json","token":api_key})
    owners, page, total = set(), 1, None
    while True:
        params = {"address": mint, "page": page, "page_size": 40}
        if min_amount: params["from_amount"] = min_amount
        r = session.get(f"{API_BASE}/token/holders", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(1.0); continue
        r.raise_for_status()
        data = r.json()
        payload = data.get("data", {})
        if total is None:
            total = int(payload.get("total", 0))
        items = payload.get("items", []) or []
        for it in items:
            if it.get("owner"): owners.add(it["owner"])
        if not items or (total and page*40 >= total): break
        page += 1; time.sleep(sleep)
    return owners, total or len(owners)

st.set_page_config(page_title="SOL 两币共同持有人查询", layout="wide")
st.title("Solana 两个代币的共同持有人查询（Solscan Pro API）")

api_key = st.text_input("Solscan API Key（必填，前端本地保存，不会上传到服务端）", type="password")
col1, col2 = st.columns(2)
with col1:
    token_a = st.text_input("Token A Mint（如 WSOL）", "So11111111111111111111111111111111111111112")
    min_a   = st.text_input("A 的最小持仓（可选，单位=代币单位）", "")
with col2:
    token_b = st.text_input("Token B Mint（如 USDC）", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    min_b   = st.text_input("B 的最小持仓（可选，单位=代币单位）", "")

if st.button("开始查询", type="primary") and api_key and token_a and token_b:
    with st.spinner("抓取 Token A 持有人中…"):
        owners_a, total_a = get_holders(api_key, token_a, min_a or None)
    with st.spinner("抓取 Token B 持有人中…"):
        owners_b, total_b = get_holders(api_key, token_b, min_b or None)
    common = owners_a & owners_b
    st.success(f"A持有人：{total_a:,}；B持有人：{total_b:,}；共同持有人：{len(common):,}")

    if common:
        df = pd.DataFrame(sorted(common), columns=["wallet"])
        st.dataframe(df, use_container_width=True)
        st.download_button("下载共同持有人 CSV", df.to_csv(index=False).encode("utf-8"), "common_holders.csv", "text/csv")
else:
    st.info("输入 API Key 与两条 Mint 后点击“开始查询”。")
