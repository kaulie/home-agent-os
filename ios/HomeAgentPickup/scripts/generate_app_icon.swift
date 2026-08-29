import AppKit
import Foundation

let pixels = 1024
let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: pixels,
    pixelsHigh: pixels,
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
)!
let image = NSImage(size: NSSize(width: pixels, height: pixels))
image.addRepresentation(rep)
image.lockFocus()

let canvas = NSRect(x: 0, y: 0, width: CGFloat(pixels), height: CGFloat(pixels))

NSGradient(colors: [
    NSColor(red: 0.11, green: 0.16, blue: 0.30, alpha: 1),
    NSColor(red: 0.04, green: 0.06, blue: 0.11, alpha: 1),
])?.draw(in: canvas, angle: 140)

let glow = NSBezierPath(ovalIn: NSRect(x: 220, y: 220, width: 584, height: 584))
NSColor(red: 0.96, green: 0.48, blue: 0.20, alpha: 0.18).setFill()
glow.fill()

let cream = NSColor(red: 0.98, green: 0.93, blue: 0.86, alpha: 1)
let roof = NSBezierPath()
roof.move(to: NSPoint(x: 512, y: 700))
roof.line(to: NSPoint(x: 286, y: 500))
roof.line(to: NSPoint(x: 738, y: 500))
roof.close()
cream.setFill()
roof.fill()
NSBezierPath(rect: NSRect(x: 332, y: 290, width: 360, height: 210)).fill()
let door = NSBezierPath(roundedRect: NSRect(x: 462, y: 310, width: 100, height: 190), xRadius: 14, yRadius: 14)
NSColor(red: 0.16, green: 0.20, blue: 0.32, alpha: 1).setFill()
door.fill()

let micCircle = NSBezierPath(ovalIn: NSRect(x: 352, y: 352, width: 320, height: 320))
NSGraphicsContext.saveGraphicsState()
micCircle.addClip()
NSGradient(colors: [
    NSColor(red: 0.96, green: 0.24, blue: 0.30, alpha: 1),
    NSColor(red: 0.74, green: 0.10, blue: 0.16, alpha: 1),
])?.draw(in: micCircle.bounds, angle: 135)
NSGraphicsContext.restoreGraphicsState()

NSColor.white.setFill()
NSBezierPath(roundedRect: NSRect(x: 432, y: 520, width: 160, height: 210), xRadius: 80, yRadius: 80).fill()
NSBezierPath(rect: NSRect(x: 492, y: 455, width: 40, height: 78)).fill()
NSBezierPath(roundedRect: NSRect(x: 442, y: 422, width: 140, height: 26), xRadius: 13, yRadius: 13).fill()
let stand = NSBezierPath()
stand.move(to: NSPoint(x: 472, y: 422))
stand.line(to: NSPoint(x: 428, y: 378))
stand.move(to: NSPoint(x: 552, y: 422))
stand.line(to: NSPoint(x: 596, y: 378))
stand.lineWidth = 16
stand.lineCapStyle = .round
NSColor.white.setStroke()
stand.stroke()

image.unlockFocus()

let outPath = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "AppIcon.png"
guard let data = rep.representation(using: .png, properties: [:]) else {
    fputs("Failed to encode PNG\n", stderr)
    exit(1)
}
try data.write(to: URL(fileURLWithPath: outPath))
print("Wrote \(outPath) (\(pixels)x\(pixels))")
