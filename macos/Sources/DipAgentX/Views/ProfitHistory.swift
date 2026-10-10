import AppKit
import Charts
import DipAgentXKit
import Observation
import SwiftUI

// MARK: - Window

/// The profit chart in a window of its own – there is no room for it in the menu bar panel.
@MainActor
enum ProfitWindow {
    private static var window: NSWindow?

    static func show(store: AppStore) {
        if window == nil {
            let window = NSWindow(
                contentRect: NSRect(x: 0, y: 0, width: 1200, height: 880),
                styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                backing: .buffered, defer: false
            )
            window.title = String(localized: "Profit history")
            window.titlebarAppearsTransparent = true // the background runs up under the title bar
            window.contentMinSize = NSSize(width: 960, height: 680)
            window.isReleasedWhenClosed = false
            let host = NSHostingView(rootView: ProfitHistoryView().environment(store))
            host.sizingOptions = [] // the window decides the size
            window.contentView = host
            window.center()
            self.window = window
        }
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}

/// The window's two greys: a calm background and lighter cards on it.
private enum Surface {
    static let background = color(light: 0xF2F2F4, dark: 0x1C1C1E)
    static let card = color(light: 0xFFFFFF, dark: 0x29292C)
    /// Tooltips float above the cards.
    static let raised = color(light: 0xFFFFFF, dark: 0x38383B)

