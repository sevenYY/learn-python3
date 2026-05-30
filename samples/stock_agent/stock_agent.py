#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import parse, request


MARKET_US = 'US'
MARKET_HK = 'HK'
MARKET_A = 'A'

STATUS_BUY = 'buy_zone'
STATUS_NEAR = 'near'
STATUS_WATCH = 'watch'
STATUS_WAIT = 'wait'
STATUS_NO_DATA = 'no_data'

STATUS_LABELS = {
    STATUS_BUY: '击球区',
    STATUS_NEAR: '临近',
    STATUS_WATCH: '观察',
    STATUS_WAIT: '等待',
    STATUS_NO_DATA: '缺数据',
}


@dataclass
class WatchItem:
    symbol: str
    market: str
    direction: str
    name: str
    yahoo_symbol: str
    target_pe: Optional[float] = None
    target_dividend_yield: Optional[float] = None
    max_buy_price: Optional[float] = None
    safety_margin: float = 0.2


@dataclass
class Quote:
    symbol: str
    name: str
    currency: str
    price: Optional[float]
    pe: Optional[float]
    dividend_yield: Optional[float]
    eps: Optional[float]
    annual_dividend: Optional[float]
    source: str = 'unknown'


@dataclass
class Evaluation:
    item: WatchItem
    quote: Quote
    suggested_buy_price: Optional[float]
    status: str
    distance_to_buy: Optional[float]
    reasons: List[str]


def coerce_float(value: Any) -> Optional[float]:
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(',', '')
        if text.endswith('%'):
            number = coerce_float(text[:-1])
            return None if number is None else number / 100
        try:
            return float(text)
        except ValueError:
            return None
    return None


def normalize_percent(value: Any) -> Optional[float]:
    number = coerce_float(value)
    if number is None:
        return None
    if number < 0:
        return None
    if number > 1:
        return number / 100
    return number


def normalize_yahoo_dividend_yield(raw: Any) -> Optional[float]:
    number = coerce_float(raw)
    if number is None or number < 0:
        return None
    # Yahoo's quote API commonly returns dividendYield as a percentage
    # number, while trailingAnnualDividendYield is already a decimal.
    if number > 0.2:
        return number / 100
    return number


def normalize_market(market: str) -> str:
    text = market.strip().upper()
    if text in ('US', 'USA', 'NASDAQ', 'NYSE'):
        return MARKET_US
    if text in ('HK', 'HKG', 'HONGKONG', 'HONG KONG'):
        return MARKET_HK
    if text in ('A', 'CN', 'CHINA', 'ASHARE', 'A股'):
        return MARKET_A
    raise ValueError('Unsupported market: %s' % market)


def yahoo_symbol(symbol: str, market: str) -> str:
    market = normalize_market(market)
    text = symbol.strip().upper()
    if market == MARKET_US:
        return text
    if market == MARKET_HK:
        if text.endswith('.HK'):
            return text
        code = text.split('.')[0]
        if code.isdigit() and len(code) < 4:
            code = code.zfill(4)
        return '%s.HK' % code
    if market == MARKET_A:
        if text.endswith(('.SS', '.SZ')):
            return text
        code = text.split('.')[0]
        suffix = '.SS' if code.startswith(('5', '6', '9')) else '.SZ'
        return '%s%s' % (code, suffix)
    raise ValueError('Unsupported market: %s' % market)


def a_share_code(symbol: str) -> str:
    return symbol.strip().upper().split('.')[0]


def eastmoney_symbol_prefix(symbol: str) -> str:
    code = a_share_code(symbol)
    return 'SH' if code.startswith(('5', '6', '9')) else 'SZ'


def eastmoney_secid(symbol: str) -> str:
    code = a_share_code(symbol)
    market_id = '1' if eastmoney_symbol_prefix(code) == 'SH' else '0'
    return '%s.%s' % (market_id, code)


