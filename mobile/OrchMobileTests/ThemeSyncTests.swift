import XCTest
import SwiftUI
import UIKit
@testable import OrchMobile

/// Theme.swift must keep the colours of brand/tokens.css (copy in Fixtures; re-copy when the brand changes).
/// `borderStrong` is deliberately different (3:1 touch borders) and is not compared.
final class ThemeSyncTests: XCTestCase {
    private func tokens() throws -> [String: UInt32] {
        let url = Bundle(for: BundleToken.self).url(forResource: "tokens", withExtension: "css")!
        var out: [String: UInt32] = [:]
        for line in try String(contentsOf: url, encoding: .utf8).split(separator: "\n") {
            let t = line.trimmingCharacters(in: .whitespaces)
            guard t.hasPrefix("--"), let colon = t.firstIndex(of: ":") else { continue }
            let value = t[t.index(after: colon)...].trimmingCharacters(in: CharacterSet(charactersIn: "; ")).components(separatedBy: " ")[0]
            guard value.hasPrefix("#"), let v = UInt32(value.dropFirst(), radix: 16) else { continue }
            out[String(t[t.index(t.startIndex, offsetBy: 2)..<colon])] = v
        }
        return out
    }
    private func hex(_ c: Color) -> UInt32 {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(c).getRed(&r, green: &g, blue: &b, alpha: &a)
        return (UInt32((r * 255).rounded()) << 16) | (UInt32((g * 255).rounded()) << 8) | UInt32((b * 255).rounded())
    }
    func testThemeMatchesBrandTokens() throws {
        let t = try tokens()
        let pairs: [(String, Color)] = [("bg", Theme.bg), ("sidebar", Theme.sidebar), ("surface", Theme.surface), ("surface-2", Theme.surface2),
                                        ("surface-3", Theme.surface3), ("border", Theme.border), ("text", Theme.text), ("text-muted", Theme.muted),
                                        ("brand", Theme.brand), ("on-brand", Theme.onBrand), ("warning", Theme.warn), ("danger", Theme.danger)]
        for (name, color) in pairs {
            XCTAssertEqual(hex(color), t[name], "Theme differs from brand token --\(name)")
        }
    }
}
