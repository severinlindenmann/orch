import SwiftUI

struct ShellAvatar: View {
    let name: String
    var size: CGFloat = 46
    /// When set, shows the green dot while the workspace is online (re-checked every minute so "online" expires).
    var lastSeen: String?? = nil
    private var tint: Color {
        let hash = name.utf8.reduce(UInt64(5381)) { ($0 &* 33) &+ UInt64($1) }
        return [Theme.brand, Color(red: 0.76, green: 0.64, blue: 0.88), Color(red: 0.85, green: 0.71, blue: 0.46)][Int(hash % 3)]
    }
    var body: some View {
        Text(String(name.trimmingCharacters(in: .whitespaces).prefix(1)).uppercased())
            .themeFont(size * 0.44, .semibold).foregroundStyle(tint)
            .frame(width: size, height: size).background(tint.opacity(0.18), in: RoundedRectangle(cornerRadius: Theme.Radius.avatar(size), style: .continuous))
            .overlay(alignment: .bottomTrailing) {
                if let lastSeen {
                    TimelineView(.everyMinute) { context in
                        Circle().fill(Presence.of(lastSeen: lastSeen, now: context.date).isOnline ? Theme.online : Theme.muted).frame(width: 8, height: 8)
                            .overlay(Circle().stroke(Theme.surface, lineWidth: 2))
                    }
                }
            }.accessibilityHidden(true)
    }
}

struct ShellBadge: View {
    let count: Int
    var body: some View {
        if count > 0 {
            Text(count > 99 ? "99+" : "\(count)").themeFont(12, .semibold)
                .foregroundStyle(Theme.onBrand).padding(.horizontal, 6).padding(.vertical, 3)
                .background(Theme.brand, in: Capsule(style: .continuous)).accessibilityLabel("\(count) unread")
        }
    }
}

struct PresenceLine: View {
    let lastSeen: String?
    var body: some View {
        TimelineView(.everyMinute) { context in
            let presence = Presence.of(lastSeen: lastSeen, now: context.date)
            HStack(spacing: 5) {
                Circle().fill(presence.isOnline ? Theme.online : Theme.muted).frame(width: 7, height: 7).accessibilityHidden(true)
                Text(presence.line(now: context.date)).themeFont(13).foregroundStyle(Theme.muted)
            }.accessibilityElement(children: .combine)
        }
    }
}

enum ShellTime {
    static func date(_ iso: String?) -> Date? {
        guard let iso else { return nil }
        let clean = String(iso.prefix(while: { $0 != "~" }))
        let f = ISO8601DateFormatter()
        if let date = f.date(from: clean) { return date }
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.date(from: clean)
    }
    static func short(_ iso: String?) -> String {
        guard let date = date(iso) else { return "" }
        if Calendar.current.isDateInYesterday(date) { return "Yesterday" }
        return formatted(date, Calendar.current.isDateInToday(date) ? "HH:mm" : "d MMM")
    }
    static func day(_ iso: String?) -> String {
        guard let date = date(iso) else { return "" }
        return formatted(date, "d MMM")
    }
    private static func formatted(_ date: Date, _ format: String) -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_GB"); f.dateFormat = format
        return f.string(from: date)
    }
}

struct ShellChevron: View {
    var body: some View { Image(systemName: "chevron.right").themeFont(14).foregroundStyle(Theme.muted).accessibilityHidden(true) }
}

struct ShellCloseButton: View {
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: "xmark").themeFont(17).foregroundStyle(Theme.muted)
                .frame(width: 44, height: 44).background(Theme.surface2, in: Circle())
        }.buttonStyle(PressStyle()).accessibilityLabel("Close")
    }
}

struct ShellDivider: View {
    var body: some View { Rectangle().fill(Theme.border).frame(height: 0.5).accessibilityHidden(true) }
}
