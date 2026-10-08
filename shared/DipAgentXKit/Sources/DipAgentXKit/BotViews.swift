import SwiftUI

/// How the bot list is ordered (within "Active" and "Stopped").
public enum BotSort: String, CaseIterable, Identifiable {
    case running, result, name, newest
    public var id: String { rawValue }

    public var title: LocalizedStringKey {
        switch self {
        case .running: return "Running first"
        case .result: return "Result"
        case .name: return "Name"
        case .newest: return "Newest"
        }
    }

    /// Stable: bots that compare equal keep their order from the agent.
    public func apply(_ bots: [Bot]) -> [Bot] {
        let indexed = bots.enumerated().map { ($0.offset, $0.element) }
        let sorted: [(Int, Bot)]
        switch self {
        case .running:
            sorted = indexed.sorted { ($0.1.position == nil ? 1 : 0, $0.0) < ($1.1.position == nil ? 1 : 0, $1.0) }
        case .result:
            sorted = indexed.sorted { ($0.1.totalPnl, -$0.0) > ($1.1.totalPnl, -$1.0) }
        case .name:
            sorted = indexed.sorted { ($0.1.name.localizedCaseInsensitiveCompare($1.1.name), $0.0) < (.orderedSame, $1.0) }
        case .newest:
            sorted = indexed.sorted { ($0.1.createdAt, -$0.0) > ($1.1.createdAt, -$1.0) }
        }
        return sorted.map(\.1)
    }
}

extension ComparisonResult: @retroactive Comparable {
    public static func < (lhs: ComparisonResult, rhs: ComparisonResult) -> Bool { lhs.rawValue < rhs.rawValue }
}

/// "−1.80% to buy" first, then the trigger price, the stop and the current price in small print.
/// Strategies without a fixed trigger show their note (or the price) instead.
public struct GoalLines: View {
    let bot: Bot
    var large = false

    public init(bot: Bot, large: Bool = false) {
        self.bot = bot
        self.large = large
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: large ? 3 : 2) {
            if let goal = bot.goal {
                Text(headline(goal))
                    .font(.ui(large ? 17 : 12, weight: .semibold, design: large ? .rounded : .default))
                    .foregroundStyle(goal.reached ? Color.accentColor : Color.primary)
            } else if let note = bot.targets?.note {
                Text(note).font(.ui(large ? 17 : 12, weight: .medium, design: large ? .rounded : .default))
            } else if let market = bot.market {
                Text(Fmt.price(market.price, bot.quoteCurrency)).font(.ui(12, weight: .medium))
            }
            if let details {
                // up to two lines: with open trades both buy conditions are listed
                Text(verbatim: details)
                    .font(.ui(large ? 11 : 10)).foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .monospacedDigit()
        .lineLimit(1)
    }

    private func headline(_ goal: BotGoal) -> String {
        let pct = Fmt.pct(goal.percent)
        switch (goal.kind, goal.reached) {
        case (.buy, false) where !bot.openTrades.isEmpty: return String(localized: "\(pct) to the next trade")
        case (.buy, false): return String(localized: "\(pct) to buy")
        case (.buy, true): return String(localized: "Buy price reached")
        case (.sell, false): return String(localized: "\(pct) to sell")
        case (.sell, true): return String(localized: "Sell price reached")
        case (.trailingStart, false): return String(localized: "\(pct) until trailing starts")
        case (.trailingStart, true): return String(localized: "Trailing starts")
        case (.trailingStop, false): return String(localized: "\(pct) to the trailing stop")
        case (.trailingStop, true): return String(localized: "Trailing stop reached")
        }
    }

    /// Trigger price, stop and current price; the 24 h change only while the line has room for it.
    private var details: String? {
        guard let market = bot.market else { return nil }
        let q = bot.quoteCurrency
        var parts: [String] = []
        if let goal = bot.goal {
            switch goal.kind {
            case .buy:
                if let signal = bot.targets?.signalPrice, let spacing = bot.targets?.spacingPrice {
                    // both must be reached – show each with its distance, so it is clear which one holds the buy back
                    func distance(_ price: Double) -> String {
                        market.price <= price ? String(localized: "already reached") : Fmt.pct((price / market.price - 1) * 100)
                    }
                    parts.append(String(localized: "Buy threshold ≤ \(Fmt.price(signal, q)) (\(distance(signal)))"))
                    parts.append(String(localized: "Distance to open trades ≤ \(Fmt.price(spacing, q)) (\(distance(spacing)))"))
                } else {
                    parts.append(String(localized: "Buy at ≤ \(Fmt.price(goal.target, q))"))
                }
            case .sell: parts.append(String(localized: "Sell at ≥ \(Fmt.price(goal.target, q))"))
            case .trailingStart: parts.append(String(localized: "Trailing from \(Fmt.price(goal.target, q))"))
            case .trailingStop: parts.append(String(localized: "Trailing stop \(Fmt.price(goal.target, q))"))
            }
        }
        if bot.position != nil, let stop = bot.targets?.stopPrice {
            parts.append(String(localized: "Stop \(Fmt.price(stop, q))"))
        }
        if !parts.isEmpty || bot.targets?.note != nil {
            parts.append(String(localized: "Price \(Fmt.price(market.price, q))"))
        }
        if parts.count < 3 {
            parts.append(String(localized: "\(Fmt.pct(market.change24h)) 24h"))
        }
        return parts.joined(separator: " · ")
    }
}

public struct StatusLine: View {
    let bot: Bot