    private static func color(light: UInt32, dark: UInt32) -> Color {
        func ns(_ hex: UInt32) -> NSColor {
            NSColor(srgbRed: CGFloat(hex >> 16 & 0xFF) / 255, green: CGFloat(hex >> 8 & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
        }
        return Color(nsColor: NSColor(name: nil) { $0.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? ns(dark) : ns(light) })
    }
}

struct ProfitHistoryView: View {
    @Environment(AppStore.self) private var store
    /// The whole history as far as the agent hands it out; until it is loaded the trades of the panel are shown.
    @State private var history: [Trade]?
    @State private var loading = false
    @State private var live = false
    @State private var currency = "EUR"
    @State private var range: HistoryRange = .month
    @State private var perBot = true
    @State private var hidden: Set<Int> = []
    /// The bot row under the mouse – its lines stand out in the chart.
    @State private var highlighted: Int?
    /// Where the mouse is over the charts.
    @State private var hover = ChartHover()
    /// 0 → 1 when the curves (re)appear: they grow out of the zero line.
    @State private var reveal = 0.0
    /// The trade whose details are shown next to the chart.
    @State private var detail: Trade?
    /// Momentum bots whose "only held" line is shown – and the lines loaded for them.
    @State private var hodlShown: Set<Int> = []
    @State private var hodlLines: [Int: [HodlPoint]] = [:]

    private static let historyLimit = 1000

    // MARK: Data

    private var trades: [Trade] { history ?? store.trades }

    private var data: ProfitHistoryData {
        ProfitHistoryData(trades: trades, bots: store.bots, summary: store.summary, live: live, currency: currency,
                          range: range, perBot: perBot, hidden: hidden,
                          hodl: hodlLines.filter { hodlShown.contains($0.key) })
    }

    private func toggleHodl(_ botId: Int) {
        if hodlShown.contains(botId) {
            withAnimation(.smooth(duration: 0.4)) { _ = hodlShown.remove(botId) }
            return
        }
        Task {
            let line = await store.hodlHistory(botId: botId)
            hodlLines[botId] = line
            withAnimation(.smooth(duration: 0.4)) { _ = hodlShown.insert(botId) }
        }
    }

    // MARK: Layout

    var body: some View {
        let data = data
        VStack(alignment: .leading, spacing: 14) {
            controls(data)
            if data.scoped.isEmpty {
                Spacer()
                EmptyStateView(icon: "chart.xyaxis.line", title: "No trades yet", message: "As soon as a bot buys or sells, its curve shows up here.")
                Spacer()
            } else {
                let stats = data.stats
                HStack(alignment: .top, spacing: 14) {
                    VStack(alignment: .leading, spacing: 14) {
                        tiles(data)
                        chartPanel(data)
                        botTable(data, stats: stats, compact: detail != nil)
                    }
                    if let detail {
                        Panel(padding: 16) {
                            ScrollView {
                                TradeDetailPanel(
                                    trade: detail, links: data.links, botName: data.name(detail.botId), botColor: data.color(detail.botId),
                                    market: store.bots.first { $0.id == detail.botId && $0.symbol == detail.symbol }?.market?.price,
                                    close: { self.detail = nil }, framed: false
                                )
                            }
                            .scrollIndicators(.never)
                        }
                        .frame(width: 330)
                        .frame(maxHeight: .infinity, alignment: .top)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                    }
                }
                .animation(.snappy(duration: 0.25), value: detail == nil)
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 4)
        .padding(.bottom, 18)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Surface.background.ignoresSafeArea())
        .task(id: store.trades.first?.id) { await load() }
        .onAppear {
            live = store.summary?.mode == "live"
            currency = store.summary?.currencies.first?.currency ?? data.currencies.first ?? currency
            replay()
        }
        .onChange(of: perBot) { replay() }
        .onChange(of: data.currencies) { _, available in
            if !available.contains(currency), let first = available.first { currency = first }
        }
        .onChange(of: range) { hover.clear() }
        .onChange(of: live) { detail = nil; replay() }
        .onChange(of: currency) { detail = nil; replay() }
    }

    /// Lets the curves grow out of the zero line again – when the window opens or other data is shown.
    private func replay() {
        hover.clear()
        reveal = 0
        DispatchQueue.main.async {
            withAnimation(.spring(duration: 0.9, bounce: 0.15)) { reveal = 1 }
        }
    }

    private func load() async {
        loading = true
        if let all = await store.allTrades(limit: Self.historyLimit) { history = all }
        loading = false
    }

    private func controls(_ data: ProfitHistoryData) -> some View {
        HStack(spacing: 12) {
            Picker("Mode", selection: $live) {
                Text("Paper").tag(false)
                Text("Live").tag(true)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            .help("Paper and live results are kept apart.")
            if data.currencies.count > 1 {
                Picker("Currency", selection: $currency) {
                    ForEach(data.currencies, id: \.self) { Text(verbatim: $0).tag($0) }
                }
                .labelsHidden()
                .fixedSize()
            }
            Spacer()
            Picker("Period", selection: $range) {
                ForEach(HistoryRange.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            Picker("View", selection: $perBot) {
                Text("Per bot").tag(true)
                Text("Combined").tag(false)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            .help("One line per bot, or the shown bots added up to one line.")
            Button {
                Task { await load() }
            } label: {
                if loading {
                    ProgressView().controlSize(.mini).frame(width: 13, height: 13)
                } else {
                    Image(systemName: "arrow.clockwise")
                }
            }
            .disabled(loading)
            .help("Refresh")
        }
        .controlSize(.small)
    }

    // MARK: Tiles

    private func tiles(_ data: ProfitHistoryData) -> some View {
        let totals = data.totals
        let trades = totals.buys + totals.sells
        return HStack(alignment: .top, spacing: 12) {
            tile("Profit/loss", help: "Realized result of the shown bots in this period, fees already deducted.") {
                PnLText(value: totals.pnl, currency: currency, font: Self.tileFont)
            } footer: {
                Sparkline(points: ProfitCurve.points(data.shown, from: range.start), color: totals.pnl < 0 ? .red : .profit, reveal: reveal)
                    .frame(height: 24)
            }
            tile("Volume", help: "Value of all buys and sales of the shown bots in this period.") {
                tileText(Fmt.money(totals.volume, currency))
            } footer: {
                if trades > 0 { footnote(Text("Ø \(Fmt.money(totals.volume / Double(trades), currency)) per trade")) }
            }
            tile("Trades", help: "Buys / sales in this period") {
                tileText(String(trades))
            } footer: {
                VStack(alignment: .leading, spacing: 5) {
                    SplitBar(left: Double(totals.buys), right: Double(totals.sells))
                        .frame(height: 5)
                    footnote(Text("\(String(totals.buys)) buys · \(String(totals.sells)) sales"))
                }
            }
            tile("Win rate", help: "Share of the sales that ended with a profit.") {
                HStack(alignment: .center, spacing: 10) {
                    tileText(totals.sells > 0 ? Fmt.rate(Double(totals.wins) / Double(totals.sells) * 100) : "–")
                    Spacer(minLength: 0)
                    if totals.sells > 0 {
                        Ring(share: Double(totals.wins) / Double(totals.sells) * reveal)
                            .frame(width: 26, height: 26)
                    }
                }
            } footer: {
                if totals.sells > 0 { footnote(Text("\(String(totals.wins)) of \(String(totals.sells)) with profit")) }
            }
            tile("Fees", help: "Exchange fees – already included in the result.") {
                tileText(Fmt.money(totals.fees, currency))
            } footer: {
                if totals.volume > 0 { footnote(Text("\(Fmt.rate(totals.fees / totals.volume * 100)) of the volume")) }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .animation(.snappy(duration: 0.4), value: totals.pnl)
        .animation(.snappy(duration: 0.4), value: totals.sells)
    }

    private static let tileFont = Font.system(size: 21, weight: .semibold, design: .rounded)

    private func tile<Value: View, Footer: View>(
        _ title: LocalizedStringKey, help: LocalizedStringKey,
        @ViewBuilder value: () -> Value, @ViewBuilder footer: () -> Footer
    ) -> some View {
        Panel(padding: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.system(size: 11, weight: .medium)).foregroundStyle(.secondary)
                value()
                Spacer(minLength: 0)
                footer()
            }
            .frame(maxHeight: .infinity, alignment: .topLeading)
        }
        .help(Text(help))
    }

    private func tileText(_ text: String) -> some View {
        Text(verbatim: text).font(Self.tileFont).monospacedDigit()
            .contentTransition(.numericText())
            .lineLimit(1)
            .minimumScaleFactor(0.7)
    }

    private func footnote(_ text: Text) -> some View {
        text.font(.system(size: 10.5)).foregroundStyle(.secondary).monospacedDigit().lineLimit(1).minimumScaleFactor(0.8)
    }

    // MARK: Charts

    private func chartPanel(_ data: ProfitHistoryData) -> some View {
        let model = ChartModel(data)
        let related = detail.map { data.related(to: $0, links: data.links) } ?? []
        return Panel(padding: 14) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text("Realized result").font(.system(size: 13, weight: .semibold))
                    Text("after fees").font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                    HStack(spacing: 14) {
                        legendItem("Buy") { TradeSymbol(isBuy: true).fill(Color.profit).frame(width: 8, height: 8) }
                        legendItem("Sale") { TradeSymbol(isBuy: false).fill(Color.red).frame(width: 8, height: 8) }
                        if !model.hodl.isEmpty {
                            legendItem("HODL") { LineKey(color: .secondary, dashed: true) }
                                .help("Dashed: only held (HODL) since the bot's start")
                        }
                        if trades.count >= Self.historyLimit {
                            Text("Latest \(String(Self.historyLimit)) trades").foregroundStyle(.tertiary)
                        }
                    }
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                }
                .help("The line shows the realized result, fees deducted – it moves with every sale.")
                ChartStack(model: model, reveal: reveal, highlighted: highlighted, related: related, hover: hover,
                           detailId: detail?.id) { trade in
                    detail = trade
                }
            }
        }
        .animation(.smooth(duration: 0.5), value: range)
    }

    private func legendItem<Key: View>(_ title: LocalizedStringKey, @ViewBuilder key: () -> Key) -> some View {
        HStack(spacing: 5) {
            key()
            Text(title)
        }
    }

    // MARK: Bots

    /// `compact`: without fees and last trade – while the trade details take up room next to it.
    private func botTable(_ data: ProfitHistoryData, stats: [ProfitHistoryData.BotStats], compact: Bool) -> some View {
        let scale = stats.map { abs($0.pnl) }.max() ?? 0
        let diverging = stats.contains { $0.pnl < 0 } && stats.contains { $0.pnl > 0 }
        let ideal = BotColumns.header + CGFloat(stats.count) * BotColumns.row + 17
        return Panel(padding: 8) {
            VStack(spacing: 0) {
                HStack(spacing: BotColumns.spacing) {
                    HStack(spacing: 8) {
                        Text("Bot")
                        Button(hidden.isEmpty ? "Hide all" : "Show all") {
                            withAnimation(.smooth(duration: 0.4)) { hidden = hidden.isEmpty ? Set(data.botIds) : [] }
                        }
                        .buttonStyle(.link)
                        .font(.system(size: 10.5))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    Text("Trades").frame(width: BotColumns.trades, alignment: .trailing)
                        .help("Buys / sales in this period")
                    Text("Win rate").frame(width: BotColumns.winRate, alignment: .trailing)
                    Text("Volume").frame(width: BotColumns.volume, alignment: .trailing)
                    Text("Profit/loss").frame(width: BotColumns.result, alignment: .trailing)
                    if !compact {
                        Text("Fees").frame(width: BotColumns.fees, alignment: .trailing)
                        Text("Last trade").frame(width: BotColumns.last, alignment: .trailing)
                    }
                    Text("HODL").frame(width: BotColumns.hodl, alignment: .center)
                        .help("Shows what holding would have made since the bot's start – a dashed line in a paler colour.")
                }
                .font(.system(size: 10.5, weight: .medium))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 8)
                .frame(height: BotColumns.header)
                Divider().opacity(0.5)
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(stats) { row in
                            botRow(row, data: data, scale: scale, diverging: diverging, compact: compact)
                        }
                    }
                }
                .scrollIndicators(.automatic)
            }
        }
        .frame(minHeight: min(ideal, 130), maxHeight: min(ideal, 220))
        .onHover { inside in
            if !inside { withAnimation(.easeOut(duration: 0.2)) { highlighted = nil } }
        }
    }

    private func botRow(_ row: ProfitHistoryData.BotStats, data: ProfitHistoryData, scale: Double, diverging: Bool, compact: Bool) -> some View {
        let isShown = !hidden.contains(row.id)
        let isHighlighted = highlighted == row.id
        return HStack(spacing: BotColumns.spacing) {
            HStack(spacing: 8) {
                Image(systemName: isShown ? "checkmark.square.fill" : "square")
                    .font(.system(size: 13))
                    .foregroundStyle(isShown ? data.color(row.id) : Color.secondary)
                Text(verbatim: row.name).font(.system(size: 12, weight: .medium)).lineLimit(1)
                if row.deleted {
                    Text("Deleted").font(.system(size: 10)).foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Text(verbatim: "\(row.buys) / \(row.sells)")
                .frame(width: BotColumns.trades, alignment: .trailing)
                .help("Buys / sales in this period")
            Text(verbatim: row.sells > 0 ? Fmt.rate((Double(row.wins) / Double(row.sells) * 100).rounded()) : "–")
                .foregroundStyle(.secondary)
                .frame(width: BotColumns.winRate, alignment: .trailing)
            Text(verbatim: Fmt.money(row.volume, currency))
                .frame(width: BotColumns.volume, alignment: .trailing)
            HStack(spacing: 10) {
                ResultBar(value: row.pnl, scale: scale, diverging: diverging)
                    .frame(width: 64, height: 6)
                PnLText(value: row.pnl, currency: currency, font: .system(size: 12, weight: .semibold))
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            .frame(width: BotColumns.result, alignment: .trailing)
            if !compact {
                Text(verbatim: Fmt.money(row.fees, currency)).foregroundStyle(.secondary)
                    .frame(width: BotColumns.fees, alignment: .trailing)
                Text(verbatim: row.last?.formatted(.dateTime.day().month(.abbreviated).hour().minute()) ?? "–").foregroundStyle(.secondary)
                    .frame(width: BotColumns.last, alignment: .trailing)
            }
            Group {
                if data.canCompare(row.id) {
                    let on = hodlShown.contains(row.id)
                    Button { toggleHodl(row.id) } label: {
                        Image(systemName: on ? "checkmark.square.fill" : "square")
                            .font(.system(size: 13))
                            .foregroundStyle(on ? data.color(row.id).opacity(0.55) : Color.secondary)
                    }
                    .buttonStyle(.plain)
                    .help(on ? "Hide the HODL line of this bot" : "Show what holding would have made since this bot's start")
                } else {
                    Text(verbatim: "–").foregroundStyle(.tertiary)
                }
            }
            .frame(width: BotColumns.hodl, alignment: .center)
        }
        .font(.system(size: 12))
        .monospacedDigit()
        .padding(.horizontal, 8)
        .frame(height: BotColumns.row)
        .background(RoundedRectangle(cornerRadius: 7, style: .continuous).fill(Color.primary.opacity(isHighlighted ? 0.055 : 0)))
        .opacity(isShown ? 1 : 0.45)
        .contentShape(Rectangle())
        .onHover { inside in
            withAnimation(.easeOut(duration: 0.2)) {
                if inside { highlighted = isShown ? row.id : nil } else if highlighted == row.id { highlighted = nil }
            }
        }
        .onTapGesture {
            withAnimation(.smooth(duration: 0.4)) {
                if isShown { hidden.insert(row.id) } else { hidden.remove(row.id) }
                highlighted = nil
            }
        }
        .help(isShown ? "Click to hide this bot in the chart" : "Click to show this bot in the chart")
    }
}

/// Column widths of the bot table – header and rows line up.
private enum BotColumns {
    static let spacing: CGFloat = 16
    static let trades: CGFloat = 54
    static let winRate: CGFloat = 76
    static let volume: CGFloat = 98
    static let result: CGFloat = 164
    static let fees: CGFloat = 70
    static let last: CGFloat = 108
    static let hodl: CGFloat = 40
    static let header: CGFloat = 28
    static let row: CGFloat = 32
}

// MARK: - Chart model

/// Where the mouse is over the charts – shared by the curve and the bars, so both mark the same moment. Only the
/// hover layers read it: moving the mouse does not redraw the charts themselves.
@MainActor
@Observable
final class ChartHover {
    enum Pane { case curve, bars }

    var pane: Pane?
    var date: Date?
    /// The mouse in the hovered chart's coordinates.
    var location: CGPoint = .zero
    /// The buy or sale under the mouse (curve).
    var marker: String?
    /// The period under the mouse (bars).
    var bucket: Date?

    /// Sets only what changed – the views that read the pane (z-order) don't redraw on every mouse move.
    func update(pane: Pane, date: Date?, location: CGPoint, marker: String?, bucket: Date?) {
        if self.pane != pane { self.pane = pane }
        if self.marker != marker { self.marker = marker }
        if self.bucket != bucket { self.bucket = bucket }
        self.date = date
        self.location = location
    }

    func clear() {
        guard pane != nil else { return }
        pane = nil
        date = nil
        marker = nil
        bucket = nil
    }
}

/// Everything the two charts draw – computed once per change of data or filters, not per mouse move.
private struct ChartModel {
    typealias Curve = ProfitHistoryData.Curve

    let curves: [Curve]
    let hodl: [Curve]
    let markers: [ProfitHistoryData.Marker]
    let buckets: [ProfitHistoryData.Bucket]
    let unit: Calendar.Component
    let xDomain: ClosedRange<Date>
    let yDomain: ClosedRange<Double>
    let currency: String
    let perBot: Bool
    private let names: [Int: String]
    private let colors: [Int: Color]

    init(_ data: ProfitHistoryData) {
        curves = data.curves
        hodl = data.hodlCurves
        markers = curves.flatMap { curve in curve.points.filter { $0.trade != nil }.map { (curve, $0) } }
        buckets = data.buckets
        unit = data.bucketUnit
        xDomain = data.xDomain
        yDomain = data.yDomain
        currency = data.currency
        perBot = data.perBot
        names = Dictionary(uniqueKeysWithValues: data.botIds.map { ($0, data.name($0)) })
        colors = Dictionary(uniqueKeysWithValues: data.botIds.map { ($0, data.color($0)) })
    }

    func name(_ botId: Int) -> String { names[botId] ?? "#\(botId)" }

    func color(_ botId: Int) -> Color { colors[botId] ?? .secondary }

    /// The bot a curve belongs to – its own line or its "only held" line.
    static func botId(_ curve: Curve) -> Int { curve.id <= -1000 ? -1000 - curve.id : curve.id }

    func bucket(at date: Date) -> ProfitHistoryData.Bucket? {
        let start = Calendar.current.dateInterval(of: unit, for: date)?.start
        return buckets.first { $0.start == start }
    }

    var bucketTitle: LocalizedStringKey {
        switch unit {
        case .day: return "Result per day"
        case .weekOfYear: return "Result per week"
        default: return "Result per month"
        }
    }

    /// A period's name in the tooltip: the day, the week or the month.
    func periodTitle(_ bucket: ProfitHistoryData.Bucket) -> String {
        switch unit {
        case .day:
            return bucket.start.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
        case .weekOfYear:
            let week = Calendar.current.component(.weekOfYear, from: bucket.start)
            let last = bucket.end.addingTimeInterval(-1)
            return String(localized: "Week \(String(week))") + " · "
                + "\(bucket.start.formatted(.dateTime.day().month(.abbreviated))) – \(last.formatted(.dateTime.day().month(.abbreviated)))"
        default:
            return bucket.start.formatted(.dateTime.month(.wide).year())
        }
    }

    /// The date labels start at their line – one right at the end would be cut off.
    func hasRoomForLabel(at date: Date) -> Bool {
        let span = xDomain.upperBound.timeIntervalSince(xDomain.lowerBound)
        return xDomain.upperBound.timeIntervalSince(date) > span * 0.05
    }

    var axisFormat: Date.FormatStyle {
        unit == .month ? .dateTime.month(.abbreviated).year(.twoDigits) : .dateTime.day().month(.abbreviated)
    }
}

// MARK: - Curve

/// The curve with the bars below it. The chart under the mouse lies on top, so its tooltip may reach over the other.
private struct ChartStack: View {
    let model: ChartModel
    let reveal: Double
    let highlighted: Int?
    let related: Set<Int>
    let hover: ChartHover
    let detailId: Int?
    let select: (Trade?) -> Void

    var body: some View {
        let barsOnTop = hover.pane == .bars
        VStack(alignment: .leading, spacing: 8) {
            CurveChart(model: model, reveal: reveal, highlighted: highlighted, related: related, hover: hover,
                       detailId: detailId, select: select)
                .frame(minHeight: 150, maxHeight: .infinity)
                .zIndex(barsOnTop ? 0 : 1)
            Text(model.bucketTitle)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .padding(.top, 6)
                .help("Sum of the sales' results per period – green with a profit, red with a loss.")
            BarsChart(model: model, reveal: reveal, hover: hover)
                .frame(height: 84)
                .zIndex(barsOnTop ? 1 : 0)
        }
    }
}

/// The realized result over time: one line per bot (or one for all), every buy ▲ and sale ▼ on it.
private struct CurveChart: View {
    let model: ChartModel
    let reveal: Double
    let highlighted: Int?
    /// The trade in the details and the trades it belongs to – emphasized.
    let related: Set<Int>
    let hover: ChartHover
    let detailId: Int?
    let select: (Trade?) -> Void

    private func faded(_ curve: ChartModel.Curve) -> Bool {
        highlighted.map { ChartModel.botId(curve) != $0 } ?? false
    }

    var body: some View {
        Chart {
            RuleMark(y: .value("Result", 0))
                .lineStyle(StrokeStyle(lineWidth: 1))
                .foregroundStyle(Color.primary.opacity(0.25))
            if model.curves.count == 1, let curve = model.curves.first {
                ForEach(curve.points) { point in
                    AreaMark(x: .value("Date", point.date), yStart: .value("Result", 0), yEnd: .value("Result", point.value * reveal))
                        .interpolationMethod(.stepEnd)
                        .foregroundStyle(LinearGradient(colors: [curve.color.opacity(0.22), curve.color.opacity(0.02)], startPoint: .top, endPoint: .bottom))
                }
            }
            ForEach(model.hodl) { curve in
                ForEach(curve.points) { point in
                    LineMark(x: .value("Date", point.date), y: .value("Result", point.value * reveal), series: .value("Bot", curve.id))
                        .interpolationMethod(.linear)
                        .lineStyle(StrokeStyle(lineWidth: 1.5, lineCap: .round, dash: [5, 4]))
                        .foregroundStyle(curve.color)
                        .opacity(faded(curve) ? 0.12 : 1)
                }
            }
            ForEach(model.curves) { curve in
                ForEach(curve.points) { point in
                    LineMark(x: .value("Date", point.date), y: .value("Result", point.value * reveal), series: .value("Bot", curve.id))
                        .interpolationMethod(.stepEnd)
                        .lineStyle(StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                        .foregroundStyle(curve.color)
                        .opacity(faded(curve) ? 0.12 : 1)
                }
            }
            ForEach(model.markers, id: \.point.id) { marker in
                let isBuy = marker.point.trade?.isBuy == true
                let emphasized = marker.point.trade.map { related.contains($0.id) } ?? false
                let opacity = (faded(marker.curve) ? 0.1 : related.isEmpty || emphasized ? 1 : 0.3) * reveal
                // a ring in the card's colour keeps the symbol readable where it sits on a line
                PointMark(x: .value("Date", marker.point.date), y: .value("Result", marker.point.value * reveal))
                    .symbol(TradeSymbol(isBuy: isBuy))
                    .symbolSize(emphasized ? 190 : 92)
                    .foregroundStyle(Surface.card)
                    .opacity(opacity)
                PointMark(x: .value("Date", marker.point.date), y: .value("Result", marker.point.value * reveal))
                    .symbol(TradeSymbol(isBuy: isBuy))
                    .symbolSize(emphasized ? 110 : 40)
                    .foregroundStyle(isBuy ? Color.profit : .red)
                    .opacity(opacity)
            }
        }
        .chartXScale(domain: model.xDomain)
        .chartYScale(domain: model.yDomain) // fixed, so the curves grow instead of the axis rescaling with them
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 7)) { _ in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Color.primary.opacity(0.09))
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 5)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Color.primary.opacity(0.09))
                AxisValueLabel {
                    if let amount = value.as(Double.self) { AxisLabel(text: Fmt.money(amount, model.currency)) }
                }
            }
        }
        .chartLegend(.hidden)
        .animation(.smooth(duration: 0.4), value: model.curves.map(\.id))
        .animation(.easeOut(duration: 0.2), value: highlighted)
        .animation(.spring(duration: 0.35, bounce: 0.3), value: related)
        .chartOverlay { proxy in
            CurveHoverLayer(proxy: proxy, model: model, hover: hover, detailId: detailId, select: select)
        }
    }
}

