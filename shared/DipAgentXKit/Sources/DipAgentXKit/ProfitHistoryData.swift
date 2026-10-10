import SwiftUI
#if canImport(AppKit)
import AppKit
#else
import UIKit
#endif

/// Everything the profit chart shows, computed from the trade history and the chosen filters – the same numbers
/// on the Mac (window) and the iPhone (page).
public struct ProfitHistoryData {
    public struct Curve: Identifiable {
        public let id: Int // bot id, -1 = all shown bots together, -1000 - bot id = the bot's "only held" line
        public let color: Color
        public let points: [ProfitPoint]

        /// The value at `date`, nil before the curve starts. The realized result only changes with a sale, so it is
        /// the last point's; the "only held" line moves all the time, so it is interpolated between two points.
        public func value(at date: Date) -> Double? {
            guard let first = points.first, date >= first.date else { return nil }
            var low = 0, high = points.count - 1
            while low < high { // the last point not after `date`
                let mid = (low + high + 1) / 2
                if points[mid].date <= date { low = mid } else { high = mid - 1 }
            }
            guard id <= -1000, low + 1 < points.count else { return points[low].value }
            let (a, b) = (points[low], points[low + 1])
            let span = b.date.timeIntervalSince(a.date)
            return span > 0 ? a.value + (b.value - a.value) * date.timeIntervalSince(a.date) / span : a.value
        }
    }

    public struct BotStats: Identifiable {
        public let id: Int
        public let name: String
        public let deleted: Bool
        public let buys: Int
        public let sells: Int
        public let wins: Int
        public let volume: Double
        public let pnl: Double
        public let fees: Double
        public let last: Date?
    }

    /// The realized result of one day, week or month – a bar below the curve.
    public struct Bucket: Identifiable {
        public let start: Date
        public let end: Date
        public let pnl: Double
        public let sales: Int
        public let wins: Int
        /// Each bot's share of the result, the largest first.
        public let perBot: [(botId: Int, pnl: Double)]
        public var id: Date { start }
    }

    public typealias Marker = (curve: Curve, point: ProfitPoint)

    /// Bot colours, one shade for light and one for dark mode. No green and no red: those mean buy / profit and
    /// sale / loss in the chart. The order keeps neighbouring colours apart for colour-blind eyes too.
    public static let palette: [Color] = [
        shade(0x2A78D6, 0x3987E5), shade(0xEB6834, 0xD95926), shade(0x1BAF7A, 0x199E70), shade(0xEDA100, 0xC98500),
        shade(0xE87BA4, 0xD55181), shade(0x4A3AA7, 0x9085E9), shade(0x8A9A1B, 0x8E9E1F), shade(0xA8327F, 0xB9488F),
    ]

