import SwiftUI

/// The icon of a strategy (and of a bot): a tile in the strategy's colours with its symbol. The momentum trend follower
/// and the lead-lag bot get a drawn symbol instead of an SF symbol and, for the ten most important coins, a small coin
/// badge in the corner – the coin the bot trades (or will trade, in the editor).
public struct StrategyIcon: View {
    let strategy: String
    let symbol: String
    var coin: String?
    var size: CGFloat

    public init(strategy: String, symbol: String, coin: String? = nil, size: CGFloat = 30) {
        self.strategy = strategy
        self.symbol = symbol
        self.coin = coin
        self.size = size
    }

    public var body: some View {
        switch strategy {
        case "momentum": TrendTile(size: size).overlay(alignment: .bottomTrailing) { badge }
        case "leadlag": LeadLagTile(size: size).overlay(alignment: .bottomTrailing) { badge }
        default: IconTile(symbol: symbol, colors: strategyColors(strategy), size: size)
        }
    }

    @ViewBuilder private var badge: some View {
        if let coin, let mark = CoinMark.of(coin) {
            CoinBadge(mark: mark, size: (size * 0.5).rounded())
                .offset(x: size * 0.16, y: size * 0.16)
        }
    }
}

/// The lead-lag tile, from Bitcoin orange to Ethereum blue: BTC jumps first (the bright line), the coin follows a
/// moment later (the faint line) – the bot buys in between.
struct LeadLagTile: View {
    let size: CGFloat

    var body: some View {
        let colors = strategyColors("leadlag")
        let line = max(1.6, size * 0.085)
        RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
            .fill(LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottomTrailing))
            .frame(width: size, height: size)
            .overlay {
                ZStack {
                    StepLine(from: 0.70, to: 0.40, start: 0.40, end: 0.54)
                        .stroke(.white.opacity(0.55), style: StrokeStyle(lineWidth: line, lineCap: .round, lineJoin: .round))
                    StepLine(from: 0.50, to: 0.08, start: 0.12, end: 0.28)
                        .stroke(.white, style: StrokeStyle(lineWidth: line, lineCap: .round, lineJoin: .round))
                }
                .frame(width: size * 0.66, height: size * 0.66)
            }
            .shadow(color: colors.last!.opacity(0.35), radius: 4, y: 2)
    }
}

/// A flat line that jumps from height ``from`` to ``to`` between ``start`` and ``end`` (unit square, y downwards).
struct StepLine: Shape {
    let from: Double, to: Double, start: Double, end: Double

    func path(in rect: CGRect) -> Path {
        func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: rect.minX + rect.width * x, y: rect.minY + rect.height * y) }
        var path = Path()
        path.move(to: p(0.0, from))
        path.addLine(to: p(start, from))
        path.addLine(to: p(end, to))
        path.addLine(to: p(1.0, to))
        return path
    }
}

/// The momentum tile: a rising line with an arrow head over three steps – the position grows in steps with the trend.
struct TrendTile: View {
    let size: CGFloat

    var body: some View {
        let colors = strategyColors("momentum")
        RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
            .fill(LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottomTrailing))
            .frame(width: size, height: size)
            .overlay {
                ZStack {
                    TrendSteps().fill(.white.opacity(0.28))
                    TrendArrow().stroke(.white, style: StrokeStyle(lineWidth: max(1.6, size * 0.085), lineCap: .round,
                                                                   lineJoin: .round))
                }
                .frame(width: size * 0.66, height: size * 0.66)
            }
            .shadow(color: colors.first!.opacity(0.35), radius: 4, y: 2)
    }
}

/// Three bars of rising height along the bottom (unit square).
struct TrendSteps: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let w = rect.width, h = rect.height
        for (i, height) in [0.26, 0.44, 0.62].enumerated() {
            let x = rect.minX + w * (0.04 + Double(i) * 0.34)
            path.addRoundedRect(in: CGRect(x: x, y: rect.maxY - h * height, width: w * 0.24, height: h * height),
                                cornerSize: CGSize(width: w * 0.06, height: w * 0.06))
        }
        return path
    }
}

/// A zigzag line rising to the top right, ending in an arrow head.
struct TrendArrow: Shape {
    func path(in rect: CGRect) -> Path {
        func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: rect.minX + rect.width * x, y: rect.minY + rect.height * y) }
        var path = Path()
        path.move(to: p(0.0, 0.70))
        path.addLine(to: p(0.36, 0.36))
        path.addLine(to: p(0.56, 0.54))
        path.addLine(to: p(0.98, 0.10))
        path.move(to: p(0.62, 0.08))
        path.addLine(to: p(0.98, 0.08))
        path.addLine(to: p(0.98, 0.44))
        return path
    }
}