/// The crosshair over the curve: a line at the mouse, a dot on every line with its value in a tooltip – or, right
/// on a buy or sale, that trade. Also marks the period whose bar is under the mouse.
private struct CurveHoverLayer: View {
    let proxy: ChartProxy
    let model: ChartModel
    let hover: ChartHover
    let detailId: Int?
    let select: (Trade?) -> Void

    var body: some View {
        let pane = hover.pane, date = hover.date, location = hover.location, markerId = hover.marker, bucketStart = hover.bucket
        GeometryReader { geo in
            let plot = proxy.plotFrame.map { geo[$0] } ?? .zero
            ZStack(alignment: .topLeading) {
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in track(phase, plot: plot) }
                    .onTapGesture { location in
                        // a click next to the markers closes the details
                        select(nearestMarker(location, plot: plot)?.point.trade)
                    }
                Group {
                    if pane == .bars, let bucketStart, let bucket = model.buckets.first(where: { $0.start == bucketStart }) {
                        PeriodBand(start: bucket.start, end: bucket.end, proxy: proxy, plot: plot)
                    }
                    if pane == .curve, let date, let x = proxy.position(forX: date) {
                        Rectangle().fill(Color.primary.opacity(0.3))
                            .frame(width: 1, height: plot.height)
                            .position(x: plot.minX + x, y: plot.midY)
                        if let marker = model.markers.first(where: { $0.point.id == markerId }), let trade = marker.point.trade {
                            if let y = proxy.position(forY: marker.point.value) {
                                ZStack {
                                    TradeSymbol(isBuy: trade.isBuy).fill(Surface.card).frame(width: 20, height: 20)
                                    TradeSymbol(isBuy: trade.isBuy).fill(trade.isBuy ? Color.profit : .red).frame(width: 13, height: 13)
                                }
                                .position(x: plot.minX + x, y: plot.minY + y)
                            }
                            TradeTooltip(trade: trade, name: model.name(trade.botId), color: marker.curve.id < 0 ? .secondary : marker.curve.color,
                                         total: marker.point.value, perBot: model.perBot, showsHint: detailId != trade.id)
                                .tooltip(at: location, in: geo.size)
                        } else {
                            let values = rows(at: date)
                            ForEach(values) { row in
                                if let y = proxy.position(forY: row.value) {
                                    Circle().fill(row.color)
                                        .frame(width: 8, height: 8)
                                        .background(Circle().fill(Surface.card).frame(width: 12, height: 12))
                                        .position(x: plot.minX + x, y: plot.minY + y)
                                }
                            }
                            if !values.isEmpty {
                                TimeTooltip(date: date, rows: values, currency: model.currency, perBot: model.perBot)
                                    .tooltip(at: location, in: geo.size)
                            }
                        }
                    }
                }
                .allowsHitTesting(false)
            }
        }
    }

    /// The value of every shown line at `date`, the highest first; the "only held" lines after the bots'.
    private func rows(at date: Date) -> [TimeTooltip.Row] {
        let own = model.curves.compactMap { curve in
            curve.value(at: date).map { TimeTooltip.Row(id: curve.id, name: curve.id < 0 ? nil : model.name(curve.id), color: curve.color, value: $0, dashed: false) }
        }
        let held = model.hodl.compactMap { curve in
            curve.value(at: date).map {
                TimeTooltip.Row(id: curve.id, name: model.name(ChartModel.botId(curve)), color: curve.color, value: $0, dashed: true)
            }
        }
        return own.sorted { $0.value > $1.value } + held.sorted { $0.value > $1.value }
    }

    private func track(_ phase: HoverPhase, plot: CGRect) {
        guard case .active(let location) = phase, location.x >= plot.minX - 2, location.x <= plot.maxX + 2 else {
            if hover.pane == .curve { hover.clear() }
            NSCursor.arrow.set()
            return
        }
        let marker = nearestMarker(location, plot: plot)
        let x = min(max(location.x, plot.minX), plot.maxX) - plot.minX
        hover.update(pane: .curve, date: marker?.point.date ?? proxy.value(atX: x, as: Date.self), location: location,
                     marker: marker?.point.id, bucket: nil)
        (marker == nil ? NSCursor.arrow : NSCursor.pointingHand).set()
    }

    /// The buy or sale within reach of the pointer, the closest one.
    private func nearestMarker(_ location: CGPoint, plot: CGRect) -> ProfitHistoryData.Marker? {
        var best: (marker: ProfitHistoryData.Marker, distance: CGFloat)?
        for marker in model.markers {
            guard let x = proxy.position(forX: marker.point.date), abs(plot.minX + x - location.x) < 14,
                  let y = proxy.position(forY: marker.point.value) else { continue }
            let distance = hypot(plot.minX + x - location.x, plot.minY + y - location.y)
            if distance < 14, distance < best?.distance ?? .infinity { best = (marker, distance) }
        }
        return best?.marker
    }
}

