import Foundation

/// Loosely typed JSON value for strategy parameters.
public enum JSONValue: Codable, Hashable {
    case number(Double)
    case string(String)
    case bool(Bool)
    case null

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let d = try? c.decode(Double.self) { self = .number(d) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else { self = .null }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .number(let d): try c.encode(d)
        case .string(let s): try c.encode(s)
        case .bool(let b): try c.encode(b)
        case .null: try c.encodeNil()
        }
    }

    public var double: Double? {
        switch self {
        case .number(let d): return d
        case .string(let s): return Double(s)
        case .bool(let b): return b ? 1 : 0
        case .null: return nil
        }
    }

    public var bool: Bool { if case .bool(let b) = self { return b }; return (double ?? 0) != 0 }

    public var string: String {
        switch self {
        case .string(let s): return s
        case .number(let d): return d.formatted()
        case .bool(let b): return b ? String(localized: "Yes") : String(localized: "No")
        case .null: return "–"
        }
    }
}

/// The brokers the agent trades on. Every bot belongs to one; results, limits, fees and the trading mode are kept
/// per broker. The app shows one at a time – the tabs above the statistics switch between them.
public enum Broker: String, CaseIterable, Identifiable, Codable {
    case revolutX = "revolutx"
    case tradeRepublic = "traderepublic"

    public var id: String { rawValue }

    public var title: String {
        switch self {
        case .revolutX: return "Revolut X"
        case .tradeRepublic: return "Trade Republic"
        }
    }

    public var icon: String {
        switch self {
        case .revolutX: return "bitcoinsign.circle"
        case .tradeRepublic: return "building.columns"
        }
    }

    /// Bots and trades from agents before 1.20 carry no broker – they are Revolut X's.
    public init(id: String?) {
        self = Broker(rawValue: id ?? "") ?? .revolutX
    }
}

/// One broker as the agent sees it (agent 1.20+).
public struct ExchangeStatus: Codable, Identifiable, Equatable {
    public struct FeeInfo: Codable, Equatable {
        public let rate: Double
        public let fixed: Double
    }

    public let id: String
    public let title: String
    /// The agent runs the demo market (EXCHANGE=mock) – no live trading.
    public let simulated: Bool
    /// Credentials or a session exist – the broker can be asked for prices.
    public let configured: Bool
    public let ok: Bool
    public let error: String?
    public let liveTradingAllowed: Bool
    /// Switched on in the settings (nil: agent 1.20 before the switch existed – on).
    public let enabled: Bool?
    /// What a live order costs on this broker.
    public let fees: FeeInfo?

    public var broker: Broker { Broker(id: id) }
    public var isEnabled: Bool { enabled ?? true }

    enum CodingKeys: String, CodingKey {
        case id, title, simulated, configured, ok, error, fees, enabled
        case liveTradingAllowed = "live_trading_allowed"
    }
}

public struct ServerStatus: Codable {
    public let version: String
    public let exchange: String
    public let exchangeOk: Bool
    public let exchangeError: String?
    public let engineError: String?
    public let liveTradingAllowed: Bool
    public let lastTick: Int64?
    public let tickSeconds: Int
    /// Exchange fee per order as a fraction (0.0009 = 0.09 %); older agents don't send it.
    public let takerFee: Double?
    /// Whether the agent has an Anthropic API key for the "AI decides" strategy (nil: older agent).
    public let aiConfigured: Bool?
    /// Every broker (agent 1.20+); nil: an older agent that only knows Revolut X.
    public let exchanges: [ExchangeStatus]?

    public func exchange(_ broker: Broker) -> ExchangeStatus? { exchanges?.first { $0.id == broker.rawValue } }

    /// Live trading on the broker – older agents only have Revolut X's switch.
    public func liveTradingAllowed(_ broker: Broker) -> Bool {
        exchange(broker)?.liveTradingAllowed ?? (broker == .revolutX && liveTradingAllowed)
    }

    /// The agent runs the simulated demo market instead of the real brokers.
    public var isDemo: Bool { exchange == "mock" }

