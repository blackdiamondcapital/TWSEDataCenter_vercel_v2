#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

# 可選地指定 yfinance 套件路徑（若存在才加入），避免在雲端環境造成錯誤
yfinance_path = '/opt/anaconda3/envs/bdstock/lib/python3.10/site-packages'
try:
    if os.path.isdir(yfinance_path) and yfinance_path not in sys.path:
        sys.path.insert(0, yfinance_path)
except Exception:
    pass

import time
import requests
import pandas as pd
import yfinance as yf
import numpy as np
from datetime import datetime, timedelta, date
import logging
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import os
import math

# 配置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 獲取當前目錄作為靜態文件目錄
current_dir = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder=current_dir, static_url_path='')
CORS(app)  # 允許跨域請求

class DatabaseManager:
    def __init__(self):
        # 優先使用環境變數中的 DATABASE_URL（例如 Neon 提供的連線字串）
        # 範例: postgresql://user:pass@host/dbname?sslmode=require
        self.database_url = os.environ.get('DATABASE_URL')
        # 仍保留本機預設（開發環境用）
        self.db_config = {
            'host': os.environ.get('PGHOST', 'localhost'),
            'port': os.environ.get('PGPORT', '5432'),
            'user': os.environ.get('PGUSER', 'postgres'),
            'password': os.environ.get('PGPASSWORD', ''),
            'database': os.environ.get('PGDATABASE', 'postgres')
        }
        self.connection = None
        
    def connect(self):
        """連接到PostgreSQL資料庫"""
        try:
            if self.database_url:
                # 直接使用連線字串（Neon 建議 sslmode=require 已在 URI 內）
                self.connection = psycopg2.connect(self.database_url, cursor_factory=RealDictCursor)
            else:
                self.connection = psycopg2.connect(
                    host=self.db_config['host'],
                    port=self.db_config['port'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    database=self.db_config['database'],
                    cursor_factory=RealDictCursor
                )
            logger.info("資料庫連接成功")
            return True
        except Exception as e:
            logger.error(f"資料庫連接失敗: {e}")
            return False
    
    def disconnect(self):
        """斷開資料庫連接"""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.info("資料庫連接已關閉")
    
    def test_connection(self):
        """測試資料庫連接"""
        try:
            if self.connect():
                cursor = self.connection.cursor()
                cursor.execute("SELECT version();")
                version = cursor.fetchone()
                cursor.close()
                self.disconnect()
                return True, f"PostgreSQL版本: {version['version']}"
            else:
                return False, "無法連接到資料庫"
        except Exception as e:
            return False, f"連接測試失敗: {e}"
    
    def create_tables(self):
        """創建股票數據表"""
        try:
            if self.connection is None:
                if not self.connect():
                    return False
                
            cursor = self.connection.cursor()
            
            # 創建股票代碼表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_symbols (
                    symbol VARCHAR(20) PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    market VARCHAR(20),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 創建股價數據表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_prices (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    date DATE NOT NULL,
                    open_price DECIMAL(10,2),
                    high_price DECIMAL(10,2),
                    low_price DECIMAL(10,2),
                    close_price DECIMAL(10,2),
                    volume BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, date)
                );
            """)
            
            # 創建報酬率數據表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_returns (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    date DATE NOT NULL,
                    daily_return DECIMAL(10,6),
                    weekly_return DECIMAL(10,6),
                    monthly_return DECIMAL(10,6),
                    cumulative_return DECIMAL(10,6),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, date)
                );
            """)
            
            # 為現有表添加新欄位（如果不存在）
            try:
                cursor.execute("""
                    ALTER TABLE stock_returns 
                    ADD COLUMN IF NOT EXISTS weekly_return DECIMAL(10,6),
                    ADD COLUMN IF NOT EXISTS monthly_return DECIMAL(10,6);
                """)
            except Exception as e:
                logger.warning(f"添加新欄位時出現警告: {e}")
                # 嘗試單獨添加每個欄位
                try:
                    cursor.execute("ALTER TABLE stock_returns ADD COLUMN IF NOT EXISTS weekly_return DECIMAL(10,6);")
                    cursor.execute("ALTER TABLE stock_returns ADD COLUMN IF NOT EXISTS monthly_return DECIMAL(10,6);")
                except Exception as e2:
                    logger.warning(f"單獨添加欄位也失敗: {e2}")
            
            self.connection.commit()
            cursor.close()
            logger.info("資料庫表創建成功")
            return True
        except Exception as e:
            logger.error(f"創建表失敗: {e}")
            return False