    public init(bot: Bot) { self.bot = bot }
    @Environment(AppStore.self) private var store
    @State private var pulse = false

    /// The pulse redraws the view every frame – only while it can be seen (a hidden macOS panel keeps animating otherwise).
    private var pulsing: Bool { bot.enabled && store.isVisible }

    public var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 6, height: 6)
                .opacity(pulse ? 0.35 : 1)
                .padding(.top, 4)
                .onChange(of: pulsing, initial: true) { _, on in
                    // a new non-repeating transaction replaces the running repeatForever animation
                    withAnimation(on ? .easeInOut(duration: 1).repeatForever() : .default) { pulse = on }
                }
            VStack(alignment: .leading, spacing: 3) {
                if let split = statusWithSignals {
                    // the status, then each indicator with a small traffic light: green lets the bot invest,
                    // orange holds it partly back, red keeps it out
                    if !split.head.isEmpty {
                        Text(verbatim: split.head).font(.ui(10.5)).foregroundStyle(.secondary)
                    }
                    FlowLayout(spacing: 8, lineSpacing: 3) {
                        ForEach(Array(split.signals.enumerated()), id: \.offset) { _, signal in
                            HStack(spacing: 4) {
                                TrafficLight(tone: signal.tone)
                                Text(verbatim: signal.text).font(.ui(10.5)).foregroundStyle(.secondary)
                            }
                        }
                    }
                } else {
                    Text(statusText)
                        .font(.ui(10.5))
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if bot.enabled, let hint = bot.hint {
                    Label(hint, systemImage: "exclamationmark.triangle.fill")
                        .font(.ui(10.5, weight: .medium))
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    /// The status split into its plain part and the strategy's indicators (when the agent sends them).
    private var statusWithSignals: (head: String, signals: [BotSignal])? {
        let text = statusText
        guard bot.enabled, let signals = bot.signals, let first = signals.first,
              let range = text.range(of: first.text) else { return nil }
        let head = String(text[..<range.lowerBound]).trimmingCharacters(in: .whitespaces)
        return (head.hasSuffix("·") ? String(head.dropLast()).trimmingCharacters(in: .whitespaces) : head, signals)
    }

    private var statusText: String {
        guard bot.enabled else { return String(localized: "Stopped") }
        return bot.status.isEmpty ? String(localized: "Waiting for the first check …") : bot.status
    }

    private var color: Color {
        if !bot.enabled { return .gray }
        if bot.statusError == true { return .red }
        if bot.pendingOrder { return .yellow }
        return .green
    }
}

public struct PositionStrip: View {
    let bot: Bot
    let position: BotPosition

    public init(bot: Bot, position: BotPosition) {
        self.bot = bot
        self.position = position
    }

    public var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text("Open position")
                    .font(.ui(9.5, weight: .semibold))
                    .foregroundStyle(.secondary)
                // how big the position is: its current value and what went in
                Text("Value \(Fmt.money(position.value, bot.quoteCurrency)) · invested \(Fmt.money(position.cost, bot.quoteCurrency))")
                    .font(.ui(10.5, weight: .medium)).monospacedDigit()
                Text("\(Fmt.qty(position.qty)) \(bot.baseCurrency) · entry \(Fmt.price(position.entryPrice, bot.quoteCurrency))")
                    .font(.ui(9.5)).foregroundStyle(.secondary).monospacedDigit()
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 1) {
                PnLText(value: position.unrealizedPnl, currency: bot.quoteCurrency, font: .ui(11, weight: .semibold))
                Text(Fmt.pct(position.unrealizedPct))
                    .font(.ui(9.5, weight: .medium))
                    .foregroundStyle(position.unrealizedPct.pnlColor)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color.accentColor.opacity(0.08)))
    }
}