// MARK: - Bars

/// The realized result per day, week or month below the curve, on the same time axis.
private struct BarsChart: View {
    let model: ChartModel
    let reveal: Double
    let hover: ChartHover

    var body: some View {
        GeometryReader { geo in
            Chart {
                RuleMark(y: .value("Result", 0))
                    .lineStyle(StrokeStyle(lineWidth: 1))
                    .foregroundStyle(Color.primary.opacity(0.25))
                ForEach(model.buckets) { bucket in
                    BarMark(x: .value("Date", bucket.start, unit: model.unit), y: .value("Result", bucket.pnl * reveal),
                            width: .fixed(barWidth(geo.size.width)))
                        .cornerRadius(2.5)
                        .foregroundStyle(bucket.pnl < 0 ? Color.red : Color.profit)
                }
            }
            .chartXScale(domain: model.xDomain)
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 7)) { value in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Color.primary.opacity(0.09))
                    if let date = value.as(Date.self), model.hasRoomForLabel(at: date) {
                        AxisValueLabel(format: model.axisFormat)
                    }
                }
            }
            .chartYAxis {
                AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(Color.primary.opacity(0.09))
                    AxisValueLabel {
                        if let amount = value.as(Double.self) { AxisLabel(text: Fmt.money(amount, model.currency)) }
                    }
                }
            }
            .chartPlotStyle { $0.clipped() } // a day that began before the period stays inside
            .chartOverlay { proxy in
                BarsHoverLayer(proxy: proxy, model: model, hover: hover)
            }
        }
    }

    /// At most 16 pt – thin bars, with air between them.
    private func barWidth(_ width: CGFloat) -> CGFloat {
        let seconds: Double = model.unit == .day ? 86_400 : model.unit == .weekOfYear ? 7 * 86_400 : 30.4 * 86_400
        let periods = max(model.xDomain.upperBound.timeIntervalSince(model.xDomain.lowerBound) / seconds, 1)
        return min(max((width - AxisLabel.width) / periods * 0.62, 2), 16)
    }
}

