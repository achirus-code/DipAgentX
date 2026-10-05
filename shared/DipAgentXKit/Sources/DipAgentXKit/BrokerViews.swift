import SwiftUI

/// The two tabs above the statistics: Revolut X and Trade Republic. Each broker has its own statistics, bots,
/// trades, trading mode, limits and simulation fees – the selected tab decides which of them the app shows.
public struct BrokerTabs: View {
    @Binding var selection: Broker
    let summaries: [Broker: Summary]
    let isLive: (Broker) -> Bool
    /// Something needs the user, e.g. the Trade Republic login ran out.
    let attention: (Broker) -> Bool
    @Namespace private var namespace

    public init(selection: Binding<Broker>, summaries: [Broker: Summary], isLive: @escaping (Broker) -> Bool,
                attention: @escaping (Broker) -> Bool = { _ in false }) {
        _selection = selection
        self.summaries = summaries
        self.isLive = isLive
        self.attention = attention
    }

    public var body: some View {
        HStack(spacing: 4) {
            ForEach(Broker.allCases) { broker in
                tab(broker)
            }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.primary.opacity(0.06)))
    }

    private func tab(_ broker: Broker) -> some View {
        let selected = selection == broker
        let result = summaries[broker]?.currencies.first
        return Button {
            withAnimation(.snappy(duration: 0.25)) { selection = broker }
        } label: {
            VStack(spacing: 2) {
                HStack(spacing: 5) {
                    Image(systemName: broker.icon).font(.ui(11, weight: .semibold))
                    Text(verbatim: broker.title).font(.ui(12, weight: .semibold)).lineLimit(1)
                    if isLive(broker) {
                        Circle().fill(Color.red).frame(width: 6, height: 6)
                            .help("Live trading is active")
                    }
                    if attention(broker) {
                        Image(systemName: "exclamationmark.circle.fill")
                            .font(.ui(10, weight: .semibold)).foregroundStyle(.orange)
                    }
                }
                if let result {
                    PnLText(value: result.total, currency: result.currency, font: .ui(10, weight: .medium, design: .rounded),
                            calmLosses: true)
                        .opacity(selected ? 1 : 0.75)
                } else {
                    Text(verbatim: "–").font(.ui(10)).foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 5)
            .foregroundStyle(selected ? Color.primary : Color.secondary)
            .background {
                if selected {
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(.background.opacity(0.9))
                        .shadow(color: .black.opacity(0.12), radius: 2, y: 1)
                        .matchedGeometryEffect(id: "broker", in: namespace)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

extension AppStore {
    /// The broker tab needs a look: the Trade Republic login waits for a confirmation, ran out while live trading
    /// is on, or the broker reports an error.
    public func needsAttention(_ broker: Broker) -> Bool {
        switch broker {
        case .revolutX:
            return isLive(.revolutX) && exchangeInfo?.connected == false
        case .tradeRepublic:
            guard let info = tradeRepublic, !info.isDemo else { return false }
            return info.waiting || (isLive(.tradeRepublic) && !info.connected)
        }
    }
}

/// "🏛 Trade Republic" – next to a section title whose settings belong to one broker.
public struct BrokerName: View {
    let broker: Broker

    public init(broker: Broker) {
        self.broker = broker
    }

    public var body: some View {
        Label(broker.title, systemImage: broker.icon)
            .font(.ui(10, weight: .semibold))
            .foregroundStyle(.secondary)
            .labelStyle(CompactLabelStyle())
    }
}

extension Instrument {
    /// "Stock", "ETF", "Crypto" … for the agent's type ids.
    public static func typeName(_ type: String?) -> String? {
        switch type?.lowercased() {
        case "stock": return String(localized: "Stock")
        case "fund", "etf": return String(localized: "ETF")
        case "crypto": return String(localized: "Crypto")
        case "bond": return String(localized: "Bond")
        case "derivative", "warrant": return String(localized: "Derivative")
        case nil, "": return nil
        default: return type
        }
    }

    /// "AAPL · Stock · US0378331005"
    public var details: String {
        [short, Instrument.typeName(type), isin ?? symbol.split(separator: "-").first.map(String.init)]
            .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

extension Broker {
    /// What can be traded there – the line under the switch in the settings.
    public var offering: String {
        switch self {
        case .revolutX: return String(localized: "Crypto")
        case .tradeRepublic: return String(localized: "Stocks, ETFs and crypto")
        }
    }
}