public extension BotSignal {
    /// Green lets the bot invest, orange holds it partly back, red keeps it out.
    var color: Color { tone == "good" ? .green : tone == "bad" ? .red : .orange }
}

/// A small traffic light: the light of the tone is on, the other two are dimmed.
public struct TrafficLight: View {
    let tone: String

    public init(tone: String) { self.tone = tone }

    public var body: some View {
        VStack(spacing: 1.5) {
            light(.red, on: tone == "bad")
            light(.orange, on: tone == "warn")
            light(.green, on: tone == "good")
        }
        .padding(.horizontal, 2)
        .padding(.vertical, 2)
        .background(Capsule().fill(Color.primary.opacity(0.12)))
        .accessibilityElement()
        .accessibilityLabel(tone == "good" ? Text("Green") : tone == "bad" ? Text("Red") : Text("Orange"))
    }

    private func light(_ color: Color, on: Bool) -> some View {
        Circle().fill(on ? color : color.opacity(0.18)).frame(width: 4, height: 4)
    }
}

/// Lays its children out left to right and wraps to the next line when the width runs out.
public struct FlowLayout: Layout {
    var spacing: CGFloat = 8
    var lineSpacing: CGFloat = 4

    public init(spacing: CGFloat = 8, lineSpacing: CGFloat = 4) {
        self.spacing = spacing
        self.lineSpacing = lineSpacing
    }

    public func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = rows(width: proposal.width ?? .infinity, subviews: subviews)
        let width = rows.map { $0.width }.max() ?? 0
        let height = rows.reduce(0) { $0 + $1.height } + lineSpacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: proposal.width ?? width, height: height)
    }

    public func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in rows(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for index in row.items {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y + (row.height - size.height) / 2), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + lineSpacing
        }
    }

    private func rows(width: CGFloat, subviews: Subviews) -> [(items: [Int], width: CGFloat, height: CGFloat)] {
        var rows: [(items: [Int], width: CGFloat, height: CGFloat)] = []
        var current: (items: [Int], width: CGFloat, height: CGFloat) = ([], 0, 0)
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let needed = current.items.isEmpty ? size.width : current.width + spacing + size.width
            if needed > width, !current.items.isEmpty {
                rows.append(current)
                current = ([index], size.width, size.height)
            } else {
                current = (current.items + [index], needed, max(current.height, size.height))
            }
        }
        if !current.items.isEmpty { rows.append(current) }
        return rows
    }
}

/// The strategy's indicators one per line, coloured by what they mean for the decision – and the decision below.
public struct IndicatorsList: View {
    let signals: [BotSignal]
    let decision: String?
    var lookbacks: Lookbacks?