/// The period under the mouse: its bar lit up with the numbers next to it – and a line at the curve's moment.
private struct BarsHoverLayer: View {
    let proxy: ChartProxy
    let model: ChartModel
    let hover: ChartHover

    var body: some View {
        let pane = hover.pane, date = hover.date, location = hover.location, bucketStart = hover.bucket
        GeometryReader { geo in
            let plot = proxy.plotFrame.map { geo[$0] } ?? .zero
            ZStack(alignment: .topLeading) {
                Rectangle().fill(.clear).contentShape(Rectangle())
                    .onContinuousHover { phase in track(phase, plot: plot) }
                Group {
                    if pane == .curve, let date, let x = proxy.position(forX: date) {
                        Rectangle().fill(Color.primary.opacity(0.3))
                            .frame(width: 1, height: plot.height)
                            .position(x: plot.minX + x, y: plot.midY)
                    }
                    if pane == .bars, let bucketStart, let bucket = model.buckets.first(where: { $0.start == bucketStart }) {
                        PeriodBand(start: bucket.start, end: bucket.end, proxy: proxy, plot: plot)
                        BucketTooltip(bucket: bucket, title: model.periodTitle(bucket), currency: model.currency, name: model.name, color: model.color)
                            .tooltip(at: location, in: geo.size, above: true) // the bars are low – there is room above
                    } else if pane == .bars, let date, let x = proxy.position(forX: date) {
                        Rectangle().fill(Color.primary.opacity(0.3))
                            .frame(width: 1, height: plot.height)
                            .position(x: plot.minX + x, y: plot.midY)
                    }
                }
                .allowsHitTesting(false)
            }
        }
    }

