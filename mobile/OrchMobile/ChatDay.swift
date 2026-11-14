import Foundation

/// Chat dates follow the local wall clock, including on daylight-saving changes.
enum ChatDay {
    static let queuedNote = "Waiting · will send when online"
    typealias Day = (day: String, items: [ConvItem])

    static func key(for date: Date, calendar: Calendar = .current) -> String {
        let components = calendar.dateComponents([.year, .month, .day, .hour], from: date)
        let start = calendar.date(from: DateComponents(year: components.year, month: components.month, day: components.day)) ?? date
        let day = (components.hour ?? 0) < 4 ? calendar.date(byAdding: .day, value: -1, to: start) ?? start : start
        let c = calendar.dateComponents([.year, .month, .day], from: day)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    static func key(of item: ConvItem, calendar: Calendar = .current) -> String {
        if let day = item.day { return day }
        if let date = SharedISO.iso.date(from: item.at) ?? SharedISO.isoFraction.date(from: item.at) { return key(for: date, calendar: calendar) }
        return String(item.at.prefix(10))
    }

    static func split(_ items: [ConvItem], today: String) -> (past: [Day], today: [ConvItem]) {
        let groups = Dictionary(grouping: items) { key(of: $0) }
        return (groups.keys.filter { $0 < today }.sorted().map { ($0, groups[$0] ?? []) }, groups[today] ?? [])
    }

    static func label(forDay day: String, today: String) -> String {
        if day == today { return "Today" }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: day), let current = formatter.date(from: today) else { return day }
        if formatter.calendar.date(byAdding: .day, value: -1, to: current) == date { return "Yesterday" }
        formatter.dateFormat = "EEE d MMM"
        return formatter.string(from: date)
    }

    /// Keep whole days so opening a search result retains its surrounding conversation.
    static func search(_ days: [Day], _ q: String) -> [Day] {
        let query = q.trimmingCharacters(in: .whitespacesAndNewlines)
        return query.isEmpty ? days : days.filter { $0.items.contains { $0.preview.localizedCaseInsensitiveContains(query) } }
    }

    /// The transport direction decides; `by` may only add "you typed it on the dashboard" to a workspace text
    /// (contract chat-groups §1/G4: only the Chat's own workspace speaks as "you", and only via the dashboard).
    static func side(by: String?, via: String? = nil, fromPhone: Bool) -> ConvItem.Side {
        if fromPhone { return .me }
        return by == "you" && via == "dashboard" ? .me : .them
    }
}

/// Shared ISO-8601 parsers: creating one per call (per row) is slow.
enum SharedISO {
    nonisolated(unsafe) static let relative: RelativeDateTimeFormatter = {
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .full; return f
    }()
    nonisolated(unsafe) private static var patterns: [String: DateFormatter] = [:]
    private static let patternLock = NSLock()
    /// One shared DateFormatter per (pattern, locale id, time zone id); creating one per call is slow.
    static func formatter(_ pattern: String, localeId: String? = nil, timeZone: TimeZone = .current) -> DateFormatter {
        let key = "\(pattern)|\(localeId ?? "")|\(timeZone.identifier)"
        patternLock.lock(); defer { patternLock.unlock() }
        if let f = patterns[key] { return f }
        let f = DateFormatter()
        if let localeId { f.locale = Locale(identifier: localeId) }
        f.dateFormat = pattern; f.timeZone = timeZone
        patterns[key] = f
        return f
    }
    nonisolated(unsafe) static let iso = ISO8601DateFormatter()
    nonisolated(unsafe) static let isoFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter(); f.formatOptions.insert(.withFractionalSeconds); return f
    }()
}