    public init(signals: [BotSignal], decision: String?, lookbacks: Lookbacks? = nil) {
        self.signals = signals
        self.decision = decision
        self.lookbacks = lookbacks
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(signals.enumerated()), id: \.offset) { index, signal in
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Circle().fill(signal.color).frame(width: 7, height: 7)
                    Text(verbatim: signal.text)
                        .font(.ui(12, weight: .medium))
                        .foregroundStyle(signal.color)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if index == 0, let lookbacks, !lookbacks.items.isEmpty {
                    lookbackGrid(lookbacks).padding(.leading, 14).padding(.bottom, 4)
                }
            }
            if let decision {
                Divider().padding(.vertical, 2)
                Text("Decision").font(.ui(10, weight: .semibold)).foregroundStyle(.secondary)
                Text(verbatim: decision)
                    .font(.ui(12, weight: .semibold))
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

extension IndicatorsList {
    /// Every lookback of the trend: how much the price changed over it and whether it counts as up.
    func lookbackGrid(_ lookbacks: Lookbacks) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 3) {
                ForEach(lookbacks.items, id: \.days) { item in
                    GridRow {
                        Text("\(String(item.days)) days").foregroundStyle(.secondary)
                        Text(verbatim: item.change.map { Fmt.pct($0) } ?? "–")
                            .monospacedDigit()
                            .gridColumnAlignment(.trailing)
                        Label { item.up ? Text("Up") : Text("Down") } icon: {
                            Image(systemName: item.up ? "arrow.up.right" : "arrow.down.right")
                        }
                            .foregroundStyle(item.up ? Color.green : Color.red)
                    }
                    .font(.ui(11, weight: .medium))
                }
            }
            if let entry = lookbacks.entry, let exit = lookbacks.exit {
                Text("Up above \(Fmt.pct(entry)), down below \(Fmt.pct(exit)) – in between a lookback stays as it was.")
                    .font(.ui(10)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// "Indicators": opens the strategy's indicators in colour and the decision – a popover on the Mac, a sheet on
/// the iPhone.
public struct IndicatorsButton: View {
    let bot: Bot
    @State private var open = false

    public init(bot: Bot) { self.bot = bot }

    public var body: some View {
        if let signals = bot.signals, !signals.isEmpty {
            Button { open = true } label: {
                Label("Indicators", systemImage: "gauge.with.dots.needle.33percent")
            }
            #if os(macOS)
            .controlSize(.small)
            .popover(isPresented: $open, arrowEdge: .bottom) {
                IndicatorsList(signals: signals, decision: bot.decision, lookbacks: bot.lookbacks)
                    .padding(14)
                    .frame(width: 340)
            }
            #else
            .buttonStyle(.bordered)
            .sheet(isPresented: $open) {
                NavigationStack {
                    ScrollView {
                        IndicatorsList(signals: signals, decision: bot.decision, lookbacks: bot.lookbacks)
                            .padding()
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .navigationTitle(Text("Indicators"))
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar { Button("Done") { open = false } }
                }
                .presentationDetents([.medium])
            }
            #endif
        }
    }
}

/// Several open trades on the card: the count and their result, then one line per trade.
public struct TradesStrip: View {
    let bot: Bot

    public init(bot: Bot) { self.bot = bot }

    public var body: some View {
        let trades = bot.openTrades
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text("Open trades \(String(trades.count))/\(String(bot.maxTrades ?? trades.count))")
                    .font(.ui(9.5, weight: .semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                PnLText(value: trades.reduce(0) { $0 + $1.unrealizedPnl }, currency: bot.quoteCurrency,
                        font: .ui(11, weight: .semibold))
            }
            ForEach(Array(trades.enumerated()), id: \.offset) { index, trade in
                OpenTradeRow(bot: bot, trade: trade, number: index + 1)
            }
        }
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color.accentColor.opacity(0.08)))
    }
}

/// The trades a sliced position (momentum follower) is made of, oldest first: when bought, how much, at what
/// price, what it is worth now.
public struct SlicesList: View {
    let bot: Bot

    public init(bot: Bot) { self.bot = bot }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(bot.openTrades.enumerated()), id: \.offset) { index, trade in
                HStack(spacing: 6) {
                    Text(verbatim: "\(index + 1)")
                        .font(.ui(9, weight: .bold)).foregroundStyle(.secondary)
                        .frame(width: 16, height: 16)
                        .background(Circle().fill(Color.primary.opacity(0.08)))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(verbatim: "\(Fmt.qty(trade.qty)) \(bot.baseCurrency)")
                            .font(.ui(10.5, weight: .medium))
                        Text(Date(ms: trade.openedAt).formatted(date: .abbreviated, time: .shortened))
                            .font(.ui(9.5)).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 4)
                    VStack(alignment: .trailing, spacing: 1) {
                        Text("Entry \(Fmt.price(trade.entryPrice, bot.quoteCurrency))")
                            .font(.ui(10)).foregroundStyle(.secondary)
                        HStack(spacing: 4) {
                            Text(verbatim: Fmt.money(trade.value, bot.quoteCurrency)).font(.ui(10.5, weight: .medium))
                            Text(Fmt.pct(trade.unrealizedPct))
                                .font(.ui(10, weight: .medium)).foregroundStyle(trade.unrealizedPct.pnlColor)
                        }
                    }
                }
                .monospacedDigit()
            }
        }
    }
}

