// Renders the app icon (gradient squircle + chart symbol + the X of Revolut X in the bottom-right corner):
//   make-icon.swift <dir>                  .iconset folder for the macOS app
//   make-icon.swift --ios <file.png>       the iPhone icon: one 1024 px square without transparency (iOS rounds the corners)
//   make-icon.swift --png <px> <file.png>  a single rounded icon (Home Assistant add-on icon)
//   make-icon.swift --logo <file.png>      icon + name, 250 × 100 (Home Assistant add-on logo)
import AppKit

let args = Array(CommandLine.arguments.dropFirst())

func bitmap(_ width: Int, _ height: Int, _ draw: () -> Void) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height, bitsPerSample: 8,
                               samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

/// The icon itself, drawn into `rect` (square). `rounded` = squircle, otherwise full bleed.
func drawIcon(in rect: NSRect, rounded: Bool) {
    let w = rect.width
    let path = rounded ? NSBezierPath(roundedRect: rect, xRadius: w * 0.225, yRadius: w * 0.225) : NSBezierPath(rect: rect)
    NSGradient(colors: [NSColor(red: 0.22, green: 0.52, blue: 1.0, alpha: 1),
                        NSColor(red: 0.50, green: 0.28, blue: 0.95, alpha: 1)])!.draw(in: path, angle: -45)

    // the chart, moved up and to the left to make room for the X
    let config = NSImage.SymbolConfiguration(pointSize: w * 0.38, weight: .semibold)
        .applying(.init(paletteColors: [.white]))
    if let symbol = NSImage(systemSymbolName: "chart.line.uptrend.xyaxis", accessibilityDescription: nil)?
        .withSymbolConfiguration(config) {
        let size = symbol.size
        symbol.draw(in: NSRect(x: rect.minX + w * 0.42 - size.width / 2, y: rect.minY + w * 0.59 - size.height / 2,
                               width: size.width, height: size.height))
    }

    // the X of Revolut X, bottom right
    NSColor.white.setFill()
    revolutX(in: NSRect(x: rect.minX + w * 0.63, y: rect.minY + w * 0.12, width: w * 0.23, height: w * 0.245))
}

/// The X of Revolut X, filled with the current color: flat horizontal ends, one continuous stroke from top left to
/// bottom right, the other one broken – its upper right arm stands apart from the main stroke.
func revolutX(in r: NSRect) {
    let t = 0.24, gap = 0.1 // stroke width and gap, as a fraction of the width
    func p(_ x: Double, _ y: Double) -> NSPoint { NSPoint(x: r.minX + x * r.width, y: r.maxY - y * r.height) }
    func poly(_ points: [NSPoint]) -> NSBezierPath {
        let path = NSBezierPath()
        path.move(to: points[0])
        points.dropFirst().forEach(path.line(to:))
        path.close()
        return path
    }
    poly([p(0, 0), p(t, 0), p(1, 1), p(1 - t, 1)]).fill()
    let other = poly([p(1 - t, 0), p(1, 0), p(t, 1), p(0, 1)])
    for side in [poly([p(t / 2, 0), p(1 - t / 2, 1), p(0, 1)]),          // lower left arm, runs into the main stroke
                 poly([p(t + gap, 0), p(1 + gap, 1), p(2, 1), p(2, 0)])] { // upper right arm, apart from it
        NSGraphicsContext.saveGraphicsState()
        side.addClip()
        other.fill()
        NSGraphicsContext.restoreGraphicsState()
    }
}

func icon(_ px: Int, fullBleed: Bool = false) -> Data {
    bitmap(px, px) {
        let s = CGFloat(px)
        let inset = fullBleed ? 0 : s * 0.1
        drawIcon(in: NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset), rounded: !fullBleed)
    }
}

func write(_ data: Data, _ path: String) {
    try! data.write(to: URL(fileURLWithPath: path))
}

switch args.first {
case "--ios":
    write(icon(1024, fullBleed: true), args[1])
case "--png":
    write(bitmap(Int(args[1])!, Int(args[1])!) {
        let s = CGFloat(Int(args[1])!)
        drawIcon(in: NSRect(x: 0, y: 0, width: s, height: s), rounded: true)
    }, args[2])
case "--logo":
    write(bitmap(250, 100) {
        drawIcon(in: NSRect(x: 4, y: 14, width: 72, height: 72), rounded: true)
        let font = NSFont.systemFont(ofSize: 30, weight: .bold)
        let text = NSAttributedString(string: "DipAgentX", attributes: [
            .font: font, .foregroundColor: NSColor(red: 0.11, green: 0.11, blue: 0.12, alpha: 1),
        ])
        text.draw(at: NSPoint(x: 88, y: 50 - text.size().height / 2))
    }, args[1])
default:
    let out = args[0]
    try? FileManager.default.createDirectory(atPath: out, withIntermediateDirectories: true)
    for base in [16, 32, 128, 256, 512] {
        write(icon(base), "\(out)/icon_\(base)x\(base).png")
        write(icon(base * 2), "\(out)/icon_\(base)x\(base)@2x.png")
    }
}
