# ETF Pipeline

ETF 多因子分析 + LLM 决策 + B站视频观点采集，统一流水线工具。

## 功能

- **ETF 分析**：多因子技术分析（MA/RSI/MACD/布林带） + LLM 智能决策（买入/卖出/观望）
- **视频解析**：B站视频字幕提取 → AI 摘要 → 事实核验
- **定期跟踪**：UP 主批量跟踪 → 自动转写 → 批次总结
- **统一配置**：共享 LLM Key 和模型设置
- **流水线时间轴**：可视化展示当前执行步骤

## 安装

```powershell
git clone <repo-url> etf-pipeline
cd etf-pipeline
setup.bat
```

## 使用

```powershell
# 开发模式
.venv\Scripts\python.exe gui.py

# 构建 EXE
.venv\Scripts\python.exe -m PyInstaller gui.spec
```

## 依赖

- Python 3.10+
- bili2text（视频转写引擎，需单独安装）
- akshare / baostock（行情数据）

## 数据管道

```
视频解析 → E:\video2txt\{mmdd}\批次总结.json → ETF 分析（板块情绪注入）
```

## License

MIT
