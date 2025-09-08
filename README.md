
# Streamlit: 查询同时持有两个 Solana 代币的钱包地址

## 快速开始
```bash
# 1) 创建虚拟环境（可选）
python -m venv .venv && source .venv/bin/activate

# 2) 安装依赖
pip install -r requirements.txt

# 3) 填写 API Key（至少准备一个数据源）
mkdir -p .streamlit
cat > .streamlit/secrets.toml << 'EOF'
HELIUS_API_KEY = "你的helius_api_key"
SOLSCAN_API_KEY = "你的_solscan_api_key"
EOF

# 4) 本地运行
streamlit run app.py
```

## 说明
- **Helius**：调用 `getTokenAccounts`（按 mint + 分页）和 `getTokenSupply`（拿 decimals），汇总每个 owner 的 UI 持仓；
- **Solscan Pro**：调用 `/v1.0/token/holders`（支持 `fromAmount` 过滤）与 `/v2.0/token/meta`（拿 decimals），更适合快速筛选较大持仓；
- **注意**：USDC/USDT 等大盘币持有者数量巨大，请务必设置**最低持仓阈值**，否则请求会很慢。

## 部署
- **Streamlit Community Cloud**：直接上传本仓库并在“高级设置”里配置 `secrets`；
- **自建服务器**：`tmux/screen` 等驻留运行即可，建议配合 Nginx 反代 + BasicAuth。
