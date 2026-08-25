import SwiftUI

/// Brand mark: house outline + central agent hub with three edge nodes on an orbit.
struct HomeAgentMark: View {
    var body: some View {
        GeometryReader { geo in
            let s = min(geo.size.width, geo.size.height)
            let line = max(1.2, s * 0.055)
            Canvas { context, size in
                let cx = size.width * 0.5
                let cy = size.height * 0.52
                let sand = Color(red: 0.82, green: 0.70, blue: 0.48)

                // House roof + walls (rounded base).
                var house = Path()
                let roofY = size.height * 0.18
                let eavesY = size.height * 0.38
                let baseY = size.height * 0.86
                let left = size.width * 0.18
                let right = size.width * 0.82
                let mid = size.width * 0.5
                house.move(to: CGPoint(x: mid, y: roofY))
                house.addLine(to: CGPoint(x: right + s * 0.02, y: eavesY))
                house.addLine(to: CGPoint(x: right, y: eavesY))
                house.addLine(to: CGPoint(x: right, y: baseY - s * 0.08))
                house.addQuadCurve(
                    to: CGPoint(x: left, y: baseY - s * 0.08),
                    control: CGPoint(x: mid, y: baseY + s * 0.04)
                )
                house.addLine(to: CGPoint(x: left, y: eavesY))
                house.addLine(to: CGPoint(x: left - s * 0.02, y: eavesY))
                house.closeSubpath()
                context.stroke(house, with: .color(sand), style: StrokeStyle(lineWidth: line, lineJoin: .round))

                // Orbit (dashed).
                let orbitR = s * 0.22
                let orbit = Path(ellipseIn: CGRect(x: cx - orbitR, y: cy - orbitR, width: orbitR * 2, height: orbitR * 2))
                context.stroke(
                    orbit,
                    with: .color(sand.opacity(0.55)),
                    style: StrokeStyle(lineWidth: line * 0.55, dash: [s * 0.04, s * 0.035])
                )

                // Three edge spokes + nodes.
                let angles: [Double] = [-.pi / 2 + 0.35, .pi / 6 + 0.15, .pi - .pi / 6 - 0.15]
                for a in angles {
                    let nx = cx + cos(a) * orbitR
                    let ny = cy + sin(a) * orbitR
                    var spoke = Path()
                    spoke.move(to: CGPoint(x: cx, y: cy))
                    spoke.addLine(to: CGPoint(x: nx, y: ny))
                    context.stroke(spoke, with: .color(sand.opacity(0.75)), style: StrokeStyle(lineWidth: line * 0.7, lineCap: .round))
                    let nodeR = s * 0.045
                    let node = Path(ellipseIn: CGRect(x: nx - nodeR, y: ny - nodeR, width: nodeR * 2, height: nodeR * 2))
                    context.fill(node, with: .color(sand))
                }

                // Hub.
                let hubR = s * 0.085
                let hub = Path(ellipseIn: CGRect(x: cx - hubR, y: cy - hubR, width: hubR * 2, height: hubR * 2))
                context.fill(hub, with: .color(sand))
                let glow = Path(ellipseIn: CGRect(x: cx - hubR * 1.55, y: cy - hubR * 1.55, width: hubR * 3.1, height: hubR * 3.1))
                context.fill(glow, with: .color(sand.opacity(0.18)))
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

#Preview {
    ZStack {
        EdgeTheme.ink
        HomeAgentMark()
            .frame(width: 120, height: 120)
    }
}
