import AppKit
import Foundation

// Synthetic test postings only. No personal or real job data.
let root = URL(fileURLWithPath: CommandLine.arguments[1])

func make(_ name: String, _ rows: [(String, CGFloat, CGFloat)], _ format: NSBitmapImageRep.FileType) {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 1800, pixelsHigh: 1200,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    NSColor.white.setFill()
    NSRect(x: 0, y: 0, width: 1800, height: 1200).fill()
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 48), .foregroundColor: NSColor.black
    ]
    for (line, x, y) in rows {
        (line as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: attributes)
    }
    NSGraphicsContext.restoreGraphicsState()
    let data = bitmap.representation(using: format, properties: [:])!
    try! data.write(to: root.appendingPathComponent(name))
}

make("page1.png", [
    ("[가상 공고] 데이터 분석가", 80, 1060),
    ("필수 Python 3년", 80, 940),
    ("SQL 경험 없음", 80, 820),
    ("마감 2026-10-31", 80, 700),
    ("[다른 직무] 디자인", 920, 940),
    ("우대 Figma 2년", 920, 820)
], .png)
make("page2.jpg", [
    ("[가상 공고] 두 번째 페이지", 80, 1040),
    ("English reports required", 80, 900),
    ("지원 가능 2026-11-15", 80, 760)
], .jpeg)