/// How a coin is drawn in its badge: an SF symbol or a character, on the coin's colour(s).
struct CoinMark {
    enum Glyph {
        case symbol(String)
        case text(String)
        case ethereum, solana  // drawn: their logos have no SF symbol or character
    }

    let glyph: Glyph
    let colors: [Color]
    var dark = false  // a dark glyph on a light colour

    private static func rgb(_ hex: UInt32) -> Color {
        Color(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }

    /// The ten most important coins (by market value, without stablecoins) – everything else gets no badge.
    static func of(_ coin: String) -> CoinMark? {
        switch coin.uppercased() {
        case "BTC": return CoinMark(glyph: .symbol("bitcoinsign"), colors: [rgb(0xF7931A)])
        case "ETH": return CoinMark(glyph: .ethereum, colors: [rgb(0x627EEA)])
        case "XRP": return CoinMark(glyph: .symbol("xmark"), colors: [rgb(0x23292F)])
        case "BNB": return CoinMark(glyph: .symbol("diamond.fill"), colors: [rgb(0xF3BA2F)], dark: true)
        case "SOL": return CoinMark(glyph: .solana, colors: [rgb(0x9945FF), rgb(0x14F195)])
        case "DOGE": return CoinMark(glyph: .text("Ð"), colors: [rgb(0xC2A633)])
        case "ADA": return CoinMark(glyph: .text("₳"), colors: [rgb(0x0033AD)])
        case "TRX": return CoinMark(glyph: .symbol("triangle.fill"), colors: [rgb(0xEB0029)])
        case "LINK": return CoinMark(glyph: .symbol("hexagon"), colors: [rgb(0x2A5ADA)])
        case "LTC": return CoinMark(glyph: .text("Ł"), colors: [rgb(0x345D9D)])
        default: return nil
        }
    }
}

/// A round coin badge with a ring in the background colour, so it stands out from the tile it sits on.
struct CoinBadge: View {
    let mark: CoinMark
    let size: CGFloat

    var body: some View {
        Circle()
            .fill(LinearGradient(colors: mark.colors.count > 1 ? mark.colors : [mark.colors[0], mark.colors[0]],
                                 startPoint: .topLeading, endPoint: .bottomTrailing))
            .frame(width: size, height: size)
            .overlay { glyph.foregroundStyle(mark.dark ? Color.black.opacity(0.8) : .white) }
            .padding(max(1.2, size * 0.1))
            .background(Circle().fill(.background))
    }

    @ViewBuilder private var glyph: some View {
        switch mark.glyph {
        case .symbol(let name):
            Image(systemName: name)
                .font(.system(size: size * (name == "bitcoinsign" ? 0.6 : 0.46), weight: .bold))
                .rotationEffect(name == "triangle.fill" ? .degrees(180) : .zero)
        case .text(let text):
            Text(verbatim: text).font(.system(size: size * 0.62, weight: .bold, design: .rounded))
        case .ethereum:
            EthereumMark().frame(width: size * 0.36, height: size * 0.6)
        case .solana:
            SolanaMark().frame(width: size * 0.54, height: size * 0.42)
        }
    }
}

/// The Ethereum diamond: an upper and a lower part with a small gap.
struct EthereumMark: Shape {
    func path(in rect: CGRect) -> Path {
        func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: rect.minX + rect.width * x, y: rect.minY + rect.height * y) }
        var path = Path()
        path.addLines([p(0.5, 0), p(1, 0.52), p(0.5, 0.68), p(0, 0.52)])
        path.closeSubpath()
        path.addLines([p(0, 0.62), p(0.5, 0.78), p(1, 0.62), p(0.5, 1)])
        path.closeSubpath()
        return path
    }
}

/// The Solana mark: three slanted bars, the middle one slanted the other way.
struct SolanaMark: Shape {
    func path(in rect: CGRect) -> Path {
        func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: rect.minX + rect.width * x, y: rect.minY + rect.height * y) }
        var path = Path()
        for (top, flip) in [(0.0, false), (0.38, true), (0.76, false)] {
            let bottom = top + 0.24
            if flip {
                path.addLines([p(0, top), p(0.8, top), p(1, bottom), p(0.2, bottom)])
            } else {
                path.addLines([p(0.2, top), p(1, top), p(0.8, bottom), p(0, bottom)])
            }
            path.closeSubpath()
        }
        return path
    }
}
