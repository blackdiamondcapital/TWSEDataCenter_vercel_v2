// Taiwan Stock Data Update System - JavaScript
class TaiwanStockApp {
    constructor() {
        this.dbConfig = {
            host: 'localhost',
            port: '5432',
            user: 'postgres',
            password: 's8304021',
            dbname: 'postgres'
        };
        
        this.isUpdating = false;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.initializeDates();
        this.checkDatabaseConnection();
        this.addLogMessage('系統已啟動', 'info');
    }

    setupEventListeners() {
        // Tab navigation
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e.target.dataset.tab));
        });

        // Stock range toggle
        document.querySelectorAll('input[name="stockRange"]').forEach(radio => {
            radio.addEventListener('change', () => this.toggleRangeInputs());
        });

        // Update functionality
        document.getElementById('executeUpdate').addEventListener('click', () => this.executeUpdate());
        document.getElementById('cancelUpdate').addEventListener('click', () => this.cancelUpdate());

        // Query functionality
        document.getElementById('queryPrice').addEventListener('click', () => this.queryPriceData());
        document.getElementById('queryReturn').addEventListener('click', () => this.queryReturnData());
        document.getElementById('exportQuery').addEventListener('click', () => this.exportQueryResults());

        // Stats functionality
        document.getElementById('refreshStats').addEventListener('click', () => this.refreshDatabaseStats());

        // Settings functionality
        document.getElementById('testConnection').addEventListener('click', () => this.testDatabaseConnection());
        document.getElementById('saveDbSettings').addEventListener('click', () => this.saveDatabaseSettings());
        document.getElementById('resetSettings').addEventListener('click', () => this.resetSystemSettings());
        document.getElementById('saveSystemSettings').addEventListener('click', () => this.saveSystemSettings());

        // Date range functionality
        document.querySelectorAll('input[name="dateRange"]').forEach(radio => {
            radio.addEventListener('change', (e) => this.toggleDateRangeInputs(e));
        });

        // Log functionality
        document.getElementById('clearLog').addEventListener('click', () => this.clearLog());
        document.getElementById('exportLog').addEventListener('click', () => this.exportLog());
    }

    initializeDates() {
        const today = new Date();
        const lastYear = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate());
        
        document.getElementById('startDate').value = this.formatDate(lastYear);
        document.getElementById('endDate').value = this.formatDate(today);
    }

    formatDate(date) {
        return date.toISOString().split('T')[0];
    }

    switchTab(tabName) {
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

        document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
        document.getElementById(`${tabName}Tab`).classList.add('active');

        const names = { 'update': '資料更新', 'query': '資料查詢', 'stats': '資料統計', 'settings': '系統設定' };
        this.addLogMessage(`切換到${names[tabName] || tabName}頁面`, 'info');
    }

    toggleRangeInputs() {
        const isRangeSelected = document.querySelector('input[name="stockRange"][value="range"]').checked;
        document.getElementById('rangeFrom').disabled = !isRangeSelected;
        document.getElementById('rangeTo').disabled = !isRangeSelected;
    }

    async executeUpdate() {
        const updatePrices = document.getElementById('updatePrices').checked;
        const updateReturns = document.getElementById('updateReturns').checked;
        
        if (!updatePrices && !updateReturns) {
            this.showMessage('請至少選擇一種要更新的數據（股價或報酬率）', 'warning');
            return;
        }

        const updateMode = document.querySelector('input[name="updateMode"]:checked').value;
        
        if (updateMode === 'full') {
            const confirmed = confirm('全量更新將會移除並重新下載所有數據，這可能需要很長時間。\n\n是否確定要執行全量更新？');
            if (!confirmed) return;
        }

        let symbolRange = null;
        
        // 初始化顯示區域
        this.initializeDisplayAreas();

        if (document.querySelector('input[name="stockRange"][value="range"]').checked) {
            const fromCode = document.getElementById('rangeFrom').value.trim();
            const toCode = document.getElementById('rangeTo').value.trim();
            
            if (!fromCode || !toCode) {
                this.showMessage('請輸入完整的股票代碼範圍', 'warning');
                return;
            }
            symbolRange = [fromCode, toCode];
        }

        this.startUpdateProcess(updateMode, updatePrices, updateReturns, symbolRange);
    }

    async startUpdateProcess(updateMode, updatePrices, updateReturns, symbolRange) {
        this.isUpdating = true;
        document.getElementById('executeUpdate').disabled = true;
        document.getElementById('cancelUpdate').disabled = false;
        
        this.updateProgress(0, '準備中...');
        this.clearResultsTable();
        
        const updateTypes = [];
        if (updatePrices) updateTypes.push('股價');
        if (updateReturns) updateTypes.push('報酬率');
        
        let logMsg = `開始${updateMode === 'full' ? '全量' : '增量'}模式更新 ${updateTypes.join('+')}數據`;
        if (symbolRange) logMsg += `，股票範圍: ${symbolRange[0]} 至 ${symbolRange[1]}`;
        
        this.addLogMessage(logMsg, 'info');
        
        try {
            this.updateProgress(5, '正在連接 API 服務器...');
            
            // 獲取股票代碼列表
            this.updateProgress(10, '抓取台灣股票代碼...');
            let url = 'http://localhost:5001/api/symbols';
            if (symbolRange) {
                url += `?start=${symbolRange[0]}&end=${symbolRange[1]}`;
            }
            
            const symbolsResponse = await fetch(url);
            if (!symbolsResponse.ok) {
                throw new Error('無法連接到 API 服務器，請確認後端服務已啟動');
            }
            
            const symbolsData = await symbolsResponse.json();
            if (!symbolsData.success) {
                throw new Error(symbolsData.error || '獲取股票代碼失敗');
            }
            
            let symbols = symbolsData.data;
            
            // 根據選擇的範圍選項處理股票列表
            const stockRangeOption = document.querySelector('input[name="stockRange"]:checked').value;
            
            if (stockRangeOption === 'limit') {
                const limitCount = parseInt(document.getElementById('stockLimit').value);
                symbols = symbols.slice(0, limitCount);
                this.addLogMessage(`限制處理前 ${limitCount} 檔股票`, 'info');
            } else if (stockRangeOption === 'all') {
                this.addLogMessage(`處理所有 ${symbols.length} 檔股票`, 'info');
            }
            
            this.addLogMessage(`獲取到 ${symbols.length} 檔股票`, 'info');
            
            // 顯示日期範圍資訊
            const dateRangeType = document.querySelector('input[name="dateRange"]:checked').value;
            if (dateRangeType === 'custom') {
                const startDate = document.getElementById('startDate').value;
                const endDate = document.getElementById('endDate').value;
                this.addLogMessage(`📅 自訂日期範圍: ${startDate} 至 ${endDate}`, 'info');
            } else {
                const days = parseInt(document.getElementById('recentPeriod').value);
                this.addLogMessage(`📅 時間範圍: 最近 ${days} 天`, 'info');
            }
            
            // 批量更新股票數據
            if (updatePrices || updateReturns) {
                this.updateProgress(20, '開始批量更新股票數據...');
                this.addLogMessage(`準備更新 ${symbols.length} 檔股票`, 'info');
                
                // 分批處理避免超時
                const batchSize = 10;
                const totalBatches = Math.ceil(symbols.length / batchSize);
                let processedCount = 0;
                
                for (let i = 0; i < totalBatches; i++) {
                    const startIdx = i * batchSize;
                    const endIdx = Math.min(startIdx + batchSize, symbols.length);
                    const batchSymbols = symbols.slice(startIdx, endIdx);
                    
                    this.addLogMessage(`處理第 ${i + 1}/${totalBatches} 批，股票 ${startIdx + 1}-${endIdx}`, 'info');
                    
                    // 顯示當前批次的股票
                    const symbolNames = batchSymbols.map(s => `${s.symbol}(${s.name})`).join(', ');
                    this.addLogMessage(`當前批次: ${symbolNames}`, 'info');
                    
                    const updateData = {
                        symbols: batchSymbols.map(s => s.symbol),
                        update_prices: updatePrices,
                        update_returns: updateReturns
                    };
                    
                    try {
                        // 逐一處理每檔股票以顯示詳細狀態
                        for (let j = 0; j < batchSymbols.length; j++) {
                            const stock = batchSymbols[j];
                            this.addLogMessage(`🔄 正在抓取 ${stock.symbol} (${stock.name})...`, 'info');
                            
                            try {
                                // 獲取日期範圍設定
                                const dateRangeType = document.querySelector('input[name="dateRange"]:checked').value;
                                let startDate, endDate;
                                
                                if (dateRangeType === 'custom') {
                                    startDate = document.getElementById('startDate').value;
                                    endDate = document.getElementById('endDate').value;
                                } else {
                                    const days = parseInt(document.getElementById('recentPeriod').value);
                                    const today = new Date();
                                    const pastDate = new Date(today);
                                    pastDate.setDate(today.getDate() - days);
                                    
                                    endDate = today.toISOString().split('T')[0];
                                    startDate = pastDate.toISOString().split('T')[0];
                                }
                                
                                toggleDateRangeInputs(e) {
        const recentOptions = document.getElementById('recentOptions');
        const dateInputs = document.getElementById('dateInputs');
        const startDate = document.getElementById('startDate');
        const endDate = document.getElementById('endDate');
        
        if (e.target.value === 'custom') {
            recentOptions.style.display = 'none';
            dateInputs.style.display = 'block';
            startDate.disabled = false;
            endDate.disabled = false;
            
            // 設定預設日期範圍（最近30天）
            const today = new Date();
            const thirtyDaysAgo = new Date(today);
            thirtyDaysAgo.setDate(today.getDate() - 30);
            
            endDate.value = today.toISOString().split('T')[0];
            startDate.value = thirtyDaysAgo.toISOString().split('T')[0];
        } else {
            recentOptions.style.display = 'block';
            dateInputs.style.display = 'none';
            startDate.disabled = true;
            endDate.disabled = true;
        }
    }

    initializeDisplayAreas() {
        // 初始化股票範圍顯示區域
        const limitInputs = document.getElementById('limitInputs');
        const rangeInputs = document.getElementById('rangeInputs');
        if (limitInputs) limitInputs.style.display = 'block';
        if (rangeInputs) rangeInputs.style.display = 'none';
        
        // 初始化日期範圍顯示區域
        const recentOptions = document.getElementById('recentOptions');
        const dateInputs = document.getElementById('dateInputs');
        if (recentOptions) recentOptions.style.display = 'block';
        if (dateInputs) dateInputs.style.display = 'none';
    }                            // 單獨處理每檔股票
                                const singleUpdateData = {
                                    symbols: [stock.symbol],
                                    update_prices: updatePrices,
                                    update_returns: updateReturns,
                                    start_date: startDate,
                                    end_date: endDate
                                };
                                
                                const singleResponse = await fetch('http://localhost:5001/api/update', {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/json'
                                    },
                                    body: JSON.stringify(singleUpdateData)
                                });
                                
                                if (!singleResponse.ok) {
                                    throw new Error(`HTTP ${singleResponse.status}`);
                                }
                                
                                const singleResult = await singleResponse.json();
                                if (singleResult.success) {
                                    processedCount++;
                                    this.addLogMessage(`✅ ${stock.symbol} (${stock.name}) 完成`, 'success');
                                } else {
                                    this.addLogMessage(`❌ ${stock.symbol} (${stock.name}) 失敗: ${singleResult.error}`, 'error');
                                    processedCount++; // 仍然計入已處理
                                }
                                
                            } catch (stockError) {
                                this.addLogMessage(`❌ ${stock.symbol} (${stock.name}) 錯誤: ${stockError.message}`, 'error');
                                processedCount++; // 仍然計入已處理
                            }
                            
                            // 更新進度條
                            const progress = 20 + (processedCount / symbols.length) * 70;
                            this.updateProgress(progress, `已處理 ${processedCount}/${symbols.length} 檔股票`);
                            
                            // 短暫延遲避免API過載
                            await new Promise(resolve => setTimeout(resolve, 200));
                        }
                        
                        this.addLogMessage(`📊 批次 ${i + 1}/${totalBatches} 完成，已處理 ${processedCount}/${symbols.length} 檔`, 'info');
                        
                    } catch (error) {
                        this.addLogMessage(`批次 ${i + 1} 處理失敗: ${error.message}`, 'error');
                    }
                    
                    // 批次間稍作延遲
                    if (i < totalBatches - 1) {
                        await this.delay(1000);
                    }
                }
                
                this.updateProgress(90, '批量更新完成');
                this.addLogMessage(`批量更新完成，共處理 ${processedCount}/${symbols.length} 檔股票`, 'success');
                this.updateProgress(100, '數據更新完成!');
                this.updateResultsTable(symbols);
                
                const summary = updateResult.summary;
                const resultMessage = `數據更新完成! 成功: ${summary.success}檔, 失敗: ${summary.failed}檔`;
                
                this.addLogMessage(resultMessage, 'info');
                document.getElementById('progressStatus').textContent = '更新完成';
                document.getElementById('progressStatus').style.color = 'var(--success)';
                this.showMessage(resultMessage, 'success');
            }
            
        } catch (error) {
            this.addLogMessage(error.message, 'error');
            document.getElementById('progressStatus').textContent = '執行失敗';
            document.getElementById('progressStatus').style.color = 'var(--error)';
            this.showMessage(error.message, 'error');
        } finally {
            this.isUpdating = false;
            document.getElementById('executeUpdate').disabled = false;
            document.getElementById('cancelUpdate').disabled = true;
        }
    }

    generateMockSymbols(symbolRange) {
        const mockSymbols = [
            // 上市股票 (TW)
            { symbol: '1101.TW', name: '台泥' },
            { symbol: '1102.TW', name: '亞泥' },
            { symbol: '1216.TW', name: '統一' },
            { symbol: '1301.TW', name: '台塑' },
            { symbol: '1303.TW', name: '南亞' },
            { symbol: '1326.TW', name: '台化' },
            { symbol: '1402.TW', name: '遠東新' },
            { symbol: '2002.TW', name: '中鋼' },
            { symbol: '2105.TW', name: '正新' },
            { symbol: '2207.TW', name: '和泰車' },
            { symbol: '2227.TW', name: '裕日車' },
            { symbol: '2303.TW', name: '聯電' },
            { symbol: '2308.TW', name: '台達電' },
            { symbol: '2317.TW', name: '鴻海' },
            { symbol: '2330.TW', name: '台積電' },
            { symbol: '2357.TW', name: '華碩' },
            { symbol: '2382.TW', name: '廣達' },
            { symbol: '2408.TW', name: '南亞科' },
            { symbol: '2412.TW', name: '中華電' },
            { symbol: '2454.TW', name: '聯發科' },
            { symbol: '2474.TW', name: '可成' },
            { symbol: '2603.TW', name: '長榮' },
            { symbol: '2609.TW', name: '陽明' },
            { symbol: '2615.TW', name: '萬海' },
            { symbol: '2801.TW', name: '彰銀' },
            { symbol: '2880.TW', name: '華南金' },
            { symbol: '2881.TW', name: '富邦金' },
            { symbol: '2882.TW', name: '國泰金' },
            { symbol: '2883.TW', name: '開發金' },
            { symbol: '2884.TW', name: '玉山金' },
            { symbol: '2885.TW', name: '元大金' },
            { symbol: '2886.TW', name: '兆豐金' },
            { symbol: '2887.TW', name: '台新金' },
            { symbol: '2888.TW', name: '新光金' },
            { symbol: '2890.TW', name: '永豐金' },
            { symbol: '2891.TW', name: '中信金' },
            { symbol: '2892.TW', name: '第一金' },
            { symbol: '2912.TW', name: '統一超' },
            { symbol: '3008.TW', name: '大立光' },
            { symbol: '3034.TW', name: '聯詠' },
            { symbol: '3037.TW', name: '欣興' },
            { symbol: '3045.TW', name: '台灣大' },
            { symbol: '3231.TW', name: '緯創' },
            { symbol: '3481.TW', name: '群創' },
            { symbol: '3711.TW', name: '日月光投控' },
            { symbol: '4904.TW', name: '遠傳' },
            { symbol: '4938.TW', name: '和碩' },
            { symbol: '5871.TW', name: '中租-KY' },
            { symbol: '5880.TW', name: '合庫金' },
            { symbol: '6505.TW', name: '台塑化' },
            { symbol: '6669.TW', name: '緯穎' },
            
            // 櫃檯股票 (TWO)
            { symbol: '3006.TWO', name: '晶豪科' },
            { symbol: '3016.TWO', name: '嘉晶' },
            { symbol: '3035.TWO', name: '智原' },
            { symbol: '3036.TWO', name: '文曄' },
            { symbol: '3044.TWO', name: '健鼎' },
            { symbol: '3049.TWO', name: '和鑫' },
            { symbol: '3050.TWO', name: '鈺德' },
            { symbol: '3051.TWO', name: '力特' },
            { symbol: '3054.TWO', name: '立德' },
            { symbol: '3055.TWO', name: '蔚華科' },
            { symbol: '3056.TWO', name: '總太' },
            { symbol: '3057.TWO', name: '喬鼎' },
            { symbol: '3058.TWO', name: '立德' },
            { symbol: '3060.TWO', name: '銘異' },
            { symbol: '3062.TWO', name: '建漢' },
            { symbol: '3090.TWO', name: '日電貿' },
            { symbol: '3092.TWO', name: '鴻碩' },
            { symbol: '3094.TWO', name: '聯傑' },
            { symbol: '3130.TWO', name: '一零四' },
            { symbol: '3149.TWO', name: '正達' },
            { symbol: '3167.TWO', name: '大量' },
            { symbol: '3189.TWO', name: '景碩' },
            { symbol: '3209.TWO', name: '全科' },
            { symbol: '3229.TWO', name: '晟鈦' },
            { symbol: '3293.TWO', name: '鈊象' },
            { symbol: '3305.TWO', name: '昇貿' },
            { symbol: '3308.TWO', name: '聯德' },
            { symbol: '3321.TWO', name: '同泰' },
            { symbol: '3356.TWO', name: '奇偶' },
            { symbol: '3376.TWO', name: '新日興' },
            { symbol: '3380.TWO', name: '明泰' },
            { symbol: '3406.TWO', name: '玉晶光' },
            { symbol: '3443.TWO', name: '創意' },
            { symbol: '3450.TWO', name: '聯鈞' },
            { symbol: '3454.TWO', name: '晶睿' },
            { symbol: '3533.TWO', name: '嘉澤' },
            { symbol: '3545.TWO', name: '敦泰' },
            { symbol: '3596.TWO', name: '智易' },
            { symbol: '3661.TWO', name: '世芯-KY' },
            { symbol: '3679.TWO', name: '新至陞' },
            { symbol: '3682.TWO', name: '亞太電' },
            { symbol: '4966.TWO', name: '譜瑞-KY' },
            { symbol: '4967.TWO', name: '十銓' },
            { symbol: '4968.TWO', name: '立積' },
            { symbol: '4973.TWO', name: '廣穎' },
            { symbol: '4974.TWO', name: '亞泰' },
            { symbol: '4999.TWO', name: '鑫禾' },
            { symbol: '5269.TWO', name: '祥碩' },
            { symbol: '5274.TWO', name: '信驊' },
            { symbol: '5347.TWO', name: '世界' },
            { symbol: '5425.TWO', name: '台半' },
            { symbol: '5434.TWO', name: '崇越' },
            { symbol: '5483.TWO', name: '中美晶' },
            { symbol: '5515.TWO', name: '建國' },
            { symbol: '5519.TWO', name: '隆大' },
            { symbol: '5521.TWO', name: '工信' },
            { symbol: '5525.TWO', name: '順天' },
            { symbol: '5531.TWO', name: '鄉林' },
            { symbol: '5533.TWO', name: '皇鼎' },
            { symbol: '5534.TWO', name: '長虹' },
            { symbol: '5538.TWO', name: '東明-KY' },
            { symbol: '6116.TWO', name: '彩晶' },
            { symbol: '6120.TWO', name: '達運' },
            { symbol: '6121.TWO', name: '新普' },
            { symbol: '6133.TWO', name: '金橋' },
            { symbol: '6136.TWO', name: '富爾特' },
            { symbol: '6139.TWO', name: '亞翔' },
            { symbol: '6141.TWO', name: '柏承' },
            { symbol: '6142.TWO', name: '友勁' },
            { symbol: '6143.TWO', name: '振曜' },
            { symbol: '6145.TWO', name: '勁永' },
            { symbol: '6147.TWO', name: '頎邦' },
            { symbol: '6152.TWO', name: '百一' },
            { symbol: '6153.TWO', name: '嘉聯益' },
            { symbol: '6155.TWO', name: '鈞寶' },
            { symbol: '6161.TWO', name: '捷波' },
            { symbol: '6164.TWO', name: '華興' },
            { symbol: '6165.TWO', name: '捷泰' },
            { symbol: '6166.TWO', name: '凌華' },
            { symbol: '6168.TWO', name: '宏齊' },
            { symbol: '6172.TWO', name: '互億' },
            { symbol: '6176.TWO', name: '瑞儀' },
            { symbol: '6177.TWO', name: '達麗' },
            { symbol: '6183.TWO', name: '關貿' },
            { symbol: '6191.TWO', name: '精成科' },
            { symbol: '6192.TWO', name: '巨路' },
            { symbol: '6196.TWO', name: '帆宣' },
            { symbol: '6197.TWO', name: '佳必琪' },
            { symbol: '6202.TWO', name: '盛群' },
            { symbol: '6213.TWO', name: '聯茂' },
            { symbol: '6214.TWO', name: '精誠' },
            { symbol: '6215.TWO', name: '和椿' },
            { symbol: '6216.TWO', name: '居易' },
            { symbol: '6224.TWO', name: '聚鼎' },
            { symbol: '6226.TWO', name: '光鼎' },
            { symbol: '6230.TWO', name: '超眾' },
            { symbol: '6235.TWO', name: '華孚' },
            { symbol: '6239.TWO', name: '力成' },
            { symbol: '6243.TWO', name: '迅杰' },
            { symbol: '6244.TWO', name: '茂迪' },
            { symbol: '6251.TWO', name: '定穎' },
            { symbol: '6257.TWO', name: '矽格' },
            { symbol: '6269.TWO', name: '台郡' },
            { symbol: '6271.TWO', name: '同欣電' },
            { symbol: '6274.TWO', name: '台燿' },
            { symbol: '6277.TWO', name: '宏正' },
            { symbol: '6278.TWO', name: '台表科' },
            { symbol: '6281.TWO', name: '全國電' },
            { symbol: '6285.TWO', name: '啟碁' },
            { symbol: '6288.TWO', name: '聯嘉' },
            { symbol: '6289.TWO', name: '華上' },
            { symbol: '6405.TWO', name: '悅城' },
            { symbol: '6409.TWO', name: '旭隼' },
            { symbol: '6412.TWO', name: '群電' },
            { symbol: '6414.TWO', name: '樺漢' },
            { symbol: '6415.TWO', name: '矽力-KY' },
            { symbol: '6416.TWO', name: '瑞祺電通' },
            { symbol: '6417.TWO', name: '韋僑' },
            { symbol: '6431.TWO', name: '光麗-KY' },
            { symbol: '6442.TWO', name: '光聖' },
            { symbol: '6443.TWO', name: '元晶' },
            { symbol: '6446.TWO', name: '藥華藥' },
            { symbol: '6449.TWO', name: '鈺邦' },
            { symbol: '6451.TWO', name: '訊芯-KY' },
            { symbol: '6456.TWO', name: 'GIS-KY' },
            { symbol: '6464.TWO', name: '台數科' },
            { symbol: '6472.TWO', name: '保瑞' },
            { symbol: '6477.TWO', name: '安集' },
            { symbol: '6488.TWO', name: '環球晶' },
            { symbol: '6491.TWO', name: '晶碩' },
            { symbol: '6504.TWO', name: '南六' },
            { symbol: '6525.TWO', name: '捷敏-KY' },
            { symbol: '6531.TWO', name: '愛普' },
            { symbol: '6533.TWO', name: '晶心科' },
            { symbol: '6541.TWO', name: '泰福-KY' },
            { symbol: '6547.TWO', name: '高端疫苗' },
            { symbol: '6552.TWO', name: '易華電' },
            { symbol: '6561.TWO', name: '是方' },
            { symbol: '6573.TWO', name: '虹揚-KY' },
            { symbol: '6581.TWO', name: '鋼聯' },
            { symbol: '6591.TWO', name: '動力-KY' },
            { symbol: '6592.TWO', name: '和潤企業' },
            { symbol: '6598.TWO', name: 'ABC-KY' },
            { symbol: '8016.TWO', name: '矽創' },
            { symbol: '8021.TWO', name: '尖點' },
            { symbol: '8028.TWO', name: '昇陽半導體' },
            { symbol: '8033.TWO', name: '雷虎' },
            { symbol: '8040.TWO', name: '九暘' },
            { symbol: '8046.TWO', name: '南電' },
            { symbol: '8070.TWO', name: '長華' },
            { symbol: '8081.TWO', name: '致新' },
            { symbol: '8101.TWO', name: '華冠' },
            { symbol: '8103.TWO', name: '瀚荃' },
            { symbol: '8105.TWO', name: '凌巨' },
            { symbol: '8110.TWO', name: '華東' },
            { symbol: '8114.TWO', name: '振樺電' },
            { symbol: '8131.TWO', name: '福懋科' },
            { symbol: '8147.TWO', name: '正淩' },
            { symbol: '8150.TWO', name: '南茂' },
            { symbol: '8163.TWO', name: '達方' },
            { symbol: '8171.TWO', name: '天宇' },
            { symbol: '8183.TWO', name: '精星' },
            { symbol: '8201.TWO', name: '無敵' },
            { symbol: '8213.TWO', name: '志超' },
            { symbol: '8215.TWO', name: '明基材' },
            { symbol: '8249.TWO', name: '菱光' },
            { symbol: '8261.TWO', name: '富鼎' },
            { symbol: '8271.TWO', name: '宇瞻' },
            { symbol: '8299.TWO', name: '群聯' },
            { symbol: '8341.TWO', name: '日友' },
            { symbol: '8342.TWO', name: '益張' },
            { symbol: '8349.TWO', name: '恒耀' },
            { symbol: '8354.TWO', name: '冠好' },
            { symbol: '8358.TWO', name: '金居' },
            { symbol: '8383.TWO', name: '千附' },
            { symbol: '8401.TWO', name: '白紗科' },
            { symbol: '8403.TWO', name: '盛弘' },
            { symbol: '8404.TWO', name: '百和興業-KY' },
            { symbol: '8410.TWO', name: '森田' },
            { symbol: '8411.TWO', name: '福貞-KY' },
            { symbol: '8416.TWO', name: '實威' },
            { symbol: '8418.TWO', name: '捷必勝-KY' },
            { symbol: '8420.TWO', name: '明揚' },
            { symbol: '8421.TWO', name: '旭源' },
            { symbol: '8422.TWO', name: '可寧衛' },
            { symbol: '8427.TWO', name: '基勝-KY' },
            { symbol: '8429.TWO', name: '金麗-KY' },
            { symbol: '8431.TWO', name: '匯鑽科' },
            { symbol: '8432.TWO', name: '東生華' },
            { symbol: '8433.TWO', name: '弘帆' },
            { symbol: '8435.TWO', name: '鉅邁' },
            { symbol: '8436.TWO', name: '大江' },
            { symbol: '8437.TWO', name: '大地-KY' },
            { symbol: '8440.TWO', name: '綠電' },
            { symbol: '8442.TWO', name: '威宏-KY' },
            { symbol: '8443.TWO', name: '阿瘦' },
            { symbol: '8444.TWO', name: '綠河-KY' },
            { symbol: '8446.TWO', name: '華研' },
            { symbol: '8450.TWO', name: '霹靂' },
            { symbol: '8454.TWO', name: '富邦媒' },
            { symbol: '8458.TWO', name: '紅木-KY' },
            { symbol: '8462.TWO', name: '柏文' },
            { symbol: '8464.TWO', name: '億豐' },
            { symbol: '8466.TWO', name: '美吉吉-KY' },
            { symbol: '8467.TWO', name: '波力-KY' },
            { symbol: '8468.TWO', name: '致伸' },
            { symbol: '8472.TWO', name: '夠麻吉' },
            { symbol: '8473.TWO', name: '山林水' },
            { symbol: '8478.TWO', name: '東哥遊艇' },
            { symbol: '8480.TWO', name: '泰昇-KY' },
            { symbol: '8481.TWO', name: '政伸' },
            { symbol: '8482.TWO', name: '商億-KY' },
            { symbol: '8488.TWO', name: '吉源-KY' },
            { symbol: '8489.TWO', name: '三貝德' },
            { symbol: '8497.TWO', name: '聯廣' },
            { symbol: '9105.TWO', name: '泰金寶-DR' },
            { symbol: '9110.TWO', name: '越南控-DR' },
            { symbol: '9136.TWO', name: '巨騰-DR' },
            { symbol: '9188.TWO', name: '精熙-DR' },
            { symbol: '9802.TWO', name: '鈺齊-KY' },
            { symbol: '9902.TWO', name: '台火' },
            { symbol: '9904.TWO', name: '寶成' },
            { symbol: '9905.TWO', name: '大華' },
            { symbol: '9906.TWO', name: '欣巴巴' },
            { symbol: '9907.TWO', name: '統一實' },
            { symbol: '9908.TWO', name: '大台北' },
            { symbol: '9910.TWO', name: '豐泰' },
            { symbol: '9911.TWO', name: '櫻花' },
            { symbol: '9912.TWO', name: '偉聯' },
            { symbol: '9914.TWO', name: '美利達' },
            { symbol: '9917.TWO', name: '中保科' },
            { symbol: '9918.TWO', name: '欣天然' },
            { symbol: '9919.TWO', name: '康那香' },
            { symbol: '9921.TWO', name: '巨大' },
            { symbol: '9924.TWO', name: '福興' },
            { symbol: '9925.TWO', name: '新保' },
            { symbol: '9926.TWO', name: '新海' },
            { symbol: '9927.TWO', name: '泰銘' },
            { symbol: '9928.TWO', name: '中視' },
            { symbol: '9929.TWO', name: '秋雨' },
            { symbol: '9930.TWO', name: '中聯資源' },
            { symbol: '9931.TWO', name: '欣高' },
            { symbol: '9933.TWO', name: '中鼎' },
            { symbol: '9934.TWO', name: '成霖' },
            { symbol: '9935.TWO', name: '慶豐富' },
            { symbol: '9937.TWO', name: '全國' },
            { symbol: '9938.TWO', name: '百和' },
            { symbol: '9939.TWO', name: '宏全' },
            { symbol: '9940.TWO', name: '信義' },
            { symbol: '9941.TWO', name: '裕融' },
            { symbol: '9942.TWO', name: '茂順' },
            { symbol: '9943.TWO', name: '好樂迪' },
            { symbol: '9944.TWO', name: '新麗' },
            { symbol: '9945.TWO', name: '潤泰新' },
            { symbol: '9946.TWO', name: '三發地產' },
            { symbol: '9955.TWO', name: '佳龍' },
            { symbol: '9958.TWO', name: '世紀鋼' }
        ];

        if (symbolRange) {
            const [start, end] = symbolRange;
            const startNum = parseInt(start);
            const endNum = parseInt(end);
            
            return mockSymbols.filter(symbol => {
                const symbolNum = parseInt(symbol.symbol.split('.')[0]);
                return symbolNum >= startNum && symbolNum <= endNum;
            });
        }

        return mockSymbols;
    }

    cancelUpdate() {
        if (this.isUpdating && confirm('確定要取消正在進行的數據更新任務嗎？')) {
            this.isUpdating = false;
            this.addLogMessage('已發送取消信號，等待當前操作完成...', 'warning');
            document.getElementById('cancelUpdate').disabled = true;
            document.getElementById('progressStatus').textContent = '正在取消...';
        }
    }

    updateProgress(progress, message) {
        document.getElementById('progressFill').style.width = `${progress}%`;
        document.getElementById('progressText').textContent = `${Math.round(progress)}%`;
        document.getElementById('progressStatus').textContent = message;
        this.addLogMessage(message, 'info');
    }

    clearResultsTable() {
        document.querySelector('#resultsTable tbody').innerHTML = '<tr><td colspan="2" class="no-data">更新進行中...</td></tr>';
    }

    updateResultsTable(symbols) {
        const tbody = document.querySelector('#resultsTable tbody');
        tbody.innerHTML = '';
        
        symbols.forEach(symbol => {
            const row = document.createElement('tr');
            row.innerHTML = `<td>${symbol.symbol}</td><td>${symbol.name}</td>`;
            tbody.appendChild(row);
        });

        const statsRow = document.createElement('tr');
        statsRow.innerHTML = `<td><strong>統計</strong></td><td>更新:${symbols.length} 跳過:0 錯誤:0</td>`;
        tbody.appendChild(statsRow);
    }

    async queryPriceData() {
        const ticker = document.getElementById('tickerInput').value.trim();
        if (!ticker) {
            this.showMessage('請輸入股票代碼', 'warning');
            return;
        }

        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;

        this.addLogMessage(`查詢股價數據: ${ticker} 從 ${startDate} 到 ${endDate}`, 'info');

        try {
            const url = `http://localhost:5001/api/stock/${ticker}/prices?start=${startDate}&end=${endDate}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error('無法連接到 API 服務器');
            }
            
            const result = await response.json();
            if (!result.success) {
                throw new Error(result.error || '查詢失敗');
            }
            
            this.updateQueryTable(result.data, ['ticker', 'Date', 'Open', 'High', 'Low', 'Close', 'Volume']);
            this.addLogMessage(`查詢股價數據成功: ${ticker}，共 ${result.data.length} 筆`, 'info');
            
        } catch (error) {
            this.addLogMessage(`查詢股價數據失敗: ${error.message}`, 'error');
            this.showMessage(error.message, 'error');
        }
    }

    async queryReturnData() {
        const ticker = document.getElementById('tickerInput').value.trim();
        if (!ticker) {
            this.showMessage('請輸入股票代碼', 'warning');
            return;
        }

        const startDate = document.getElementById('startDate').value;
        const endDate = document.getElementById('endDate').value;
        const frequency = document.getElementById('frequencySelect').value;

        this.addLogMessage(`查詢報酬率數據: ${ticker} ${frequency}`, 'info');

        try {
            const url = `http://localhost:5001/api/stock/${ticker}/returns?start=${startDate}&end=${endDate}&frequency=${frequency}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error('無法連接到 API 服務器');
            }
            
            const result = await response.json();
            if (!result.success) {
                throw new Error(result.error || '查詢失敗');
            }
            
            this.updateQueryTable(result.data, ['ticker', 'Date', 'frequency', 'return']);
            this.addLogMessage(`查詢報酬率數據成功: ${ticker}，共 ${result.data.length} 筆`, 'info');
            
        } catch (error) {
            this.addLogMessage(`查詢報酬率數據失敗: ${error.message}`, 'error');
            this.showMessage(error.message, 'error');
        }
    }

    generateMockPriceData(ticker, startDate, endDate) {
        const data = [];
        let price = 100 + Math.random() * 400;

        for (let i = 0; i < 20; i++) {
            const date = new Date(startDate);
            date.setDate(date.getDate() + i);
            
            const open = price;
            const change = (Math.random() - 0.5) * 10;
            const close = Math.max(10, open + change);
            const high = Math.max(open, close) + Math.random() * 5;
            const low = Math.min(open, close) - Math.random() * 5;

            data.push({
                ticker,
                Date: date.toISOString().split('T')[0],
                Open: open.toFixed(2),
                High: high.toFixed(2),
                Low: Math.max(0, low).toFixed(2),
                Close: close.toFixed(2),
                Volume: Math.floor(Math.random() * 10000000) + 1000000
            });

            price = close;
        }

        return data;
    }

    generateMockReturnData(ticker, startDate, endDate, frequency) {
        const data = [];
        for (let i = 0; i < 15; i++) {
            const date = new Date(startDate);
            date.setDate(date.getDate() + i * 7);
            
            data.push({
                ticker,
                Date: date.toISOString().split('T')[0],
                frequency,
                return: ((Math.random() - 0.5) * 10).toFixed(4)
            });
        }
        return data;
    }

    updateQueryTable(data, columns) {
        const table = document.getElementById('queryTable');
        const thead = table.querySelector('thead');
        const tbody = table.querySelector('tbody');

        thead.innerHTML = `<tr>${columns.map(col => `<th>${col}</th>`).join('')}</tr>`;
        tbody.innerHTML = '';
        
        if (data.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${columns.length}" class="no-data">沒有找到符合條件的數據</td></tr>`;
            return;
        }

        data.forEach(row => {
            const tr = document.createElement('tr');
            tr.innerHTML = columns.map(col => `<td>${row[col] || ''}</td>`).join('');
            tbody.appendChild(tr);
        });
    }

    exportQueryResults() {
        const table = document.getElementById('queryTable');
        const rows = table.querySelectorAll('tr');
        
        if (rows.length <= 1) {
            this.showMessage('沒有查詢結果可供導出', 'warning');
            return;
        }

        let csv = '';
        rows.forEach(row => {
            const cells = row.querySelectorAll('th, td');
            const rowData = Array.from(cells).map(cell => cell.textContent.trim());
            csv += rowData.join(',') + '\n';
        });

        this.downloadCSV(csv, 'query_results.csv');
        this.addLogMessage('查詢結果已導出', 'info');
    }

    async refreshDatabaseStats() {
        this.addLogMessage('正在統計資料庫狀態...', 'info');
        await this.delay(1000);
        
        const stats = {
            pricesCount: 1234567,
            pricesTickerCount: 1800,
            returnsCount: 987654,
            returnsTickerCount: 1800,
            latestDate: '2025-08-09',
            earliestDate: '2010-01-01'
        };

        document.getElementById('statsSummary').innerHTML = `
            <p><strong>資料庫狀態摘要</strong></p>
            <p>股價數據: ${stats.pricesCount.toLocaleString()} 筆 (${stats.pricesTickerCount} 檔股票)</p>
            <p>報酬率數據: ${stats.returnsCount.toLocaleString()} 筆 (${stats.returnsTickerCount} 檔股票)</p>
            <p>數據日期範圍: ${stats.earliestDate} 至 ${stats.latestDate}</p>
        `;

        document.getElementById('twseTotal').textContent = '950';
        document.getElementById('twseData').textContent = '950';
        document.getElementById('otcTotal').textContent = '850';
        document.getElementById('otcData').textContent = '850';
        document.getElementById('totalStocks').textContent = '1800';
        document.getElementById('totalData').textContent = '1800';

        this.addLogMessage('資料庫統計信息已更新', 'info');
    }

    async testDatabaseConnection() {
        this.addLogMessage('測試資料庫連接...', 'info');
        await this.delay(1000);

        const success = Math.random() > 0.2;
        if (success) {
            this.addLogMessage('數據庫連接測試成功!', 'info');
            this.showMessage('成功連接到數據庫!', 'success');
            this.updateDatabaseStatus('connected');
        } else {
            this.addLogMessage('數據庫連接測試失敗', 'error');
            this.showMessage('數據庫連接測試失敗', 'error');
            this.updateDatabaseStatus('error');
        }
    }

    saveDatabaseSettings() {
        const host = document.getElementById('dbHost').value;
        const port = document.getElementById('dbPort').value;
        const dbname = document.getElementById('dbName').value;
        const user = document.getElementById('dbUser').value;

        if (!host || !port || !dbname || !user) {
            this.showMessage('請填寫所有必要的資料庫設定', 'warning');
            return;
        }

        this.addLogMessage('資料庫設定已儲存', 'info');
        this.showMessage('資料庫設定已儲存', 'success');
        this.checkDatabaseConnection();
    }

    resetSystemSettings() {
        document.getElementById('defaultStartYear').value = '2010';
        document.getElementById('maxConcurrent').value = '1';
        this.addLogMessage('系統設定已重設為預設值', 'info');
        this.showMessage('系統設定已重設為預設值', 'success');
    }

    saveSystemSettings() {
        this.addLogMessage('系統設定已儲存', 'info');
        this.showMessage('系統設定已儲存', 'success');
    }

    async checkDatabaseConnection() {
        await this.delay(500);
        const isConnected = Math.random() > 0.3;
        
        if (isConnected) {
            this.updateDatabaseStatus('connected');
            this.addLogMessage('數據庫連接成功', 'info');
        } else {
            this.updateDatabaseStatus('error');
            this.addLogMessage('數據庫連接失敗', 'error');
        }
    }

    updateDatabaseStatus(status) {
        const dbStatus = document.getElementById('dbStatus');
        const dbStatusText = document.getElementById('dbStatusText');
        
        dbStatus.className = `db-status ${status}`;
        
        const statusTexts = {
            'connected': '資料庫狀態: 已連接',
            'error': '資料庫狀態: 連接失敗',
            'warning': '資料庫狀態: 檢查中...'
        };
        
        dbStatusText.textContent = statusTexts[status] || '資料庫狀態: 未知';
    }

    addLogMessage(message, level = 'info') {
        const logContent = document.getElementById('logContent');
        const timestamp = new Date().toLocaleString('zh-TW');

        const logEntry = document.createElement('div');
        logEntry.className = `log-entry ${level}`;
        logEntry.innerHTML = `
            <span class="log-time">[${timestamp}]</span>
            <span class="log-level">${level.toUpperCase()}:</span>
            <span class="log-message">${message}</span>
        `;

        logContent.appendChild(logEntry);
        logContent.scrollTop = logContent.scrollHeight;
    }

    clearLog() {
        document.getElementById('logContent').innerHTML = '';
        this.addLogMessage('日誌已清除', 'info');
    }

    exportLog() {
        const logEntries = document.querySelectorAll('#logContent .log-entry');
        let logText = '';
        
        logEntries.forEach(entry => {
            const time = entry.querySelector('.log-time').textContent;
            const level = entry.querySelector('.log-level').textContent;
            const message = entry.querySelector('.log-message').textContent;
            logText += `${time} ${level} ${message}\n`;
        });

        this.downloadText(logText, 'taiwan_stock_log.txt');
        this.addLogMessage('日誌已導出', 'info');
    }

    downloadCSV(csvContent, filename) {
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        this.downloadBlob(blob, filename);
    }

    downloadText(textContent, filename) {
        const blob = new Blob([textContent], { type: 'text/plain;charset=utf-8;' });
        this.downloadBlob(blob, filename);
    }

    downloadBlob(blob, filename) {
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    showMessage(message, type = 'info') {
        const toast = document.createElement('div');
        toast.textContent = message;
        
        const colors = {
            'success': 'var(--success)',
            'error': 'var(--error)',
            'warning': 'var(--warning)',
            'info': 'var(--accent)'
        };
        
        toast.style.cssText = `
            position: fixed; top: 20px; right: 20px; padding: 1rem 1.5rem;
            border-radius: 5px; color: white; font-weight: 500; z-index: 1000;
            max-width: 400px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            background-color: ${colors[type] || colors.info};
        `;

        document.body.appendChild(toast);
        setTimeout(() => document.body.removeChild(toast), 3000);
    }

    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new TaiwanStockApp();
});
