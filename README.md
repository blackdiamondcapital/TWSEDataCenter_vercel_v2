# 台灣股市數據中心

一個功能完整的台灣股票數據管理系統，提供股票價格數據抓取、儲存和視覺化功能。本系統專為台灣股市設計，支援上市、上櫃股票及各類市場指數的即時數據更新與分析。

## 🚀 功能特色

 - **即時股票數據抓取**: 支援台灣上市（.TW）、上櫃（.TWO）股票及市場指數
 - **台灣加權指數 (^TWII)**: 特別優化的加權指數數據抓取與驗證
 - **多種更新模式**: 全部股票、指定範圍、指定清單、指數更新
 - **批次更新（新）**: 前端提供「更新所有上市股票」「更新所有上櫃股票」一鍵批更
 - **數據視覺化**: 提供股價圖表和統計資訊
 - **PostgreSQL 數據庫**: 高效的數據儲存與查詢
 - **現代化 Web 介面**: 響應式設計，桌面/行動皆適用
 - **並發加速（強化）**: 後端多執行緒 + 前端受控並發，提升批量吞吐
 - **跨源存取（CORS）處理**: 前端以 HTTP 服務，後端固定 `http://localhost:5003`

## 📋 系統需求

- Python 3.8+
- PostgreSQL 資料庫
- Anaconda 環境 (推薦)

## 🛠️ 安裝與設定

### 1. 環境設定

```bash
# 建立 conda 環境
conda create -n stocknexus python=3.10
conda activate stocknexus

# 安裝相依套件
pip install -r requirements.txt
```

### 2. 資料庫設定

確保 PostgreSQL 已安裝並運行，建立相應的資料庫和表格。

### 3. 啟動後端 API 服務

```bash
# 啟動 Flask 服務器
python server.py
```

服務器將在 `http://localhost:5003` 啟動。

> 本版已啟用後端多執行緒並停用自動重載：`app.run(..., threaded=True, use_reloader=False)`，在除錯器下可穩定並行處理請求。

### 4. 啟動前端（務必以 HTTP 服務）

請勿以檔案模式直接開啟 `index.html`（`file://` 會導致 CORS/Fetch 問題）。建議以下方式其一：

```bash
# 方式 A：使用 VS Code Live Server 擴充套件
# 右鍵 index.html -> Open with Live Server（常見位址 http://127.0.0.1:5500）

# 方式 B：使用 Python 提供靜態伺服器（於專案根目錄執行）
python -m http.server 5500
# 然後在瀏覽器開啟 http://localhost:5500/index.html
```

前端已於 `script.js` 中以完整 URL 呼叫後端（`http://localhost:5003/api/...`），確保後端可存取。

### 5.（可選）以 Waitress 在 Windows 上執行

```bash
pip install waitress
waitress-serve --listen=0.0.0.0:5003 server:app
```

說明：Waitress 為生產級 WSGI 伺服器（多執行緒），在 Windows 上較穩定。若需更高吞吐，可啟動多個實例並以反向代理負載均衡。

## 📁 專案結構

```
TWSEDataCenter-main/
├── server.py              # Flask 後端服務器
├── index.html             # 主要網頁介面
├── script.js              # 前端 JavaScript 邏輯
├── styles.css             # 樣式表
├── requirements.txt       # Python 相依套件
├── test_twii.py          # ^TWII 測試腳本
├── simple_test.py        # 簡單測試腳本
├── test_twse_api.py      # TWSE API 測試
└── README.md             # 專案說明文件
```

## 🔧 主要組件

### 後端 API (server.py)

- **StockDataAPI**: 核心股票數據抓取類別
- **DatabaseManager**: 資料庫連接和操作管理
- **Flask 路由**: RESTful API 端點

#### 主要 API 端點

- `GET /api/symbols` - 獲取所有股票代碼（回傳 `{ success: true, data: [...], count: N }`）
- `GET /api/stock/<symbol>/prices` - 獲取股價數據
- `POST /api/update` - 批量更新股票數據
- `GET /api/health` - 健康檢查
- `GET /api/statistics` - 系統統計資訊

### 前端介面

- **現代化設計**: 使用 CSS Grid 和 Flexbox
- **響應式布局**: 支援各種螢幕尺寸
- **即時回饋**: 前端日誌與進度條即時回饋
- **圖表視覺化**: 使用 Chart.js 和 Lightweight Charts
 - **進階選項（新增）**：
   - 「更新所有上市股票」：批次更新所有 `.TW` 股票
   - 「更新所有上櫃股票」：批次更新所有 `.TWO` 股票

