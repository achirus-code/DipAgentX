import Foundation
import Observation
import UserNotifications

public enum ConnectionState: Equatable {
    case notConfigured
    case connecting
    case connected
    case failed(String)
}

/// The app's view of the agent: connection, polling, the data the views show and every action. Shared by the
/// macOS and the iPhone app – what only one platform needs (file dialogs, launch at login, wake-up, the
/// background refresh) lives in the apps.
@MainActor
@Observable
public final class AppStore {
    // Settings
    public internal(set) var serverURL: String = UserDefaults.standard.string(forKey: "serverURL") ?? ""
    // `-apiToken <t>` on the command line overrides the keychain (used by the snapshot tool)
    public internal(set) var token: String = UserDefaults.standard.volatileDomain(forName: UserDefaults.argumentDomain)["apiToken"] as? String
        ?? Keychain.get("apiToken") ?? ""
    /// Seconds between two refreshes – one of `refreshIntervals`.
    public static let refreshIntervals: [Double] = [30, 60, 120, 300]
    public var refreshInterval: Double = {
        let v = UserDefaults.standard.double(forKey: "refreshInterval")
        // Older versions allowed 5 s / 15 s – snap to the nearest option that still exists.
        return refreshIntervals.contains(v) ? v : (v > 0 && v < 30 ? 30 : 60)
    }() {
        didSet {
            UserDefaults.standard.set(refreshInterval, forKey: "refreshInterval")
            startPolling()
        }
    }
    public var notificationsEnabled: Bool = UserDefaults.standard.object(forKey: "notifications") as? Bool ?? true {
        didSet {
            UserDefaults.standard.set(notificationsEnabled, forKey: "notifications")
            if notificationsEnabled { requestNotificationPermission() }
        }
    }

    /// The broker the app shows – the tabs above the statistics switch it. Statistics, bots, trades, the trading
    /// mode, limits and simulation fees all belong to one broker.
    public var selectedBroker: Broker = Broker(id: UserDefaults.standard.string(forKey: "broker")) {
        didSet {
            UserDefaults.standard.set(selectedBroker.rawValue, forKey: "broker")
            if selectedBroker != oldValue, isConnected { Task { await refreshBalances(force: true) } }
        }
    }

    // Data from the agent
    public internal(set) var connection: ConnectionState = .notConfigured
    public internal(set) var status: ServerStatus?
    public internal(set) var summaries: [Broker: Summary] = [:]
    /// All bots and the latest trades of every broker – `brokerBots`/`brokerTrades` are the selected broker's.
    public internal(set) var bots: [Bot] = []
    public internal(set) var trades: [Trade] = []
    public internal(set) var strategies: [Strategy] = []
    public internal(set) var pairsByBroker: [Broker: [String]] = [:]
    public internal(set) var balancesByBroker: [Broker: [Balance]] = [:]
    public internal(set) var limitsByBroker: [Broker: Limits] = [:]
    public internal(set) var paperFeesByBroker: [Broker: PaperFees] = [:]
    public internal(set) var exchangeInfo: ExchangeInfo?
    public internal(set) var tradeRepublic: TradeRepublicInfo?