    enum CodingKeys: String, CodingKey {
        case version, exchange, exchanges
        case exchangeOk = "exchange_ok"
        case exchangeError = "exchange_error"
        case engineError = "engine_error"
        case liveTradingAllowed = "live_trading_allowed"
        case lastTick = "last_tick"
        case tickSeconds = "tick_seconds"
        case takerFee = "taker_fee"
        case aiConfigured = "ai_configured"
    }
}

public struct CurrencyTotal: Codable, Identifiable {
    public let currency: String
    public let realized: Double
    public let unrealized: Double
    public let today: Double
    public let invested: Double
    public let total: Double
    /// Exchange fees paid so far; older agents don't send it.
    public let fees: Double?
    public var id: String { currency }
}

public struct OtherModeTotal: Codable {
    public let currency: String
    public let total: Double
}

public struct Summary: Codable {
    /// The broker these numbers belong to (agent 1.20+).
    public let exchange: String?
    public let currencies: [CurrencyTotal]
    /// "paper" or "live" – the mode the numbers above belong to (older agents mix both and send nothing).
    public let mode: String?
    /// The other mode's result per currency, and how many trades it has.
    public let otherMode: [OtherModeTotal]?
    public let otherModeTrades: Int?
    public let botsTotal: Int
    public let botsActive: Int
    public let openPositions: Int
    public let maxOpenPositions: Int?
    public let tradesCount: Int

    enum CodingKeys: String, CodingKey {
        case exchange, currencies, mode
        case otherMode = "other_mode"
        case otherModeTrades = "other_mode_trades"
        case botsTotal = "bots_total"
        case botsActive = "bots_active"
        case openPositions = "open_positions"
        case maxOpenPositions = "max_open_positions"
        case tradesCount = "trades_count"
    }
}

/// One open trade – or, as `Bot.position`, all of a bot's trades summed up.
public struct BotPosition: Codable, Equatable, Identifiable {
    public let id: String? // agent 1.13+; a bot can hold several trades at once
    public let qty: Double
    public let cost: Double
    public let entryPrice: Double
    public let openedAt: Int64
    public let value: Double
    public let unrealizedPnl: Double
    public let unrealizedPct: Double
    public let paper: Bool?
    // per trade (agent 1.13+): the price its sale waits for, its stop, or the strategy's note
    public let sellPrice: Double?
    public let stopPrice: Double?
    public let note: String?
    // agent 1.22+: the instrument the trade holds when it isn't the bot's own (the monthly trend follower's
    // currency-hedged share class, or the bonds it parks in)
    public let heldSymbol: String?
    public let heldName: String?
    public let heldUnit: String?

    /// The unit of `qty`: the held instrument's ticker, else the bot's.
    public func unit(of bot: Bot) -> String { heldUnit ?? bot.baseCurrency }

    enum CodingKeys: String, CodingKey {
        case id, qty, cost, value, paper, note
        case heldSymbol = "symbol"
        case heldName = "display_symbol"
        case heldUnit = "base_currency"
        case entryPrice = "entry_price"
        case sellPrice = "sell_price"
        case stopPrice = "stop_price"
        case openedAt = "opened_at"
        case unrealizedPnl = "unrealized_pnl"
        case unrealizedPct = "unrealized_pct"
    }
}

public struct MarketInfo: Codable, Equatable {
    public let price: Double
    public let change24h: Double
    /// Why the instrument can't be traded right now, e.g. outside the trading hours of a stock (agent 1.20+).
    public let closed: String?

    enum CodingKeys: String, CodingKey {
        case price, closed
        case change24h = "change_24h"
    }
}

/// The prices a bot waits for – a buy below, a sale above, the stop below – or a note when there is no fixed price.
public struct BotTargets: Codable, Equatable {
    public let buyPrice: Double?
    public let sellPrice: Double?
    public let stopPrice: Double?
    public let note: String?
    // with open trades a further buy needs both: the strategy's own signal and the distance to the open trades
    // (agent 1.15+); `buyPrice` is the stricter of the two
    public let signalPrice: Double?
    public let spacingPrice: Double?

