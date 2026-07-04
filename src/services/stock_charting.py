# -*- coding: utf-8 -*-
"""
Stock Charting Service

Converts stock data (akshare) to ChartGenerator-compatible chart configurations.
Supports: price trend charts, financial indicator trend charts, valuation band charts.
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.services.chart_generator import ChartGenerator, ChartConfig, ChartType

logger = logging.getLogger(__name__)


class StockChartService:
    """
    Stock Charting Service
    
    Usage:
        1. StockDataSkill fetches data
        2. StockChartService converts to ChartConfig
        3. ChartGenerator generates images
    """
    
    def __init__(self, output_dir: str = "output/charts"):
        self.generator = ChartGenerator(output_dir=output_dir)
    
    def _extract_field(self, row: Dict, *keys) -> Any:
        for k in keys:
            if k in row and row[k] is not None:
                return row[k]
        return None

    async def price_chart(self, symbol: str, price_data: List[Dict]) -> Dict[str, Any]:
        """Generate price trend chart"""
        if not price_data:
            return {"success": False, "error": "No price data"}
        
        try:
            dates = []
            prices = []
            for row in price_data[:60]:
                date_val = self._extract_field(row, "date", "日期", "trade_date")
                dates.append(str(date_val)[-5:] if date_val else "")
                close = self._extract_field(row, "close", "收盘", "close_price")
                prices.append(float(close) if close else 0)
            
            config = ChartConfig(
                chart_type=ChartType.LINE,
                title=f"{symbol} Price Trend",
                data={
                    "years": dates,
                    "scenarios": {symbol: prices},
                },
                xlabel="Date",
                ylabel="Close Price",
                source="akshare/Stock Quotes",
            )
            result = self.generator.generate(config)
            return {"success": True, "chart_path": result.image_path, "chart_type": "line"}
        except Exception as e:
            logger.error(f"Price chart generation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def financial_trend_chart(self, symbol: str, financial_data: Dict) -> Dict[str, Any]:
        """Generate financial trend chart (revenue/net profit trend)"""
        income = financial_data.get("income_statement", [])
        if not income or not isinstance(income, list):
            return {"success": False, "error": "No financial data"}
        
        try:
            periods = []
            revenue = []
            net_profit = []
            
            for row in income[:8]:
                periods.append(str(self._extract_field(row, "period", "报告期", "REPORT_DATE", "截止日期", ""))[-7:])
                rev = self._extract_field(row, "revenue", "营业总收入", "营业收入", "TOTAL_OPERATE_INCOME")
                np_ = self._extract_field(row, "net_profit", "净利润", "归属净利润", "NET_PROFIT", "PARENT_NETPROFIT")
                revenue.append(float(rev) if rev else 0)
                net_profit.append(float(np_) if np_ else 0)
            
            if len(revenue) < 2:
                return {"success": False, "error": "Insufficient data"}
            
            config = ChartConfig(
                chart_type=ChartType.BAR_LINE,
                title=f"{symbol} Revenue & Net Profit Trend",
                data={
                    "years": periods,
                    "bar": revenue,
                    "line": net_profit,
                    "bar_label": "Revenue",
                    "line_label": "Net Profit",
                },
                xlabel="Period",
                ylabel="Amount (CNY)",
                source="akshare/Financial Statements",
            )
            result = self.generator.generate(config)
            return {"success": True, "chart_path": result.image_path, "chart_type": "bar_line"}
        except Exception as e:
            logger.error(f"Financial trend chart generation failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def valuation_band_chart(self, symbol: str, price_data: List[Dict]) -> Dict[str, Any]:
        """Generate valuation band chart"""
        if not price_data or len(price_data) < 20:
            return {"success": False, "error": "Insufficient data"}
        
        try:
            dates = []
            prices = []
            for row in price_data[:120]:
                date_val = self._extract_field(row, "date", "日期", "trade_date")
                dates.append(str(date_val)[-5:] if date_val else "")
                close = self._extract_field(row, "close", "收盘", "close_price")
                prices.append(float(close) if close else 0)
            
            if not prices:
                return {"success": False, "error": "No valid price data"}
            
            avg = sum(prices) / len(prices)
            upper = avg * 1.2
            lower = avg * 0.8
            
            config = ChartConfig(
                chart_type=ChartType.LINE,
                title=f"{symbol} Price & Valuation Band",
                data={
                    "years": dates,
                    "scenarios": {
                        "Close Price": prices,
                        "Upper Band": [upper] * len(prices),
                        "Lower Band": [lower] * len(prices),
                    },
                },
                xlabel="Date",
                ylabel="Price",
                source="akshare/Stock Quotes",
            )
            result = self.generator.generate(config)
            return {"success": True, "chart_path": result.image_path, "chart_type": "valuation_band"}
        except Exception as e:
            logger.error(f"Valuation band chart generation failed: {e}")
            return {"success": False, "error": str(e)}