    /// The agent knows several brokers (1.20+). Older agents only trade on Revolut X – no tabs then.
    public var supportsBrokers: Bool { status?.exchanges != nil }
    /// The brokers switched on in the settings (older agents: Revolut X).
    public var enabledBrokers: [Broker] {
        guard supportsBrokers else { return [.revolutX] }
        let on = Broker.allCases.filter { status?.exchange($0)?.isEnabled ?? true }
        return on.isEmpty ? [.revolutX] : on
    }
    /// The tabs above the statistics – only while more than one broker is on.
    public var showsBrokerTabs: Bool { enabledBrokers.count > 1 }
    /// The broker whose data the app shows right now: the selected tab – or the only broker that is on.
    public var broker: Broker { enabledBrokers.contains(selectedBroker) ? selectedBroker : enabledBrokers[0] }
    public var summary: Summary? { summaries[broker] }
    public var limits: Limits? { limitsByBroker[broker] }
    public var paperFees: PaperFees? { paperFeesByBroker[broker] }
    public var balances: [Balance] { balancesByBroker[broker] ?? [] }
    public var pairs: [String] { pairsByBroker[broker] ?? [] }
    public func pairs(for broker: Broker) -> [String] { pairsByBroker[broker] ?? [] }
    public var brokerBots: [Bot] { bots.filter { $0.broker == broker } }
    public var brokerTrades: [Trade] { trades.filter { $0.broker == broker } }
    /// Live trading on the selected broker.
    public var isLive: Bool { status?.liveTradingAllowed(broker) ?? false }
    public func isLive(_ broker: Broker) -> Bool { status?.liveTradingAllowed(broker) ?? false }
    /// The broker can trade: connected (Revolut X: API key, Trade Republic: logged in) and answering.
    public func brokerReady(_ broker: Broker) -> Bool {
        switch broker {
        case .revolutX: return exchangeInfo?.connected == true
        case .tradeRepublic: return tradeRepublic?.connected == true
        }
    }
    public internal(set) var lastUpdate: Date?
    /// Set by the app: the panel (macOS) or the app (iPhone) is on screen. Balances are only fetched then –
    /// nobody sees them otherwise, and every fetch is a request to Revolut X.
    public var isVisible = false
    private var balancesUpdatedAt: [Broker: Date] = [:]
    public internal(set) var isRefreshing = false
    /// macOS: while true (Revolut X setup, file dialogs) the panel stays open when the user clicks elsewhere.
    @ObservationIgnored public var keepPanelOpen = false

    private var client: APIClient?
    private var pollTask: Task<Void, Never>?
    private var loginWatch: Task<Void, Never>?
    /// The newest trade the user has been told about. The iPhone keeps it across launches, so trades made while
    /// the app was closed are reported by the background refresh or on the next start.
    private var lastSeenTradeId: Int? {
        didSet { if persistsLastSeenTrade { UserDefaults.standard.set(lastSeenTradeId, forKey: "lastSeenTradeId") } }
    }
    private let persistsLastSeenTrade: Bool

    /// Seconds until the next reconnect attempt while the agent is unreachable (5 s, doubling up to 60 s).
    private var retryDelay: Double = 5

    public init(persistLastSeenTrade: Bool = false) {
        persistsLastSeenTrade = persistLastSeenTrade
        if persistLastSeenTrade {
            lastSeenTradeId = UserDefaults.standard.object(forKey: "lastSeenTradeId") as? Int
        }
        // after "Disconnect" the app stays disconnected until the user connects again
        if !serverURL.isEmpty && !token.isEmpty && !UserDefaults.standard.bool(forKey: "userDisconnected") {
            Task { await connect() }
        }
    }

    /// Address and token are known and the user has not disconnected.
    public var isConfigured: Bool {
        !serverURL.isEmpty && !token.isEmpty && !UserDefaults.standard.bool(forKey: "userDisconnected")
    }

    /// Refresh when connected, otherwise try to reconnect immediately – used on wake-up and when the panel opens.
    public func refreshNow() async {
        guard isConfigured else { return }
        retryDelay = 5
        if connection == .connected {
            await refresh()
        } else if connection != .connecting {
            await handshake()
            startPolling() // restart the loop so the next attempt is due in `retryDelay`, not in a minute
        }
    }

    /// Like refreshNow, but only if the data is older than a few seconds (the panel opens often).
    public func refreshIfStale() {
        if connection == .connected, let lastUpdate, Date().timeIntervalSince(lastUpdate) < 10 { return }
        Task { await refreshNow() }
    }

    /// iPhone: the app comes to the front – fresh data right away, then the regular polling again.
    public func resume() async {
        guard isConfigured else { return }
        retryDelay = 5
        if connection == .connected {
            await refresh()
        } else if connection != .connecting {
            await handshake()
        }
        startPolling()
    }

