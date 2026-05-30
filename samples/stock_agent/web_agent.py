#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import html
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib import parse

import stock_agent


PAGE_CSS = '''
:root {
  color-scheme: light;
  --bg: #f5f7fb;
  --card: #ffffff;
  --text: #182230;
  --muted: #667085;
  --line: #d0d5dd;
  --primary: #175cd3;
  --buy: #067647;
  --near: #b54708;
  --watch: #175cd3;
  --wait: #667085;
  --error: #b42318;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.page { max-width: 1180px; margin: 0 auto; padding: 32px 20px 48px; }
.hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-start;
  margin-bottom: 24px;
}
h1 { margin: 0 0 8px; font-size: 32px; }
p { margin: 0; color: var(--muted); }
.badge {
  display: inline-flex;
  border-radius: 999px;
  padding: 6px 12px;
  background: #e0eaff;
  color: var(--primary);
  font-weight: 600;
  white-space: nowrap;
}
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: 0 12px 28px rgba(16, 24, 40, .06);
  padding: 20px;
  margin-bottom: 20px;
}
.filters {
  display: grid;
  grid-template-columns: repeat(5, minmax(120px, 1fr));
  gap: 14px;
  align-items: end;
}
label { display: block; color: #344054; font-size: 13px; font-weight: 600; margin-bottom: 6px; }
select, input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  background: #fff;
}
button {
  border: 0;
  border-radius: 10px;
  padding: 11px 16px;
  color: #fff;
  background: var(--primary);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}
.meta { margin-top: 12px; font-size: 13px; color: var(--muted); }
.error {
  border-color: #fecdca;
  background: #fffbfa;
  color: var(--error);
}
.summary {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.stat { padding: 16px; border-radius: 14px; background: #f8fafc; }
.stat strong { display: block; font-size: 26px; }
.stat span { color: var(--muted); font-size: 13px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 12px 10px; border-bottom: 1px solid #eaecf0; text-align: left; }
th { color: #475467; font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
tbody tr:hover { background: #f9fafb; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.pill { display: inline-block; border-radius: 999px; padding: 4px 9px; font-weight: 700; font-size: 12px; }
.status-buy_zone { color: var(--buy); background: #dcfae6; }
.status-near { color: var(--near); background: #fef0c7; }
.status-watch { color: var(--watch); background: #d1e9ff; }
.status-wait { color: var(--wait); background: #f2f4f7; }
.status-no_data { color: var(--error); background: #fee4e2; }
.recommendations { display: grid; gap: 12px; }
.recommendation { padding: 14px; border: 1px solid #eaecf0; border-radius: 14px; }
.recommendation strong { display: block; margin-bottom: 6px; }
.small { font-size: 13px; color: var(--muted); }
@media (max-width: 860px) {
  .hero, .summary { display: block; }
  .badge { margin-top: 14px; }
  .filters { grid-template-columns: 1fr 1fr; }
  .table-wrap { overflow-x: auto; }
}
'''