    enum CodingKeys: String, CodingKey {
        case buyPrice = "buy_price"
        case signalPrice = "signal_price"
        case spacingPrice = "spacing_price"
        case sellPrice = "sell_price"
        case stopPrice = "stop_price"
        case note
    }
}

/// What a strategy looks at, line by line – the monthly trend follower's trend, recession signs, dollar and bonds.
public struct BotSignals: Codable, Equatable {
    public struct Row: Codable, Equatable, Identifiable {
        public let label: String
        public let value: String
        /// on/off: a trend signal · ok/warn: a recession sign · neutral · unknown: no data
        public let state: String?
        /// How far it is from turning, e.g. "Today 112 € – off below 103 € (−8 %) at the month end".
        public let note: String?
        public var id: String { label }
    }

    public struct Month: Codable, Equatable, Identifiable {
        public let month: String // "2026-10"
        public let label: String // "Oct 2026"
        public let state: String // in, hedged, parked, cash
        public let name: String? // the instrument it parked in or the hedged share class
        public var id: String { month }
    }

    public let rows: [Row]
    public let history: [Month]
}

/// The trend followers as one portfolio: the share each should have (by its amount) and has (by its value).
public struct BotPillars: Codable, Equatable {
    public struct Share: Codable, Equatable, Identifiable {
        public let id: Int
        public let name: String
        public let value: Double
        public let target: Double // %
        public let actual: Double // %
        public let rebalanced: Double // the amount that would restore the target share
    }

    public let shares: [Share]
    public let total: Double
    public let drift: Double // the largest deviation in percentage points
    public let due: Bool
}

/// How far the price still has to move until the bot trades – what the card shows first.
public struct BotGoal {
    public enum Kind { case buy, sell, trailingStart, trailingStop }

    public let kind: Kind
    public let target: Double
    public let percent: Double // target relative to the current price
    public let reached: Bool
}

public struct Bot: Codable, Identifiable, Equatable {
    public let id: Int
    public let name: String
    public let strategy: String
    public let strategyName: String
    public let strategyIcon: String
    public let symbol: String
    /// The broker the bot trades on (agent 1.20+; older agents: Revolut X).
    public let exchange: String?
    /// What the app shows instead of the symbol – Trade Republic: the instrument's name instead of its ISIN.
    public let displaySymbol: String?
    /// crypto, stock, fund … (agent 1.20+).
    public let instrumentType: String?
    public let baseCurrency: String
    public let quoteCurrency: String
    public let params: [String: JSONValue]
    public let enabled: Bool
    public let paper: Bool
    public let paperRequested: Bool
    public let status: String
    public let statusError: Bool?
    public let hint: String? // e.g. a buy signal the limits blocked – shown until the limits allow it
    public let targets: BotTargets? // what the bot waits for (agent 1.12+)
    public let lastCheck: Int64?
    public let createdAt: Int64
    public let pendingOrder: Bool
    public let position: BotPosition? // all open trades summed up
    public let positions: [BotPosition]? // the open trades one by one (agent 1.13+)
    public let maxTrades: Int? // how many trades the bot may hold at once (agent 1.13+)
    /// The trades are slices of one position (momentum follower, agent 1.27+) – shown as one position.
    public let sliced: Bool?
    public let realizedPnl: Double
    public let tradesCount: Int
    public let wins: Int
    public let losses: Int
    public let market: MarketInfo?
    /// The signals behind the decision, each with its value and how far it is from turning (agent 1.24+).
    public let signals: BotSignals?
    /// The running trend followers of the broker side by side – their shares and whether to rebalance (agent 1.24+).
    public let pillars: BotPillars?