    private func track(_ phase: HoverPhase, plot: CGRect) {
        guard case .active(let location) = phase, location.x >= plot.minX - 2, location.x <= plot.maxX + 2,
              let date = proxy.value(atX: min(max(location.x, plot.minX), plot.maxX) - plot.minX, as: Date.self) else {
            if hover.pane == .bars { hover.clear() }
            return
        }
        hover.update(pane: .bars, date: date, location: location, marker: nil, bucket: model.bucket(at: date)?.start)
    }
}

/// A day, week or month lit up across the plot.
private struct PeriodBand: View {
    let start: Date
    let end: Date
    let proxy: ChartProxy
    let plot: CGRect

    var body: some View {
        let from = proxy.position(forX: start).map { max($0, 0) } ?? 0
        let to = proxy.position(forX: end).map { min($0, plot.width) } ?? plot.width
        RoundedRectangle(cornerRadius: 4, style: .continuous)
            .fill(Color.primary.opacity(0.07))
            .frame(width: max(to - from, 2), height: plot.height)
            .position(x: plot.minX + (from + to) / 2, y: plot.midY)
    }
}

// MARK: - Tooltips

private struct TooltipCard<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(.horizontal, 11)
            .padding(.vertical, 9)
            .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Surface.raised))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(Color.primary.opacity(0.1), lineWidth: 0.5))
            .shadow(color: .black.opacity(0.18), radius: 12, y: 4)
    }
}