class StockDataAPI:
    def __init__(self):
        self.symbols_cache = None
        self.cache_time = None
        self.db_manager = DatabaseManager()
        
    def fetch_twse_symbols(self):
        """抓取台灣上市公司股票代碼"""
        try:
            url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=2'
            # 加入SSL憑證驗證處理和User-Agent
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, timeout=10, verify=False, headers=headers)
            response.encoding = 'big5'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            table = soup.find('table', {'class': 'h4'})
            if not table:
                tables = soup.find_all('table')
                if tables:
                    table = tables[0]
                else:
                    return []
            
            rows = table.find_all('tr')[1:]
            symbols = []
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > 1 and cols[0].text.strip():
                    code_name = cols[0].text.strip().split()
                    if len(code_name) >= 2 and code_name[0].isdigit():
                        symbols.append({
                            'symbol': code_name[0] + '.TW', 
                            'name': code_name[1],
                            'market': '上市'
                        })
            
            logger.info(f"取得 {len(symbols)} 檔上市股票")
            return symbols
        except Exception as e:
            logger.error(f"抓取上市股票失敗: {e}")
            # 返回備用的熱門上市股票清單
            return self.get_backup_twse_symbols()

    def fetch_otc_symbols(self):
        """抓取台灣櫃檯買賣中心股票代碼"""
        try:
            url = 'https://isin.twse.com.tw/isin/C_public.jsp?strMode=4'
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, timeout=10, verify=False, headers=headers)
            response.encoding = 'big5'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            table = soup.find('table', {'class': 'h4'})
            if not table:
                tables = soup.find_all('table')
                if tables:
                    table = tables[0]
                else:
                    return []
            
            rows = table.find_all('tr')[1:]
            symbols = []
            for row in rows:
                cols = row.find_all('td')
                if len(cols) > 1 and cols[0].text.strip():
                    code_name = cols[0].text.strip().split()
                    if len(code_name) >= 2 and code_name[0].isdigit():
                        symbols.append({
                            'symbol': code_name[0] + '.TWO', 
                            'name': code_name[1],
                            'market': '上櫃'
                        })
            
            logger.info(f"取得 {len(symbols)} 檔櫃檯股票")
            return symbols
        except Exception as e:
            logger.error(f"抓取櫃檯股票失敗: {e}")
            # 返回備用的熱門櫃檯股票清單
            return self.get_backup_otc_symbols()
    
    def get_backup_twse_symbols(self):
        """備用的熱門上市股票清單"""
        backup_symbols = [
            {'symbol': '2330.TW', 'name': '台積電', 'market': '上市'},
            {'symbol': '2317.TW', 'name': '鴻海', 'market': '上市'},
            {'symbol': '2454.TW', 'name': '聯發科', 'market': '上市'},
            {'symbol': '2881.TW', 'name': '富邦金', 'market': '上市'},
            {'symbol': '2882.TW', 'name': '國泰金', 'market': '上市'},
            {'symbol': '2886.TW', 'name': '兆豐金', 'market': '上市'},
            {'symbol': '2891.TW', 'name': '中信金', 'market': '上市'},
            {'symbol': '2892.TW', 'name': '第一金', 'market': '上市'},
            {'symbol': '2303.TW', 'name': '聯電', 'market': '上市'},
            {'symbol': '2308.TW', 'name': '台達電', 'market': '上市'},
            {'symbol': '2382.TW', 'name': '廣達', 'market': '上市'},
            {'symbol': '2412.TW', 'name': '中華電', 'market': '上市'},
            {'symbol': '2474.TW', 'name': '可成', 'market': '上市'},
            {'symbol': '3008.TW', 'name': '大立光', 'market': '上市'},
            {'symbol': '3711.TW', 'name': '日月光投控', 'market': '上市'},
            {'symbol': '5880.TW', 'name': '合庫金', 'market': '上市'},
            {'symbol': '6505.TW', 'name': '台塑化', 'market': '上市'},
            {'symbol': '1301.TW', 'name': '台塑', 'market': '上市'},
            {'symbol': '1303.TW', 'name': '南亞', 'market': '上市'},
            {'symbol': '1326.TW', 'name': '台化', 'market': '上市'},
            {'symbol': '2002.TW', 'name': '中鋼', 'market': '上市'},
            {'symbol': '2207.TW', 'name': '和泰車', 'market': '上市'},
            {'symbol': '2357.TW', 'name': '華碩', 'market': '上市'},
            {'symbol': '2395.TW', 'name': '研華', 'market': '上市'},
            {'symbol': '2408.TW', 'name': '南亞科', 'market': '上市'},
            {'symbol': '2409.TW', 'name': '友達', 'market': '上市'},
            {'symbol': '2603.TW', 'name': '長榮', 'market': '上市'},
            {'symbol': '2609.TW', 'name': '陽明', 'market': '上市'},
            {'symbol': '2615.TW', 'name': '萬海', 'market': '上市'},
            {'symbol': '3034.TW', 'name': '聯詠', 'market': '上市'},
            {'symbol': '3045.TW', 'name': '台灣大', 'market': '上市'},
            {'symbol': '4904.TW', 'name': '遠傳', 'market': '上市'},
            {'symbol': '6415.TW', 'name': '矽力-KY', 'market': '上市'},
            {'symbol': '2327.TW', 'name': '國巨', 'market': '上市'},
            {'symbol': '2379.TW', 'name': '瑞昱', 'market': '上市'},
            {'symbol': '2884.TW', 'name': '玉山金', 'market': '上市'},
            {'symbol': '2885.TW', 'name': '元大金', 'market': '上市'},
            {'symbol': '3231.TW', 'name': '緯創', 'market': '上市'},
            {'symbol': '3481.TW', 'name': '群創', 'market': '上市'},
            {'symbol': '6669.TW', 'name': '緯穎', 'market': '上市'},
            {'symbol': '1216.TW', 'name': '統一', 'market': '上市'},
            {'symbol': '1101.TW', 'name': '台泥', 'market': '上市'},
            {'symbol': '1102.TW', 'name': '亞泥', 'market': '上市'},
            {'symbol': '2105.TW', 'name': '正新', 'market': '上市'},
            {'symbol': '2201.TW', 'name': '裕隆', 'market': '上市'},
            {'symbol': '2301.TW', 'name': '光寶科', 'market': '上市'},
            {'symbol': '2324.TW', 'name': '仁寶', 'market': '上市'},
            {'symbol': '2356.TW', 'name': '英業達', 'market': '上市'},
            {'symbol': '2801.TW', 'name': '彰銀', 'market': '上市'},
            {'symbol': '2880.TW', 'name': '華南金', 'market': '上市'}
        ]
        logger.info(f"使用備用上市股票清單: {len(backup_symbols)} 檔")
        return backup_symbols
    
    def get_backup_otc_symbols(self):
        """備用的熱門櫃檯股票清單"""
        backup_symbols = [
            {'symbol': '1565.TWO', 'name': '精華', 'market': '上櫃'},
            {'symbol': '3529.TWO', 'name': '力旺', 'market': '上櫃'},
            {'symbol': '4966.TWO', 'name': '譜瑞-KY', 'market': '上櫃'},
            {'symbol': '6446.TWO', 'name': '藥華藥', 'market': '上櫃'},
            {'symbol': '6488.TWO', 'name': '環球晶', 'market': '上櫃'},
            {'symbol': '8299.TWO', 'name': '群聯', 'market': '上櫃'}
        ]
        logger.info(f"使用備用櫃檯股票清單: {len(backup_symbols)} 檔")
        return backup_symbols

    def get_market_indices(self):
        """獲取台灣主要市場指數和代表性股票"""
        indices = [
            {
                'symbol': '^TWII',
                'name': '台灣加權指數',
                'market': '指數'
            },
            {
                'symbol': '0050.TW',
                'name': '元大台灣50',
                'market': 'ETF'
            },
            {
                'symbol': '0056.TW',
                'name': '元大高股息',
                'market': 'ETF'
            },
            {
                'symbol': '0051.TW',
                'name': '元大中型100',
                'market': 'ETF'
            },
            {
                'symbol': '006208.TW',
                'name': '富邦台50',
                'market': 'ETF'
            },
            {
                'symbol': '2330.TW',
                'name': '台積電',
                'market': '權值股'
            },
            {
                'symbol': '2317.TW',
                'name': '鴻海',
                'market': '權值股'
            }
        ]
        
        logger.info(f"添加 {len(indices)} 個市場指數/ETF")
        return indices

    def get_all_symbols(self, force_refresh=False):
        """獲取所有台灣股票代碼"""
        # 檢查快取
        if not force_refresh and self.symbols_cache and self.cache_time:
            if time.time() - self.cache_time < 3600:  # 1小時快取
                return self.symbols_cache
        
        # 抓取新數據
        twse_symbols = self.fetch_twse_symbols()
        otc_symbols = self.fetch_otc_symbols()
        market_indices = self.get_market_indices()
        all_symbols = twse_symbols + otc_symbols + market_indices
        
        # 過濾掉權證等衍生商品
        filtered_symbols = []
        for symbol in all_symbols:
            if not any(keyword in symbol['name'] for keyword in ['購', '牛熊證', '權證']):
                filtered_symbols.append(symbol)
        
        # 更新快取
        self.symbols_cache = filtered_symbols
        self.cache_time = time.time()
        
        logger.info(f"總共取得 {len(filtered_symbols)} 檔股票")
        return filtered_symbols

    def fetch_stock_data(self, symbol, start_date=None, end_date=None):
        """從台灣證交所或櫃買中心獲取股票數據"""
        try:
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')
            if not start_date:
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            
            logger.info(f"下載 {symbol} 股價數據，時間範圍: {start_date} 到 {end_date}")
            
            # 檢查是否為台灣加權指數，使用更新後的yfinance
            if symbol == '^TWII':
                logger.info(f"檢測到台灣加權指數 {symbol}，使用更新後的 yfinance 抓取")
                return self.fetch_twii_direct(start_date, end_date)
            
            # 解析股票代碼
            if '.TW' in symbol or '.TWO' in symbol:
                stock_code = symbol.split('.')[0]
                market_suffix = symbol.split('.')[1]
            else:
                stock_code = symbol
                market_suffix = None
            
            # 判斷是上市還是上櫃股票
            if market_suffix == 'TWO' or self.is_otc_stock(stock_code):
                # 上櫃股票，使用櫃買中心API
                logger.info(f"檢測到上櫃股票 {symbol}，使用櫃買中心API")
                result = self.fetch_tpex_stock_data(stock_code, start_date, end_date)
            else:
                # 上市股票，使用證交所API
                logger.info(f"檢測到上市股票 {symbol}，使用證交所API")
                result = self.fetch_twse_stock_data(stock_code, start_date, end_date)
            
            if result:
                logger.info(f"成功獲取 {symbol} 數據，共 {len(result)} 筆")
                # 將list格式轉換為DataFrame格式
                if isinstance(result, list) and result:
                    import pandas as pd
                    df = pd.DataFrame(result)
                    return df
                return result
            
            # 如果台灣API失敗，嘗試 yfinance
            logger.info(f"台灣API獲取失敗，嘗試 yfinance")
            return self.fetch_yfinance_data(symbol, start_date, end_date)
            
        except Exception as e:
            logger.error(f"下載 {symbol} 股價失敗: {e}")
            return None
    

    def fetch_twse_stock_data(self, stock_code, start_date, end_date):
        """從台灣證交所 API 獲取股票數據"""
        try:
            # 將日期轉換為證交所 API 格式
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            result = []
            current_date = start_dt
            
            # 逐月獲取數據（證交所 API 限制）
            while current_date <= end_dt:
                year = current_date.year
                month = current_date.month
                
                # 證交所 API URL
                url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY"
                params = {
                    'response': 'json',
                    'date': f'{year}{month:02d}01',
                    'stockNo': stock_code
                }
                
                logger.info(f"獲取 {stock_code} {year}-{month:02d} 數據")
                
                # 添加重試機制
                max_retries = 3
                retry_count = 0
                success = False
                
                while retry_count < max_retries and not success:
                    try:
                        response = requests.get(url, params=params, timeout=15, verify=False)
                        if response.status_code == 200:
                            success = True
                        elif response.status_code == 500:
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.warning(f"HTTP 500 錯誤，第 {retry_count} 次重試 {stock_code} {year}-{month:02d}")
                                time.sleep(2)  # 等待2秒後重試
                                continue
                            else:
                                logger.error(f"HTTP 500 錯誤，已達最大重試次數，跳過 {stock_code} {year}-{month:02d}")
                                break
                        else:
                            logger.error(f"HTTP {response.status_code} 錯誤，跳過 {stock_code} {year}-{month:02d}")
                            break
                    except requests.exceptions.Timeout:
                        retry_count += 1
                        if retry_count < max_retries:
                            logger.warning(f"請求超時，第 {retry_count} 次重試 {stock_code} {year}-{month:02d}")
                            time.sleep(3)
                            continue
                        else:
                            logger.error(f"請求超時，已達最大重試次數，跳過 {stock_code} {year}-{month:02d}")
                            break
                    except Exception as e:
                        logger.error(f"請求異常: {e}，跳過 {stock_code} {year}-{month:02d}")
                        break
                
                if success and response.status_code == 200:
                    data = response.json()
                    
                    if data.get('stat') == 'OK' and data.get('data'):
                        for row in data['data']:
                            try:
                                # 解析日期 (民國年/月/日)
                                date_parts = row[0].split('/')
                                if len(date_parts) == 3:
                                    year_roc = int(date_parts[0]) + 1911  # 民國年轉西元年
                                    month_val = int(date_parts[1])
                                    day_val = int(date_parts[2])
                                    
                                    trade_date = datetime(year_roc, month_val, day_val)
                                    
                                    # 檢查是否在指定範圍內
                                    if start_dt <= trade_date <= end_dt:
                                        # 移除千分位逗號並轉換數值
                                        volume = int(row[1].replace(',', '')) if row[1] != '--' else 0
                                        open_price = float(row[3].replace(',', '')) if row[3] != '--' else 0
                                        high_price = float(row[4].replace(',', '')) if row[4] != '--' else 0
                                        low_price = float(row[5].replace(',', '')) if row[5] != '--' else 0
                                        close_price = float(row[6].replace(',', '')) if row[6] != '--' else 0
                                        
                                        # 驗證所有價格都小於30000
                                        if (open_price < 30000 and high_price < 30000 and 
                                            low_price < 30000 and close_price < 30000):
                                            result.append({
                                                'ticker': f"{stock_code}.TW",
                                                'Date': trade_date.strftime('%Y-%m-%d'),
                                                'Open': round(open_price, 2),
                                                'High': round(high_price, 2),
                                                'Low': round(low_price, 2),
                                                'Close': round(close_price, 2),
                                                'Volume': volume
                                            })
                                        else:
                                            logger.warning(f"價格超過30000，跳過 {trade_date.strftime('%Y-%m-%d')}: "
                                                          f"O:{open_price}, H:{high_price}, L:{low_price}, C:{close_price}")
                            except (ValueError, IndexError) as e:
                                logger.warning(f"解析數據行失敗: {row}, 錯誤: {e}")
                                continue
                
                # 移到下個月
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
                
                time.sleep(1.5)  # 增加延遲避免請求過於頻繁
            
            # 按日期排序
            result.sort(key=lambda x: x['Date'])
            return result
            
        except Exception as e:
            logger.error(f"從證交所獲取 {stock_code} 數據失敗: {e}")
            return None
    
    def is_otc_stock(self, stock_code):
        """判斷是否為上櫃股票"""
        try:
            # 先查詢我們的股票清單來確定市場
            if hasattr(self, 'symbols_cache') and self.symbols_cache:
                for stock in self.symbols_cache:
                    if stock['symbol'] == stock_code or stock['symbol'].startswith(stock_code + '.'):
                        return stock.get('market') == '上櫃'
            
            # 如果快取中找不到，使用已知的上櫃股票代碼範圍和特定股票
            code_num = int(stock_code)
            
            # 已知的上櫃股票代碼（部分範例）
            known_otc_stocks = {
                # 科技類
                '3443', '4966', '6488', '3034', '3702', '4904', '5269', '6415',
                # 其他產業
                '1565', '1569', '1580', '2596', '2633', '2719', '2724', '2729',
                '3131', '3149', '3163', '3167', '3169', '3171', '3176', '3178',
                '4102', '4106', '4108', '4116', '4119', '4126', '4128', '4129',
                '5203', '5222', '5234', '5243', '5245', '5251', '5263', '5264',
                '6104', '6116', '6120', '6121', '6122', '6126', '6128', '6129',
                '7556', '7557', '7561', '7566', '7567', '7568', '7569', '7570',
                '8024', '8027', '8028', '8029', '8032', '8033', '8034', '8035',
                '9188', '9802', '9910', '9911', '9912', '9914', '9917', '9918'
            }
            
            if stock_code in known_otc_stocks:
                return True
            
            # 上櫃股票通常集中在某些代碼範圍
            # 1000-1999: 部分傳統產業（上櫃較多）
            # 2000-2999: 部分食品、服務業（上櫃較多）
            # 3000-3999: 部分電子股（上櫃較多）
            # 4000-4999: 部分紡織、電子股（上櫃較多）
            # 5000-5999: 部分電機股（上櫃較多）
            # 6000-6999: 部分電子、生技股（上櫃較多）
            # 7000-7999: 部分玻璃陶瓷、其他產業（上櫃較多）
            # 8000-8999: 部分其他產業（上櫃較多）
            # 9000-9999: 部分綜合、其他產業（上櫃較多）
            
            if (1500 <= code_num <= 1999 or 
                2500 <= code_num <= 2999 or 
                3000 <= code_num <= 3999 or 
                4000 <= code_num <= 4999 or 
                5200 <= code_num <= 5999 or 
                6100 <= code_num <= 6999 or 
                7500 <= code_num <= 7999 or 
                8000 <= code_num <= 8999 or 
                9100 <= code_num <= 9999):
                return True
            
            return False
        except:
            return False
    
    def fetch_tpex_stock_data(self, stock_code, start_date, end_date):
        """從櫃買中心 API 獲取上櫃股票數據"""
        try:
            # 將日期轉換為櫃買中心 API 格式
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            result = []
            current_date = start_dt
            
            # 逐日獲取數據（櫃買中心 API 支援日期查詢）
            while current_date <= end_dt:
                year = current_date.year
                month = current_date.month
                day = current_date.day
                
                # 櫃買中心 API URL (使用正確的格式)
                url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
                params = {
                    'response': 'json',
                    'date': f'{year}/{month:02d}/{day:02d}',
                    'stockno': stock_code
                }
                
                logger.info(f"從櫃買中心獲取 {stock_code} {year}-{month:02d}-{day:02d} 數據")
                
                # 添加重試機制
                max_retries = 3
                retry_count = 0
                success = False
                
                while retry_count < max_retries and not success:
                    try:
                        headers = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                        response = requests.get(url, params=params, headers=headers, timeout=15, verify=False)
                        
                        if response.status_code == 200:
                            success = True
                            data = response.json()
                            
                            if 'tables' in data and len(data['tables']) > 0:
                                # 櫃買中心新API格式：tables[0]['data'] 包含股票資料
                                table_data = data['tables'][0]['data']
                                
                                for row in table_data:
                                    if len(row) >= 19 and row[0] == stock_code:  # 確保是目標股票
                                        try:
                                            # 櫃買中心數據格式：[代號, 名稱, 收盤, 漲跌, 開盤, 最高, 最低, 均價, 成交股數, 成交金額, ...]
                                            date_str = f"{year}-{month:02d}-{day:02d}"
                                            
                                            # 處理價格數據（去除逗號和特殊符號）
                                            close_price = float(row[2].replace(',', '')) if row[2] and row[2] != '---' else None
                                            open_price = float(row[4].replace(',', '')) if row[4] and row[4] != '---' else None
                                            high_price = float(row[5].replace(',', '')) if row[5] and row[5] != '---' else None
                                            low_price = float(row[6].replace(',', '')) if row[6] and row[6] != '---' else None
                                            volume = int(row[8].replace(',', '')) if row[8] and row[8] != '---' else 0
                                            
                                            if close_price is not None:
                                                result.append({
                                                    'ticker': f"{stock_code}.TWO",
                                                    'Date': date_str,
                                                    'Open': round(open_price, 2) if open_price is not None else None,
                                                    'High': round(high_price, 2) if high_price is not None else None,
                                                    'Low': round(low_price, 2) if low_price is not None else None,
                                                    'Close': round(close_price, 2),
                                                    'Volume': volume
                                                })
                                                break  # 找到目標股票後跳出
                                        except (ValueError, IndexError) as e:
                                            logger.warning(f"解析櫃買中心數據行失敗: {e}, row: {row}")
                                            continue
                            else:
                                logger.warning(f"櫃買中心回傳空數據: {stock_code} {year}-{month:02d}-{day:02d}")
                        else:
                            logger.error(f"櫃買中心API HTTP {response.status_code} 錯誤，跳過 {stock_code} {year}-{month:02d}-{day:02d}")
                            break
                            
                    except requests.exceptions.Timeout:
                        retry_count += 1
                        if retry_count < max_retries:
                            logger.warning(f"櫃買中心API超時，第 {retry_count} 次重試 {stock_code} {year}-{month:02d}-{day:02d}")
                            time.sleep(2)
                            continue
                        else:
                            logger.error(f"櫃買中心API超時，已達最大重試次數，跳過 {stock_code} {year}-{month:02d}-{day:02d}")
                            break
                    except Exception as e:
                        retry_count += 1
                        if retry_count < max_retries:
                            logger.warning(f"櫃買中心API請求失敗: {e}，第 {retry_count} 次重試")
                            time.sleep(2)
                            continue
                        else:
                            logger.error(f"櫃買中心API請求失敗: {e}，已達最大重試次數")
                            break
                
                # 移動到下一天
                current_date = current_date + timedelta(days=1)
                
                # 避免請求過於頻繁
                time.sleep(0.5)
            
            # 按日期排序
            if result:
                result.sort(key=lambda x: x['Date'])
                logger.info(f"成功從櫃買中心獲取 {stock_code} 數據，共 {len(result)} 筆")
            
            return result
            
        except Exception as e:
            logger.error(f"從櫃買中心獲取 {stock_code} 數據失敗: {e}")
            return None

    def fetch_twii_direct(self, start_date, end_date):
        """直接使用 yfinance 抓取台灣加權指數 ^TWII"""
        try:
            import yfinance as yf
            logger.info(f"使用 yfinance 版本: {yf.__version__}")

            ticker_symbol = '^TWII'
            twii = yf.Ticker(ticker_symbol)
            df = twii.history(period="1y", interval="1d")
            
            if df.empty:
                logger.warning(f"使用 yfinance 抓取 {ticker_symbol} 數據失敗，返回空數據框")
                return pd.DataFrame()

            # 檢查數據有效性
            if 'Close' not in df.columns or df['Close'].isnull().all():
                logger.warning(f"yfinance 回傳的數據中沒有有效的 'Close' 價格")
                return pd.DataFrame()

            # 轉換為 pandas DataFrame 並返回
            df.reset_index(inplace=True)
            df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
            df.columns = ['date', 'open_price', 'high_price', 'low_price', 'close_price', 'volume']
            df['date'] = pd.to_datetime(df['date']).dt.date
            
            # 增加數據有效性檢查
            latest_price = df['close_price'].iloc[-1]
            if latest_price > 30000 or latest_price < 1000:
                logger.warning(f"yfinance 抓取到不合理的價格: {latest_price}，可能數據有誤")
                return pd.DataFrame()

            logger.info(f"成功使用 yfinance 抓取 {ticker_symbol} 的最新數據")
            return df

        except Exception as e:
            logger.error(f"使用 yfinance 抓取 {ticker_symbol} 時發生未知錯誤: {e}")
            return pd.DataFrame()

    def fetch_twse_index_data(self, index_code, start_date, end_date):
        """從台灣證交所 API 獲取指數數據"""
        try:
            # 將日期轉換為證交所 API 格式
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
            result = []
            current_date = start_dt
            
            # 逐月獲取指數數據（證交所FMTQIK API按月提供數據）
            while current_date <= end_dt:
                year = current_date.year
                month = current_date.month
                
                # 使用證交所市場成交資訊API (FMTQIK)
                url = "https://www.twse.com.tw/exchangeReport/FMTQIK"
                params = {
                    'response': 'json',
                    'date': f'{year}{month:02d}01'
                }
                
                logger.info(f"獲取加權指數 {year}-{month:02d} 數據")
                
                try:
                    response = requests.get(url, params=params, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        
                        if data.get('stat') == 'OK' and data.get('data'):
                            # FMTQIK API 數據格式: ["日期","成交股數","成交金額","成交筆數","發行量加權股價指數","漲跌點數"]
                            for row in data['data']:
                                try:
                                    # 解析日期 (民國年/月/日)
                                    date_parts = row[0].split('/')
                                    if len(date_parts) == 3:
                                        year_roc = int(date_parts[0]) + 1911  # 民國年轉西元年
                                        month_val = int(date_parts[1])
                                        day_val = int(date_parts[2])
                                        
                                        trade_date = datetime(year_roc, month_val, day_val)
                                        
                                        # 檢查是否在指定範圍內
                                        if start_dt <= trade_date <= end_dt:
                                            # 發行量加權股價指數在第5個欄位 (index 4)
                                            # 數據格式: ["日期","成交股數","成交金額","成交筆數","發行量加權股價指數","漲跌點數"]
                                            if len(row) >= 5:
                                                index_value = None
                                                
                                                # 嘗試從第5欄位（index 4）獲取指數值
                                                if row[4] != '--' and row[4].strip():
                                                    try:
                                                        candidate_value = float(row[4].replace(',', ''))
                                                        # 檢查是否為合理的指數值（8000-30000之間）
                                                        if 8000 <= candidate_value <= 30000:
                                                            index_value = candidate_value
                                                        else:
                                                            logger.warning(f"第5欄位值異常: {candidate_value}，嘗試其他欄位")
                                                    except ValueError:
                                                        logger.warning(f"第5欄位無法解析: '{row[4]}'")
                                                
                                                # 如果第5欄位不合理，嘗試其他可能的欄位
                                                if index_value is None:
                                                    for col_idx in [5, 3, 2]:  # 嘗試第6、4、3欄位
                                                        if len(row) > col_idx and row[col_idx] != '--' and row[col_idx].strip():
                                                            try:
                                                                candidate_value = float(row[col_idx].replace(',', ''))
                                                                if 8000 <= candidate_value <= 30000:
                                                                    index_value = candidate_value
                                                                    logger.info(f"在第{col_idx+1}欄位找到合理指數值: {candidate_value}")
                                                                    break
                                                            except ValueError:
                                                                continue
                                                
                                                # 如果找到合理的指數值，再次驗證是否小於30000
                                                if index_value is not None and index_value < 30000:
                                                    result.append({
                                                        'ticker': '^TWII',
                                                        'Date': trade_date.strftime('%Y-%m-%d'),
                                                        'Open': round(index_value, 2),
                                                        'High': round(index_value, 2),
                                                        'Low': round(index_value, 2),
                                                        'Close': round(index_value, 2),
                                                        'Volume': 0  # 指數沒有成交量概念
                                                    })
                                                    logger.info(f"成功解析 {trade_date.strftime('%Y-%m-%d')} 加權指數: {index_value}")
                                                elif index_value is not None:
                                                    logger.warning(f"指數值超過30000，跳過 {trade_date.strftime('%Y-%m-%d')}: {index_value}")
                                                else:
                                                    logger.warning(f"無法找到合理的指數值，跳過 {trade_date.strftime('%Y-%m-%d')}")
                                                    logger.debug(f"完整數據行: {row}")
                                                    
                                except (ValueError, IndexError) as e:
                                    logger.warning(f"解析指數數據行失敗: {row}, 錯誤: {e}")
                                    continue
                                
                except requests.RequestException as e:
                    logger.warning(f"請求 {year}-{month:02d} 數據失敗: {e}")
                
                # 移到下個月
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
                
                time.sleep(0.3)  # 避免請求過於頻繁
            
            # 按日期排序
            result.sort(key=lambda x: x['Date'])
            logger.info(f"成功獲取加權指數數據 {len(result)} 筆")
            return result if result else None
            
        except Exception as e:
            logger.error(f"從證交所獲取指數數據失敗: {e}")
            return None

    def fetch_yfinance_data(self, symbol, start_date, end_date):
        """使用 yfinance 作為備用方案"""
        try:
            symbols_to_try = []
            
            if '.TW' in symbol or '.TWO' in symbol:
                base_code = symbol.split('.')[0]
                symbols_to_try = [f"{base_code}.TW", f"{base_code}.TWO"]
            else:
                symbols_to_try = [symbol]
            
            for try_symbol in symbols_to_try:
                try:
                    logger.info(f"yfinance 嘗試下載 {try_symbol}")
                    
                    # 嘗試多種下載方式
                    df = None
                    
                    # 方法1: 直接下載 (台股需要加 .TW 後綴)
                    try_symbol = f"{symbol}.TW" if not symbol.endswith('.TW') else symbol
                    df = yf.download(try_symbol, start=start_date, end=end_date, progress=False)
                    
                    # 方法2: 使用Ticker對象
                    if df is None or df.empty:
                        try:
                            ticker = yf.Ticker(try_symbol)
                            df = ticker.history(start=start_date, end=end_date, auto_adjust=True)
                        except:
                            pass
                    
                    # 方法3: 嘗試不同的時間範圍
                    if df is None or df.empty:
                        try:
                            df = yf.download(try_symbol, period="1mo", progress=False)
                        except:
                            pass
                    
                    if df is not None and not df.empty:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        
                        df.reset_index(inplace=True)
                        df['ticker'] = symbol
                        
                        result = []
                        for _, row in df.iterrows():
                            # 檢查日期是否在範圍內
                            row_date = pd.to_datetime(row['Date']).strftime('%Y-%m-%d')
                            if start_date <= row_date <= end_date:
                                # 提取價格數據
                                open_price = float(row['Open'])
                                high_price = float(row['High'])
                                low_price = float(row['Low'])
                                close_price = float(row['Close'])
                                
                                # 驗證所有價格都小於30000
                                if (open_price < 30000 and high_price < 30000 and 
                                    low_price < 30000 and close_price < 30000):
                                    result.append({
                                        'ticker': row['ticker'],
                                        'Date': row_date,
                                        'Open': round(open_price, 2),
                                        'High': round(high_price, 2),
                                        'Low': round(low_price, 2),
                                        'Close': round(close_price, 2),
                                        'Volume': int(row['Volume']) if not pd.isna(row['Volume']) else 0
                                    })
                                else:
                                    logger.warning(f"yfinance價格超過30000，跳過 {row_date}: "
                                                  f"O:{open_price}, H:{high_price}, L:{low_price}, C:{close_price}")
                        
                        if result:
                            logger.info(f"yfinance 成功獲取 {try_symbol} 數據，共 {len(result)} 筆")
                            return result
                        
                except Exception as e:
                    logger.warning(f"yfinance 下載 {try_symbol} 失敗: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.error(f"yfinance 備用方案失敗: {e}")
            return None

    def calculate_returns(self, price_data, frequency='daily'):
        """計算報酬率"""
        if price_data is None or (hasattr(price_data, 'empty') and price_data.empty) or (isinstance(price_data, list) and len(price_data) == 0):
            return []
        
        # Handle both DataFrame and list inputs
        if isinstance(price_data, pd.DataFrame):
            df = price_data.copy()
        else:
            df = pd.DataFrame(price_data)
        
        # Normalize column names to handle both formats
        date_col = 'date' if 'date' in df.columns else 'Date'
        close_col = 'close_price' if 'close_price' in df.columns else 'Close'
        
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col)
        
        if len(df) < 2:
            return []
        
        results = []
        
        if frequency == 'daily':
            df['return'] = df[close_col].pct_change()
            # 計算累積報酬率
            df['cumulative_return'] = (1 + df['return']).cumprod() - 1
            
            for _, row in df.iterrows():
                if pd.notna(row['return']):
                    results.append({
                        'ticker': row.get('ticker', '^TWII'),  # Default to ^TWII if no ticker
                        'Date': row[date_col].strftime('%Y-%m-%d'),
                        'frequency': 'daily',
                        'return': round(float(row['return']), 6),
                        'cumulative_return': round(float(row['cumulative_return']), 6) if pd.notna(row['cumulative_return']) else 0.0
                    })
        
        elif frequency == 'weekly':
            weekly = df.set_index(date_col)[close_col].resample('W').last().pct_change(fill_method=None).dropna()
            # 計算累積報酬率
            weekly_cumulative = (1 + weekly).cumprod() - 1
            for date, ret in weekly.items():
                results.append({
                    'ticker': df.get('ticker', '^TWII').iloc[0] if 'ticker' in df.columns else '^TWII',
                    'Date': date.strftime('%Y-%m-%d'),
                    'frequency': 'weekly',
                    'return': round(float(ret), 6),
                    'cumulative_return': round(float(weekly_cumulative[date]), 6) if date in weekly_cumulative.index else 0.0
                })
        
        elif frequency == 'monthly':
            monthly = df.set_index(date_col)[close_col].resample('ME').last().pct_change(fill_method=None).dropna()
            # 計算累積報酬率
            monthly_cumulative = (1 + monthly).cumprod() - 1
            for date, ret in monthly.items():
                results.append({
                    'ticker': df.get('ticker', '^TWII').iloc[0] if 'ticker' in df.columns else '^TWII',
                    'Date': date.strftime('%Y-%m-%d'),
                    'frequency': 'monthly',
                    'return': round(float(ret), 6),
                    'cumulative_return': round(float(monthly_cumulative[date]), 6) if date in monthly_cumulative.index else 0.0
                })
        
        return results



# 初始化 API 實例
stock_api = StockDataAPI()

# 主頁路由 - 提供前端 UI
@app.route('/')
def index():
    """提供主頁面"""
    return send_file(os.path.join(current_dir, 'index.html'))

@app.route('/<path:filename>')
def static_files(filename):
    """提供靜態文件"""
    return send_from_directory(current_dir, filename)

# API 路由定義

@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    """獲取所有股票代碼"""
    try:
        force_refresh = request.args.get('refresh', 'false').lower() == 'true'
        symbols = stock_api.get_all_symbols(force_refresh)
        
        # 支援範圍篩選
        start_code = request.args.get('start')
        end_code = request.args.get('end')
        
        if start_code and end_code:
            try:
                start_num = int(start_code)
                end_num = int(end_code)
                filtered_symbols = []
                
                for symbol in symbols:
                    code = symbol['symbol'].split('.')[0]
                    if code.isdigit():
                        code_num = int(code)
                        if start_num <= code_num <= end_num:
                            filtered_symbols.append(symbol)
                
                symbols = filtered_symbols
            except ValueError:
                pass
        
        return jsonify({
            'success': True,
            'data': symbols,
            'count': len(symbols)
        })
    except Exception as e:
        logger.error(f"獲取股票代碼失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stock/<symbol>/prices', methods=['GET'])
def get_stock_prices(symbol):
    """從資料庫或 API 獲取股票價格數據"""
    try:
        start_date = request.args.get('start')
        end_date = request.args.get('end')

        # 如果是台灣加權指數，直接從 API 抓取
        if symbol == '^TWII':
            logger.info(f"偵測到 {symbol}，直接呼叫 API 抓取最新數據")
            data = stock_api.fetch_stock_data(symbol, start_date, end_date)
            if data is not None and not data.empty:
                # 將 DataFrame 轉換為 JSON
                price_data = data.to_dict('records')
                # 日期對象轉換為字符串
                for record in price_data:
                    if isinstance(record['date'], pd.Timestamp):
                        record['date'] = record['date'].strftime('%Y-%m-%d')
                    elif isinstance(record['date'], date):
                        record['date'] = record['date'].strftime('%Y-%m-%d')

                return jsonify({
                    'success': True,
                    'data': price_data,
                    'count': len(price_data)
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f'無法從 yfinance 獲取 {symbol} 數據'
                }), 404

        # 對於其他股票，從資料庫查詢
        db_manager = DatabaseManager()
        if not db_manager.connect():
            return jsonify({
                'success': False,
                'error': '資料庫連接失敗'
            }), 500
        
        try:
            cursor = db_manager.connection.cursor()
            
            # 先檢查表是否存在並獲取欄位資訊
            cursor.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'stock_prices' AND table_schema = 'public'
                ORDER BY ordinal_position
            """)
            results = cursor.fetchall()
            columns = []
            for row in results:
                if isinstance(row, dict):
                    columns.append(row['column_name'])
                elif isinstance(row, (list, tuple)):
                    columns.append(row[0])
                else:
                    columns.append(str(row))
            
            if not columns:
                # 表不存在，嘗試創建
                logger.info("stock_prices 表不存在，嘗試創建...")
                db_manager.create_tables()
                return jsonify({
                    'success': False,
                    'error': '資料庫表不存在，已嘗試創建，請重新查詢'
                }), 500
            
            # 檢查是否有必要的欄位，如果沒有則重新創建表
            required_columns = ['symbol', 'date', 'open_price', 'high_price', 'low_price', 'close_price', 'volume']
            missing_columns = [col for col in required_columns if col not in columns]
            
            if missing_columns:
                logger.warning(f"stock_prices 表缺少欄位: {missing_columns}")
                # 刪除舊表並重新創建
                cursor.execute("DROP TABLE IF EXISTS stock_prices CASCADE")
                cursor.execute("DROP TABLE IF EXISTS stock_returns CASCADE")
                db_manager.connection.commit()
                logger.info("已刪除舊表，重新創建...")
                db_manager.create_tables()
                return jsonify({
                    'success': False,
                    'error': '資料庫表結構不完整，已重新創建，請重新查詢'
                }), 500
            
            logger.info(f"stock_prices 表欄位: {columns}")
            
            # 根據實際欄位構建查詢
            if 'open_price' in columns:
                query = """
                    SELECT date, open_price, high_price, low_price, close_price, volume
                    FROM stock_prices 
                    WHERE symbol = %s
                """
            else:
                # 如果沒有 open_price 等欄位，可能是舊的表結構
                query = """
                    SELECT date, close_price, volume
                    FROM stock_prices 
                    WHERE symbol = %s
                """
            
            # 支援多種股票代碼格式查詢
            # 如果輸入的是純數字代碼，嘗試匹配完整格式
            if symbol.isdigit():
                # 先嘗試直接查詢，如果沒有結果，再嘗試添加後綴
                cursor.execute("SELECT COUNT(*) FROM stock_prices WHERE symbol = %s", [symbol])
                result = cursor.fetchone()
                count = result[0] if isinstance(result, (list, tuple)) else result.get('count', 0)
                
                if count == 0:
                    # 嘗試查找帶有 .TW 或 .TWO 後綴的股票
                    cursor.execute("""
                        SELECT symbol FROM stock_prices 
                        WHERE symbol IN (%s, %s) 
                        LIMIT 1
                    """, [f"{symbol}.TW", f"{symbol}.TWO"])
                    
                    result = cursor.fetchone()
                    if result:
                        found_symbol = result[0] if isinstance(result, (list, tuple)) else result.get('symbol')
                        if found_symbol:
                            symbol = found_symbol  # 使用找到的完整格式
            
            params = [symbol]
            
            if start_date:
                query += " AND date >= %s"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= %s"
                params.append(end_date)
                
            query += " ORDER BY date ASC"
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            if not results:
                return jsonify({
                    'success': True,
                    'data': [],
                    'count': 0,
                    'message': f'沒有找到 {symbol} 的股價數據'
                })
            
            price_data = []
            for row in results:
                record = {
                    'date': row['date'].strftime('%Y-%m-%d') if row['date'] else None,
                }
                
                # 根據實際欄位動態添加數據
                if 'open_price' in row:
                    record['open_price'] = float(row['open_price']) if row['open_price'] else None
                if 'high_price' in row:
                    record['high_price'] = float(row['high_price']) if row['high_price'] else None
                if 'low_price' in row:
                    record['low_price'] = float(row['low_price']) if row['low_price'] else None
                if 'close_price' in row:
                    record['close_price'] = float(row['close_price']) if row['close_price'] else None
                if 'volume' in row:
                    record['volume'] = int(row['volume']) if row['volume'] else None
                
                price_data.append(record)
            
            return jsonify({
                'success': True,
                'data': price_data,
                'count': len(price_data)
            })
            
        finally:
            db_manager.disconnect()
            
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"獲取 {symbol} 股價失敗: {e}")
        logger.error(f"詳細錯誤: {error_details}")
        return jsonify({
            'success': False,
            'error': f"查詢股價數據時發生錯誤: {str(e)}",
            'details': error_details if app.debug else None
        }), 500

@app.route('/api/stock/<symbol>/returns', methods=['GET'])
def get_stock_returns(symbol):
    """從資料庫獲取股票報酬率數據"""
    try:
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        # 連接資料庫
        db_manager = DatabaseManager()
        if not db_manager.connect():
            return jsonify({
                'success': False,
                'error': '資料庫連接失敗'
            }), 500
        
        try:
            cursor = db_manager.connection.cursor()
            
            # 構建查詢語句
            query = """
                SELECT date, daily_return, weekly_return, monthly_return, cumulative_return
                FROM stock_returns 
                WHERE symbol = %s
            """
            
            # 支援多種股票代碼格式查詢
            # 如果輸入的是純數字代碼，嘗試匹配完整格式
            if symbol.isdigit():
                # 先嘗試直接查詢，如果沒有結果，再嘗試添加後綴
                cursor.execute("SELECT COUNT(*) FROM stock_returns WHERE symbol = %s", [symbol])
                result = cursor.fetchone()
                count = result[0] if isinstance(result, (list, tuple)) else result.get('count', 0)
                
                if count == 0:
                    # 嘗試查找帶有 .TW 或 .TWO 後綴的股票
                    cursor.execute("""
                        SELECT symbol FROM stock_returns 
                        WHERE symbol IN (%s, %s) 
                        LIMIT 1
                    """, [f"{symbol}.TW", f"{symbol}.TWO"])
                    
                    result = cursor.fetchone()
                    if result:
                        found_symbol = result[0] if isinstance(result, (list, tuple)) else result.get('symbol')
                        if found_symbol:
                            symbol = found_symbol  # 使用找到的完整格式
            
            params = [symbol]
            
            if start_date:
                query += " AND date >= %s"
                params.append(start_date)
            
            if end_date:
                query += " AND date <= %s"
                params.append(end_date)
                
            query += " ORDER BY date ASC"
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            # 轉換為字典格式
            returns_data = []
            for row in results:
                if isinstance(row, (list, tuple)):
                    date_val, daily_ret, weekly_ret, monthly_ret, cumulative_ret = row
                else:
                    date_val = row.get('date')
                    daily_ret = row.get('daily_return')
                    weekly_ret = row.get('weekly_return')
                    monthly_ret = row.get('monthly_return')
                    cumulative_ret = row.get('cumulative_return')
                
                returns_data.append({
                    'date': date_val.strftime('%Y-%m-%d') if date_val else None,
                    'daily_return': float(daily_ret) if daily_ret is not None else None,
                    'weekly_return': float(weekly_ret) if weekly_ret is not None else None,
                    'monthly_return': float(monthly_ret) if monthly_ret is not None else None,
                    'cumulative_return': float(cumulative_ret) if cumulative_ret is not None else None
                })
            
            # 計算實際返回的日期範圍
            actual_date_range = {}
            if returns_data:
                dates = [pd.to_datetime(record['date']) for record in returns_data if record['date']]
                if dates:
                    actual_date_range = {
                        'start': min(dates).strftime('%Y-%m-%d'),
                        'end': max(dates).strftime('%Y-%m-%d'),
                        'trading_days_count': len(dates)
                    }
            
            return jsonify({
                'success': True,
                'data': returns_data,
                'count': len(returns_data),
                'date_range': {
                    'requested': {
                        'start': start_date,
                        'end': end_date
                    },
                    'actual': actual_date_range
                }
            })
            
        finally:
            db_manager.disconnect()
            
    except Exception as e:
        logger.error(f"獲取 {symbol} 報酬率失敗: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/update', methods=['POST'])
def update_stocks():
    """批量更新股票數據"""
    db_manager = None
    try:
        # 檢查請求數據
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': '請求必須是 JSON 格式'
            }), 400
            
        data = request.get_json()
        if data is None:
            return jsonify({
                'success': False,
                'error': '無效的 JSON 數據'
            }), 400
            
        symbols = data.get('symbols', [])
        start_date = data.get('start_date', '2023-01-01')
        end_date = data.get('end_date', None)  # 添加 end_date 參數
        update_prices = data.get('update_prices', True)
        update_returns = data.get('update_returns', True)
        
        if not symbols:
            # 如果沒有指定股票，獲取所有股票
            try:
                all_symbols = stock_api.get_all_symbols()
                symbols = [s['symbol'] for s in all_symbols[:50]]  # 限制50檔避免超時
            except Exception as e:
                logger.error(f"獲取股票代碼失敗: {e}")
                return jsonify({
                    'success': False,
                    'error': f'獲取股票代碼失敗: {str(e)}'
                }), 500
        
        results = []
        errors = []
        
        # 連接資料庫
        db_manager = DatabaseManager()
        logger.info("嘗試連接資料庫...")
        if not db_manager.connect():
            logger.error("資料庫連接失敗")
            return jsonify({
                'success': False,
                'error': '資料庫連接失敗'
            }), 500
        
        logger.info("資料庫連接成功，檢查連接狀態...")
        if db_manager.connection is None:
            logger.error("資料庫連接物件為 None")
            return jsonify({
                'success': False,
                'error': '資料庫連接物件為空'
            }), 500
        
        # 確保資料庫表格存在
        try:
            db_manager.create_tables()
            logger.info("資料庫表格檢查/建立完成")
        except Exception as e:
            logger.error(f"建立資料庫表格失敗: {e}")
            return jsonify({
                'success': False,
                'error': f'建立資料庫表格失敗: {str(e)}'
            }), 500
        
        try:
            # 再次確認連接狀態
            if db_manager.connection is None:
                logger.error("資料庫連接在 create_tables 後變為 None")
                return jsonify({
                    'success': False,
                    'error': '資料庫連接丟失'
                }), 500
                
            cursor = db_manager.connection.cursor()

            # 預先查詢每個 symbol 在 prices/returns 的最新日期，用於增量更新
            latest_price_date_map = {}
            try:
                # 使用單次查詢獲取所有 symbols 的最新日期
                placeholders = ','.join(['%s'] * len(symbols))
                cursor.execute(f"""
                    SELECT symbol, MAX(date) AS max_date
                    FROM stock_prices
                    WHERE symbol IN ({placeholders})
                    GROUP BY symbol
                """, symbols)
                for row in cursor.fetchall():
                    # row 是 RealDictCursor，鍵為 'symbol', 'max_date'
                    latest_price_date_map[row['symbol']] = row['max_date']
            except Exception as e:
                logger.warning(f"查詢最新股價日期失敗，將以請求日期為準: {e}")
                latest_price_date_map = {}

            for i, symbol in enumerate(symbols):
                try:
                    result = {'symbol': symbol, 'status': 'success'}
                    
                    if update_prices:
                        # 增量更新：若資料庫已有資料，從最新日期的翌日開始抓取
                        effective_start_date = start_date
                        latest_dt = latest_price_date_map.get(symbol)
                        if latest_dt is not None:
                            try:
                                next_day = (latest_dt + timedelta(days=1)).strftime('%Y-%m-%d')
                                if end_date is None or next_day <= (end_date or next_day):
                                    if next_day > start_date:
                                        effective_start_date = next_day
                            except Exception as _:
                                pass

                        logger.info(f"獲取 {symbol} 股價數據，請求日期範圍: {effective_start_date} 到 {end_date}")
                        price_data = stock_api.fetch_stock_data(symbol, effective_start_date, end_date)
                        if price_data is not None and (
                            (isinstance(price_data, pd.DataFrame) and not price_data.empty) or
                            (isinstance(price_data, list) and len(price_data) > 0)
                        ):
                            # 儲存股價數據到資料庫（批量 upsert）
                            dates = []

                            # 標準化資料為 list[dict]
                            if isinstance(price_data, pd.DataFrame):
                                price_records = price_data.to_dict('records')
                            else:
                                price_records = price_data

                            # 準備批量資料
                            values = []
                            for pr in price_records:
                                record_date = pr.get('date') or pr.get('Date')
                                dates.append(record_date)
                                values.append((
                                    symbol,
                                    record_date,
                                    pr.get('open_price') or pr.get('Open'),
                                    pr.get('high_price') or pr.get('High'),
                                    pr.get('low_price') or pr.get('Low'),
                                    pr.get('close_price') or pr.get('Close'),
                                    pr.get('volume') or pr.get('Volume')
                                ))

                            if values:
                                # 在 upsert 前統計資料庫已存在的日期（重複筆數）
                                duplicate_count = 0
                                try:
                                    date_list = [v[1] for v in values]
                                    if date_list:
                                        # 動態 placeholders 查詢既有日期
                                        date_placeholders = ','.join(['%s'] * len(date_list))
                                        cursor.execute(
                                            f"""
                                                SELECT date FROM stock_prices
                                                WHERE symbol = %s AND date IN ({date_placeholders})
                                            """,
                                            [symbol] + date_list
                                        )
                                        existing_rows = cursor.fetchall()
                                        # 正規化為字串日期集合
                                        existing_dates = set()
                                        for row in existing_rows:
                                            d = row['date']
                                            existing_dates.add(d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d))
                                        # 與 values 的日期交集
                                        duplicate_count = len(existing_dates)
                                except Exception as e:
                                    logger.warning(f"統計 {symbol} 既有日期失敗，略過重複統計: {e}")

                                upsert_sql = """
                                    INSERT INTO stock_prices (symbol, date, open_price, high_price, low_price, close_price, volume)
                                    VALUES %s
                                    ON CONFLICT (symbol, date) DO UPDATE SET
                                        open_price = EXCLUDED.open_price,
                                        high_price = EXCLUDED.high_price,
                                        low_price = EXCLUDED.low_price,
                                        close_price = EXCLUDED.close_price,
                                        volume = EXCLUDED.volume
                                """
                                try:
                                    execute_values(cursor, upsert_sql, values, page_size=1000)
                                    db_manager.connection.commit()
                                except Exception as e:
                                    logger.warning(f"批量寫入 {symbol} 價格數據失敗，將嘗試較小批次: {e}")
                                    # 回退為小批次
                                    batch = 200
                                    for idx in range(0, len(values), batch):
                                        sub = values[idx:idx+batch]
                                        execute_values(cursor, upsert_sql, sub, page_size=len(sub))
                                    db_manager.connection.commit()
                            # 真正新增筆數 = 擬寫入總筆數 - 已存在筆數（近似計算）
                            new_insert_count = max(len(values) - (duplicate_count if 'duplicate_count' in locals() else 0), 0)
                            result['price_records'] = new_insert_count
                            if 'duplicate_count' in locals():
                                result['duplicate_records'] = duplicate_count

                            # 添加日期範圍資訊
                            if dates:
                                dates = sorted([str(d) for d in dates])
                                result['price_date_range'] = {
                                    'start': dates[0],
                                    'end': dates[-1],
                                    'requested_start': start_date,
                                    'requested_end': end_date,
                                    'trading_days_count': len(dates)
                                }
                        else:
                            result['price_records'] = 0
                            result['status'] = 'partial'
                    
                    if update_returns and price_data is not None and (
                        (isinstance(price_data, pd.DataFrame) and not price_data.empty and len(price_data) > 1) or
                        (isinstance(price_data, list) and len(price_data) > 1)
                    ):
                        # 計算各種頻率的報酬率
                        daily_returns = stock_api.calculate_returns(price_data, 'daily')
                        weekly_returns = stock_api.calculate_returns(price_data, 'weekly')
                        monthly_returns = stock_api.calculate_returns(price_data, 'monthly')
                        
                        # 除錯：記錄計算結果
                        logger.info(f"Daily returns count: {len(daily_returns) if daily_returns else 0}")
                        logger.info(f"Weekly returns count: {len(weekly_returns) if weekly_returns else 0}")
                        logger.info(f"Monthly returns count: {len(monthly_returns) if monthly_returns else 0}")
                        if weekly_returns:
                            logger.info(f"Weekly returns sample: {weekly_returns[:2]}")
                        if monthly_returns:
                            logger.info(f"Monthly returns sample: {monthly_returns[:2]}")
                        
                        if daily_returns is not None and len(daily_returns) > 0:
                            # 儲存報酬率數據到資料庫
                            stored_returns = 0
                            return_dates = []
                            
                            # 建立週報酬率和月報酬率的查找字典
                            weekly_dict = {}
                            monthly_dict = {}
                            
                            # 為週報酬率建立映射 - 將週報酬率分配給該週的所有交易日
                            if weekly_returns:
                                for wr in weekly_returns:
                                    week_end_date = pd.to_datetime(wr['Date'])
                                    # 找到該週的所有交易日
                                    for dr in daily_returns:
                                        daily_date = pd.to_datetime(dr['Date'])
                                        # 檢查是否在同一週（週日為一週開始）
                                        if daily_date.isocalendar()[1] == week_end_date.isocalendar()[1] and daily_date.year == week_end_date.year:
                                            weekly_dict[dr['Date']] = wr['return']
                            
                            # 為月報酬率建立映射 - 將月報酬率分配給該月的所有交易日
                            if monthly_returns:
                                for mr in monthly_returns:
                                    month_end_date = pd.to_datetime(mr['Date'])
                                    # 找到該月的所有交易日
                                    for dr in daily_returns:
                                        daily_date = pd.to_datetime(dr['Date'])
                                        # 檢查是否在同一月
                                        if daily_date.year == month_end_date.year and daily_date.month == month_end_date.month:
                                            monthly_dict[dr['Date']] = mr['return']
                            for return_record in daily_returns:
                                try:
                                    date_str = return_record.get('Date')
                                    weekly_return = None
                                    monthly_return = None
                                    
                                    if weekly_returns:
                                        for wr in weekly_returns:
                                            week_end_date = pd.to_datetime(wr['Date'])
                                            # 找到該週的所有交易日
                                            daily_date = pd.to_datetime(date_str)
                                            # 檢查是否在同一週（週日為一週開始）
                                            if daily_date.isocalendar()[1] == week_end_date.isocalendar()[1] and daily_date.year == week_end_date.year:
                                                weekly_return = wr['return']
                                                break
                                    
                                    if monthly_returns:
                                        for mr in monthly_returns:
                                            month_end_date = pd.to_datetime(mr['Date'])
                                            # 找到該月的所有交易日
                                            daily_date = pd.to_datetime(date_str)
                                            # 檢查是否在同一月
                                            if daily_date.year == month_end_date.year and daily_date.month == month_end_date.month:
                                                monthly_return = mr['return']
                                                break
                                    
                                    daily_return = return_record.get('return')
                                    cumulative_return = return_record.get('cumulative_return')

                                    if daily_return is not None and (math.isinf(daily_return) or math.isnan(daily_return)):
                                        daily_return = None
                                    if weekly_return is not None and (math.isinf(weekly_return) or math.isnan(weekly_return)):
                                        weekly_return = None
                                    if monthly_return is not None and (math.isinf(monthly_return) or math.isnan(monthly_return)):
                                        monthly_return = None
                                    if cumulative_return is not None and (math.isinf(cumulative_return) or math.isnan(cumulative_return)):
                                        cumulative_return = None

                                    return_values.append((
                                        symbol,
                                        date_str,
                                        daily_return,
                                        weekly_return,
                                        monthly_return,
                                        cumulative_return
                                    ))
                                    return_dates.append(date_str)
                                except Exception as e:
                                    logger.warning(f"準備 {symbol} 報酬率數據失敗: {e}")

                            if return_values:
                                returns_upsert_sql = """
                                    INSERT INTO stock_returns (symbol, date, daily_return, weekly_return, monthly_return, cumulative_return)
                                    VALUES %s
                                    ON CONFLICT (symbol, date)
                                    DO UPDATE SET
                                        daily_return = EXCLUDED.daily_return,
                                        weekly_return = EXCLUDED.weekly_return,
                                        monthly_return = EXCLUDED.monthly_return,
                                        cumulative_return = EXCLUDED.cumulative_return
                                """
                                try:
                                    execute_values(cursor, returns_upsert_sql, return_values, page_size=2000)
                                    db_manager.connection.commit()
                                except Exception as e:
                                    logger.warning(f"批量寫入報酬率失敗，改用小批次: {e}")
                                    batch = 500
                                    for idx in range(0, len(return_values), batch):
                                        sub = return_values[idx:idx+batch]
                                        execute_values(cursor, returns_upsert_sql, sub, page_size=len(sub))
                                    db_manager.connection.commit()

                            result['return_records'] = len(return_values)
                            
                            # 添加報酬率日期範圍資訊
                            if return_dates:
                                return_dates.sort()
                                result['return_date_range'] = {
                                    'start': return_dates[0],
                                    'end': return_dates[-1],
                                    'requested_start': start_date,
                                    'requested_end': end_date,
                                    'trading_days_count': len(return_dates)
                                }
                    
                    results.append(result)
                
                except Exception as e:
                    errors.append({'symbol': symbol, 'error': str(e)})
                    logger.error(f"更新 {symbol} 失敗: {e}")
        
        finally:
            if db_manager:
                db_manager.disconnect()
        
        return jsonify({
            'success': True,
            'results': results,
            'errors': errors,
            'summary': {
                'total': len(symbols),
                'success': len(results),
                'failed': len(errors)
            }
        })
    except Exception as e:
        logger.error(f"批量更新失敗: {e}")
        # 確保資料庫連接被關閉
        if db_manager:
            try:
                db_manager.disconnect()
            except:
                pass
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康檢查 - 包含資料庫連接狀態和數據統計"""
    try:
        # 檢查資料庫連接
        db_manager = DatabaseManager()
        db_connected, db_message = db_manager.test_connection()
        
        if db_connected:
            # 獲取資料庫統計資訊
            try:
                if db_manager.connect():
                    cursor = db_manager.connection.cursor()
                    
                    # 查詢股價數據統計
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_records, 
                            COUNT(DISTINCT symbol) as unique_stocks,
                            MIN(date) as earliest_date,
                            MAX(date) as latest_date
                        FROM stock_prices;
                    """)
                    price_stats = cursor.fetchone()
                    
                    # 查詢報酬率數據統計
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_records, 
                            COUNT(DISTINCT symbol) as unique_stocks,
                            MIN(date) as earliest_date,
                            MAX(date) as latest_date
                        FROM stock_returns;
                    """)
                    return_stats = cursor.fetchone()
                    
                    # 獲取資料庫連接資訊
                    db_info = {
                        'host': db_manager.db_config['host'],
                        'port': db_manager.db_config['port'],
                        'database': db_manager.db_config['database'],
                        'user': db_manager.db_config['user']
                    }
                    
                    db_manager.disconnect()
                    
                    return jsonify({
                        'status': 'healthy',
                        'database': 'connected',
                        'database_info': db_message,
                        'database_connection': db_info,
                        'data_statistics': {
                            'stock_prices': {
                                'total_records': price_stats['total_records'],
                                'unique_stocks': price_stats['unique_stocks'],
                                'date_range': {
                                    'earliest': price_stats['earliest_date'].isoformat() if price_stats['earliest_date'] else None,
                                    'latest': price_stats['latest_date'].isoformat() if price_stats['latest_date'] else None
                                }
                            },
                            'stock_returns': {
                                'total_records': return_stats['total_records'],
                                'unique_stocks': return_stats['unique_stocks'],
                                'date_range': {
                                    'earliest': return_stats['earliest_date'].isoformat() if return_stats['earliest_date'] else None,
                                    'latest': return_stats['latest_date'].isoformat() if return_stats['latest_date'] else None
                                }
                            }
                        },
                        'timestamp': datetime.now().isoformat(),
                        'version': '1.0.0'
                    })
                else:
                    return jsonify({
                        'status': 'healthy',
                        'database': 'connected',
                        'database_info': db_message,
                        'timestamp': datetime.now().isoformat(),
                        'version': '1.0.0'
                    })
            except Exception as stats_error:
                return jsonify({
                    'status': 'healthy',
                    'database': 'connected',
                    'database_info': db_message,
                    'stats_error': str(stats_error),
                    'timestamp': datetime.now().isoformat(),
                    'version': '1.0.0'
                })
        else:
            return jsonify({
                'status': 'warning',
                'database': 'disconnected',
                'database_error': db_message,
                'timestamp': datetime.now().isoformat(),
                'version': '1.0.0'
            }), 503
    except Exception as e:
        return jsonify({
            'status': 'error',
            'database': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0'
        }), 500

@app.route('/api/test-connection', methods=['GET'])
def test_connection():
    """測試資料庫連接"""
    try:
        db_manager = DatabaseManager()
        if db_manager.connect():
            db_manager.disconnect()
            return jsonify({
                'success': True,
                'status': 'connected',
                'message': '資料庫連接成功'
            })
        else:
            return jsonify({
                'success': False,
                'status': 'disconnected',
                'message': '資料庫連接失敗'
            }), 500
    except Exception as e:
        logger.error(f"測試資料庫連接錯誤: {e}")
        return jsonify({
            'success': False,
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/env-check', methods=['GET'])
def env_check():
    """診斷環境變數設定，檢查 DATABASE_URL 是否可讀取（不回傳明文密碼）。"""
    try:
        db_url = os.environ.get('DATABASE_URL')
        present = db_url is not None and len(db_url) > 0

        masked_url = None
        has_sslmode = None
        has_channel_binding = None

        if present:
            try:
                # 遮蔽密碼：postgresql://user:*****@host/db?... 只保留帳號與主機
                # 簡單遮蔽實作，避免在日誌或回應中外洩密碼
                prefix, rest = db_url.split('://', 1)
                if '@' in rest and ':' in rest.split('@')[0]:
                    user_part, host_part = rest.split('@', 1)
                    user_name = user_part.split(':', 1)[0]
                    masked_url = f"{prefix}://{user_name}:****@{host_part}"
                else:
                    masked_url = f"{prefix}://****@{rest}"
            except Exception:
                masked_url = 'MASK_FAILED'

            try:
                lower_qs = db_url.lower()
                has_sslmode = ('sslmode=' in lower_qs)
                has_channel_binding = ('channel_binding=' in lower_qs)
            except Exception:
                has_sslmode = False
                has_channel_binding = False

        return jsonify({
            'success': True,
            'database_url_present': present,
            'masked_database_url': masked_url,
            'flags': {
                'sslmode_param_found': has_sslmode,
                'channel_binding_param_found': has_channel_binding
            }
        })
    except Exception as e:
        logger.error(f"env-check 發生錯誤: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/statistics', methods=['GET'])
def get_statistics():
    """獲取資料庫統計信息"""
    try:
        db_manager = DatabaseManager()
        if not db_manager.connect():
            return jsonify({
                'success': False,
                'error': '無法連接到資料庫'
            }), 500
        
        cursor = db_manager.connection.cursor()
        
        # 初始化統計數據
        total_records = 0
        unique_stocks = 0
        date_range_result = None
        last_update_result = None
        
        try:
            # 獲取總記錄數 - 檢查表是否存在
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'stock_prices'
            """)
            if cursor.fetchone()[0] > 0:
                cursor.execute("SELECT COUNT(*) FROM stock_prices")
                total_records = cursor.fetchone()[0]
                
                # 獲取日期範圍
                cursor.execute("""
                    SELECT MIN(date) as start_date, MAX(date) as end_date 
                    FROM stock_prices 
                    WHERE date IS NOT NULL
                """)
                date_range_result = cursor.fetchone()
                
                # 獲取最後更新時間
                cursor.execute("""
                    SELECT MAX(updated_at) as last_update 
                    FROM stock_prices 
                    WHERE updated_at IS NOT NULL
                """)
                last_update_result = cursor.fetchone()
        except Exception as e:
            logger.warning(f"stock_prices 表查詢錯誤: {e}")
        
        try:
            # 獲取股票數量 - 檢查表是否存在
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'stock_symbols'
            """)
            if cursor.fetchone()[0] > 0:
                cursor.execute("SELECT COUNT(DISTINCT symbol) FROM stock_symbols")
                unique_stocks = cursor.fetchone()[0]
        except Exception as e:
            logger.warning(f"stock_symbols 表查詢錯誤: {e}")
        
        db_manager.disconnect()
        
        # 準備統計數據
        stats = {
            'totalRecords': total_records or 0,
            'uniqueStocks': unique_stocks or 0,
            'dateRange': {
                'start': str(date_range_result[0]) if date_range_result[0] else None,
                'end': str(date_range_result[1]) if date_range_result[1] else None
            } if date_range_result else None,
            'lastUpdate': str(last_update_result[0]) if last_update_result and last_update_result[0] else None
        }
        
        return jsonify({
            'success': True,
            'data': stats
        })
        
    except Exception as e:
        logger.error(f"獲取統計信息錯誤: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    import sys
    port = 5003  # 使用 5003 端口避免衝突
    
    print("Taiwan Stock Data API Server Starting...")
    print("API Endpoints:")
    print("   GET  /api/symbols - Get all stock symbols")
    print("   GET  /api/stock/<symbol>/prices - Get stock price data")
    print("   GET  /api/stock/<symbol>/returns - Get return data")
    print("   POST /api/update - Batch update stock data")
    print("   GET  /api/health - Health check")
    print(f"Server address: http://localhost:{port}")
    
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True, use_reloader=False)