    /// iPhone: the app goes to the background – no polling there (the system's background refresh takes over).
    public func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    public var menuBarSymbol: String {
        switch connection {
        case .connecting: return "arrow.triangle.2.circlepath"
        case .failed: return "exclamationmark.triangle"
        case .connected where bots.contains { $0.position != nil }: return "chart.line.uptrend.xyaxis.circle.fill"
        default: return "chart.line.uptrend.xyaxis"
        }
    }

    public var isConnected: Bool { connection == .connected }

    // MARK: - Connection

    public func saveConnection(server: String, token: String) async {
        serverURL = server.trimmingCharacters(in: .whitespacesAndNewlines)
        self.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(serverURL, forKey: "serverURL")
        Keychain.set(self.token, for: "apiToken")
        await connect()
    }

    /// User-triggered (or first) connect: handshake, then the polling loop keeps the connection alive.
    public func connect() async {
        pollTask?.cancel()
        retryDelay = 5
        await handshake()
        startPolling() // also while failed: the loop keeps retrying
    }

    /// One connection attempt: status, strategies, pairs, then a first refresh. Never touches the polling
    /// task – the loop itself calls this, and cancelling the loop from inside would abort the request.
    private func handshake() async {
        guard !serverURL.isEmpty, !token.isEmpty else {
            connection = .notConfigured
            return
        }
        connection = .connecting
        do {
            let client = try APIClient(server: serverURL, token: token)
            self.client = client
            status = try await client.get("/status")
            strategies = try await client.get("/strategies")
            await loadPairs()
            connection = .connected
            retryDelay = 5
            UserDefaults.standard.set(false, forKey: "userDisconnected")
            await refresh()
            if notificationsEnabled { requestNotificationPermission() }
        } catch {
            connection = .failed(error.localizedDescription)
        }
    }

    public func disconnect() {
        UserDefaults.standard.set(true, forKey: "userDisconnected")
        pollTask?.cancel()
        client = nil
        connection = .notConfigured
        bots = []; trades = []; summaries = [:]; status = nil; balancesByBroker = [:]; limitsByBroker = [:]
        paperFeesByBroker = [:]; exchangeInfo = nil; tradeRepublic = nil; pairsByBroker = [:]
    }

    /// The brokers to load: every broker the agent knows (older agents: Revolut X only, without a query).
    private var loadedBrokers: [Broker] { supportsBrokers ? Broker.allCases : [.revolutX] }

    private func query(_ broker: Broker, _ extra: [String: String] = [:]) -> [String: String] {
        supportsBrokers ? extra.merging(["exchange": broker.rawValue]) { a, _ in a } : extra
    }

    private func loadPairs() async {
        guard let client else { return }
        for broker in loadedBrokers {
            if let pairs: [String] = try? await client.get("/pairs", query: query(broker)) { pairsByBroker[broker] = pairs }
        }
    }

    /// The selected broker's balances – only while the app is on screen (each fetch asks the broker), at the latest
    /// every 10 minutes, or right away after switching the broker.
    public func refreshBalances(force: Bool = false) async {
        guard let client else { return }
        let broker = self.broker
        let stale = balancesUpdatedAt[broker].map { Date().timeIntervalSince($0) > 600 } ?? true
        guard force || isVisible || stale else { return }
        if let fresh: [Balance] = try? await client.get("/balances", query: query(broker)) {
            balancesByBroker[broker] = fresh
            balancesUpdatedAt[broker] = Date()
        }
    }

