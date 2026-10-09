import SwiftUI

/// "i" in the bot details: how the bot works exactly (the strategy, every setting with its value and what it does)
/// and the state it is in right now – a sheet on the iPhone, a popover on the Mac.
public struct BotInfoButton: View {
    let bot: Bot
    @State private var open = false

    public init(bot: Bot) { self.bot = bot }

    public var body: some View {
        Button { open = true } label: {
            Image(systemName: "info.circle")
                .font(.system(size: 17, weight: .medium))
                .accessibilityLabel(Text("How this bot works"))
        }
        .help(Text("How this bot works"))
        #if os(macOS)
        .buttonStyle(.plain)
        .popover(isPresented: $open, arrowEdge: .bottom) {
            ScrollView { BotInfoView(bot: bot).padding(16) }
                .frame(width: 420, height: 560)
        }
        #else
        .sheet(isPresented: $open) {
            NavigationStack {
                ScrollView { BotInfoView(bot: bot).padding() }
                    .navigationTitle(Text("How this bot works"))
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar { Button("Done") { open = false } }
            }
            .presentationDetents([.large])
        }
        #endif
    }
}

/// The explanation itself: the strategy in words, the bot's settings one by one, the state now.
public struct BotInfoView: View {
    let bot: Bot
    @Environment(AppStore.self) private var store

    public init(bot: Bot) { self.bot = bot }

    private var strategy: Strategy? { store.strategies.first { $0.key == bot.strategy } }

    public var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            header
            if let strategy {
                section("How it works") {
                    Text(verbatim: strategy.description)
                        .font(.ui(13))
                        .fixedSize(horizontal: false, vertical: true)
                }
                section("Your settings") { settings(strategy) }
            }
            section("State now") { state }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var header: some View {
        HStack(spacing: 12) {
            StrategyIcon(strategy: bot.strategy, symbol: bot.strategyIcon, coin: bot.baseCurrency, size: 44)
            VStack(alignment: .leading, spacing: 3) {
                Text(verbatim: bot.name).font(.ui(16, weight: .bold))
                Text(verbatim: "\(bot.strategyName) · \(bot.symbol)").font(.ui(12)).foregroundStyle(.secondary)
            }
        }
    }

    private func section<Content: View>(_ title: LocalizedStringKey, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.ui(11, weight: .semibold)).foregroundStyle(.secondary).textCase(.uppercase)
            content()
        }
    }

    // MARK: Settings

    private func settings(_ strategy: Strategy) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(strategy.params) { param in
                let value = bot.params[param.key] ?? param.default
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(verbatim: param.label).font(.ui(12.5, weight: .medium))
                        Spacer(minLength: 8)
                        Text(verbatim: ParamFormatting.display(param, value, currency: bot.quoteCurrency))
                            .font(.ui(12.5, weight: .semibold)).monospacedDigit()
                            .multilineTextAlignment(.trailing)
                    }
                    if let help = param.help, !help.isEmpty {
                        Text(verbatim: help)
                            .font(.ui(11)).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    // MARK: State

    @ViewBuilder private var state: some View {
        VStack(alignment: .leading, spacing: 10) {
            row("Running", bot.enabled ? String(localized: "Yes") : String(localized: "No – stopped"))
            row("Mode", bot.paper ? String(localized: "Paper trading (simulated)") : String(localized: "Live on the exchange"))
            if let last = bot.lastCheck, last > 0 {
                HStack(alignment: .firstTextBaseline) {
                    Text("Last check").font(.ui(12.5))
                    Spacer()
                    Text(Date(timeIntervalSince1970: Double(last) / 1000), style: .relative)
                        .font(.ui(12.5, weight: .semibold))
                }
            }
            if bot.pendingOrder {
                Label("An order is waiting to be filled", systemImage: "hourglass").font(.ui(12)).foregroundStyle(.orange)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("Status").font(.ui(12.5))
                Text(verbatim: bot.enabled ? (bot.status.isEmpty ? String(localized: "Waiting for the first check …") : bot.status)
                                           : String(localized: "Stopped"))
                    .font(.ui(12.5, weight: .medium))
                    .foregroundStyle(bot.statusError == true ? Color.red : Color.primary)
                    .fixedSize(horizontal: false, vertical: true)
                if let hint = bot.hint {
                    Label(hint, systemImage: "exclamationmark.triangle.fill")
                        .font(.ui(11.5, weight: .medium)).foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if bot.enabled, bot.goal != nil || bot.targets?.note != nil {
                GoalLines(bot: bot)
            }
            if let signals = bot.signals, !signals.isEmpty {
                IndicatorsList(signals: signals, decision: bot.decision, lookbacks: bot.lookbacks)
            }
            Divider()
            if bot.openTrades.isEmpty {
                row("Open trades", String(localized: "None"))
            } else {
                row("Open trades", String(bot.openTrades.count))
                if let pos = bot.position {
                    row("Invested", Fmt.money(pos.cost, bot.quoteCurrency))
                    row("Average entry", Fmt.price(pos.entryPrice, bot.quoteCurrency))
                    row("Open result", "\(Fmt.money(pos.unrealizedPnl, bot.quoteCurrency, signed: true)) (\(Fmt.pct(pos.unrealizedPct)))",
                        color: pos.unrealizedPnl.pnlColor)
                }
            }
            row("Closed trades", "\(bot.tradesCount) (\(bot.wins) + / \(bot.losses) −)")
            row("Realized result", Fmt.money(bot.realizedPnl, bot.quoteCurrency, signed: true), color: bot.realizedPnl.pnlColor)
            if let fees = bot.fees, fees > 0 { row("Fees paid", Fmt.money(fees, bot.quoteCurrency)) }
        }
    }

    private func row(_ label: LocalizedStringKey, _ value: String, color: Color = .primary) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).font(.ui(12.5))
            Spacer(minLength: 8)
            Text(verbatim: value).font(.ui(12.5, weight: .semibold)).monospacedDigit().foregroundStyle(color)
        }
    }
}
