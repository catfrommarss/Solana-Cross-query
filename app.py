
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Streamlit: 查找同时持有两个 Solana 代币的钱包地址
支持数据源：Helius（DAS getTokenAccounts + getTokenSupply）/ Solscan Pro（/token/holders + /token/meta）

使用方法：
1) 在 .streamlit/secrets.toml 填写
   HELIUS_API_KEY = "xxx"        # 可选，但使用 Helius 时必填
   SOLSCAN_API_KEY = "xxx"       # 可选，但使用 Solscan Pro 时必填
2) 运行：streamlit run app.py
"""

import math
import time
import requests
import pandas as pd
import streamlit as st
from typing import Dict, Tuple, List

# ------------------------- 配置 -------------------------

HELIUS_BASE = "https://mainnet.helius-rpc.com/?api-key={api_key}"
SOLSCAN_HOLDERS = "https://pro-api.solscan.io/v1.0/token/holders"
SOLSCAN_TOKEN_META = "https://pro-api.solscan.io/v2.0/token/meta"
HELIUS_GET_TOKEN_ACCOUNTS = "https://mainnet.helius-rpc.com/?api-key={api_key}"
HELIUS_GET_TOKEN_SUPPLY = "https://mainnet.helius-rpc.com/?api-key={api_key}"

# ------------------------- 工具函数 -------------------------

def get_secret(key: str, fallback: str = "") -> str:
    try:
        return st.secrets.get(key, fallback)
    except Exception:
        return fallback

def ui_amount(amount_int: int, decimals: int) -> float:
    return float(amount_int) / (10 ** decimals)

def retry_fetch_json(method: str, url: str, headers=None, params=None, json_body=None, max_retries=5, backoff=0.8):
    """简单重试机制，返回 (ok, json或错误文本)"""
    for i in range(max_retries):
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, params=params, timeout=30)
            else:
                r = requests.post(url, headers=headers, json=json_body, timeout=60)
            if r.status_code == 200:
                return True, r.json()
            # 429/5xx 退避
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (i + 1))
                continue
            return False, f"{r.status_code} {r.text[:200]}"
        except Exception as e:
            time.sleep(backoff * (i + 1))
            last = str(e)
    return False, last

# ------------------------- Solscan Pro 实现 -------------------------

def solscan_get_decimals(mint: str, api_key: str) -> int:
    headers = {"accept": "application/json", "token": api_key}
    ok, data = retry_fetch_json(
        "GET",
        SOLSCAN_TOKEN_META,
        headers=headers,
        params={"address": mint},
    )
    if not ok:
        raise RuntimeError(f"Solscan meta失败: {data}")
    dec = data.get("data", {}).get("decimals")
    if dec is None:
        # 兜底：常见 6/9，若拿不到，默认 9
        dec = 9
    return int(dec)

def solscan_list_holders(mint: str, api_key: str, min_amount_ui: float = 0.0, max_pages: int = 2000, page_size: int = 50) -> Dict[str, float]:
    """返回 {owner: ui_amount}，注意：若一个owner有多个token account，Solscan返回通常已聚合为owner层级。"""
    headers = {"accept": "application/json", "token": api_key}
    holders: Dict[str, float] = {}
    offset = 0

    params = {"tokenAddress": mint, "limit": page_size}
    # fromAmount 用于缩小查询范围（单位通常为 UI 数量）
    if min_amount_ui and min_amount_ui > 0:
        params["fromAmount"] = min_amount_ui

    pages = 0
    while pages < max_pages:
        params["offset"] = offset
        ok, data = retry_fetch_json("GET", SOLSCAN_HOLDERS, headers=headers, params=params)
        if not ok:
            raise RuntimeError(f"Solscan holders失败: {data}")
        items = (data or {}).get("data", [])
        if not items:
            break
        for it in items:
            owner = it.get("owner") or it.get("address") or it.get("tokenAccount")
            # 尽量兼容字段：uiAmount / amount
            amt_ui = it.get("uiAmount")
            if amt_ui is None:
                amt_ui = it.get("amount")
                # 如果返回的是int，需要 decimals 转换；但Solscan通常直接给 uiAmount
                if isinstance(amt_ui, dict):
                    # 某些返回会嵌套 {amount, decimals, uiAmount}
                    amt_ui = amt_ui.get("uiAmount") or 0.0
            if owner:
                holders[owner] = float(amt_ui or 0.0)
        if len(items) < page_size:
            break
        offset += page_size
        pages += 1
        # 简单限速
        time.sleep(0.1)

    return holders

# ------------------------- Helius 实现 -------------------------

def helius_get_decimals(mint: str, api_key: str) -> int:
    """通过 getTokenSupply 获取 decimals"""
    url = HELIUS_GET_TOKEN_SUPPLY.format(api_key=api_key)
    payload = {
        "jsonrpc": "2.0",
        "id": "getTokenSupply",
        "method": "getTokenSupply",
        "params": [mint]
    }
    ok, data = retry_fetch_json("POST", url, headers={"Content-Type": "application/json"}, json_body=payload)
    if not ok:
        raise RuntimeError(f"Helius getTokenSupply失败: {data}")
    val = (data or {}).get("result", {}).get("value", {})
    dec = val.get("decimals")
    if dec is None:
        dec = 9
    return int(dec)

def helius_list_holders(mint: str, api_key: str, min_amount_ui: float = 0.0, page_limit: int = 1000, max_pages: int = 10000) -> Dict[str, float]:
    """
    使用 Helius DAS getTokenAccounts（按 mint 查询 + 分页）
    返回 {owner: ui_amount(已按多个token account汇总)}
    """
    url = HELIUS_GET_TOKEN_ACCOUNTS.format(api_key=api_key)
    headers = {"Content-Type": "application/json"}
    decimals = helius_get_decimals(mint, api_key)
    owners: Dict[str, float] = {}

    page = 1
    pages = 0
    while pages < max_pages:
        payload = {
            "jsonrpc": "2.0",
            "id": "helius-getTokenAccounts",
            "method": "getTokenAccounts",
            "params": {
                "mint": mint,
                "limit": page_limit,
                "page": page,
                # "displayOptions": {},  # 可选
            }
        }
        ok, data = retry_fetch_json("POST", url, headers=headers, json_body=payload)
        if not ok:
            raise RuntimeError(f"Helius getTokenAccounts失败: {data}")
        result = (data or {}).get("result", {})
        items = result.get("token_accounts", [])
        if not items:
            break
        for acc in items:
            owner = acc.get("owner")
            amount_int = acc.get("amount", 0)
            amt_ui = ui_amount(int(amount_int or 0), decimals)
            if amt_ui < (min_amount_ui or 0.0):
                continue
            if owner:
                owners[owner] = owners.get(owner, 0.0) + float(amt_ui)
        if len(items) < page_limit:
            break
        page += 1
        pages += 1
        # 限速以防 429
        time.sleep(0.05)

    return owners

# ------------------------- 业务逻辑 -------------------------

def intersect_holders(a_map: Dict[str, float], b_map: Dict[str, float]) -> pd.DataFrame:
    keys = set(a_map.keys()) & set(b_map.keys())
    rows = []
    for k in keys:
        rows.append({"owner": k, "bal_a": a_map.get(k, 0.0), "bal_b": b_map.get(k, 0.0)})
    df = pd.DataFrame(rows).sort_values(by=["bal_a", "bal_b"], ascending=[False, False]).reset_index(drop=True)
    return df

# ------------------------- Streamlit UI -------------------------

st.set_page_config(page_title="Solana 双代币持有地址查询", layout="wide")
st.title("🔎 Solana 双代币持有地址查询（Streamlit）")

with st.expander("使用说明 / 注意事项"):
    st.markdown("""
