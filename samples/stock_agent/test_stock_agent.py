#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stock_agent
import web_agent


class StockAgentTest(unittest.TestCase):

    def test_yahoo_symbol_normalizes_three_markets(self):
        self.assertEqual(stock_agent.yahoo_symbol('AAPL', 'US'), 'AAPL')
        self.assertEqual(stock_agent.yahoo_symbol('700', 'HK'), '0700.HK')
        self.assertEqual(stock_agent.yahoo_symbol('9988', 'HK'), '9988.HK')
        self.assertEqual(stock_agent.yahoo_symbol('600519', 'A'), '600519.SS')
        self.assertEqual(stock_agent.yahoo_symbol('000001', 'A'), '000001.SZ')

    def test_us_latest_quote_parsers_preserve_fundamentals(self):
        item = stock_agent.WatchItem(
            symbol='AAPL',
            market='US',
            direction='AI算力',
            name='Apple',
            yahoo_symbol='AAPL',
        )
        nasdaq = stock_agent.quote_from_nasdaq({
            'data': {
                'companyName': 'Apple Inc.',
                'primaryData': {'lastSalePrice': '$210.12'},
            }
        }, item)
        chart = stock_agent.quote_from_yahoo_chart({
            'chart': {
                'result': [{
                    'meta': {'currency': 'USD', 'regularMarketPrice': 209.0},
                    'indicators': {'quote': [{'close': [None, 208.5, 209.7]}]},
                }]
            }
        }, item)
        base = stock_agent.Quote(
            symbol='AAPL',
            name='Apple Inc.',
            currency='USD',
            price=188.5,
            pe=29.2,
            dividend_yield=0.0051,
            eps=6.45,
            annual_dividend=1.0,
            source='yahoo',
        )

        merged = stock_agent.merge_quotes({'AAPL': base}, {'AAPL': nasdaq})

        self.assertEqual(nasdaq.source, 'nasdaq')
        self.assertAlmostEqual(nasdaq.price, 210.12)
        self.assertAlmostEqual(chart.price, 209.7)
        self.assertAlmostEqual(merged['AAPL'].price, 210.12)
        self.assertAlmostEqual(merged['AAPL'].pe, 29.2)
        self.assertEqual(merged['AAPL'].source, 'yahoo+nasdaq')

    def test_eastmoney_helpers_parse_a_share_data(self):
        self.assertEqual(stock_agent.eastmoney_secid('600519'), '1.600519')
        self.assertEqual(stock_agent.eastmoney_secid('000001'), '0.000001')

        item = stock_agent.WatchItem(
            symbol='600519',
            market='A',
            direction='消费龙头',
            name='贵州茅台',
            yahoo_symbol='600519.SS',
        )
        quote = stock_agent.quote_from_eastmoney({
            'f43': 132600,
            'f59': 2,
            'f58': '贵州茅台',
            'f162': 22.68,
        }, item)

        self.assertEqual(quote.source, 'eastmoney')
        self.assertEqual(quote.currency, 'CNY')
        self.assertAlmostEqual(quote.price, 1326.0)
        self.assertAlmostEqual(quote.pe, 22.68)
        self.assertAlmostEqual(quote.eps, 1326.0 / 22.68)

    def test_eastmoney_dividend_payload_supports_f10_shapes(self):
        payload = {
            'Result': {
                'Data': [
                    {
                        'EX_DIVIDEND_DATE': '2025-12-31',
                        'CASHBTAXRMB': 276.91,
                    },
                    {
                        'EX_DIVIDEND_DATE': '2025-09-10',
                        'CASHBTAXRMB': 238.82,
                    },
                    {
                        'EX_DIVIDEND_DATE': '2024-01-10',
                        'CASHBTAXRMB': 192.93,
                    },
                ]
            }
        }
        self.assertAlmostEqual(
            stock_agent.annual_dividend_ttm_from_eastmoney_payload(payload, as_of=stock_agent.parse_date('2026-01-01')),
            51.573,
        )
        self.assertAlmostEqual(
            stock_agent.annual_dividend_from_text('10派276.91元'),
            27.691,
        )

    def test_evaluate_uses_conservative_buy_price(self):
        item = stock_agent.WatchItem(
            symbol='TEST',
            market='US',
            direction='AI',
            name='Test Co',
            yahoo_symbol='TEST',
            target_pe=12,
            target_dividend_yield=0.04,
            max_buy_price=85,
        )
        quote = stock_agent.Quote(
            symbol='TEST',
            name='Test Co',
            currency='USD',
            price=82,
            pe=15,
            dividend_yield=0.03,
            eps=6,
            annual_dividend=3,
        )

        row = stock_agent.evaluate(item, quote)

        self.assertEqual(row.suggested_buy_price, 72)
        self.assertEqual(row.status, stock_agent.STATUS_WATCH)
        self.assertIn('PE <= 12.0', row.reasons)
        self.assertIn('股息率 >= 4.00%', row.reasons)
        self.assertIn('手动买入价', row.reasons)

    def test_evaluate_marks_buy_zone(self):
        item = stock_agent.WatchItem(
            symbol='DIV',
            market='HK',
            direction='高股息',
            name='Dividend Co',
            yahoo_symbol='DIV.HK',
            target_dividend_yield=0.05,
        )
        quote = stock_agent.Quote(
            symbol='DIV.HK',
            name='Dividend Co',
            currency='HKD',
            price=60,
            pe=8,
            dividend_yield=0.06,
            eps=7.5,
            annual_dividend=3.6,
        )

        row = stock_agent.evaluate(item, quote)

        self.assertAlmostEqual(row.suggested_buy_price, 72)
        self.assertEqual(row.status, stock_agent.STATUS_BUY)
        self.assertAlmostEqual(row.distance_to_buy, 0.2)

    def test_loads_fixture_and_builds_report(self):
        base = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base, 'watchlist.example.json')
        quote_path = os.path.join(base, 'sample_quotes.json')
        _, items = stock_agent.load_watchlist(config_path)
        provider = stock_agent.FixtureQuoteProvider.from_path(quote_path)

        evaluations = stock_agent.build_evaluations(items, provider.fetch(items))
        report = stock_agent.render_report(evaluations, top=3)

        self.assertEqual(len(evaluations), 6)
        maotai = next(row for row in evaluations if row.item.symbol == '600519')
        self.assertEqual(maotai.quote.price, 1326.0)
        self.assertAlmostEqual(maotai.quote.dividend_yield, 0.0392)
        self.assertIn('股票追踪 Agent 报告', report)
        self.assertIn('推荐击球点', report)
        self.assertIn('000001', report)

    def test_web_app_builds_page_and_json_report(self):
        base = os.path.dirname(os.path.abspath(__file__))
        app = web_agent.StockWebApp(
            os.path.join(base, 'watchlist.example.json'),
            os.path.join(base, 'sample_quotes.json'),
            default_source='offline',
        )

        report = app.build_report({'source': ['offline'], 'market': ['HK'], 'top': ['2']})
        page = web_agent.render_page(report)
        payload = web_agent.report_to_json(report)

        self.assertIn('股票追踪 Agent', page)
        self.assertIn('腾讯控股', page)
        self.assertIn('汇丰控股', page)
        self.assertEqual(len(payload['stocks']), 2)
        self.assertEqual(payload['source'], 'offline')


if __name__ == '__main__':
    unittest.main()
