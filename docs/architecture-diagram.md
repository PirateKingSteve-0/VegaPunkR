# VegaPunkR Architecture - Visual Diagrams

## 1. High-Level System Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        UI[Angular 20 UI<br/>Dashboard, Strategies,<br/>Positions, Trades,<br/>Performance, Admin]
    end

    subgraph "API Layer - FastAPI"
        AUTH[Auth Router<br/>Login/Register/JWT]
        STRAT[Strategies Router<br/>CRUD + Toggle]
        POS[Positions Router<br/>View + Close]
        TRADE[Trades Router<br/>History]
        PERF[Performance Router<br/>Metrics + Equity]
        ADMIN[Admin Router<br/>User Management]
        SYS[System Router<br/>Environment Switch]
        EXEC[Execution Router<br/>Start/Stop]
    end

    subgraph "Trading Engine - Event Driven"
        SDW[StreamDrivenWorker<br/>Persistent Tasks<br/>Per Strategy]
        TSM[TradierStreamManager<br/>Single WebSocket<br/>wss://ws.tradier.com]
        SR[StreamRouter<br/>Multiplexer<br/>Ref-Counted Queues]

        subgraph "Execution Pipeline"
            SE[StrategyExecutor<br/>Orchestrator]
            RM[RiskManager<br/>Position Sizing<br/>Pre-Trade Validation]
            SG[SignalGenerator<br/>EMA, VWAP, Volume<br/>Entry/Exit Logic]
            OM[OrderManager<br/>Preview → Place<br/>Poll → DB Write]
        end
    end

    subgraph "Broker Integrations"
        TCM[TradingClientManager<br/>Paper OR Live Router<br/>BOTH return TradierClient]
        TC[TradierClient<br/>REST + WebSocket<br/>THE ONLY LIVE BROKER]
        ASM[TradierAccountStream<br/>order events - pushed fills]
        SC[SchwabClient<br/>NOT a trading path -<br/>TCM never returns it.<br/>OAuth router still mounted]
        AC[AlpacaClient<br/>DEAD - removed from<br/>the import graph 2026-07-13]
    end

    subgraph "Data Layer"
        DB[(PostgreSQL<br/>TimescaleDB<br/><br/>3 Databases:<br/>dev:5435<br/>test:5433<br/>prod:5434)]
    end

    subgraph "External Services"
        TRADIER[Tradier API<br/>Sandbox + Live]
        SCHWAB[Schwab API<br/>OAuth]
        DISCORD[Discord Webhooks<br/>Notifications]
        EMAIL[Resend Email API<br/>Reports]
    end

    subgraph "Background Services"
        EMAILSCHED[Email Report Scheduler<br/>APScheduler<br/>Daily/Weekly/Monthly]
        RECON[Reconciliation Service<br/>60s Forced Sync]
    end

    %% Client connections
    UI -->|REST API| AUTH
    UI -->|REST API| STRAT
    UI -->|REST API| POS
    UI -->|REST API| TRADE
    UI -->|REST API| PERF
    UI -->|REST API| ADMIN
    UI -->|REST API| SYS
    UI -->|REST API| EXEC

    %% Router to Engine
    STRAT -.->|start strategy| SDW
    EXEC -.->|start stop| SDW

    %% Engine flow
    TSM -->|Events| SR
    SR -->|Per-Strategy Queue| SDW
    SDW -->|Entry Exit Tick| SE
    SE -->|1. Check Risk| RM
    SE -->|2. Check Signal| SG
    SE -->|3. Execute Order| OM
    OM -->|Route Order| TCM

    %% Broker routing — paper vs live is Tradier SANDBOX vs Tradier LIVE.
    %% TradingClientManager is not a broker abstraction: both branches return TradierClient.
    TCM -->|Paper Mode - sandbox| TC
    TCM -->|Live Mode - live| TC
    TCM -.->|dead branch| SC
    TCM -.->|dead branch| AC

    %% External calls
    TC <-->|REST| TRADIER
    OM -->|await fill| ASM
    ASM <-->|WebSocket - account events| TRADIER
    TSM <-->|WebSocket - market events| TRADIER
    SC <-.->|REST - OAuth router only,<br/>no order placement| SCHWAB

    %% Database
    AUTH ---|Read Write Users| DB
    STRAT ---|Read Write Strategies| DB
    POS ---|Read Write Positions| DB
    TRADE ---|Read Write Trades| DB
    PERF ---|Read Performance| DB
    SDW ---|Read Write Positions| DB
    OM ---|Write Trades Positions| DB
    EMAILSCHED ---|Read Trades Performance| DB

    %% Notifications
    OM -.->|Position Events| DISCORD
    EMAILSCHED -.->|Scheduled Reports| EMAIL

    %% Background
    SDW -.->|60s Interval| RECON

    classDef engine fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    classDef broker fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef db fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef external fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px

    class SDW,TSM,SR,SE,RM,SG,OM engine
    class TCM,TC,SC,AC broker
    class DB db
    class TRADIER,SCHWAB,DISCORD,EMAIL external
```

## 2. Database Schema & Relationships

```mermaid
erDiagram
    USERS ||--o{ STRATEGIES : owns
    USERS ||--o{ POSITIONS : has
    USERS ||--o{ TRADES : executes
    USERS ||--o{ RISK_EVENTS : triggers
    STRATEGIES ||--o{ POSITIONS : creates
    STRATEGIES ||--o{ PERFORMANCE_METRICS : tracks
    POSITIONS ||--o{ TRADES : generates
    STRATEGIES ||--o{ SYSTEM_EVENTS : logs

    USERS {
        uuid id PK
        string email UK
        string role "user|admin|viewer|auditor|strategy_author"
        decimal account_size_usd
        decimal max_trade_percentage
        decimal daily_loss_limit_pct
        enum selected_environment "dev|test|prod"
        enum selected_trading_mode "paper|live"
        boolean trading_window_enabled
        time trading_window_start
        time trading_window_end
        jsonb notification_preferences
        timestamp created_at
    }

    STRATEGIES {
        uuid id PK
        uuid user_id FK
        string name
        string strategy_type
        jsonb params_json "EMA, VWAP, TP, SL, etc"
        array instruments "symbols[]"
        string timeframe
        int max_positions
        decimal stop_loss_percentage
        decimal take_profit_percentage
        boolean is_active
        boolean is_paper_trading
        timestamp created_at
    }

    POSITIONS {
        uuid id PK
        uuid user_id FK
        uuid strategy_id FK
        string symbol "SPY"
        string option_symbol "SPY260424C00370000"
        int qty
        decimal avg_entry_price
        decimal current_price
        decimal unrealized_pnl
        decimal peak_price
        decimal trough_price
        timestamp opened_at
        timestamp closed_at
    }

    TRADES {
        uuid id PK
        uuid user_id FK
        uuid position_id FK
        string symbol
        string side "buy|sell"
        string order_type "market|limit"
        int qty
        int filled_qty
        decimal price
        decimal exit_price
        decimal commission
        decimal fees
        decimal pnl
        timestamp timestamp "PARTITION KEY"
        string status "filled|rejected|canceled"
        jsonb notes
    }

    PERFORMANCE_METRICS {
        uuid id PK
        uuid strategy_id FK
        string period "daily|weekly|monthly|all_time"
        int total_trades
        int winning_trades
        decimal total_pnl
        decimal win_rate
        decimal sharpe_ratio
        decimal max_drawdown
        timestamp period_start
        timestamp period_end
    }

    SYSTEM_EVENTS {
        uuid id PK
        uuid user_id FK
        uuid strategy_id FK
        string event_type "order_placed|position_opened|position_closed|risk_alert"
        string severity "info|warning|error"
        string title
        string detail
        string symbol
        jsonb event_data
        timestamp timestamp
    }

    RISK_EVENTS {
        uuid id PK
        uuid user_id FK
        uuid strategy_id FK
        string event_type "daily_loss|max_drawdown|position_limit"
        string severity "warning|critical"
        string action_taken "halt_entries|close_position|alert_only"
        jsonb details
        timestamp timestamp
    }
```

## 3. Trading Execution Flow (Entry Signal → Filled Order)

```mermaid
sequenceDiagram
    participant WS as Tradier WebSocket
    participant TSM as TradierStreamManager
    participant SR as StreamRouter
    participant SDW as StreamDrivenWorker
    participant SE as StrategyExecutor
    participant SG as SignalGenerator
    participant RM as RiskManager
    participant OM as OrderManager
    participant TCM as TradingClientManager
    participant TC as TradierClient
    participant DB as Database
    participant Discord as Discord Webhook

    %% Stream event arrives
    WS->>TSM: trade event: SPY @ $502.45
    TSM->>SR: route(event)
    SR->>SDW: queue.put(event)

    %% Accumulate state
    SDW->>SDW: market_state.apply(event)<br/>update underlying_price

    %% Check position state
    SDW->>SDW: position.qty == 0?
    Note over SDW: Yes → Entry logic

    %% Execute entry tick
    SDW->>SE: execute_strategy_tick(strategy, market_state)

    %% Market hours check
    SE->>SE: is_market_hours()?
    Note over SE: ✓ Market open

    %% Trading window check
    SE->>SE: is_in_entry_window()?
    Note over SE: ✓ After 9:45 AM

    %% Re-entry cooldown
    SE->>SE: cooldown_expired()?
    Note over SE: ✓ 30s elapsed

    %% Check entry signal
    SE->>SG: check_entry_signal(market_state, params)
    SG->>SG: price > 9EMA?<br/>price > VWAP?<br/>volume_spike?
    SG-->>SE: SIGNAL: BUY

    %% Risk validation
    SE->>RM: calculate_position_size(account, strategy, price)
    RM-->>SE: qty = 1 contract

    SE->>RM: validate_pre_trade(user, strategy, qty)
    RM->>RM: Check account daily loss cap
    RM->>RM: Check strategy daily loss limit
    RM->>RM: Check max drawdown
    RM->>RM: Check position limits
    RM->>RM: Check trading mode consistency
    RM-->>SE: ✓ All checks passed

    %% Execute order
    SE->>OM: execute_signal(strategy, signal, qty)

    %% Entry lockout
    OM->>DB: SELECT FOR UPDATE position<br/>WHERE strategy_id = X
    Note over OM: Row-level lock acquired

    %% Order rate limit
    OM->>OM: check_rate_limit(user, symbol)
    Note over OM: ✓ Last order > 5s ago

    %% Preview order
    OM->>TCM: preview_order(symbol, qty, side)
    TCM->>TC: POST /v1/accounts/123/orders/preview
    TC-->>TCM: {commission: $0.35, buying_power_ok: true}
    TCM-->>OM: preview_result

    %% Cash reservation
    OM->>OM: reserve_cash(user_id, amount, 60s TTL)
    Note over OM: In-memory ledger hold

    %% Place order
    OM->>TCM: place_order(SPY260424C00370000, 1, buy, market)
    TCM->>TCM: route_by_mode(user.trading_mode)
    Note over TCM: Mode = paper → Sandbox
    TCM->>TC: POST /v1/accounts/123/orders
    TC-->>TCM: {id: "789", status: "ok"}
    TCM-->>OM: order_id = "789"

    %% Poll for fill
    loop Every 1.5s (max 30s)
        OM->>TC: GET /v1/accounts/123/orders/789
        TC-->>OM: {status: "pending"}
    end

    OM->>TC: GET /v1/accounts/123/orders/789
    TC-->>OM: {status: "filled", avg_fill_price: $1.23}

    %% Update database
    OM->>DB: INSERT INTO trades<br/>(symbol, side, qty, price, status)
    OM->>DB: INSERT INTO positions<br/>(symbol, option_symbol, qty, avg_entry_price)
    OM->>DB: INSERT INTO system_events<br/>(event_type: position_opened)

    %% Release cash
    OM->>OM: release_cash_reservation(user_id)

    %% Notifications
    OM->>Discord: POST webhook<br/>Position Opened: SPY Call @ $1.23

    OM-->>SE: Order filled successfully
    SE-->>SDW: Entry complete

    Note over SDW: Position now OPEN<br/>Switch to exit logic
```

## 4. Exit Signal Flow (Open Position → Close)

```mermaid
sequenceDiagram
    participant WS as Tradier WebSocket
    participant SDW as StreamDrivenWorker
    participant SE as StrategyExecutor
    participant SG as SignalGenerator
    participant OM as OrderManager
    participant TC as TradierClient
    participant DB as Database
    participant Discord as Discord

    %% Stream event arrives
    WS->>SDW: trade event: SPY @ $503.10
    SDW->>SDW: market_state.apply(event)

    %% Check position state
    SDW->>SDW: position.qty > 0?
    Note over SDW: Yes → Exit logic

    %% Execute exit tick
    SDW->>SE: execute_exit_tick(strategy, position, market_state)

    %% Get current P&L
    SE->>SE: calculate_unrealized_pnl(position, current_price)
    Note over SE: Entry: $1.23<br/>Current: $1.35<br/>P&L: +9.76%

    %% Check exit signals
    SE->>SG: check_exit_signal(position, market_state, params)

    %% Take profit check
    SG->>SG: pnl_pct >= take_profit_pct?
    Note over SG: 9.76% >= 10%? NO

    %% Stop loss check
    SG->>SG: pnl_pct <= -stop_loss_pct?
    Note over SG: 9.76% <= -5%? NO

    %% Trailing stop check
    SG->>SG: trailing_stop_triggered(peak_price, current_price)?
    Note over SG: Peak: $1.40, Trail: 3%<br/>$1.35 < ($1.40 * 0.97)? YES

    SG-->>SE: SIGNAL: SELL (trailing_stop)

    %% Execute sell order
    SE->>OM: execute_signal(strategy, sell_signal, position.qty)

    %% Place order
    OM->>TC: POST /v1/accounts/123/orders<br/>{symbol: SPY260424C00370000, qty: 1, side: sell}
    TC-->>OM: {id: "790", status: "ok"}

    %% Poll for fill
    loop Every 1.5s
        OM->>TC: GET /v1/accounts/123/orders/790
        TC-->>OM: {status: "pending"}
    end

    OM->>TC: GET /v1/accounts/123/orders/790
    TC-->>OM: {status: "filled", avg_fill_price: $1.35}

    %% Update database
    OM->>DB: INSERT INTO trades<br/>(side: sell, price: $1.35, pnl: $12.00)
    OM->>DB: UPDATE positions SET<br/>qty = 0, closed_at = NOW()
    OM->>DB: INSERT INTO system_events<br/>(event_type: position_closed)
    OM->>DB: UPDATE performance_metrics

    %% Notifications
    OM->>Discord: POST webhook<br/>Position Closed: SPY Call<br/>Entry: $1.23, Exit: $1.35<br/>P&L: +$12.00 (+9.76%)

    OM-->>SE: Exit complete
    SE-->>SDW: Position closed

    %% Re-entry cooldown
    SDW->>SDW: set_cooldown_until(now + 30s)
    Note over SDW: Prevent immediate re-entry
```

## 5. Component Dependency Graph

```mermaid
graph LR
    subgraph "Core Models"
        M[models.py<br/>User, Strategy,<br/>Position, Trade,<br/>Performance]
        DB[database.py<br/>Multi-Env<br/>Connection Pool]
        CFG[config.py<br/>Settings<br/>API Keys]
        SCH[schemas.py<br/>Pydantic<br/>Request/Response]
    end

    subgraph "Authentication"
        AUTH[auth.py<br/>JWT<br/>Role Guards]
    end

    subgraph "Routers"
        R1[strategies.py]
        R2[positions.py]
        R3[trades.py]
        R4[execution.py]
        R5[admin.py]
    end

    subgraph "Engine Core"
        SDW[stream_driven_worker.py<br/>Singleton Task Manager<br/>arm - drift check - reselect]
        TSM[tradier_stream_manager.py<br/>MARKET WebSocket]
        TAS[tradier_account_stream.py<br/>ACCOUNT WebSocket<br/>pushed order events]
        SR[stream_router.py<br/>Multiplexer]
        SE[strategy_executor.py<br/>Orchestrator]
    end

    subgraph "Execution Modules"
        RM[risk_manager.py<br/>Position Sizing<br/>Pre-Trade Checks]
        SG[signal_generator.py<br/>Indicators<br/>Entry/Exit Logic]
        OM[order_manager.py<br/>Order Lifecycle<br/>Cash Ledger]
        TCM[trading_client_manager.py<br/>Paper/Live Router]
    end

    subgraph "Broker Clients"
        TC[tradier_integration/<br/>client.py<br/>router.py]
        SC[schwab_integration/<br/>router MOUNTED in app.py<br/>but NOT a trading path]
        AC[alpaca/<br/>DEAD - vendored SDK,<br/>0 modules loaded at runtime]
    end

    subgraph "Services"
        MKT[services/market_data.py<br/>Quotes, Chains]
        RPT[notifications/reports.py<br/>Email Reports]
        SCHED[services/email_report_scheduler.py<br/>APScheduler]
        RECON[services/reconciliation.py<br/>Broker Sync]
    end

    %% Dependencies
    R1 --> AUTH
    R2 --> AUTH
    R3 --> AUTH
    R4 --> AUTH
    R5 --> AUTH

    R1 --> M
    R2 --> M
    R3 --> M
    R4 --> SDW
    R5 --> M

    M --> DB
    AUTH --> DB
    AUTH --> CFG

    SDW --> TSM
    SDW --> SR
    SDW --> SE
    SDW --> M
    SDW --> OM

    TSM --> TC
    TAS --> TC

    SE --> RM
    SE --> SG
    SE --> OM

    OM --> TCM
    OM --> M
    OM --> RPT
    OM --> TAS

    TCM --> TC
    TCM -.-> SC
    TCM -.-> AC

    TC --> CFG
    SC --> CFG
    AC --> CFG

    SCHED --> RPT
    SCHED --> M

    RECON --> TCM
    RECON --> M

    classDef core fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    classDef engine fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef broker fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px

    class M,DB,CFG,SCH core
    class SDW,TSM,SR,SE,RM,SG,OM,TCM engine
    class TC,SC,AC broker
```

## 6. Multi-Environment Database Routing

```mermaid
graph TB
    subgraph "API Process"
        REQ[Incoming Request<br/>JWT Token]
        MW[JWT Middleware<br/>Decode 'env' claim]
        ROUTER[Database Router<br/>database.py]
    end

    subgraph "Engine Process"
        WORKER[StreamDrivenWorker<br/>Background Task]
        APPENV[APP_ENV<br/>Environment Variable]
    end

    subgraph "Docker PostgreSQL Instances"
        DEV[(dev Database<br/>Port 5435<br/>vegapunk_dev)]
        TEST[(test Database<br/>Port 5433<br/>vegapunk_test)]
        PROD[(prod Database<br/>Port 5434<br/>vegapunk_prod)]
    end

    %% API routing
    REQ -->|env dev| MW
    MW --> ROUTER
    ROUTER -->|select dev engine| DEV

    REQ -->|env test| MW
    MW --> ROUTER
    ROUTER -->|select test engine| TEST

    REQ -->|env prod| MW
    MW --> ROUTER
    ROUTER -->|select prod engine| PROD

    %% Engine routing
    APPENV -->|APP_ENV prod| WORKER
    WORKER -->|uses prod engine| PROD

    Note1[User in UI:<br/>Switches env dropdown<br/>→ JWT re-issued<br/>→ API auto-routes]
    Note2[Background Engine:<br/>Pinned to APP_ENV<br/>Must run dedicated<br/>process for each env]

    style Note1 fill:#e8f5e9,stroke:#2e7d32
    style Note2 fill:#fff3e0,stroke:#e65100
```

## 7. Order Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> Idle: Strategy Active

    Idle --> SignalCheck: Stream Event<br/>(trade tick)

    SignalCheck --> Idle: No Signal
    SignalCheck --> RiskValidation: Entry Signal<br/>Detected

    RiskValidation --> Idle: Risk Check<br/>Failed
    RiskValidation --> UnconfirmedGate: Risk Check<br/>Passed

    UnconfirmedGate --> Idle: BUY blocked —<br/>an earlier order is<br/>unconfirmed at broker
    UnconfirmedGate --> EntryLockout: No unconfirmed<br/>orders (SELLS always pass)

    EntryLockout --> Idle: Position Already<br/>Exists (race)
    EntryLockout --> RateLimit: Lockout<br/>Acquired

    RateLimit --> Idle: Last Order<br/>< 5s ago
    RateLimit --> Preview: Rate Limit<br/>Passed

    Preview --> Idle: Buying Power<br/>Insufficient
    Preview --> CashReserve: Preview<br/>Successful

    CashReserve --> PlaceOrder: Cash<br/>Reserved

    PlaceOrder --> PollStatus: Order ID<br/>Returned
    PlaceOrder --> ReleaseCash: Order<br/>Rejected

    PollStatus --> PollStatus: Status pending or open<br/>(sleeps on account stream,<br/>wakes early on push)
    PollStatus --> Filled: Status<br/>filled
    PollStatus --> Unconfirmed: 30s Elapsed —<br/>broker never answered

    Filled --> UpdateDB: Write Trade<br/>+ Position

    Unconfirmed --> Idle: Record order id.<br/>BLOCK further BUYS.<br/>Local state UNTOUCHED —<br/>the order may still fill!

    Unconfirmed --> Resolve: Reconcile tick (60s)<br/>re-polls the order
    Resolve --> Backfill: Broker says FILLED
    Resolve --> Idle: rejected canceled expired<br/>→ unblock, nothing taken
    Backfill --> Idle: Write Trade at the broker's<br/>real avg_fill_price → unblock

    UpdateDB --> Notify: DB<br/>Committed
    Notify --> OpenPosition: Discord<br/>+ Email

    ReleaseCash --> Idle: Cash<br/>Available

    OpenPosition --> ExitSignalCheck: Stream Event<br/>(position open)

    ExitSignalCheck --> OpenPosition: No Exit<br/>Signal
    ExitSignalCheck --> PlaceExitOrder: Exit Signal<br/>TP SL Trail

    PlaceExitOrder --> PollExitStatus: Order ID<br/>Returned

    PollExitStatus --> PollExitStatus: Status<br/>pending
    PollExitStatus --> ExitFilled: Status<br/>filled
    PollExitStatus --> ExitTimeout: 30s<br/>Elapsed

    ExitFilled --> UpdateExitDB: Write Trade<br/>Close Position
    ExitTimeout --> OpenPosition: Retry

    UpdateExitDB --> NotifyExit: Calculate<br/>P&L
    NotifyExit --> Cooldown: Discord<br/>+ Email

    Cooldown --> Idle: 30s<br/>Elapsed

    note right of RiskValidation
        Checks:
        - Account daily loss cap
        - Strategy daily loss limit
        - Max drawdown
        - Position limits
        - Trading mode consistency
    end note

    note right of Preview
        Tradier /preview:
        - Validate contract
        - Check buying power
        - Get commission/fees
    end note

    note right of Unconfirmed
        "Unconfirmed" is NOT "didn't happen".
        We do NOT cancel and do NOT assume failure —
        the broker may still fill it.

        2026-07-13: two orders timed out at 30s and
        FILLED anyway. The engine wrote no Position,
        so it believed it was flat while holding 6
        TSLA contracts: no stop, no take-profit, and
        free to stack a second entry on top.

        Hence: block further BUYS (never SELLS — an
        exit must always run), and re-poll on the
        reconcile tick to backfill the Trade row.
    end note

    note right of ExitSignalCheck
        Exit Triggers:
        - Take profit %
        - Stop loss %
        - Trailing stop
        - Max hold time
        - Trading window end
        - Market close - N min
    end note
```

## 8. WebSocket Stream Architecture

**Two independent streams run concurrently.** Tradier's "one session at a time" limit is
stated per stream-*type* — market and account each have their own session endpoint and
socket — so both coexist. Verified against sandbox 2026-07-13.

- **Market stream** (`tradier_stream_manager.py`) — price/quote ticks. Always LIVE endpoint;
  sandbox has no market-data WS host.
- **Account stream** (`tradier_account_stream.py`) — order lifecycle events. Uses the
  *trading* env, so paper mode connects to `sandbox-ws.tradier.com`. Exists so fills are
  **pushed** rather than polled: on 2026-07-13 two orders filled while the engine's 30s
  `get_order` poll expired, leaving it holding 6 contracts it had no record of.

The account stream is an **accelerator, not a replacement** — REST polling remains the
fallback, so if it drops the engine behaves exactly as it did before.

```mermaid
graph TB
    subgraph "Tradier WebSockets (two sessions, one per type)"
        WS[wss://ws.tradier.com<br/>/v1/markets/events<br/>MARKET DATA - always live]
        WSA[wss://sandbox-ws OR ws.tradier.com<br/>/v1/accounts/events<br/>ORDER EVENTS - follows trading env]
    end

    subgraph "TradierAccountStreamManager (Singleton)"
        ASM[Account Stream Manager<br/>events: order]
        ALATEST[latest event per order_id]
        AWAIT[wait_for_terminal<br/>wakes the fill poll instantly]
    end

    subgraph "OrderManager"
        OM[_await_terminal_order<br/>REST poll 1.5s / 30s deadline<br/>sleeps ON the stream]
    end

    WSA -->|order pending open filled| ASM
    ASM --> ALATEST
    ALATEST --> AWAIT
    AWAIT -.->|terminal - wake early| OM
    OM -.->|no stream? fall back to REST| OM

    subgraph "TradierStreamManager (Singleton)"
        SM[Stream Manager<br/>Single Persistent Connection]
        RECONN[Auto-Reconnect<br/>5s Backoff]
        PARSER[Event Parser<br/>trade quote tradex summary]
    end

    subgraph "StreamRouter (Multiplexer)"
        REF[Reference Counter<br/>Per Symbol]
        Q1[Queue: Strategy 1<br/>Symbols: SPY, SPX]
        Q2[Queue: Strategy 2<br/>Symbols: QQQ]
        Q3[Queue: Strategy 3<br/>Symbols: SPY, IWM]
    end

    subgraph "StreamDrivenWorker"
        T1[Task 1: Strategy 1<br/>await queue.get]
        T2[Task 2: Strategy 2<br/>await queue.get]
        T3[Task 3: Strategy 3<br/>await queue.get]
    end

    subgraph "Market State Accumulators"
        MS1[Strategy 1 State<br/>SPY: $502.45<br/>SPX: $5,234.12]
        MS2[Strategy 2 State<br/>QQQ: $412.33]
        MS3[Strategy 3 State<br/>SPY: $502.45<br/>IWM: $198.76]
    end

    %% Connections
    WS -->|WebSocket Events| SM
    SM -->|Parse| PARSER
    PARSER -->|Route by Symbol| REF

    REF -->|SPY events| Q1
    REF -->|SPX events| Q1
    REF -->|QQQ events| Q2
    REF -->|SPY events| Q3
    REF -->|IWM events| Q3

    Q1 -->|queue get| T1
    Q2 -->|queue get| T2
    Q3 -->|queue get| T3

    T1 -->|update| MS1
    T2 -->|update| MS2
    T3 -->|update| MS3

    %% Reconnect
    SM -.->|Connection Lost| RECONN
    RECONN -.->|Reconnect| WS

    %% Subscriptions
    T1 -.->|subscribe SPY SPX| REF
    T2 -.->|subscribe QQQ| REF
    T3 -.->|subscribe SPY IWM| REF

    Note1[Reference Counting is GLOBAL across strategies:<br/>SPY: 2 consumers → stays subscribed<br/>If Task 1 stops → SPY: 1 consumer<br/>If Task 3 stops → SPY: 0 → unsubscribe<br/><br/>Each strategy tracks its OWN streamed_symbols:<br/>unsubscribing a symbol it never subscribed would<br/>decrement another strategy's count and kill its feed]

    Note2[Account stream carries NO symbol and NO side.<br/>Fields: id, status, avg_fill_price, executed_quantity.<br/>It is a NOTIFICATION keyed on order id —<br/>the canonical order still comes from REST get_order.]

    style Note1 fill:#fff3e0,stroke:#e65100
    style Note2 fill:#fff3e0,stroke:#e65100

    classDef ws fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    classDef router fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef worker fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    classDef acct fill:#fce4ec,stroke:#880e4f,stroke-width:2px

    class WS,SM,RECONN,PARSER ws
    class REF,Q1,Q2,Q3 router
    class T1,T2,T3,MS1,MS2,MS3 worker
    class WSA,ASM,ALATEST,AWAIT,OM acct
```

## 9. Risk Management Hierarchy

```mermaid
graph TB
    START[Order Request] --> L1{Level 1:<br/>Role-Based Access}

    L1 -->|user or admin| L2{Level 2:<br/>Trading Mode Gate}
    L1 -->|viewer auditor<br/>strategy_author| REJECT1[Reject: Read-Only Role]

    L2 -->|Paper strategy<br/>in paper mode| L3{Level 3:<br/>Account Daily Loss Cap}
    L2 -->|Live strategy<br/>in live mode| L3
    L2 -->|Mode mismatch| REJECT2[Reject: Paper strategy<br/>cannot trade in live mode]

    L3 -->|Loss < Cap| L4{Level 4:<br/>Strategy Daily Loss}
    L3 -->|Loss exceeds Cap| REJECT3[Reject: Account<br/>daily loss cap hit]

    L4 -->|Loss under 5%| L5{Level 5:<br/>Max Drawdown}
    L4 -->|Loss over 5%| REJECT4[Reject: Strategy<br/>daily loss limit]

    L5 -->|Drawdown under 10%| L6{Level 6:<br/>Position Limits}
    L5 -->|Drawdown over 10%| REJECT5[Reject: Max<br/>drawdown exceeded]

    L6 -->|Count under Max| L7{Level 7:<br/>Entry Trading Window}
    L6 -->|Count at Max| REJECT6[Reject: Max positions<br/>reached]

    L7 -->|Within window| L8{Level 8:<br/>Market Hours}
    L7 -->|Outside window| REJECT7[Reject: Outside<br/>trading window]

    L8 -->|Market open| L9{Level 9:<br/>Entry Lockout}
    L8 -->|Market closed| REJECT8[Reject: Market<br/>closed]

    L9 -->|No existing<br/>position| L10{Level 10:<br/>Re-Entry Cooldown}
    L9 -->|Position exists| REJECT9[Reject: Position<br/>already open]

    L10 -->|Cooldown expired| L11{Level 11:<br/>Order Rate Limit}
    L10 -->|In cooldown| REJECT10[Reject: 30s cooldown<br/>after close]

    L11 -->|Last order over 5s| L12{Level 12:<br/>Cash Availability}
    L11 -->|Last order under 5s| REJECT11[Reject: 5s rate<br/>limit per symbol]

    L12 -->|Settled cash available| PREVIEW[Preview Order<br/>via Tradier]
    L12 -->|Insufficient cash| REJECT12[Reject: Insufficient<br/>settled cash]

    PREVIEW --> L13{Level 13:<br/>Buying Power Check}

    L13 -->|BP sufficient| PLACE[Place Order]
    L13 -->|BP insufficient| REJECT13[Reject: Tradier<br/>buying power check]

    PLACE --> SUCCESS[Order Placed]

    %% Styling
    classDef reject fill:#ffebee,stroke:#c62828,stroke-width:2px
    classDef check fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef success fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px

    class REJECT1,REJECT2,REJECT3,REJECT4,REJECT5,REJECT6,REJECT7,REJECT8,REJECT9,REJECT10,REJECT11,REJECT12,REJECT13 reject
    class L1,L2,L3,L4,L5,L6,L7,L8,L9,L10,L11,L12,L13 check
    class PLACE,SUCCESS success
```

## 10. Frontend Angular Architecture

> **Performance page P&L comes from `StrategyService.getClosedTrades()`
> (`GET /performance/closed-trades`), NOT from Tradier's `/gainloss`.**
> That report's FIFO lot matcher does not retire closed buy lots when a contract is
> round-tripped repeatedly, so on 2026-07-13 it reported **−$21,057** for a day that
> actually lost **−$1,851**. It is also paginated, so a busy day was truncated on top of
> being wrong. The engine's own `Trade` rows pair each exit with the entry that opened
> it, at fill time — correct by construction, no lot matching required.
> Period selector now includes **1D** (`DAY`); Tradier has no DAY bucket for historical
> balances, so `getHistoricalBalances()` sends `WEEK` and the day filtering happens on
> the closed positions.

```mermaid
graph TB
    subgraph "Angular 20 UI"
        subgraph "Pages (Lazy Loaded)"
            DASH[Dashboard Page<br/>Account Balance<br/>Risk Status Tile<br/>Open Positions<br/>Recent Trades<br/>Equity Curve]
            STRAT[Strategies Page<br/>Strategy List<br/>Template Gallery<br/>Create/Edit Forms<br/>Toggle Active<br/>Stream Drawer]
            POS[Positions Page<br/>Open Positions Table<br/>Close Position Action<br/>Position Chart Dialog]
            TRADES[Trades Page<br/>Trade History Table<br/>Date/Symbol Filters]
            PERF[Performance Page<br/>Equity Curve<br/>P&L Summary<br/>Win Rate<br/>Sharpe Ratio]
            ADMIN[Admin Page<br/>User Management<br/>Create/Edit/Delete<br/>Role Assignment]
        end

        subgraph "Services"
            AUTHS[AuthService<br/>Login/Register<br/>JWT Token Manager<br/>Role Guards]
            STRATS[StrategyService<br/>CRUD Strategies<br/>Equity Curves<br/>getClosedTrades - P&amp;L SOURCE]
            ACCTS[AccountService<br/>Fetch Balance<br/>Positions<br/>Trades]
            TRAD[TradierService<br/>Proxy to Tradier<br/>Quotes<br/>Option Chains]
            SCH[SchwabService<br/>OAuth Redirect<br/>Account Info]
            SYS[SystemService<br/>Environment Switch<br/>System Events Stream]
            STRM[MarketStreamService<br/>WebSocket to Tradier<br/>Live Quotes for UI]
            RISK[RiskService<br/>Risk Status<br/>Account Daily Loss]
        end

        subgraph "Guards"
            AG[AuthGuard<br/>JWT Validation]
            RG[RoleGuard<br/>Admin-Only Routes]
        end

        subgraph "Components"
            ENV[Environment Controls<br/>Dev/Test/Prod Toggle<br/>Paper/Live Toggle]
            PROF[Profile Dialog<br/>User Settings<br/>Trading Windows<br/>Notification Prefs]
            RISK_TILE[Risk Status Tile<br/>Daily Loss Progress Bar<br/>OK/WARNING/HALTED]
        end
    end

    subgraph "Backend API"
        API[FastAPI<br/>/api/v1/*]
    end

    %% Page to Service connections
    DASH --> ACCTS
    DASH --> RISK
    DASH --> SYS

    STRAT --> STRATS
    STRAT --> TRAD
    STRAT --> STRM

    POS --> ACCTS
    TRADES --> ACCTS
    PERF --> ACCTS
    ADMIN --> AUTHS

    %% Service to API
    AUTHS --> API
    STRATS --> API
    ACCTS --> API
    TRAD --> API
    SCH --> API
    SYS --> API
    RISK --> API

    %% Guards
    DASH -.->|protected| AG
    STRAT -.->|protected| AG
    POS -.->|protected| AG
    TRADES -.->|protected| AG
    PERF -.->|protected| AG
    ADMIN -.->|protected + admin only| RG

    %% Components
    DASH --> ENV
    DASH --> RISK_TILE
    DASH --> PROF

    classDef page fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    classDef service fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef component fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px

    class DASH,STRAT,POS,TRADES,PERF,ADMIN page
    class AUTHS,STRATS,ACCTS,TRAD,SCH,SYS,STRM,RISK service
    class ENV,PROF,RISK_TILE component
```

---

## Key Design Patterns Summary

| Pattern | Implementation | Purpose |
|---------|---------------|---------|
| **Singleton Managers** | `StreamDrivenWorker`, `TradierStreamManager`, `TradingClientManager` | Single global instance coordinates all strategies |
| **Event-Driven Architecture** | WebSocket → Queue → Executor | Real-time stream processing, no polling |
| **Ref-Counted Subscriptions** | `StreamRouter` tracks consumers per symbol | Automatic subscribe/unsubscribe management |
| **Row-Level Locking** | `SELECT FOR UPDATE` on positions | Prevent race conditions on concurrent signals |
| **Optimistic Polling** | Poll Tradier for terminal status before DB write | Fail-safe against partial fills |
| **In-Memory Cash Ledger** | Temporary holds with TTL | Prevent double-spend on concurrent orders |
| **Re-Entry Cooldown** | 30s lockout after close | Prevent flip-flop trading loops |
| **Multi-Environment DB Routing** | 3 separate PostgreSQL instances | Complete data isolation (dev/test/prod) |
| **Role-Based Access Control** | JWT claims + FastAPI dependencies | Fine-grained permissions (user/admin/viewer/auditor) |
| **Strategy Market State** | Per-strategy accumulator of stream events | Maintain real-time pricing, greeks, volume |

---

## Performance & Scale Characteristics

- **Latency**: Stream tick → Order placed: ~50-150ms (network-dependent)
- **Throughput**: Single WebSocket handles 100+ symbols simultaneously
- **Concurrency**: Supports 10+ active strategies per process
- **Database**: TimescaleDB hypertable partitions trades by timestamp
- **Live-Test Logging**: JSONL append-only logs for post-trade analysis
- **Fail-Safe**: Auto-reconnect on WebSocket disconnect (5s backoff)
- **Recovery**: Startup reconciliation syncs DB against Tradier positions

---

*Generated: 2026-07-11*
*Codebase: VegaPunkR Options Trading Automation Platform*