def load_watchlist(path: str) -> Tuple[Dict[str, Any], List[WatchItem]]:
    with open(path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    defaults = config.get('defaults', {})
    stocks = []
    for raw in config.get('stocks', []):
        market = normalize_market(raw.get('market', defaults.get('market', MARKET_US)))
        symbol = raw['symbol']
        stock = WatchItem(
            symbol=symbol,
            market=market,
            direction=raw.get('direction', defaults.get('direction', '未分类')),
            name=raw.get('name', symbol),
            yahoo_symbol=raw.get('yahoo_symbol') or yahoo_symbol(symbol, market),
            target_pe=coerce_float(raw.get('target_pe', defaults.get('target_pe'))),
            target_dividend_yield=normalize_percent(
                raw.get('target_dividend_yield', defaults.get('target_dividend_yield'))
            ),
            max_buy_price=coerce_float(raw.get('max_buy_price')),
            safety_margin=coerce_float(raw.get('safety_margin', defaults.get('safety_margin', 0.2))) or 0.2,
        )
        stocks.append(stock)
    return config, stocks


class YahooFinanceProvider(object):
    URL = 'https://query1.finance.yahoo.com/v7/finance/quote'

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch(self, items: Iterable[WatchItem]) -> Dict[str, Quote]:
        symbols = sorted({item.yahoo_symbol for item in items})
        if not symbols:
            return {}

        query = parse.urlencode({'symbols': ','.join(symbols)})
        req = request.Request('%s?%s' % (self.URL, query))
        req.add_header('User-Agent', 'Mozilla/5.0 stock-agent/1.0')

        with request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))

        result = payload.get('quoteResponse', {}).get('result', [])
        return {
            raw.get('symbol'): quote_from_raw(raw, 'yahoo')
            for raw in result
            if raw.get('symbol')
        }


class NasdaqUSQuoteProvider(object):
    URL = 'https://api.nasdaq.com/api/quote/%s/info'

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch(self, items: Iterable[WatchItem]) -> Dict[str, Quote]:
        quotes = {}
        for item in items:
            if item.market != MARKET_US:
                continue
            quote = self.fetch_one(item)
            quotes[item.yahoo_symbol] = quote
        return quotes

    def fetch_one(self, item: WatchItem) -> Quote:
        query = parse.urlencode({'assetclass': 'stocks'})
        url = '%s?%s' % (self.URL % parse.quote(item.yahoo_symbol), query)
        req = request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 stock-agent/1.0')
        req.add_header('Accept', 'application/json, text/plain, */*')
        req.add_header('Origin', 'https://www.nasdaq.com')
        req.add_header('Referer', 'https://www.nasdaq.com/')
        with request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
        return quote_from_nasdaq(payload, item)


class YahooChartQuoteProvider(object):
    URL = 'https://query1.finance.yahoo.com/v8/finance/chart/%s'

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch(self, items: Iterable[WatchItem]) -> Dict[str, Quote]:
        quotes = {}
        for item in items:
            quote = self.fetch_one(item)
            quotes[item.yahoo_symbol] = quote
        return quotes

    def fetch_one(self, item: WatchItem) -> Quote:
        query = parse.urlencode({
            'range': '1d',
            'interval': '1m',
            'includePrePost': 'false',
        })
        url = '%s?%s' % (self.URL % parse.quote(item.yahoo_symbol), query)
        req = request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 stock-agent/1.0')
        with request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
        return quote_from_yahoo_chart(payload, item)


class USLatestPriceProvider(object):
    def __init__(self, timeout: int = 10):
        self.nasdaq = NasdaqUSQuoteProvider(timeout=timeout)
        self.yahoo_chart = YahooChartQuoteProvider(timeout=timeout)

    def fetch(self, items: Iterable[WatchItem]) -> Dict[str, Quote]:
        quotes = {}
        for item in items:
            if item.market != MARKET_US:
                continue
            quote = self.fetch_one(item)
            if quote is not None:
                quotes[item.yahoo_symbol] = quote
        return quotes

    def fetch_one(self, item: WatchItem) -> Optional[Quote]:
        try:
            return self.nasdaq.fetch_one(item)
        except Exception:
            try:
                return self.yahoo_chart.fetch_one(item)
            except Exception:
                return None