    /// Connected: refresh every `refreshInterval`. Unreachable: reconnect after `retryDelay` (5 s, then doubling
    /// up to 60 s) – so the app is back a few seconds after the agent restarts or the network returns.
    private func startPolling() {
        pollTask?.cancel()
        guard !serverURL.isEmpty, !token.isEmpty else { return }
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let delay = self.connection == .connected ? self.refreshInterval : self.retryDelay
                try? await Task.sleep(for: .seconds(delay))
                guard !Task.isCancelled else { return }
                if self.connection == .connected {
                    await self.refresh()
                } else {
                    await self.handshake()
                    if self.connection != .connected { self.retryDelay = min(self.retryDelay * 2, 60) }
                }
            }
        }
    }

    // MARK: - Data

    public func refresh() async {
        guard let client, !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            async let s: ServerStatus = client.get("/status")
            // "all": every broker's bots and trades (older agents ignore it and send their Revolut X ones)
            async let b: [Bot] = client.get("/bots", query: ["exchange": "all"])
            async let t: [Trade] = client.get("/trades", query: ["limit": "500", "exchange": "all"])
            let (newStatus, newBots, newTrades) = try await (s, b, t)
            // the agent was updated while the app kept running – its strategies may have new settings
            if let old = status?.version, old != newStatus.version {
                strategies = (try? await client.get("/strategies")) ?? strategies
            }
            status = newStatus
            // every broker's statistics, limits and fees – the tabs switch without waiting for the agent
            for broker in loadedBrokers {
                async let sum: Summary = client.get("/summary", query: query(broker))
                async let lim: Limits? = try? client.get("/limits", query: query(broker))
                async let fees: PaperFees? = try? client.get("/paper-fees", query: query(broker))
                summaries[broker] = try await sum
                limitsByBroker[broker] = await lim ?? limitsByBroker[broker]
                paperFeesByBroker[broker] = await fees ?? paperFeesByBroker[broker]
            }
            notifyAboutBlockedBuys(newBots)
            bots = newBots
            notifyAboutNewTrades(newTrades)
            trades = newTrades
            await refreshBalances()
            exchangeInfo = (try? await client.get("/exchange")) ?? exchangeInfo
            if supportsBrokers, let info: TradeRepublicInfo = try? await client.get("/traderepublic") {
                notifyAboutTradeRepublic(info)
                tradeRepublic = info
            }
            if loadedBrokers.contains(where: { pairsByBroker[$0]?.isEmpty ?? true }) { await loadPairs() }
            lastUpdate = Date()
            connection = .connected
        } catch {
            connection = .failed(error.localizedDescription)
        }
    }

    /// iPhone background refresh: only the latest trades and the bots – enough to tell about new trades and
    /// blocked buys within the few seconds the system grants. Returns false when the agent was not reachable.
    public func backgroundRefresh() async -> Bool {
        guard isConfigured else { return false }
        do {
            let client = try self.client ?? APIClient(server: serverURL, token: token)
            self.client = client
            async let b: [Bot] = client.get("/bots", query: ["exchange": "all"])
            async let t: [Trade] = client.get("/trades", query: ["limit": "50", "exchange": "all"])
            let (newBots, newTrades) = try await (b, t)
            notifyAboutBlockedBuys(newBots)
            bots = newBots
            notifyAboutNewTrades(newTrades)
            return true
        } catch {
            return false
        }
    }

    public func events(for botId: Int) async -> [BotEvent] {
        guard let client else { return [] }
        return (try? await client.get("/events", query: ["bot_id": String(botId), "limit": "50"])) ?? []
    }

    public func decisions(for botId: Int) async -> [AiDecision] {
        guard let client else { return [] }
        return (try? await client.get("/bots/\(botId)/decisions", query: ["limit": "100"])) ?? []
    }

    /// The trade history for the profit chart – more than the latest trades the panel keeps (agent maximum: 1000),
    /// of the selected broker only, so a busy broker doesn't push the other one's history out of the window.
    public func allTrades(limit: Int) async -> [Trade]? {
        guard let client else { return nil }
        return try? await client.get("/trades", query: query(broker, ["limit": String(limit)]))
    }

    public func strategy(_ key: String) -> Strategy? { strategies.first { $0.key == key } }

    // MARK: - Bot actions

    @discardableResult
    public func saveBot(id: Int?, input: BotInput) async throws -> Bot {
        guard let client else { throw APIError.invalidURL }
        let bot: Bot
        if let id {
            bot = try await client.send("PUT", "/bots/\(id)", body: input)
        } else {
            bot = try await client.send("POST", "/bots", body: input)
        }
        await refresh()
        return bot
    }

    /// The selected broker's limits.
    public func saveLimits(_ newLimits: Limits) async throws {
        guard let client else { return }
        let broker = self.broker
        limitsByBroker[broker] = try await client.send("PUT", "/limits", query: query(broker), body: newLimits)
        await refresh()
    }

    /// The selected broker's simulation fees.
    public func savePaperFees(_ fees: PaperFees) async throws {
        guard let client else { return }
        let broker = self.broker
        paperFeesByBroker[broker] = try await client.send("PUT", "/paper-fees", query: query(broker), body: fees)
        await refresh()
    }

    // MARK: - Live trading

    /// Switches the selected broker. Switching on requires the explicit "LIVE" confirmation (the UI asks twice
    /// before calling this).
    @discardableResult
    public func setLiveTrading(_ enabled: Bool) async throws -> [LiveSwitchResult.ClosedPosition] {
        guard let client else { return [] }
        struct Body: Encodable { let enabled: Bool; let confirm: String?; let exchange: String? }
        let result: LiveSwitchResult = try await client.send(
            "PUT", "/live-trading",
            body: Body(enabled: enabled, confirm: enabled ? "LIVE" : nil, exchange: supportsBrokers ? broker.rawValue : nil)
        )
        await refresh()
        return result.closedPositions
    }

    // MARK: - Revolut X setup

    public func generateKeypair() async throws {
        guard let client else { return }
        exchangeInfo = try await client.post("/exchange/keypair")
    }

    public func saveApiKey(_ apiKey: String) async throws {
        guard let client else { return }
        struct Body: Encodable { let api_key: String }
        exchangeInfo = try await client.send("PUT", "/exchange/credentials", body: Body(api_key: apiKey))
        await loadPairs()
        await refresh()
    }

    public func removeExchangeCredentials() async throws {
        guard let client else { return }
        try await client.delete("/exchange/credentials")
        await refresh()
    }

    // MARK: - Brokers on/off

    /// Switches a broker off (its bots stop, the agent leaves it alone) or on again. With one broker on, the app
    /// shows no tabs.
    public func setBrokerEnabled(_ broker: Broker, _ enabled: Bool) async throws {
        guard let client else { return }
        struct Body: Encodable { let enabled: Bool }
        status = try await client.send("PUT", "/brokers/\(broker.rawValue)", body: Body(enabled: enabled))
        await refresh()
    }

    // MARK: - Trade Republic login

    /// Phone number and PIN to the agent – Trade Republic then asks for the confirmation in its app.
    public func startTradeRepublicLogin(phone: String?, pin: String?, rememberPin: Bool) async throws {
        guard let client else { return }
        struct Body: Encodable { let phone: String?; let pin: String?; let remember_pin: Bool }
        tradeRepublic = try await client.send("POST", "/traderepublic/login", body: Body(phone: phone, pin: pin, remember_pin: rememberPin))
        watchTradeRepublicLogin()
    }

    public func submitTradeRepublicCode(_ code: String) async throws {
        guard let client else { return }
        struct Body: Encodable { let code: String }
        tradeRepublic = try await client.send("POST", "/traderepublic/login/code", body: Body(code: code))
        watchTradeRepublicLogin()
    }

    public func cancelTradeRepublicLogin() async {
        guard let client else { return }
        try? await client.delete("/traderepublic/login")
        tradeRepublic = (try? await client.get("/traderepublic")) ?? tradeRepublic
    }

    /// Logs out and forgets phone number and PIN on the agent; live trading on Trade Republic is switched off.
    public func logoutTradeRepublic() async throws {
        guard let client else { return }
        try await client.delete("/traderepublic")
        await refresh()
    }

    /// While the agent waits for the confirmation in the Trade Republic app: ask every 2 seconds instead of
    /// waiting for the next refresh, so the app shows "logged in" right after the confirmation.
    private func watchTradeRepublicLogin() {
        loginWatch?.cancel()
        loginWatch = Task { [weak self] in
            for _ in 0..<120 {
                try? await Task.sleep(for: .seconds(2))
                guard let self, !Task.isCancelled, let client = self.client else { return }
                guard let info: TradeRepublicInfo = try? await client.get("/traderepublic") else { continue }
                self.tradeRepublic = info
                if !info.waiting {
                    await self.refresh()
                    return
                }
            }
        }
    }

    /// Trade Republic search (or the known instruments without a query) – for the bot editor.
    public func instruments(_ query: String, broker: Broker) async throws -> [Instrument] {
        guard let client else { return [] }
        return try await client.get("/instruments", query: self.query(broker, query.isEmpty ? [:] : ["q": query]))
    }

    /// What an order costs on the broker: a rate of its value and a fixed amount (Trade Republic: 1 €).
    public func fees(for broker: Broker, paper: Bool) -> (rate: Double, fixed: Double) {
        if paper, let fees = paperFeesByBroker[broker] { return (fees.sell, fees.fixed ?? 0) }
        if let fees = status?.exchange(broker)?.fees { return (fees.rate, fees.fixed) }
        return (status?.takerFee ?? TradeCostCheck.defaultFeeRate, 0)
    }

    public func serverPublicIP() async -> String? {
        guard let client else { return nil }
        let result: PublicIP? = try? await client.get("/exchange/public-ip")
        return result?.ip
    }

    public func setRunning(_ bot: Bot, _ running: Bool) async throws {
        guard let client else { return }
        let _: Bot = try await client.post("/bots/\(bot.id)/\(running ? "start" : "stop")")
        // the engine evaluates started bots right away – give it a moment
        if running { try? await Task.sleep(for: .milliseconds(700)) }
        await refresh()
    }

    /// Sells one trade (`positionId`) or all of the bot's trades at market.
    public func closePosition(_ bot: Bot, positionId: String? = nil) async throws {
        guard let client else { return }
        let _: Bot = try await client.post("/bots/\(bot.id)/close", query: positionId.map { ["position_id": $0] } ?? [:])
        await refresh()
    }

    /// Paper only: deletes the bot's simulated trades and open paper trades – its result starts at zero.
    public func resetPaper(_ bot: Bot) async throws {
        guard let client else { return }
        let _: Bot = try await client.post("/bots/\(bot.id)/reset-paper")
        await refresh()
    }

    /// Paper mode: deletes all simulated trades of the selected broker and discards its open paper trades – the
    /// broker's values start at zero. Live trades are never touched.
    public func resetPaperBroker() async throws {
        guard let client else { return }
        let _: Summary = try await client.post("/reset-paper", query: query(broker))
        await refresh()
    }

    /// "AI decides" only: a fresh decision from Claude right now (one extra check).
    public func askClaude(_ bot: Bot) async throws {
        guard let client else { return }
        let _: Bot = try await client.post("/bots/\(bot.id)/ask")
        await refresh()
    }

    /// Removes the position from the agent's books without selling anything.
    public func discardPosition(_ bot: Bot, positionId: String? = nil) async throws {
        guard let client else { return }
        let _: Bot = try await client.post("/bots/\(bot.id)/discard", query: positionId.map { ["position_id": $0] } ?? [:])
        await refresh()
    }

    public func deleteBot(_ bot: Bot, force: Bool) async throws {
        guard let client else { return }
        try await client.delete("/bots/\(bot.id)", query: force ? ["force": "true"] : [:])
        await refresh()
    }

    // MARK: - Backup

    /// The agent's backup (.tgz) and the file name it suggests – the app lets the user save it.
    public func backupData() async throws -> (data: Data, suggestedName: String) {
        guard let client else { throw APIError.invalidURL }
        let (data, suggestedName) = try await client.download("/backup")
        return (data, suggestedName ?? "dipagentx-backup.tgz")
    }

    /// Restores a backup file on the agent – replaces all of its data.
    public func restoreBackup(_ data: Data) async throws -> RestoreResult {
        guard let client else { throw APIError.invalidURL }
        let result: RestoreResult = try await client.upload("/restore", data: data, contentType: "application/gzip")
        pairsByBroker = [:]
        await refresh()
        return result
    }

    // MARK: - Notifications

    private func requestNotificationPermission() {
        guard Bundle.main.bundleIdentifier != nil else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    /// A bot's buy signal was skipped by the limits (new since the last refresh): the hint is on the card,
    /// but the user may not be looking – say it once. Not on the first load: an old hint is not news.
    private func notifyAboutBlockedBuys(_ newBots: [Bot]) {
        guard notificationsEnabled, Bundle.main.bundleIdentifier != nil, !bots.isEmpty else { return }
        for bot in newBots {
            guard bot.enabled, let hint = bot.hint, let before = bots.first(where: { $0.id == bot.id }), before.hint == nil else { continue }
            let content = UNMutableNotificationContent()
            content.title = String(localized: "\(bot.name): buy blocked")
            content.body = hint
            content.sound = .default
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "hint-\(bot.id)", content: content, trigger: nil))
        }
    }

    /// The agent started the daily Trade Republic login on its own (or the login ended): the user has to confirm it
    /// in the Trade Republic app – say so once.
    private func notifyAboutTradeRepublic(_ info: TradeRepublicInfo) {
        guard notificationsEnabled, Bundle.main.bundleIdentifier != nil, let before = tradeRepublic else { return }
        let content = UNMutableNotificationContent()
        if info.waiting && info.automatic && !before.waiting {
            content.title = String(localized: "Confirm the Trade Republic login")
            content.body = String(localized: "DipAgentX logs in again for the next 24 hours – confirm it in the Trade Republic app.")
        } else if before.connected && !info.connected && !info.waiting && !info.isDemo {
            content.title = String(localized: "Trade Republic logged out")
            content.body = info.error ?? String(localized: "Log in again in the settings so the bots can trade live.")
        } else {
            return
        }
        content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "tr-login", content: content, trigger: nil))
    }

    /// One notification per new trade – after a long break (iPhone: the app was closed) just one for all of them.
    private func notifyAboutNewTrades(_ newTrades: [Trade]) {
        let maxId = newTrades.map(\.id).max()
        defer { if let maxId { lastSeenTradeId = max(lastSeenTradeId ?? 0, maxId) } }
        guard notificationsEnabled, Bundle.main.bundleIdentifier != nil, let seen = lastSeenTradeId else { return }
        let fresh = newTrades.filter { $0.id > seen }
        if fresh.count > 5 {
            let content = UNMutableNotificationContent()
            content.title = "DipAgentX"
            content.body = String(localized: "\(String(fresh.count)) new trades")
            content.sound = .default
            UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "trades-\(maxId ?? 0)", content: content, trigger: nil))
            return
        }
        for trade in fresh {
            let content = UNMutableNotificationContent()
            content.title = trade.isBuy
                ? String(localized: "\(trade.botName) buys \(trade.base)")
                : String(localized: "\(trade.botName) sells \(trade.base)")
            var body = String(localized: "\(Fmt.qty(trade.baseQty)) \(trade.base) at \(Fmt.price(trade.price, trade.quote))")
            if let pnl = trade.pnl { body += " · " + String(localized: "Result \(Fmt.money(pnl, trade.quote, signed: true))") }
            if trade.paper { body += " (Paper)" }
            content.body = body
            content.sound = .default
            let request = UNNotificationRequest(identifier: "trade-\(trade.id)", content: content, trigger: nil)
            UNUserNotificationCenter.current().add(request)
        }
    }
}