class StockWebApp(object):

    def __init__(self, config_path: str, quote_path: str, default_source: str = 'offline'):
        self.config_path = config_path
        self.quote_path = quote_path
        self.default_source = default_source

    def build_report(self, query: Dict[str, List[str]]) -> Dict[str, object]:
        _, items = stock_agent.load_watchlist(self.config_path)
        market = first_query(query, 'market')
        direction = first_query(query, 'direction')
        top = int(first_query(query, 'top') or 5)
        source = first_query(query, 'source') or self.default_source
        source = source if source in ('offline', 'live') else self.default_source

        filtered = stock_agent.filter_items(items, market, direction)
        provider = self._provider(source)
        quotes = provider.fetch(filtered)
        evaluations = stock_agent.build_evaluations(filtered, quotes)
        recommendations = [
            row for row in evaluations
            if row.status in (stock_agent.STATUS_BUY, stock_agent.STATUS_NEAR, stock_agent.STATUS_WATCH)
        ]
        recommendations.sort(key=stock_agent.recommendation_sort_key)

        return {
            'source': source,
            'market': market or '',
            'direction': direction or '',
            'top': top,
            'items': items,
            'evaluations': evaluations,
            'recommendations': recommendations[:top],
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _provider(self, source: str):
        if source == 'offline':
            return stock_agent.FixtureQuoteProvider.from_path(self.quote_path)
        return stock_agent.YahooFinanceProvider()


def first_query(query: Dict[str, List[str]], key: str) -> Optional[str]:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def make_handler(app: StockWebApp):

    class StockHandler(BaseHTTPRequestHandler):

        def do_GET(self):
            parsed = parse.urlparse(self.path)
            query = parse.parse_qs(parsed.query)
            if parsed.path == '/api/report':
                self.handle_api(query)
                return
            if parsed.path not in ('/', '/index.html'):
                self.send_error(404)
                return
            self.handle_page(query)

        def handle_page(self, query):
            try:
                report = app.build_report(query)
                body = render_page(report)
                self.respond(200, body.encode('utf-8'), 'text/html; charset=utf-8')
            except Exception as e:
                body = render_error_page(e)
                self.respond(200, body.encode('utf-8'), 'text/html; charset=utf-8')

        def handle_api(self, query):
            try:
                report = app.build_report(query)
                payload = json.dumps(report_to_json(report), ensure_ascii=False, indent=2)
                self.respond(200, payload.encode('utf-8'), 'application/json; charset=utf-8')
            except Exception as e:
                payload = json.dumps({'error': str(e)}, ensure_ascii=False)
                self.respond(500, payload.encode('utf-8'), 'application/json; charset=utf-8')

        def respond(self, code, body, content_type):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            sys.stderr.write('%s - %s\n' % (self.address_string(), fmt % args))

    return StockHandler


def render_page(report: Dict[str, object]) -> str:
    evaluations = report['evaluations']
    recommendations = report['recommendations']
    items = report['items']
    directions = sorted({item.direction for item in items})
    markets = [stock_agent.MARKET_US, stock_agent.MARKET_HK, stock_agent.MARKET_A]

    return '''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>股票追踪 Agent</title>
  <style>%s</style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div>
        <h1>股票追踪 Agent</h1>
        <p>跟踪港股、美股、A 股的关注方向，展示股价、PE、股息率和合适买入价。</p>
      </div>
      <span class="badge">%s</span>
    </section>
    %s
    %s
    %s
    %s
  </main>
</body>
</html>''' % (
        PAGE_CSS,
        '离线样例行情' if report['source'] == 'offline' else '实时 Yahoo Finance 行情',
        render_filters(report, markets, directions),
        render_summary(evaluations),
        render_table(evaluations),
        render_recommendations(recommendations),
    )


def render_error_page(error: Exception) -> str:
    return '''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>股票追踪 Agent</title>
  <style>%s</style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div>
        <h1>股票追踪 Agent</h1>
        <p>页面加载时遇到问题。</p>
      </div>
    </section>
    <section class="card error">
      <strong>无法获取行情：</strong>%s
      <p class="meta">如果实时行情不可用，请回到 <a href="/?source=offline">离线样例行情</a> 查看界面效果。</p>
    </section>
  </main>
</body>
</html>''' % (PAGE_CSS, escape(str(error)))


def render_filters(report: Dict[str, object], markets: List[str], directions: List[str]) -> str:
    source = report['source']
    market = report['market']
    direction = report['direction']
    top = report['top']
    return '''<section class="card">
  <form class="filters" method="get">
    <div>
      <label for="source">行情源</label>
      <select id="source" name="source">
        %s
        %s
      </select>
    </div>
    <div>
      <label for="market">市场</label>
      <select id="market" name="market">
        <option value="">全部市场</option>
        %s
      </select>
    </div>
    <div>
      <label for="direction">方向</label>
      <select id="direction" name="direction">
        <option value="">全部方向</option>
        %s
      </select>
    </div>
    <div>
      <label for="top">推荐数量</label>
      <input id="top" name="top" value="%s" type="number" min="1" max="20">
    </div>
    <button type="submit">刷新报告</button>
  </form>
  <div class="meta">生成时间：%s</div>
</section>''' % (
        option('offline', '离线样例行情', source),
        option('live', '实时行情', source),
        ''.join(option(value, value, market) for value in markets),
        ''.join(option(value, value, direction) for value in directions),
        escape(str(top)),
        escape(report['generated_at']),
    )


def render_summary(evaluations) -> str:
    total = len(evaluations)
    buy = count_status(evaluations, stock_agent.STATUS_BUY)
    near = count_status(evaluations, stock_agent.STATUS_NEAR)
    watch = count_status(evaluations, stock_agent.STATUS_WATCH)
    return '''<section class="summary card">
  <div class="stat"><strong>%s</strong><span>跟踪股票</span></div>
  <div class="stat"><strong>%s</strong><span>击球区</span></div>
  <div class="stat"><strong>%s</strong><span>临近买入</span></div>
  <div class="stat"><strong>%s</strong><span>观察名单</span></div>
</section>''' % (total, buy, near, watch)


def render_table(evaluations) -> str:
    rows = []
    for row in evaluations:
        quote = row.quote
        rows.append('''<tr>
  <td>%s</td>
  <td>%s</td>
  <td><strong>%s</strong></td>
  <td>%s</td>
  <td class="num">%s</td>
  <td class="num">%s</td>
  <td class="num">%s</td>
  <td class="num">%s</td>
  <td><span class="pill status-%s">%s</span></td>
  <td class="num">%s</td>
</tr>''' % (
            escape(row.item.direction),
            escape(row.item.market),
            escape(row.item.symbol),
            escape(quote.name or row.item.name),
            escape(stock_agent.format_price(quote.price, quote.currency)),
            escape(stock_agent.format_number(quote.pe)),
            escape(stock_agent.format_percent(quote.dividend_yield)),
            escape(stock_agent.format_price(row.suggested_buy_price, quote.currency)),
            escape(row.status),
            escape(stock_agent.STATUS_LABELS[row.status]),
            escape(stock_agent.format_percent(row.distance_to_buy)),
        ))
    if not rows:
        rows.append('<tr><td colspan="10">没有符合筛选条件的股票。</td></tr>')
    return '''<section class="card">
  <h2>股票池</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>方向</th><th>市场</th><th>代码</th><th>名称</th>
          <th class="num">现价</th><th class="num">PE</th><th class="num">股息率</th>
          <th class="num">买入价</th><th>状态</th><th class="num">偏离</th>
        </tr>
      </thead>
      <tbody>%s</tbody>
    </table>
  </div>
</section>''' % ''.join(rows)


def render_recommendations(recommendations) -> str:
    if not recommendations:
        content = '<p>暂无进入买入区或临近买入区的股票。</p>'
    else:
        cards = []
        for row in recommendations:
            quote = row.quote
            cards.append('''<article class="recommendation">
  <strong>%s %s <span class="pill status-%s">%s</span></strong>
  <div class="small">%s / %s | 现价 %s | 买入线 %s | 偏离 %s</div>
  <div class="small">依据：%s</div>
</article>''' % (
                escape(row.item.symbol),
                escape(quote.name or row.item.name),
                escape(row.status),
                escape(stock_agent.STATUS_LABELS[row.status]),
                escape(row.item.market),
                escape(row.item.direction),
                escape(stock_agent.format_price(quote.price, quote.currency)),
                escape(stock_agent.format_price(row.suggested_buy_price, quote.currency)),
                escape(stock_agent.format_percent(row.distance_to_buy)),
                escape(', '.join(row.reasons) if row.reasons else '规则不足'),
            ))
        content = '<div class="recommendations">%s</div>' % ''.join(cards)
    return '<section class="card"><h2>推荐击球点</h2>%s</section>' % content


def report_to_json(report: Dict[str, object]) -> Dict[str, object]:
    return {
        'source': report['source'],
        'generated_at': report['generated_at'],
        'stocks': [evaluation_to_json(row) for row in report['evaluations']],
        'recommendations': [evaluation_to_json(row) for row in report['recommendations']],
    }


def evaluation_to_json(row) -> Dict[str, object]:
    quote = row.quote
    return {
        'symbol': row.item.symbol,
        'market': row.item.market,
        'direction': row.item.direction,
        'name': quote.name or row.item.name,
        'price': quote.price,
        'currency': quote.currency,
        'pe': quote.pe,
        'dividend_yield': quote.dividend_yield,
        'suggested_buy_price': row.suggested_buy_price,
        'status': row.status,
        'status_label': stock_agent.STATUS_LABELS[row.status],
        'distance_to_buy': row.distance_to_buy,
        'reasons': row.reasons,
    }


def count_status(evaluations, status: str) -> int:
    return sum(1 for row in evaluations if row.status == status)


def option(value: str, label: str, selected: str) -> str:
    marker = ' selected' if value == selected else ''
    return '<option value="%s"%s>%s</option>' % (escape(value), marker, escape(label))


def escape(value) -> str:
    return html.escape(str(value), quote=True)


def default_path(filename: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the stock tracking agent web UI.')
    parser.add_argument('--host', default='127.0.0.1', help='host to bind')
    parser.add_argument('--port', type=int, default=8000, help='port to bind')
    parser.add_argument('--config', default=default_path('watchlist.example.json'), help='watchlist JSON path')
    parser.add_argument('--quotes', default=default_path('sample_quotes.json'), help='offline quote JSON path')
    parser.add_argument(
        '--source',
        choices=('offline', 'live'),
        default='offline',
        help='default page data source',
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    app = StockWebApp(args.config, args.quotes, args.source)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    url = 'http://%s:%s/' % (args.host, args.port)
    print('Serving stock tracking agent at %s' % url)
    print('Press Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