class EastMoneyAShareProvider(object):
    QUOTE_URL = 'https://push2.eastmoney.com/api/qt/stock/get'
    BONUS_URL = 'https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/PageAjax'
    QUOTE_FIELDS = ','.join([
        'f43', 'f57', 'f58', 'f59', 'f107', 'f152',
        'f161', 'f162', 'f163', 'f164', 'f167', 'f168', 'f169', 'f170',
    ])

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch(self, items: Iterable[WatchItem]) -> Dict[str, Quote]:
        quotes = {}
        for item in items:
            if item.market != MARKET_A:
                continue
            quote = self.fetch_one(item)
            quotes[item.yahoo_symbol] = quote
        return quotes

    def fetch_one(self, item: WatchItem) -> Quote:
        payload = self._get_json(self.QUOTE_URL, {
            'fltt': '2',
            'invt': '2',
            'secid': eastmoney_secid(item.symbol),
            'fields': self.QUOTE_FIELDS,
        }, referer='https://quote.eastmoney.com/')
        data = payload.get('data') or {}
        quote = quote_from_eastmoney(data, item)

        annual_dividend = self.fetch_annual_dividend(item)
        if annual_dividend is not None:
            quote.annual_dividend = annual_dividend
            if quote.price and quote.price > 0:
                quote.dividend_yield = annual_dividend / quote.price
        return quote

    def fetch_annual_dividend(self, item: WatchItem) -> Optional[float]:
        payload = self._get_json(self.BONUS_URL, {
            'code': '%s%s' % (eastmoney_symbol_prefix(item.symbol), a_share_code(item.symbol)),
        }, referer='https://emweb.securities.eastmoney.com/')
        return annual_dividend_ttm_from_eastmoney_payload(payload)

    def _get_json(self, url: str, params: Dict[str, str], referer: str) -> Dict[str, Any]:
        query = parse.urlencode(params)
        req = request.Request('%s?%s' % (url, query))
        req.add_header('User-Agent', 'Mozilla/5.0 stock-agent/1.0')
        req.add_header('Referer', referer)
        with request.urlopen(req, timeout=self.timeout) as response:
            text = response.read().decode('utf-8')
        return json.loads(strip_jsonp(text))


class LiveQuoteProvider(object):
    def __init__(self, timeout: int = 10):
        self.yahoo = YahooFinanceProvider(timeout=timeout)
        self.us_latest = USLatestPriceProvider(timeout=timeout)
        self.eastmoney = EastMoneyAShareProvider(timeout=timeout)

    def fetch(self, items: Iterable[WatchItem]) -> Dict[str, Quote]:
        item_list = list(items)
        quotes = {}
        yahoo_items = [item for item in item_list if item.market != MARKET_A]
        us_items = [item for item in item_list if item.market == MARKET_US]
        a_share_items = [item for item in item_list if item.market == MARKET_A]
        if yahoo_items:
            quotes.update(self.yahoo.fetch(yahoo_items))
        if us_items:
            latest_quotes = self.us_latest.fetch(us_items)
            quotes = merge_quotes(quotes, latest_quotes)
        if a_share_items:
            quotes.update(self.eastmoney.fetch(a_share_items))
        return quotes


class FixtureQuoteProvider(object):
    def __init__(self, quotes: Dict[str, Quote]):
        self.quotes = quotes

    @classmethod
    def from_path(cls, path: str) -> 'FixtureQuoteProvider':
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)

        if isinstance(payload, dict) and 'quoteResponse' in payload:
            raw_quotes = payload.get('quoteResponse', {}).get('result', [])
            quotes = {
                raw.get('symbol'): quote_from_raw(raw, 'fixture')
                for raw in raw_quotes
                if raw.get('symbol')
            }
        else:
            source = payload.get('source', 'fixture') if isinstance(payload, dict) else 'fixture'
            data = payload.get('quotes', payload) if isinstance(payload, dict) else {}
            quotes = {
                symbol: quote_from_raw(dict(raw, symbol=symbol), source)
                for symbol, raw in data.items()
            }
        return cls(quotes)

    def fetch(self, items: Iterable[WatchItem]) -> Dict[str, Quote]:
        return {
            item.yahoo_symbol: self.quotes[item.yahoo_symbol]
            for item in items
            if item.yahoo_symbol in self.quotes
        }


