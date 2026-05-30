# 股票追踪 Agent

这是一个使用 Python 标准库实现的股票追踪示例 Agent，支持港股、美股和 A 股。它会读取关注股票池，展示当前股价、最新 PE、股息率和合适买入价格，并按规则推荐“击球点”。

> 说明：这只是规则型投资辅助工具，不构成投资建议。实时模式下，美股最新价优先来自 Nasdaq quote API，并用 Yahoo Finance 补充 PE/股息等基本面；港股行情来自 Yahoo Finance；A 股行情和 TTM 分红数据来自东方财富。A 股和港股代码会自动转换成对应数据源使用的代码格式。

## 快速运行

使用离线样例数据：

```bash
python samples/stock_agent/stock_agent.py --offline
```

拉取实时行情：

```bash
python samples/stock_agent/stock_agent.py --config samples/stock_agent/watchlist.example.json
```

CLI 不带 `--offline` 时会走实时行情；`--offline` 只用于演示和测试。

按市场或方向过滤：

```bash
python samples/stock_agent/stock_agent.py --offline --market HK
python samples/stock_agent/stock_agent.py --offline --direction 高股息
```

如果当前环境无法访问外部网络，可以传入自己的行情文件：

```bash
python samples/stock_agent/stock_agent.py --quotes samples/stock_agent/sample_quotes.json
```

## 页面操作界面

启动 Web 页面（默认实时行情，每次请求都会重新拉取，不使用浏览器缓存）：

```bash
python samples/stock_agent/web_agent.py
```

然后打开：

```text
http://127.0.0.1:8000/
```

页面支持：

- 切换离线样例行情或实时行情（美股最新价走 Nasdaq，港股走 Yahoo Finance，A 股走东方财富）。
- 按市场筛选：美股 `US`、港股 `HK`、A 股 `A`。
- 按关注方向筛选，例如 `AI算力`、`高股息`、`消费龙头`。
- 展示股票现价、PE、股息率、建议买入价、状态和偏离比例。
- 展示推荐击球点卡片。

也可以修改端口或切到离线演示数据：

```bash
python samples/stock_agent/web_agent.py --port 8080
python samples/stock_agent/web_agent.py --source offline
```

如果需要给其他程序读取结构化结果，可以访问 JSON API：

```text
http://127.0.0.1:8000/api/report?source=offline&market=HK
```

## 数据源

实时模式下使用混合数据源：

- 美股：Nasdaq quote API 获取最新交易价，Yahoo Finance 补充 PE、EPS 和股息等基本面；Nasdaq 不可用时回退到 Yahoo intraday chart 最新价。
- 港股：Yahoo Finance quote API。
- A 股：东方财富 quote API 获取最新价和 PE，东方财富 F10 分红融资数据按最近 12 个月现金分红合计计算 TTM 股息率。

如果某个云环境无法访问外部行情接口，页面会明确报错；需要演示界面时可手动切换到离线样例行情。离线样例只用于演示，不代表最新行情。

## 股票池配置

配置文件是 JSON，核心字段如下：

- `symbol`：股票代码，例如 `AAPL`、`0700`、`600519`。
- `market`：市场，支持 `US`、`HK`、`A`。
- `direction`：关注方向，例如 `AI算力`、`高股息`、`消费龙头`。
- `target_pe`：你愿意接受的目标 PE。
- `target_dividend_yield`：你要求的最低股息率，`0.05` 表示 5%。
- `max_buy_price`：可选，手动指定买入线。
- `safety_margin`：当缺少 PE 和股息数据时使用的安全边际。

## 买入价格规则

Agent 会计算多个候选买入价，并取最保守的一个：

1. PE 买入价：`每股收益 EPS * 目标 PE`。
2. 股息买入价：`年度股息 / 目标股息率`。
3. 手动买入价：配置里的 `max_buy_price`。
4. 数据不足时：`当前价 * (1 - safety_margin)`。

状态含义：

- `击球区`：当前价格低于或等于买入线。
- `临近`：当前价格距离买入线 5% 以内。
- `观察`：当前价格距离买入线 15% 以内。
- `等待`：当前价格明显高于买入线。
- `缺数据`：没有足够行情数据。

## 测试

```bash
python -m unittest samples.stock_agent.test_stock_agent
```
