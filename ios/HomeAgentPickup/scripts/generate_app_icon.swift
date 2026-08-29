import AppKit
import Foundation

/// Reliable Home Mic app icon (1024²). Avoid NSImage.lockFocus — it often
/// leaves the bitmap empty (solid black) on recent macOS.
let pixels = 1024
guard let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: pixels,
    pixelsHigh: pixels,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: pixels * 4,
    bitsPerPixel: 32
) else {
    fputs("Failed to create bitmap\n", stderr)
    exit(1)
}
rep.size = NSSize(width: pixels, height: pixels)

guard let ctx = NSGraphicsContext(bitmapImageRep: rep) else {
    fputs("Failed to create graphics context\n", stderr)
    exit(1)
}
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = ctx
let cg = ctx.cgContext
cg.setShouldAntialias(true)

let canvas = CGRect(x: 0, y: 0, width: pixels, height: pixels)

// Warm terracotta radial-ish fill (two-stop vertical gradient).
let colors = [
    NSColor(red: 0.98, green: 0.62, blue: 0.38, alpha: 1).cgColor,
    NSColor(red: 0.86, green: 0.36, blue: 0.22, alpha: 1).cgColor,
] as CFArray
if let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 1]) {
    cg.drawLinearGradient(
        gradient,
        start: CGPoint(x: pixels / 2, y: pixels),
        end: CGPoint(x: pixels / 2, y: 0),
        options: []
    )
}

func strokePath(_ build: (CGMutablePath) -> Void, width: CGFloat) {
    let path = CGMutablePath()
    build(path)
    cg.setStrokeColor(NSColor.white.cgColor)
    cg.setLineWidth(width)
    cg.setLineCap(.round)
    cg.setLineJoin(.round)
    cg.addPath(path)
    cg.strokePath()
}

func fillPath(_ build: (CGMutablePath) -> Void) {
    let path = CGMutablePath()
    build(path)
    cg.setFillColor(NSColor.white.cgColor)
    cg.addPath(path)
    cg.fillPath()
}

// House outline (simple, bold).
let houseLine: CGFloat = 36
strokePath({ p in
    p.move(to: CGPoint(x: 250, y: 430))
    p.addLine(to: CGPoint(x: 512, y: 720))
    p.addLine(to: CGPoint(x: 774, y: 430))
    p.addLine(to: CGPoint(x: 730, y: 430))
    p.addLine(to: CGPoint(x: 730, y: 250))
    p.addLine(to: CGPoint(x: 294, y: 250))
    p.addLine(to: CGPoint(x: 294, y: 430))
    p.closeSubpath()
}, width: houseLine)

// Chimney
strokePath({ p in
    p.move(to: CGPoint(x: 620, y: 640))
    p.addLine(to: CGPoint(x: 620, y: 720))
    p.addLine(to: CGPoint(x: 690, y: 720))
    p.addLine(to: CGPoint(x: 690, y: 580))
}, width: houseLine)

// Mic capsule
fillPath { p in
    p.addRoundedRect(
        in: CGRect(x: 452, y: 400, width: 120, height: 200),
        cornerWidth: 60,
        cornerHeight: 60
    )
}

// Mic stand + base
strokePath({ p in
    p.move(to: CGPoint(x: 420, y: 430))
    p.addQuadCurve(to: CGPoint(x: 604, y: 430), control: CGPoint(x: 512, y: 310))
    p.move(to: CGPoint(x: 512, y: 340))
    p.addLine(to: CGPoint(x: 512, y: 300))
}, width: 28)
fillPath { p in
    p.addRoundedRect(
        in: CGRect(x: 430, y: 275, width: 164, height: 28),
        cornerWidth: 14,
        cornerHeight: 14
    )
}

NSGraphicsContext.restoreGraphicsState()

let outPath = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.png"
guard let data = rep.representation(using: .png, properties: [:]) else {
    fputs("Failed to encode PNG\n", stderr)
    exit(1)
}
try data.write(to: URL(fileURLWithPath: outPath))
print("Wrote \(outPath) (\(pixels)x\(pixels))")
