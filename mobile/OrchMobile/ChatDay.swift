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
        let parser = ISO8601DateFormatter()
        if let date = parser.date(from: item.at) { return key(for: date, calendar: calendar) }
        parser.formatOptions.insert(.withFractionalSeconds)
        if let date = parser.date(from: item.at) { return key(for: date, calendar: calendar) }
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

    static func side(by: String?, fromPhone: Bool) -> ConvItem.Side {
        if let by { return by == "you" ? .me : .them }
        return fromPhone ? .me : .them
    }
}