/// Every line's value at one moment.
private struct TimeTooltip: View {
    struct Row: Identifiable {
        let id: Int
        /// nil: all shown bots together.
        let name: String?
        let color: Color
        let value: Double
        let dashed: Bool
    }

    let date: Date
    let rows: [Row]
    let currency: String
    let perBot: Bool

    var body: some View {
        TooltipCard {
            VStack(alignment: .leading, spacing: 6) {
                Text(verbatim: date.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated).year().hour().minute()))
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
                    ForEach(rows) { row in
                        GridRow {
                            HStack(spacing: 6) {
                                LineKey(color: row.color, dashed: row.dashed)
                                Group {
                                    if let name = row.name {
                                        Text(verbatim: row.dashed ? "\(name) · HODL" : name)
                                    } else {
                                        Text("Total")
                                    }
                                }
                                .font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
                            }
                            PnLText(value: row.value, currency: currency, font: .system(size: 12, weight: .semibold))
                                .gridColumnAlignment(.trailing)
                        }
                    }
                    let own = rows.filter { !$0.dashed }
                    if perBot, own.count > 1 {
                        Divider().gridCellColumns(2).opacity(0.6)
                        GridRow {
                            Text("Total").font(.system(size: 11, weight: .medium))
                            PnLText(value: own.reduce(0) { $0 + $1.value }, currency: currency, font: .system(size: 12, weight: .bold))
                        }
                    }
                }
            }
        }
    }
}

/// A buy or sale on the curve.
private struct TradeTooltip: View {
    let trade: Trade
    let name: String
    let color: Color
    let total: Double
    let perBot: Bool
    let showsHint: Bool

    var body: some View {
        TooltipCard {
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    LineKey(color: color)
                    Text(verbatim: name).font(.system(size: 11)).foregroundStyle(.secondary).lineLimit(1)
                }
                HStack(spacing: 6) {
                    TradeSymbol(isBuy: trade.isBuy).fill(trade.isBuy ? Color.profit : .red).frame(width: 9, height: 9)
                    (trade.isBuy ? Text("Buy \(trade.base)") : Text("Sell \(trade.base)"))
                        .font(.system(size: 13, weight: .semibold))
                }
                Text(verbatim: "\(Fmt.qty(trade.baseQty)) @ \(Fmt.price(trade.price, trade.quote)) = \(Fmt.money(trade.quoteAmount, trade.quote))")
                    .font(.system(size: 11)).monospacedDigit().foregroundStyle(.secondary)
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 3) {
                    if let pnl = trade.pnl {
                        GridRow {
                            Text("Result").foregroundStyle(.secondary)
                            HStack(spacing: 5) {
                                PnLText(value: pnl, currency: trade.quote, font: .system(size: 12, weight: .semibold))
                                if let pct = trade.pnlPct {
                                    Text(Fmt.pct(pct)).monospacedDigit().foregroundStyle(pct.pnlColor)
                                }
                            }
                            .gridColumnAlignment(.trailing)
                        }
                    }
                    GridRow {
                        Text(perBot ? "Bot total" : "Total").foregroundStyle(.secondary)
                        PnLText(value: total, currency: trade.quote, font: .system(size: 12, weight: .semibold))
                    }
                }
                .font(.system(size: 11))
                .padding(.top, 2)
                Text(verbatim: trade.date.formatted(date: .abbreviated, time: .shortened))
                    .font(.system(size: 10.5)).foregroundStyle(.tertiary)
                if showsHint {
                    Text("Click for details").font(.system(size: 10.5, weight: .medium)).foregroundStyle(Color.accentColor)
                }
            }
        }
    }
}

/// The result of one day, week or month.
private struct BucketTooltip: View {
    let bucket: ProfitHistoryData.Bucket
    let title: String
    let currency: String
    let name: (Int) -> String
    let color: (Int) -> Color

    var body: some View {
        TooltipCard {
            VStack(alignment: .leading, spacing: 5) {
                Text(verbatim: title).font(.system(size: 10.5)).foregroundStyle(.secondary)
                PnLText(value: bucket.pnl, currency: currency, font: .system(size: 16, weight: .bold, design: .rounded))
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 3) {
                    GridRow {
                        Text("Sales").foregroundStyle(.secondary)
                        Text(verbatim: String(bucket.sales)).monospacedDigit().gridColumnAlignment(.trailing)
                    }
                    GridRow {
                        Text("With profit").foregroundStyle(.secondary)
                        Text(verbatim: String(bucket.wins)).monospacedDigit()
                    }
                    if bucket.perBot.count > 1 {
                        Divider().gridCellColumns(2).opacity(0.6)
                        ForEach(bucket.perBot, id: \.botId) { part in
                            GridRow {
                                HStack(spacing: 6) {
                                    LineKey(color: color(part.botId))
                                    Text(verbatim: name(part.botId)).foregroundStyle(.secondary).lineLimit(1)
                                }
                                PnLText(value: part.pnl, currency: currency, font: .system(size: 11, weight: .semibold))
                            }
                        }
                    }
                }
                .font(.system(size: 11))
            }
        }
    }
}

