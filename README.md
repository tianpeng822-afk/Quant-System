# 启动项目

source .venv/bin/activate \&\& streamlit run web/0\_首页.py

您可以在终端中额外运行 source .venv/bin/activate \&\& python main.py

# MyFund-Quant-System

> 个人基金量化管理系统 · Phase 1 (MVP)  
> Python 3.10+ · SQLite · SQLAlchemy · AkShare · APScheduler

\---

## 项目目录结构

```
MyFund-Quant-System/
├── main.py                     # 程序主入口（调度器 / --now 立即执行）
├── requirements.txt            # 依赖清单
├── .env.example                # 环境变量示例（复制为 .env 并填写）
├── .gitignore
│
├── app/
│   ├── \_\_init\_\_.py
│   ├── config.py               # 全局配置（读取 .env）
│   ├── database.py             # 数据库引擎 \& Session 工厂 \& init\_db()
│   ├── logger.py               # Loguru 日志配置
│   ├── pipeline.py             # ETL 主流水线（每日 22:30 触发）
│   │
│   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── \_\_init\_\_.py         # 统一导出所有 Model
│   │   ├── base.py             # DeclarativeBase
│   │   ├── account.py          # 账户表（多账户隔离）
│   │   ├── holding.py          # 持仓表（市值/盈亏/回撤）
│   │   ├── transaction.py      # 流水表（申购/赎回/分红）
│   │   ├── nav\_history.py      # 净值历史表（AkShare 时序数据）
│   │   └── daily\_snapshot.py   # 每日快照表（日报存档）
│   │
│   ├── scraper/                # 数据抓取模块
│   │   ├── \_\_init\_\_.py
│   │   └── nav\_fetcher.py      # AkShare 净值抓取 \& Holdings 刷新
│   │
│   ├── engine/                 # 策略引擎（Phase 2 实现）
│   │   └── \_\_init\_\_.py
│   │
│   └── notifier/               # 消息推送模块
│       ├── \_\_init\_\_.py
│       └── pushplus.py         # PushPlus 微信推送
│
├── scripts/
│   ├── init\_db.py              # 初始化数据库 \& seed 演示账户
│   └── add\_transaction.py      # 手动录入申购流水
│
├── data/
│   └── myfund.db               # SQLite 数据库文件（.gitignore 忽略）
│
└── logs/
    └── myfund\_YYYY-MM-DD.log   # 按天滚动日志（.gitignore 忽略）
```

\---

## 快速开始

### 1\. 安装依赖

```bash
python -m venv .venv
# Windows:
.venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2\. 配置环境变量

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
```

编辑 `.env`，填入 `DEEPSEEK\_API\_KEY`、`PUSHPLUS\_TOKEN` 等。

### 3\. 初始化数据库

```bash
python scripts/init\_db.py
```

### 4\. 录入历史流水（示例）

```bash
# 编辑 scripts/add\_transaction.py 中的示例数据后运行
python scripts/add\_transaction.py
```

### 5\. 立即触发一次 ETL（调试）

```bash
python main.py --now
```

### 6\. 启动定时调度（守护进程）

```bash
python main.py
# 每天 22:30 (Asia/Shanghai) 自动运行 ETL 并推送微信消息
```

\---

## 数据库 ER 图（核心表关系）

```
accounts (账户)
    │ 1
    │ ─── N ──→  holdings (持仓)   ←── N ─── nav\_history (净值历史)
    │ 1                │ 1
    │                  │ 1
    └─── N ──→  transactions (流水)

daily\_snapshots (每日快照，独立存在)
```

\---

## Phase 路线图

|Phase|状态|内容|
|-|-|-|
|Phase 1|✅ MVP|记账、净值同步、盈亏计算、微信日报推送|
|Phase 2|🔜 规划中|止盈止损规则引擎、回撤预警、再平衡提示|
|Phase 3|🔜 规划中|DeepSeek AI 选基、AkShare 全市场优选池|



