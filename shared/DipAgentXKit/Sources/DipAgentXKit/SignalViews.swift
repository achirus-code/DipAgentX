import SwiftUI

/// The signals behind a strategy's decision, one line each: what it looks at, its value, and how far it is from
/// turning. Used by the monthly trend follower (trend, recession signs, dollar, bonds to park in).
public struct SignalList: View {
    let signals: BotSignals
    var compact = true

    public init(signals: BotSignals, compact: Bool = true) {
        self.signals = signals
        self.compact = compact
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 9 : 12) {
            ForEach(signals.rows) { row in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: Self.icon(row.state))
                        .foregroundStyle(Self.color(row.state))
                        .font(.ui(compact ? 11 : 15))
                        .frame(width: compact ? 14 : 20)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(verbatim: row.label)
                            .font(.ui(compact ? 11 : 15, weight: .medium))
                        Text(verbatim: row.value)
                            .font(.ui(compact ? 10.5 : 13)).foregroundStyle(.secondary)
                        if let note = row.note {
                            Text(verbatim: note)
                                .font(.ui(compact ? 10.5 : 13, weight: .medium))
                                .foregroundStyle(Self.color(row.state))
                        }
                    }
                    .monospacedDigit()
                    .fixedSize(horizontal: false, vertical: true)
                }
            }
            if !signals.history.isEmpty {
                MonthStrip(history: signals.history, compact: compact)
                    .padding(.top, 2)
            }
        }
    }

    static func icon(_ state: String?) -> String {
        switch state {
        case "on": return "checkmark.circle.fill"
        case "off": return "xmark.circle.fill"
        case "ok": return "checkmark.circle"
        case "warn": return "exclamationmark.triangle.fill"
        case "unknown": return "questionmark.circle"
        default: return "circle"
        }
    }

    static func color(_ state: String?) -> Color {
        switch state {
        case "on", "ok": return .profit
        case "off": return .red
        case "warn": return .orange
        default: return .secondary
        }
    }
}

/// The monthly decisions so far: one block per month – invested, hedged, parked in bonds or in cash.
public struct MonthStrip: View {
    let history: [BotSignals.Month]
    var compact = true

    public init(history: [BotSignals.Month], compact: Bool = true) {
        self.history = history
        self.compact = compact
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 3) {
                ForEach(history) { month in
                    RoundedRectangle(cornerRadius: 2.5, style: .continuous)
                        .fill(Self.color(month.state))
                        .frame(width: compact ? 12 : 14, height: compact ? 12 : 14)
                        .help(Text(verbatim: "\(month.label): \(Self.text(month))"))
                }
            }
            HStack(spacing: 10) {
                if let first = history.first, let last = history.last, first.month != last.month {
                    Text(verbatim: "\(first.label) – \(last.label)")
                } else if let only = history.first {
                    Text(verbatim: only.label)
                }
                ForEach(["in", "hedged", "parked", "cash"].filter { s in history.contains { $0.state == s } }, id: \.self) { state in
                    HStack(spacing: 3) {
                        Circle().fill(Self.color(state)).frame(width: 6, height: 6)
                        Text(Self.title(state))
                    }
                }
            }
            .font(.ui(compact ? 9.5 : 12)).foregroundStyle(.secondary)
        }
    }

    static func color(_ state: String) -> Color {
        switch state {
        case "in": return .profit
        case "hedged": return .blue
        case "parked": return .teal
        default: return .secondary.opacity(0.4)
        }
    }

    static func title(_ state: String) -> LocalizedStringKey {
        switch state {
        case "in": return "Invested"
        case "hedged": return "Hedged"
        case "parked": return "Bonds"
        default: return "Cash"
        }
    }

    static func text(_ month: BotSignals.Month) -> String {
        let state: String
        switch month.state {
        case "in": state = String(localized: "Invested")
        case "hedged": state = String(localized: "Hedged")
        case "parked": state = String(localized: "Bonds")
        default: state = String(localized: "Cash")
        }
        return month.name.map { "\(state) (\($0))" } ?? state
    }
}

/// The trend followers as one portfolio: each bot's share now against the share its amount stands for, and –
/// once they drift apart – the amounts that would restore it.
public struct PillarList: View {
    let pillars: BotPillars
    let currency: String
    let current: Int
    var compact = true

    public init(pillars: BotPillars, currency: String, current: Int, compact: Bool = true) {
        self.pillars = pillars
        self.currency = currency
        self.current = current
        self.compact = compact
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: compact ? 8 : 11) {
            ForEach(pillars.shares) { share in
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(verbatim: share.name)
                            .font(.ui(compact ? 11 : 15, weight: share.id == current ? .semibold : .regular))
                        Spacer()
                        Text(verbatim: "\(Self.share(share.actual)) / \(Self.share(share.target))")
                            .font(.ui(compact ? 11 : 15, weight: .medium))
                            .foregroundStyle(abs(share.actual - share.target) >= 5 ? Color.orange : Color.primary)
                    }
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(Color.primary.opacity(0.08))
                            Capsule().fill(Color.accentColor.opacity(0.8))
                                .frame(width: geo.size.width * min(1, share.actual / 100))
                            Rectangle().fill(Color.primary.opacity(0.7))
                                .frame(width: 1.5)
                                .offset(x: geo.size.width * min(1, share.target / 100))
                        }
                    }
                    .frame(height: 5)
                    Text(verbatim: Fmt.money(share.value, currency)
                         + (pillars.due ? " → " + Fmt.money(share.rebalanced, currency) : ""))
                        .font(.ui(compact ? 10 : 13)).foregroundStyle(.secondary)
                }
                .monospacedDigit()
            }
            Text(pillars.due
                 ? "Drifted \(Self.points(pillars.drift)) pp from the target shares – the amounts after the arrow restore them (a new amount applies from the bot's next buy)."
                 : "Close to the target shares (actual / target) – rebalance once a year.")
                .font(.ui(compact ? 10 : 13))
                .foregroundStyle(pillars.due ? Color.orange : Color.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    static func share(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0))) + " %"
    }

    static func points(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(1)))
    }
}