    enum CodingKeys: String, CodingKey {
        case id, name, strategy, symbol, params, enabled, paper, status, hint, targets, position, positions, wins, losses, market
        case signals, pillars, sliced
        case exchange
        case displaySymbol = "display_symbol"
        case instrumentType = "instrument_type"
        case maxTrades = "max_trades"
        case strategyName = "strategy_name"
        case strategyIcon = "strategy_icon"
        case baseCurrency = "base_currency"
        case quoteCurrency = "quote_currency"
        case paperRequested = "paper_requested"
        case statusError = "status_error"
        case lastCheck = "last_check"
        case createdAt = "created_at"
        case pendingOrder = "pending_order"
        case realizedPnl = "realized_pnl"
        case tradesCount = "trades_count"
    }

    public var totalPnl: Double { realizedPnl + (position?.unrealizedPnl ?? 0) }

    public var broker: Broker { Broker(id: exchange) }

    /// The instrument as people know it: "ETH-EUR" on Revolut X, "Apple" on Trade Republic.
    public var title: String { displaySymbol ?? symbol }

    /// The open trades one by one – older agents only send the single position.
    public var openTrades: [BotPosition] { positions ?? (position.map { [$0] } ?? []) }

    /// True when the bot may hold more than one trade (or does) – the card then lists them.
    public var tradesMode: Bool { sliced != true && ((maxTrades ?? 1) > 1 || openTrades.count > 1) }

    /// True when the sale runs through a trailing stop: the trailing strategy, or the dip buyer with
    /// "Trailing after the sell signal" (agent 1.18+) – its sale price then first lies above, later below the price.
    public var usesTrailingStop: Bool {
        strategy == "trailing" || (strategy == "dip" && (params["trail"]?.double ?? 0) > 0)
    }

    /// The next trade trigger with a fixed price: the buy price while waiting, the sale (or the trailing stop) with a
    /// position. Nil for strategies without one (AI decides, the savings plan's next instalment) or old agents.
    public var goal: BotGoal? {
        guard let targets, let price = market?.price, price > 0 else { return nil }
        let kind: BotGoal.Kind
        let target: Double
        // a buy price comes only while the bot may open another trade
        if let buy = targets.buyPrice {
            kind = .buy
            target = buy
        } else if position != nil, let sell = targets.sellPrice {
            // a trailing stop first waits for its start price above (activation / sell signal), then sells when the stop below is hit
            kind = usesTrailingStop ? (sell < price ? .trailingStop : .trailingStart) : .sell
            target = sell
        } else {
            return nil
        }
        let reached: Bool
        switch kind {
        case .buy, .trailingStop: reached = price <= target
        case .sell, .trailingStart: reached = price >= target
        }
        return BotGoal(kind: kind, target: target, percent: (target / price - 1) * 100, reached: reached)
    }
}

public struct Trade: Codable, Identifiable, Equatable {
    /// A sale's result relative to what the sold coins cost (proceeds after fees minus the result = their cost).
    public var pnlPct: Double? {
        guard let pnl, quoteAmount - pnl > 0 else { return nil }
        return pnl / (quoteAmount - pnl) * 100
    }

    public let id: Int
    public let botId: Int
    public let botName: String
    public let symbol: String
    public let side: String
    public let price: Double
    public let baseQty: Double
    public let quoteAmount: Double
    public let fee: Double
    public let pnl: Double?
    public let orderId: String?
    public let paper: Bool
    public let reason: String
    public let createdAt: Int64
    /// The trade (position) a buy opened or added to and a sale closed – agent 1.17+; nil for older trades.
    public let positionId: String?
    /// The broker (agent 1.20+; older agents: Revolut X).
    public let exchange: String?
    /// Trade Republic: the ticker and the name instead of the ISIN.
    public let baseName: String?
    public let displaySymbol: String?

    enum CodingKeys: String, CodingKey {
        case id, symbol, side, price, fee, pnl, paper, reason, exchange
        case baseName = "base_name"
        case displaySymbol = "display_symbol"
        case positionId = "position_id"
        case botId = "bot_id"
        case botName = "bot_name"
        case baseQty = "base_qty"
        case quoteAmount = "quote_amount"
        case orderId = "order_id"
        case createdAt = "created_at"
    }

