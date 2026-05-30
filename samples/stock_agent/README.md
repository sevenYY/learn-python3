# 股票追踪 Agent

这是一个使用 Python 标准库实现的股票追踪示例 Agent，支持港股、美股和 A 股。它会读取关注股票池，展示当前股价、最新 PE、股息率和合适买入价格，并按规则推荐“击球点”。

> 说明：这只是规则型投资辅助工具，不构成投资建议。线上行情来自 Yahoo Finance，A 股和港股代码会自动转换成 Yahoo Finance 使用的代码格式。

## 快速运行

使用离线样例数据：

```bash
python samples/stock_agent/stock_agent.py --offline
```

拉取实时行情：

```bash
python samples/stock_agent/stock_agent.py --config samples/stock_agent/watchlist.example.json
```

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

启动 Web 页面：

```bash
python samples/stock_agent/web_agent.py
```

然后打开：

```text
http://127.0.0.1:8000/
```

页面支持：

- 切换离线样例行情或实时行情。
- 按市场筛选：美股 `US`、港股 `HK`、A 股 `A`。
- 按关注方向筛选，例如 `AI算力`、`高股息`、`消费龙头`。
- 展示股票现价、PE、股息率、建议买入价、状态和偏离比例。
- 展示推荐击球点卡片。

也可以修改端口或默认行情源：

```bash
python samples/stock_agent/web_agent.py --port 8080 --source live
```

如果需要给其他程序读取结构化结果，可以访问 JSON API：

```text
http://127.0.0.1:8000/api/report?source=offline&market=HK
```

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
