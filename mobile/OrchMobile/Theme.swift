import SwiftUI
import UIKit

/// Orbit brand tokens (brand/tokens.css). Dark only.
enum Theme {
    static let bg = Color(hex: 0x0e1014), sidebar = Color(hex: 0x0a0c0f)
    static let surface = Color(hex: 0x15181d), surface2 = Color(hex: 0x1c2027), surface3 = Color(hex: 0x242a32)
    static let border = Color(hex: 0x2a3038)
    /// Borders of things you touch (inputs, options, chips): >= 3:1 on bg and surface.
    static let borderStrong = Color(hex: 0x667180)
    static let text = Color(hex: 0xe8eaed), muted = Color(hex: 0x9aa3ad)
    static let brand = Color(hex: 0x2fc6a3), onBrand = Color(hex: 0x06231c)
    static let warn = Color(hex: 0xfbbf24), danger = Color(hex: 0xf87171), purple = Color(hex: 0xb392f0)
}

extension Theme {
    /// Fixed design sizes that still follow the user's Dynamic Type setting.
    static func font(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: UIFontMetrics.default.scaledValue(for: size), weight: weight)
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255, blue: Double(hex & 0xff) / 255)
    }
}