def quote_from_raw(raw: Dict[str, Any], source: str) -> Quote:
    price = first_float(raw, 'regularMarketPrice', 'price', 'currentPrice')
    dividend_yield = first_float(raw, 'trailingAnnualDividendYield')
    if dividend_yield is None:
        dividend_yield = normalize_yahoo_dividend_yield(raw.get('dividendYield'))
    else:
        dividend_yield = normalize_percent(dividend_yield)

    annual_dividend = first_float(raw, 'trailingAnnualDividendRate', 'dividendRate', 'annualDividend')
    if annual_dividend is None and price is not None and dividend_yield is not None:
        annual_dividend = price * dividend_yield

    return Quote(
        symbol=raw.get('symbol', ''),
        name=raw.get('shortName') or raw.get('longName') or raw.get('name') or raw.get('symbol', ''),
        currency=raw.get('currency', ''),
        price=price,
        pe=first_float(raw, 'trailingPE', 'pe', 'forwardPE'),
        dividend_yield=dividend_yield,
        eps=first_float(raw, 'epsTrailingTwelveMonths', 'eps'),
        annual_dividend=annual_dividend,
        source=source,
    )


def quote_from_nasdaq(payload: Dict[str, Any], item: WatchItem) -> Quote:
    data = payload.get('data') or {}
    primary = data.get('primaryData') or {}
    price = parse_market_price(primary.get('lastSalePrice') or data.get('lastSalePrice'))
    return Quote(
        symbol=item.yahoo_symbol,
        name=data.get('companyName') or item.name,
        currency='USD',
        price=price,
        pe=None,
        dividend_yield=None,
        eps=None,
        annual_dividend=None,
        source='nasdaq',
    )


def quote_from_yahoo_chart(payload: Dict[str, Any], item: WatchItem) -> Quote:
    result = (payload.get('chart') or {}).get('result') or []
    data = result[0] if result else {}
    meta = data.get('meta') or {}
    price = first_latest_close(data)
    if price is None:
        price = coerce_float(meta.get('regularMarketPrice'))
    return Quote(
        symbol=item.yahoo_symbol,
        name=item.name,
        currency=meta.get('currency') or ('USD' if item.market == MARKET_US else ''),
        price=price,
        pe=None,
        dividend_yield=None,
        eps=None,
        annual_dividend=None,
        source='yahoo-chart',
    )


def first_latest_close(chart_result: Dict[str, Any]) -> Optional[float]:
    indicators = chart_result.get('indicators') or {}
    quote_sets = indicators.get('quote') or []
    if not quote_sets:
        return None
    closes = quote_sets[0].get('close') or []
    for value in reversed(closes):
        number = coerce_float(value)
        if number is not None:
            return number
    return None


def parse_market_price(value: Any) -> Optional[float]:
    if isinstance(value, str):
        value = value.replace('$', '').replace('HK$', '').replace('USD', '').strip()
    return coerce_float(value)


def merge_quotes(base: Dict[str, Quote], overlay: Dict[str, Quote]) -> Dict[str, Quote]:
    merged = dict(base)
    for symbol, latest in overlay.items():
        current = merged.get(symbol)
        if current is None:
            merged[symbol] = latest
        else:
            if latest.price is not None:
                current.price = latest.price
            if latest.currency:
                current.currency = latest.currency
            if latest.name and not current.name:
                current.name = latest.name
            current.source = '%s+%s' % (current.source, latest.source)
    return merged