    public var isBuy: Bool { side == "buy" }
    public var broker: Broker { Broker(id: exchange) }
    public var base: String { baseName ?? String(symbol.split(separator: "-").first ?? "") }
    public var quote: String { String(symbol.split(separator: "-").last ?? "EUR") }
    public var date: Date { Date(ms: createdAt) }
}

public struct SelectOption: Codable, Hashable {
    public let value: String
    public let label: String
}

public struct StrategyParam: Codable, Identifiable {
    public let key: String
    public let label: String
    public let type: String
    public let `default`: JSONValue
    public let help: String?
    public let min: Double?
    public let max: Double?
    public let step: Double?
    public let options: [SelectOption]?
    public let unit: String?
    public var id: String { key }
}

public struct Strategy: Codable, Identifiable {
    public let key: String
    public let name: String
    public let description: String
    public let icon: String
    public let params: [StrategyParam]
    public var id: String { key }
}

/// One answer of Claude for an "AI decides" bot.
public struct AiDecision: Codable, Identifiable {
    public let id: Int
    public let action: String // buy | wait | hold | sell
    public let confidence: Int // 0–100
    public let reason: String
    public let price: Double
    public let profitPct: Double?
    public let createdAt: Int64

    enum CodingKeys: String, CodingKey {
        case id, action, confidence, reason, price
        case profitPct = "profit_pct"
        case createdAt = "created_at"
    }
}

public struct BotEvent: Codable, Identifiable {
    public let id: Int
    public let botId: Int?
    public let level: String
    public let message: String
    public let createdAt: Int64

    enum CodingKeys: String, CodingKey {
        case id, level, message
        case botId = "bot_id"
        case createdAt = "created_at"
    }
}

public struct Balance: Codable, Identifiable {
    public let currency: String
    public let available: Double
    public let total: Double
    public var id: String { currency }
}

/// Revolut X connection as configured on the agent. The private key never leaves the agent.
public struct ExchangeInfo: Codable, Equatable {
    public let source: String // "env" (.env on the agent), "app" (set up via this app) or "none"
    public let apiKeyMasked: String?
    public let publicKey: String?
    public let pendingPublicKey: String?
    public let mode: String // "revolutx" | "mock"
    public let connected: Bool
    public let error: String?
    public let apiKeysUrl: String

    enum CodingKeys: String, CodingKey {
        case source, mode, connected, error
        case apiKeyMasked = "api_key_masked"
        case publicKey = "public_key"
        case pendingPublicKey = "pending_public_key"
        case apiKeysUrl = "api_keys_url"
    }
}

public struct PublicIP: Codable { public let ip: String }

/// The Trade Republic login on the agent (agent 1.20+). Prices work without it (paper trading); live trading needs
/// it. A login lasts 24 hours and is confirmed in the Trade Republic app.
public struct TradeRepublicInfo: Codable, Equatable {
    /// logged_out | waiting (for the confirmation in the TR app) | code (authenticator code needed) | logged_in
    public let state: String
    public let connected: Bool
    public let phoneMasked: String?
    public let pinSaved: Bool
    public let loggedInAt: Int64?
    /// When the 24-hour login ends.
    public let sessionExpiresAt: Int64?
    /// Until when the agent waits for the confirmation in the app.
    public let waitingUntil: Int64?
    /// The agent started the daily login itself.
    public let automatic: Bool
    public let error: String?
    public let marketError: String?
    /// "mock": the demo market – no login.
    public let mode: String

    public var isDemo: Bool { mode == "mock" }
    public var waiting: Bool { state == "waiting" || state == "code" }

    enum CodingKeys: String, CodingKey {
        case state, connected, automatic, error, mode
        case phoneMasked = "phone_masked"
        case pinSaved = "pin_saved"
        case loggedInAt = "logged_in_at"
        case sessionExpiresAt = "session_expires_at"
        case waitingUntil = "waiting_until"
        case marketError = "market_error"
    }
}

/// Response of restoring a backup on the agent.
public struct RestoreResult: Decodable {
    public let bots: Int
    public let trades: Int
    public let liveTradingDisabled: Bool
    public let credentialsRestored: Bool
    public let createdAt: Int64?
    public let agentVersion: String?