    private static func shade(_ light: UInt32, _ dark: UInt32) -> Color {
        func rgb(_ hex: UInt32) -> (CGFloat, CGFloat, CGFloat) {
            (CGFloat(hex >> 16 & 0xFF) / 255, CGFloat(hex >> 8 & 0xFF) / 255, CGFloat(hex & 0xFF) / 255)
        }
        let (l, d) = (rgb(light), rgb(dark))
        #if canImport(AppKit)
        return Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
                ? NSColor(srgbRed: d.0, green: d.1, blue: d.2, alpha: 1)
                : NSColor(srgbRed: l.0, green: l.1, blue: l.2, alpha: 1)
        })
        #else
        return Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark ? UIColor(red: d.0, green: d.1, blue: d.2, alpha: 1)
                : UIColor(red: l.0, green: l.1, blue: l.2, alpha: 1)
        })
        #endif
    }

    public let trades: [Trade]
    public let bots: [Bot]
    public let live: Bool
    public let currency: String
    public let range: HistoryRange
    public let perBot: Bool
    public let hidden: Set<Int>
    /// Momentum bots whose "only held" line is shown, with that line (bot id → points).
    public let hodl: [Int: [HodlPoint]]
    /// The currencies in the order of the agent's summary.
    let currencyOrder: [String]

    public init(trades: [Trade], bots: [Bot], summary: Summary?, live: Bool, currency: String, range: HistoryRange,
                perBot: Bool, hidden: Set<Int>, hodl: [Int: [HodlPoint]] = [:]) {
        self.trades = trades
        self.bots = bots
        self.live = live
        self.currency = currency
        self.range = range
        self.perBot = perBot
        self.hidden = hidden
        self.hodl = hodl
        currencyOrder = summary?.currencies.map(\.currency) ?? []
    }

    public var modeTrades: [Trade] { trades.filter { $0.paper != live } }

    public var currencies: [String] {
        let order = currencyOrder
        return Set(modeTrades.map(\.quote)).sorted { (order.firstIndex(of: $0) ?? .max, $0) < (order.firstIndex(of: $1) ?? .max, $1) }
    }

    /// The trades of the chosen mode and currency, over the whole history.
    public var scoped: [Trade] { modeTrades.filter { $0.quote == currency } }

    /// Every bot that ever traded, in a fixed order – so a bot keeps its color when the mode or range changes.
    public var allBotIds: [Int] {
        var seen: [Int] = []
        for trade in trades.sorted(by: { $0.createdAt < $1.createdAt }) where !seen.contains(trade.botId) {
            seen.append(trade.botId)
        }
        return seen
    }

    public var botIds: [Int] {
        let ids = Set(scoped.map(\.botId))
        return allBotIds.filter { ids.contains($0) }
    }

    public func color(_ botId: Int) -> Color {
        Self.palette[(allBotIds.firstIndex(of: botId) ?? 0) % Self.palette.count]
    }

    public func name(_ botId: Int) -> String {
        bots.first { $0.id == botId }?.name
            ?? trades.filter { $0.botId == botId }.max { $0.createdAt < $1.createdAt }?.botName
            ?? "#\(botId)"
    }

    public var shown: [Trade] { scoped.filter { !hidden.contains($0.botId) } }

    public var curves: [Curve] {
        let start = range.start
        if perBot {
            return botIds.filter { !hidden.contains($0) }.map { id in
                Curve(id: id, color: color(id), points: ProfitCurve.points(scoped.filter { $0.botId == id }, key: String(id), from: start))
            }
        }
        let points = ProfitCurve.points(shown, from: start)
        return points.isEmpty ? [] : [Curve(id: -1, color: .accentColor, points: points)]
    }

    /// Bots that can compare themselves with holding (momentum follower).
    public func canCompare(_ botId: Int) -> Bool {
        bots.first { $0.id == botId }?.strategy == "momentum"
    }

    /// The "only held" lines of the chosen bots – in a paler shade of the bot's colour, drawn dashed: the result
    /// holding would have had since the bot's start, on the same scale as the bot's own line.
    public var hodlCurves: [Curve] {
        let start = range.start
        return hodl.keys.sorted().filter { !hidden.contains($0) }.compactMap { id in
            let all = hodl[id] ?? []
            var shown = all.filter { start == nil || $0.date >= start! }
            guard !shown.isEmpty else { return nil }
            if let start, let before = all.last(where: { $0.date < start }) {
                shown.insert(HodlPoint(t: Int64(start.timeIntervalSince1970 * 1000), value: before.value), at: 0)
            }
            let points = shown.enumerated().map { index, point in
                ProfitPoint(id: "hodl-\(id)-\(index)", date: point.date, value: point.value, trade: nil)
            }
            return Curve(id: -1000 - id, color: color(id).opacity(0.45), points: points)
        }
    }

    public var inRange: [Trade] {
        guard let start = range.start else { return scoped }
        return scoped.filter { $0.date >= start }
    }

    public var stats: [BotStats] {
        botIds.map { id in
            let own = inRange.filter { $0.botId == id }
            let sales = own.compactMap(\.pnl)
            return BotStats(
                id: id, name: name(id), deleted: bots.isEmpty == false && !bots.contains { $0.id == id },
                buys: own.filter(\.isBuy).count, sells: sales.count, wins: sales.filter { $0 > 0 }.count,
                volume: own.reduce(0) { $0 + $1.quoteAmount }, pnl: sales.reduce(0, +),
                fees: own.reduce(0) { $0 + $1.fee }, last: own.map(\.date).max()
            )
        }
    }

    /// Every buy and sale on the shown curves.
    public var markers: [Marker] {
        curves.flatMap { curve in curve.points.filter { $0.trade != nil }.map { (curve, $0) } }
    }

    /// Buys and sales linked to each other – over the whole history, not just the shown range.
    public var links: TradeLinks { TradeLinks(scoped) }

    /// The trade shown in the details and the trades it belongs to – emphasized in the chart.
    public func related(to detail: Trade?, links: TradeLinks) -> Set<Int> {
        guard let detail else { return [] }
        let parts = detail.isBuy ? links.salesOfBuy[detail.id] : links.buysOfSale[detail.id]
        return Set([detail.id] + (parts ?? []).map(\.trade.id))
    }

    /// The values of the shown curves plus the zero line, with a little air above and below.
    public var yDomain: ClosedRange<Double> {
        let values: [Double] = (curves + hodlCurves).flatMap { curve in curve.points.map(\.value) } + [0]
        let low = values.min() ?? 0, high = values.max() ?? 0
        let pad = max((high - low) * 0.08, 1)
        return (low - pad)...(high + pad)
    }

    public var xDomain: ClosedRange<Date> {
        let now = Date()
        let lower = range.start ?? scoped.map(\.date).min() ?? now
        return min(lower, now.addingTimeInterval(-3600))...now
    }

    /// Days up to about three months, then weeks, beyond a year and a half months.
    public var bucketUnit: Calendar.Component {
        let days = xDomain.upperBound.timeIntervalSince(xDomain.lowerBound) / 86_400
        return days <= 100 ? .day : days <= 550 ? .weekOfYear : .month
    }

    /// The realized result of the shown bots per day, week or month in the period – only periods with a sale.
    public var buckets: [Bucket] {
        let calendar = Calendar.current
        let unit = bucketUnit
        let sales = inRange.filter { $0.pnl != nil && !hidden.contains($0.botId) }
        let groups = Dictionary(grouping: sales) { calendar.dateInterval(of: unit, for: $0.date)?.start ?? $0.date }
        return groups.map { start, trades in
            var perBot: [Int: Double] = [:]
            for trade in trades { perBot[trade.botId, default: 0] += trade.pnl ?? 0 }
            return Bucket(
                start: start, end: calendar.date(byAdding: unit, value: 1, to: start) ?? start,
                pnl: trades.reduce(0) { $0 + ($1.pnl ?? 0) }, sales: trades.count,
                wins: trades.filter { ($0.pnl ?? 0) > 0 }.count,
                perBot: perBot.map { (botId: $0.key, pnl: $0.value) }.sorted { abs($0.pnl) > abs($1.pnl) }
            )
        }
        .sorted { $0.start < $1.start }
    }

    /// Totals of the shown bots in the period – the tiles above the chart.
    public var totals: (pnl: Double, volume: Double, buys: Int, sells: Int, wins: Int, fees: Double) {
        let shownStats = stats.filter { !hidden.contains($0.id) }
        return (
            shownStats.reduce(0) { $0 + $1.pnl }, shownStats.reduce(0) { $0 + $1.volume },
            shownStats.reduce(0) { $0 + $1.buys }, shownStats.reduce(0) { $0 + $1.sells },
            shownStats.reduce(0) { $0 + $1.wins }, shownStats.reduce(0) { $0 + $1.fees }
        )
    }
}