### 並發與效能（強化）

- **後端並行**：`server.py` 以 `threaded=True` 執行。
- **前端並發控制**：`script.js` 內建 `runWithConcurrency(items, limit, worker)` 受控並發。
- **批次更新簡化流程**：`batchUpdateStocksSimple` 以批次+並發方式呼叫 `/api/update`。
- **建議值**：並發 3–8；視外部 API 限流、網路與 DB I/O 調整。

## 🎯 使用方式

### 1. 股票數據更新

1. 以 HTTP 開啟 `index.html`（Live Server 或 `python -m http.server`）。
2. 在「進階選項」中可選：
   - **更新所有上市股票**（約 900 檔，估時 45–60 分）
   - **更新所有上櫃股票**（約 800 檔，估時 40–50 分）
   - 亦可使用原有「全部股票」「指定範圍」「市場指數」等模式。
3. 點擊「執行資料更新」。
4. 即時查看前端日誌、成功/失敗計數與進度百分比。

> 提示：提高前端並發可縮短總時間，但受外部 API 限流、網路延遲與資料庫 I/O 影響，存在效益遞減與失敗率上升的風險。

### 2. 數據查詢

- 使用 API 端點查詢特定股票的歷史價格
- 支援日期範圍篩選
- 提供 JSON 格式的結構化數據

### 3. 成功驗證建議

- 於前端日誌查看每批成功/失敗與最終彙總。
- 呼叫 `GET http://localhost:5003/api/stock/<symbol>/prices` 驗證資料已更新。
- 查看後端日誌或資料庫中對應筆數變化。

## 🔍 特殊功能

### 台灣加權指數 (^TWII) 優化

本系統特別針對台灣加權指數進行了優化：
- **版本控制**: 強制使用 yfinance 0.2.65 版本
- **即時抓取**: 繞過資料庫快取，直接獲取最新數據
- **數據驗證**: 自動驗證價格合理性
- **錯誤處理**: 完善的錯誤處理和日誌記錄

### 數據格式相容性

- 支援多種數據格式 (DataFrame, List)
- 自動欄位名稱對應
- 靈活的日期格式處理

## 🐛 故障排除

### 常見問題

1. **yfinance 版本問題**
   - 確保使用 yfinance 0.2.65 版本
   - 檢查 conda 環境路徑設定

2. **資料庫連接失敗**
   - 確認 PostgreSQL 服務運行
   - 檢查資料庫連接參數

3. **^TWII 數據錯誤**
   - 系統已自動修復此問題
   - 使用即時抓取模式

4. **在除錯器下啟動 Flask 發生 `SystemExit: 3`**
   - 原因：Flask reloader 與調試流程衝突。
   - 解法：已於程式中設置 `use_reloader=False`。如仍遇到，請確保以最新版程式執行並重新啟動。

5. **CORS / Fetch 錯誤**
   - 請確認前端是以 HTTP 服務開啟（非 `file://`）。
   - 後端需在 `http://localhost:5003` 運行，前端 `script.js` 已使用完整 URL 呼叫 API。

6. **前端元素為 null 的錯誤**
   - 已移除對不存在 UI 元素的存取；若自行改版 HTML，請同步調整 `script.js` 對應選擇器。

7. **端點或回應結構不符**
   - 本版前端預期 `/api/symbols` 回傳 `{ success: true, data: [...] }`。
   - 若後端回傳結構不同，請調整 `script.js` 中對回應的解析。

## 📊 系統監控

- **健康檢查**: `/api/health` 端點
- **系統統計**: `/api/statistics` 端點
- **日誌記錄**: 詳細的操作日誌
- **錯誤追蹤**: 完整的錯誤堆疊追蹤

## 🔒 安全性

- 輸入驗證和清理
- SQL 注入防護
- 錯誤訊息過濾
- 資料庫連接池管理

## 📈 效能優化

- 批量數據處理（`execute_values` 批次 upsert）
- 資料庫索引與連線管理
- 快取機制（代碼清單快取）
- 前後端並發與節流（本版強化）

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request 來改善這個專案。

## 📄 授權

本專案採用 MIT 授權條款。

## 📞 聯絡資訊

如有問題或建議，請透過 GitHub Issues 聯絡。

---

**最後更新**: 2025-08-17
**版本**: 1.2.0
**狀態**: 穩定運行 ✅