    enum CodingKeys: String, CodingKey {
        case bots, trades
        case liveTradingDisabled = "live_trading_disabled"
        case credentialsRestored = "credentials_restored"
        case createdAt = "created_at"
        case agentVersion = "agent_version"
    }
}

/// Response of switching the live mode; switching back to paper sells all open live positions.
public struct LiveSwitchResult: Decodable {
    public struct ClosedPosition: Decodable, Identifiable {
        public let botId: Int
        public let botName: String
        public let ok: Bool
        public let message: String
        public var id: Int { botId }

        enum CodingKeys: String, CodingKey {
            case ok, message
            case botId = "bot_id"
            case botName = "bot_name"
        }
    }

    public let closedPositions: [ClosedPosition]

    enum CodingKeys: String, CodingKey {
        case closedPositions = "closed_positions"
    }
}

/// Global risk limits enforced by the agent engine.
public struct Limits: Codable, Equatable {
    public var maxOpenPositions: Int
    public var maxTotalInvested: Double
    public var onePositionPerSymbol: Bool
    public var openPositions: Int?
    public var invested: Double?

    enum CodingKeys: String, CodingKey {
        case maxOpenPositions = "max_open_positions"
        case maxTotalInvested = "max_total_invested"
        case onePositionPerSymbol = "one_position_per_symbol"
        case openPositions = "open_positions"
        case invested
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(maxOpenPositions, forKey: .maxOpenPositions)
        try c.encode(maxTotalInvested, forKey: .maxTotalInvested)
        try c.encode(onePositionPerSymbol, forKey: .onePositionPerSymbol)
    }
}

/// Fees the simulation (paper mode) charges, as fractions (0.0009 = 0.09 %), plus a fixed amount per order in the
/// quote currency (Trade Republic: 1 €; agent 1.20+, nil with older agents).
public struct PaperFees: Codable, Equatable {
    public var buy: Double
    public var sell: Double
    public var fixed: Double?

    public init(buy: Double, sell: Double, fixed: Double? = nil) {
        self.buy = buy
        self.sell = sell
        self.fixed = fixed
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(buy, forKey: .buy)
        try c.encode(sell, forKey: .sell)
        try c.encodeIfPresent(fixed, forKey: .fixed)
    }
}

/// Something a broker trades – Trade Republic identifies it by its ISIN (symbol "<ISIN>-EUR").
public struct Instrument: Codable, Identifiable, Hashable {
    public let symbol: String
    public let name: String
    /// Ticker or code used for amounts, e.g. AAPL or BTC.
    public let short: String?
    /// crypto, stock, fund, bond, derivative …
    public let type: String?
    public let isin: String?
    public var id: String { symbol }

    public init(symbol: String, name: String, short: String?, type: String?, isin: String?) {
        self.symbol = symbol
        self.name = name
        self.short = short
        self.type = type
        self.isin = isin
    }

    /// Where a new Trade Republic bot starts – suits a savings plan as well as a dip buyer.
    public static let tradeRepublicStart = Instrument(
        symbol: "IE00B4L5Y983-EUR", name: "iShares Core MSCI World", short: "EUNL", type: "fund", isin: "IE00B4L5Y983"
    )
}

public struct BotInput: Encodable {
    public var name: String
    public var strategy: String
    public var symbol: String
    public var params: [String: JSONValue]
    public var enabled: Bool
    public var paper: Bool
    public var exchange: String

    public init(name: String, strategy: String, symbol: String, params: [String: JSONValue], enabled: Bool, paper: Bool,
                broker: Broker = .revolutX) {
        self.name = name
        self.strategy = strategy
        self.symbol = symbol
        self.params = params
        self.enabled = enabled
        self.paper = paper
        self.exchange = broker.rawValue
    }
}

extension Date {
    public init(ms: Int64) { self.init(timeIntervalSince1970: TimeInterval(ms) / 1000) }
}
