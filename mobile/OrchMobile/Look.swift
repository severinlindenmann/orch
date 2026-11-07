import Foundation

/// Workspace look (contracts/look.md): default colour and letter from the name, fallbacks for unknown values.
enum Look {
    /// `clean(name)`: NFC, then trim Unicode White_Space at both ends.
    static func clean(_ name: String) -> String {
        let nfc = name.precomposedStringWithCanonicalMapping
        let ws = CharacterSet.whitespacesAndNewlines.union(CharacterSet(charactersIn: "\u{85}\u{200E}\u{200F}\u{2028}\u{2029}")).subtracting(CharacterSet(charactersIn: "\u{200B}\u{FEFF}"))
        var scalars = Substring(nfc).unicodeScalars
        while let f = scalars.first, ws.contains(f) { scalars.removeFirst() }
        while let l = scalars.last, ws.contains(l) { scalars.removeLast() }
        return String(String.UnicodeScalarView(scalars))
    }

    /// djb2 over the UTF-8 bytes, 32-bit wrapping.
    static func djb2(_ name: String) -> UInt32 {
        clean(name).utf8.reduce(UInt32(5381)) { ($0 &* 33) &+ UInt32($1) }
    }

    static func defaultColor(for name: String) -> String {
        LookData.colors[Int(djb2(name) % UInt32(LookData.colors.count))].id
    }

    /// First letter or digit of the clean name, upper-cased when that stays one code point; none gives "?".
    static func letter(for name: String) -> String {
        for ch in clean(name).unicodeScalars where CharacterSet.letters.contains(ch) || isNumber(ch) {
            let up = String(ch).uppercased()
            return up.unicodeScalars.count == 1 ? up : String(ch)
        }
        return "?"
    }
    private static func isNumber(_ s: Unicode.Scalar) -> Bool {
        switch s.properties.generalCategory { case .decimalNumber, .letterNumber, .otherNumber: return true; default: return false }
    }

    struct Shown: Equatable {
        let icon: String?
        let color: String
        let letter: String
    }

    /// What a badge draws. Unknown icon: letter. Unknown or missing colour: Automatic. Stored values are never touched.
    static func shown(icon: String?, color: String?, name: String) -> Shown {
        let known = icon.flatMap { LookData.iconIds.contains($0) ? $0 : nil }
        let col = color.flatMap { c in LookData.colors.contains { $0.id == c } ? c : nil } ?? defaultColor(for: name)
        return Shown(icon: known, color: col, letter: letter(for: name))
    }

    static func darkHex(_ token: String) -> UInt32 {
        LookData.colors.first { $0.id == token }?.dark ?? LookData.colors[0].dark
    }
}
