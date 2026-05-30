#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stock_agent


class StockAgentTest(unittest.TestCase):

    def test_yahoo_symbol_normalizes_three_markets(self):
        self.assertEqual(stock_agent.yahoo_symbol('AAPL', 'US'), 'AAPL')
        self.assertEqual(stock_agent.yahoo_symbol('700', 'HK'), '0700.HK')
        self.assertEqual(stock_agent.yahoo_symbol('9988', 'HK'), '9988.HK')
        self.assertEqual(stock_agent.yahoo_symbol('600519', 'A'), '600519.SS')
        self.assertEqual(stock_agent.yahoo_symbol('000001', 'A'), '000001.SZ')

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
        self.assertIn('股票追踪 Agent 报告', report)
        self.assertIn('推荐击球点', report)
        self.assertIn('000001', report)


if __name__ == '__main__':
    unittest.main()