private extension View {
    /// Shows the view as a tooltip next to `point`, on the side with more room – or `above` it.
    func tooltip(at point: CGPoint, in size: CGSize, above: Bool = false) -> some View {
        let alignment: Alignment = switch (point.x > size.width * 0.6, above || point.y > size.height * 0.5) {
        case (false, false): .topLeading
        case (true, false): .topTrailing
        case (false, true): .bottomLeading
        case (true, true): .bottomTrailing
        }
        return Color.clear
            .frame(width: 0, height: 0)
            .overlay(alignment: alignment) { fixedSize().padding(14) }
            .position(point)
    }
}

// MARK: - Building blocks

/// A white (dark: lighter grey) card on the window's background.
private struct Panel<Content: View>: View {
    var padding: CGFloat = 14
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Surface.card)
                    .shadow(color: .black.opacity(0.05), radius: 2, y: 1)
            )
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(Color.primary.opacity(0.07), lineWidth: 0.5))
    }
}

/// A y-axis label of fixed width – so the curve and the bars below it start at the same x.
private struct AxisLabel: View {
    static let width: CGFloat = 78
    let text: String

    var body: some View {
        Text(verbatim: text).monospacedDigit().frame(width: Self.width, alignment: .trailing)
    }
}

/// A short stroke in a line's colour – the key of a line in tooltips and the legend.
private struct LineKey: View {
    let color: Color
    var dashed = false

    var body: some View {
        Path { path in
            path.move(to: CGPoint(x: 1, y: 1.5))
            path.addLine(to: CGPoint(x: 13, y: 1.5))
        }
        .stroke(color, style: StrokeStyle(lineWidth: 2.5, lineCap: .round, dash: dashed ? [3, 3] : []))
        .frame(width: 14, height: 3)
    }
}

/// The realized result of the period as a small curve.
private struct Sparkline: View {
    let points: [ProfitPoint]
    let color: Color
    let reveal: Double

    var body: some View {
        let values = points.map(\.value)
        let low = values.min() ?? 0, high = values.max() ?? 0
        Chart {
            ForEach(points) { point in
                AreaMark(x: .value("Date", point.date), yStart: .value("Result", low), yEnd: .value("Result", low + (point.value - low) * reveal))
                    .interpolationMethod(.stepEnd)
                    .foregroundStyle(LinearGradient(colors: [color.opacity(0.22), color.opacity(0.0)], startPoint: .top, endPoint: .bottom))
                LineMark(x: .value("Date", point.date), y: .value("Result", low + (point.value - low) * reveal))
                    .interpolationMethod(.stepEnd)
                    .lineStyle(StrokeStyle(lineWidth: 1.5, lineCap: .round, lineJoin: .round))
                    .foregroundStyle(color)
            }
        }
        .chartXAxis(.hidden)
        .chartYAxis(.hidden)
        .chartLegend(.hidden)
        .chartYScale(domain: low == high ? low - 1...high + 1 : low...high)
    }
}

/// Buys (left, green) against sales (right, red).
private struct SplitBar: View {
    let left: Double
    let right: Double

    var body: some View {
        GeometryReader { geo in
            let share = left + right > 0 ? left / (left + right) : 0.5
            HStack(spacing: 2) {
                Capsule().fill(Color.profit).frame(width: max((geo.size.width - 2) * share, 0))
                Capsule().fill(Color.red)
            }
        }
    }
}

/// The share of winning sales as a ring.
private struct Ring: View {
    let share: Double

    var body: some View {
        ZStack {
            Circle().stroke(Color.primary.opacity(0.09), lineWidth: 4)
            Circle()
                .trim(from: 0, to: share)
                .stroke(Color.profit, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                .rotationEffect(.degrees(-90))
        }
    }
}

/// A bot's result against the largest one: from the left – or, with profits and losses, from the middle.
private struct ResultBar: View {
    let value: Double
    let scale: Double
    let diverging: Bool

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width
            let zero = diverging ? width / 2 : 0
            let room = diverging ? width / 2 : width
            let length = scale > 0 ? max(CGFloat(abs(value) / scale) * room, value == 0 ? 0 : 2) : 0
            ZStack(alignment: .leading) {
                Capsule().fill(Color.primary.opacity(0.06))
                Capsule().fill(value < 0 ? Color.red : Color.profit)
                    .frame(width: length)
                    .offset(x: value < 0 ? zero - length : zero)
                if diverging {
                    Rectangle().fill(Color.primary.opacity(0.3)).frame(width: 1).offset(x: zero - 0.5)
                }
            }
        }
    }
}

/// A trade's details as a page of the menu bar panel – opened from the trade list or a bot's recent trades.
struct TradeDetailPage: View {
    @Environment(AppStore.self) private var store
    let tradeId: Int
    let back: () -> Void
    /// The longer history, so the buy that belongs to an older sale is found too.
    @State private var history: [Trade]?

    private var trades: [Trade] { history ?? store.trades }

    var body: some View {
        VStack(spacing: 0) {
            PageHeader(title: "Trade", back: back)
            Divider().opacity(0.5)
            if let trade = trades.first(where: { $0.id == tradeId }) {
                let bot = store.bots.first { $0.id == trade.botId }
                ScrollView {
                    TradeDetailPanel(
                        trade: trade, links: TradeLinks(trades), botName: bot?.name ?? trade.botName,
                        botColor: bot.map { strategyColors($0.strategy)[0] } ?? .secondary,
                        market: bot?.symbol == trade.symbol ? bot?.market?.price : nil,
                        close: nil, framed: false
                    )
                    .padding(14)
                }
                .scrollIndicators(.never)
            } else if history == nil {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                EmptyStateView(icon: "tray", title: "Trade not found", message: "It is no longer among the loaded trades.")
                Spacer()
            }
        }
        .task { history = await store.allTrades(limit: 1000) ?? store.trades }
    }
}