def quote_from_eastmoney(raw: Dict[str, Any], item: WatchItem) -> Quote:
    price = eastmoney_price(raw.get('f43'), raw.get('f59') or raw.get('f152'))
    pe = first_float(raw, 'f162', 'f161', 'f163', 'f9', 'f115')
    return Quote(
        symbol=item.yahoo_symbol,
        name=raw.get('f58') or item.name,
        currency='CNY',
        price=price,
        pe=pe,
        dividend_yield=None,
        eps=price / pe if price and pe and pe > 0 else None,
        annual_dividend=None,
        source='eastmoney',
    )


def eastmoney_price(value: Any, scale: Any = None) -> Optional[float]:
    number = coerce_float(value)
    if number is None or number < 0:
        return None
    scale_number = coerce_float(scale)
    if isinstance(value, int) and scale_number is not None and scale_number >= 0:
        return number / (10 ** int(scale_number))
    return number


def strip_jsonp(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith('{') or stripped.startswith('['):
        return stripped
    match = re.search(r'^[^(]+\((.*)\)\s*;?$', stripped, re.S)
    if match:
        return match.group(1)
    return stripped


def annual_dividend_from_eastmoney_payload(payload: Any) -> Optional[float]:
    return annual_dividend_ttm_from_eastmoney_payload(payload)


def annual_dividend_ttm_from_eastmoney_payload(payload: Any, as_of=None) -> Optional[float]:
    records = []
    fallback = []
    for record in walk_dicts(payload):
        dividend = annual_dividend_from_record(record)
        if dividend is None:
            continue
        fallback.append(dividend)
        date_value = dividend_record_date(record)
        if date_value is not None:
            records.append((date_value, dividend))

    if not records:
        return fallback[0] if fallback else None

    if as_of is None:
        as_of = datetime.now().date()
    elif isinstance(as_of, datetime):
        as_of = as_of.date()

    start = as_of - timedelta(days=366)
    ttm_values = [dividend for date_value, dividend in records if start <= date_value <= as_of]
    if not ttm_values:
        latest_date = max(date_value for date_value, _ in records)
        start = latest_date - timedelta(days=366)
        ttm_values = [dividend for date_value, dividend in records if start <= date_value <= latest_date]
    return sum(ttm_values) if ttm_values else None


def annual_dividend_from_record(record: Dict[str, Any]) -> Optional[float]:
    cash_keys = [
        'CASHBTAXRMB',
        'CASH_BTAX_RMB',
        'CASH_DIVIDEND_RATIO',
        'PRETAX_BONUS_RMB',
        'BONUS_RATIO_RMB',
    ]
    for key in cash_keys:
        value = coerce_float(record.get(key))
        if value and value > 0:
            # EastMoney F10 cash dividend fields are usually RMB per 10 shares.
            return value / 10

    text_keys = [
        'IMPL_PLAN_PROFILE',
        'DISTRIBUTION_PLAN',
        'PLAN_EXPLAIN',
        'ASSIGNDSCRPT',
    ]
    for key in text_keys:
        value = record.get(key)
        if value:
            parsed = annual_dividend_from_text(str(value))
            if parsed is not None:
                return parsed
    return None


def dividend_record_date(record: Dict[str, Any]):
    date_keys = [
        'EX_DIVIDEND_DATE',
        'EX_DIVIDEND_DT',
        'EQUITY_RECORD_DATE',
        'REGISTRATION_DATE',
        'IMPLEMENTATION_DATE',
        'NOTICE_DATE',
        'REPORT_DATE',
    ]
    for key in date_keys:
        parsed = parse_date(record.get(key))
        if parsed is not None:
            return parsed
    return None


def parse_date(value: Any):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.split('T')[0].split(' ')[0].replace('/', '-')
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def annual_dividend_from_text(text: str) -> Optional[float]:
    match = re.search(r'10\s*(?:股)?\s*派\s*([0-9]+(?:\.[0-9]+)?)\s*元?', text)
    if not match:
        return None
    amount = coerce_float(match.group(1))
    if amount is None or amount <= 0:
        return None
    return amount / 10


def walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def first_float(raw: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = coerce_float(raw.get(key))
        if value is not None:
            return value
    return None


def evaluate(item: WatchItem, quote: Quote) -> Evaluation:
    candidates = []
    reasons = []

    if item.target_pe and item.target_pe > 0:
        pe_price = None
        if quote.eps and quote.eps > 0:
            pe_price = quote.eps * item.target_pe
        elif quote.price and quote.pe and quote.pe > 0:
            pe_price = quote.price * item.target_pe / quote.pe
        if pe_price is not None:
            candidates.append(pe_price)
            reasons.append('PE <= %.1f' % item.target_pe)

    if item.target_dividend_yield and item.target_dividend_yield > 0:
        annual_dividend = quote.annual_dividend
        if annual_dividend is None and quote.price and quote.dividend_yield:
            annual_dividend = quote.price * quote.dividend_yield
        if annual_dividend and annual_dividend > 0:
            dividend_price = annual_dividend / item.target_dividend_yield
            candidates.append(dividend_price)
            reasons.append('股息率 >= %s' % format_percent(item.target_dividend_yield))

    if item.max_buy_price:
        candidates.append(item.max_buy_price)
        reasons.append('手动买入价')

    if not candidates and quote.price:
        candidates.append(quote.price * (1 - item.safety_margin))
        reasons.append('安全边际 %.0f%%' % (item.safety_margin * 100))

    suggested = min(candidates) if candidates else None
    distance = None
    if suggested is not None and quote.price and quote.price > 0:
        distance = (suggested - quote.price) / quote.price

    return Evaluation(
        item=item,
        quote=quote,
        suggested_buy_price=suggested,
        status=status_for(quote.price, suggested),
        distance_to_buy=distance,
        reasons=reasons,
    )


def status_for(price: Optional[float], suggested_buy_price: Optional[float]) -> str:
    if price is None or suggested_buy_price is None or suggested_buy_price <= 0:
        return STATUS_NO_DATA
    if price <= suggested_buy_price:
        return STATUS_BUY
    if price <= suggested_buy_price * 1.05:
        return STATUS_NEAR
    if price <= suggested_buy_price * 1.15:
        return STATUS_WATCH
    return STATUS_WAIT


def build_evaluations(items: Iterable[WatchItem], quotes: Dict[str, Quote]) -> List[Evaluation]:
    rows = []
    for item in items:
        quote = quotes.get(item.yahoo_symbol)
        if quote is None:
            quote = Quote(
                symbol=item.yahoo_symbol,
                name=item.name,
                currency='',
                price=None,
                pe=None,
                dividend_yield=None,
                eps=None,
                annual_dividend=None,
            )
        if not quote.name:
            quote.name = item.name
        rows.append(evaluate(item, quote))
    return rows


def filter_items(items: List[WatchItem], market: Optional[str], direction: Optional[str]) -> List[WatchItem]:
    filtered = items
    if market:
        wanted_market = normalize_market(market)
        filtered = [item for item in filtered if item.market == wanted_market]
    if direction:
        wanted_direction = direction.strip().lower()
        filtered = [item for item in filtered if item.direction.lower() == wanted_direction]
    return filtered


def recommendation_sort_key(row: Evaluation) -> Tuple[int, float]:
    status_rank = {
        STATUS_BUY: 0,
        STATUS_NEAR: 1,
        STATUS_WATCH: 2,
        STATUS_WAIT: 3,
        STATUS_NO_DATA: 4,
    }
    distance = row.distance_to_buy if row.distance_to_buy is not None else -999
    return status_rank.get(row.status, 9), -distance


def render_report(evaluations: List[Evaluation], top: int = 5) -> str:
    lines = []
    lines.append('股票追踪 Agent 报告')
    lines.append('')
    lines.extend(render_table(evaluations))

    recommendations = [
        row for row in evaluations
        if row.status in (STATUS_BUY, STATUS_NEAR, STATUS_WATCH)
    ]
    recommendations.sort(key=recommendation_sort_key)

    lines.append('')
    lines.append('推荐击球点')
    if not recommendations:
        lines.append('- 暂无进入买入区或临近买入区的股票。')
    else:
        for row in recommendations[:top]:
            quote = row.quote
            price = format_price(quote.price, quote.currency)
            buy_price = format_price(row.suggested_buy_price, quote.currency)
            distance = format_percent(row.distance_to_buy)
            reason = ', '.join(row.reasons) if row.reasons else '规则不足'
            lines.append(
                '- %s %s（%s/%s）：现价 %s，买入线 %s，%s，偏离 %s；依据：%s。'
                % (
                    row.item.symbol,
                    quote.name or row.item.name,
                    row.item.market,
                    row.item.direction,
                    price,
                    buy_price,
                    STATUS_LABELS[row.status],
                    distance,
                    reason,
                )
            )
    return '\n'.join(lines)


def render_table(evaluations: List[Evaluation]) -> List[str]:
    headers = ['方向', '市场', '代码', '名称', '现价', 'PE', '股息率', '买入价', '状态', '偏离']
    rows = []
    for row in evaluations:
        quote = row.quote
        rows.append([
            row.item.direction,
            row.item.market,
            row.item.symbol,
            quote.name or row.item.name,
            format_price(quote.price, quote.currency),
            format_number(quote.pe),
            format_percent(quote.dividend_yield),
            format_price(row.suggested_buy_price, quote.currency),
            STATUS_LABELS[row.status],
            format_percent(row.distance_to_buy),
        ])
    return make_table(headers, rows)


def make_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def fmt(row: List[str]) -> str:
        return ' | '.join(value.ljust(widths[index]) for index, value in enumerate(row))

    lines = [fmt(headers)]
    lines.append('-+-'.join('-' * width for width in widths))
    lines.extend(fmt(row) for row in rows)
    return lines


def format_number(value: Optional[float]) -> str:
    if value is None:
        return '-'
    return '%.2f' % value


def format_percent(value: Optional[float]) -> str:
    if value is None:
        return '-'
    return '%.2f%%' % (value * 100)


def format_price(value: Optional[float], currency: str = '') -> str:
    if value is None:
        return '-'
    if currency:
        return '%s %.2f' % (currency, value)
    return '%.2f' % value


def default_path(filename: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Track HK/US/A-share stocks and recommend buy zones.')
    parser.add_argument(
        '--config',
        default=default_path('watchlist.example.json'),
        help='watchlist JSON config path',
    )
    parser.add_argument(
        '--quotes',
        help='read quotes from a JSON fixture instead of Yahoo Finance',
    )
    parser.add_argument(
        '--offline',
        action='store_true',
        help='use the bundled sample quote data',
    )
    parser.add_argument('--market', help='filter by market: US, HK, A')
    parser.add_argument('--direction', help='filter by investment direction')
    parser.add_argument('--top', type=int, default=5, help='number of recommendations to show')
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    config, items = load_watchlist(args.config)
    items = filter_items(items, args.market, args.direction)

    if not items:
        print('No stocks matched the filters.', file=sys.stderr)
        return 1

    quote_path = args.quotes
    if args.offline and not quote_path:
        quote_path = default_path('sample_quotes.json')

    provider = FixtureQuoteProvider.from_path(quote_path) if quote_path else LiveQuoteProvider()
    try:
        quotes = provider.fetch(items)
    except Exception as e:
        print('Failed to fetch quotes: %s' % e, file=sys.stderr)
        print('Tip: retry with --offline or --quotes <path> when network access is unavailable.', file=sys.stderr)
        return 2

    evaluations = build_evaluations(items, quotes)
    title = config.get('name')
    if title:
        print(title)
        print('=' * len(title))
    print(render_report(evaluations, top=args.top))
    return 0


if __name__ == '__main__':
    sys.exit(main())