/// "1  Value 251.20 € · +1.20 %      Target 2,460 €"
public struct OpenTradeRow: View {
    let bot: Bot
    let trade: BotPosition
    let number: Int

    public init(bot: Bot, trade: BotPosition, number: Int) {
        self.bot = bot
        self.trade = trade
        self.number = number
    }

    public var body: some View {
        HStack(spacing: 6) {
            Text(verbatim: "\(number)")
                .font(.ui(9, weight: .bold)).foregroundStyle(.secondary)
                .frame(width: 14, height: 14)
                .background(Circle().fill(Color.primary.opacity(0.08)))
            Text("Value \(Fmt.money(trade.value, bot.quoteCurrency))")
                .font(.ui(10.5, weight: .medium))
            Text(Fmt.pct(trade.unrealizedPct))
                .font(.ui(10, weight: .medium)).foregroundStyle(trade.unrealizedPct.pnlColor)
            Spacer(minLength: 4)
            if let line = Self.targetText(trade, bot: bot) {
                Text(verbatim: line).font(.ui(10)).foregroundStyle(.secondary).lineLimit(1)
            }
        }
        .monospacedDigit()
    }

    /// The trade's own goal: its sale price, else its stop, else the strategy's note.
    public static func targetText(_ trade: BotPosition, bot: Bot) -> String? {
        let q = bot.quoteCurrency
        if let sell = trade.sellPrice, let price = bot.market?.price, price > 0 {
            let label = bot.usesTrailingStop && sell < price
                ? String(localized: "Trailing stop \(Fmt.price(sell, q))")
                : String(localized: "Target \(Fmt.price(sell, q))")
            return "\(label) (\(Fmt.pct((sell / price - 1) * 100)))"
        }
        if let stop = trade.stopPrice { return String(localized: "Stop \(Fmt.price(stop, q))") }
        return trade.note
    }
}

/// One of Claude's answers: action badge, confidence bar, reason, price and time.
public struct DecisionRow: View {
    let decision: AiDecision
    let currency: String

    public init(decision: AiDecision, currency: String) {
        self.decision = decision
        self.currency = currency
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Badge(text: actionText, color: actionColor, icon: actionIcon)
                ConfidenceBar(value: decision.confidence, color: actionColor)
                Text(verbatim: "\(decision.confidence) %")
                    .font(.ui(10.5, weight: .semibold)).monospacedDigit()
                    .foregroundStyle(actionColor)
                Spacer()
                Text(Date(ms: decision.createdAt).formatted(date: .abbreviated, time: .shortened))
                    .font(.ui(9.5)).foregroundStyle(.tertiary)
            }
            Text(decision.reason)
                .font(.ui(10.5))
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                Text(Fmt.price(decision.price, currency)).monospacedDigit()
                if let profit = decision.profitPct {
                    Text(verbatim: "·")
                    Text(Fmt.pct(profit)).foregroundStyle(profit.pnlColor).monospacedDigit()
                }
            }
            .font(.ui(9.5)).foregroundStyle(.secondary)
        }
    }

    private var actionText: LocalizedStringKey {
        switch decision.action {
        case "buy": return "BUY"
        case "sell": return "SELL"
        case "hold": return "HOLD"
        default: return "WAIT"
        }
    }

    private var actionColor: Color {
        switch decision.action {
        case "buy": return .green
        case "sell": return .orange
        case "hold": return .blue
        default: return .gray
        }
    }

    private var actionIcon: String {
        switch decision.action {
        case "buy": return "arrow.down.circle.fill"
        case "sell": return "arrow.up.circle.fill"
        case "hold": return "hand.raised.fill"
        default: return "clock.fill"
        }
    }
}

/// 0–100 as a thin bar – the "score" of a decision.
public struct ConfidenceBar: View {
    let value: Int
    let color: Color

    public init(value: Int, color: Color) {
        self.value = value
        self.color = color
    }

    public var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.08))
                Capsule().fill(color.opacity(0.8)).frame(width: geo.size.width * CGFloat(max(0, min(value, 100))) / 100)
            }
        }
        .frame(width: 60, height: 5)
    }
}
