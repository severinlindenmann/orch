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
    static let online = brand
    static let warn = Color(hex: 0xfbbf24), danger = Color(hex: 0xf87171), purple = Color(hex: 0xb392f0)
}

// No static Theme.font(size): a size read once in body does not follow a live Dynamic Type change (the a11y audit
// flags it). Use themeFont(_:) on views, or an @ScaledMetric size for concatenated Text.

/// Scales with the live Dynamic Type setting (ScaledMetric reads the environment), so a text-size change
/// re-lays out the open screen without resetting view identity (drafts, sheets and confirmations survive).
struct ThemeFont: ViewModifier {
    @ScaledMetric private var size: CGFloat
    let weight: Font.Weight
    init(_ size: CGFloat, _ weight: Font.Weight) { _size = ScaledMetric(wrappedValue: size); self.weight = weight }
    func body(content: Content) -> some View { content.font(.system(size: size, weight: weight)) }
}

extension View {
    func themeFont(_ size: CGFloat, _ weight: Font.Weight = .regular) -> some View { modifier(ThemeFont(size, weight)) }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xff) / 255, green: Double((hex >> 8) & 0xff) / 255, blue: Double(hex & 0xff) / 255)
    }
}

/// One corner-radius scale for the whole app (iOS 26 HIG: continuous squircle corners, concentric: inner = outer - padding).
extension Theme {
    enum Radius {
        static let s: CGFloat = 8       // small chips, tags, thumbnails
        static let m: CGFloat = 14      // cards, inputs, buttons, banners
        static let l: CGFloat = 22      // message bubbles, large panels
        static let xl: CGFloat = 26     // composer, app-owned panels
        static let pill: CGFloat = 999  // capsules
        /// Rounded-square avatars: 30 percent of the size.
        static func avatar(_ size: CGFloat) -> CGFloat { size * 0.3 }
    }
}

extension View {
    /// Continuous (squircle) rounded rectangle background + optional border, from the radius scale.
    func themeCard(_ radius: CGFloat = Theme.Radius.m, fill: Color = Theme.surface2, border: Color? = Theme.border) -> some View {
        background(fill, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
            .overlay { if let border { RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(border) } }
    }
}

extension Theme {
    /// The navigation bar fills the status-bar / Dynamic Island strip with the same surface colour as the bar itself.
    static func applyBarAppearance() {
        let appearance = UINavigationBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(Theme.bg)
        appearance.shadowColor = UIColor(Theme.border)
        appearance.titleTextAttributes = [.foregroundColor: UIColor(Theme.text)]
        UINavigationBar.appearance().standardAppearance = appearance
        UINavigationBar.appearance().scrollEdgeAppearance = appearance
        UINavigationBar.appearance().compactAppearance = appearance
    }
}