- **推荐数据源**：
  - *Helius*：完整、可靠，但**热门大盘币**持有者数量巨大，请**务必设置最低持仓**以免请求过慢。  
  - *Solscan Pro*：提供 `/token/holders` 分页与 `fromAmount` 过滤，适合快速筛选较大持仓者。  
- **API Key**：在 `.streamlit/secrets.toml` 中配置。Solscan 使用请求头 `token: <API_KEY>`（不是 Bearer）。
- **单位**：最低持仓阈值以**人类可读单位（UI）**计算（例如 USDC=6 位小数）。
- **性能建议**：USDC/USDT 等持有人数在百万级，若阈值过小，任意方案都会很慢。
""")

col0, col1, col2 = st.columns([1,1,1.2])
with col0:
    provider = st.selectbox("数据源", ["Helius（推荐）", "Solscan Pro"])

with col1:
    mint_a = st.text_input("代币A Mint", placeholder="如：EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v（USDC）")
    mint_b = st.text_input("代币B Mint", placeholder="另一个 Mint 地址")

with col2:
    min_a = st.number_input("代币A 最低持仓（UI）", min_value=0.0, value=100.0, step=1.0)
    min_b = st.number_input("代币B 最低持仓（UI）", min_value=0.0, value=100.0, step=1.0)

run = st.button("开始查询")

if run:
    if not mint_a or not mint_b:
        st.error("请填写两个 Mint 地址")
        st.stop()

    if "Helius" in provider:
        api_key = get_secret("HELIUS_API_KEY")
        if not api_key:
            st.error("未检测到 HELIUS_API_KEY，请在 .streamlit/secrets.toml 配置")
            st.stop()
        with st.spinner("Helius 正在拉取代币A持有者..."):
            a_map = helius_list_holders(mint_a.strip(), api_key, min_amount_ui=min_a)
        with st.spinner("Helius 正在拉取代币B持有者..."):
            b_map = helius_list_holders(mint_b.strip(), api_key, min_amount_ui=min_b)

    else:
        api_key = get_secret("SOLSCAN_API_KEY")
        if not api_key:
            st.error("未检测到 SOLSCAN_API_KEY，请在 .streamlit/secrets.toml 配置")
            st.stop()
        # 虽然 Solscan 多半已是 UI 数量，这里还是获取 decimals 备用（也可展示）
        with st.spinner("Solscan 正在读取代币元数据..."):
            try:
                dec_a = solscan_get_decimals(mint_a.strip(), api_key)
                dec_b = solscan_get_decimals(mint_b.strip(), api_key)
                st.caption(f"Decimals: A={dec_a}, B={dec_b}")
            except Exception as e:
                st.warning(f"读取 decimals 失败（继续）：{e}")

        with st.spinner("Solscan 正在拉取代币A持有者..."):
            a_map = solscan_list_holders(mint_a.strip(), api_key, min_amount_ui=min_a)
        with st.spinner("Solscan 正在拉取代币B持有者..."):
            b_map = solscan_list_holders(mint_b.strip(), api_key, min_amount_ui=min_b)

    st.success(f"完成：A 持有人数={len(a_map)}, B 持有人数={len(b_map)}")

    df = intersect_holders(a_map, b_map)
    st.subheader(f"交集地址数：{len(df)}")
    st.dataframe(df, use_container_width=True)

    if not df.empty:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("下载结果 CSV", data=csv, file_name="holders_intersection.csv", mime="text/csv")

    st.markdown("---")
    st.caption("提示：若时间过长，请提高最低持仓阈值，或改用 Solscan Pro 数据源。")
