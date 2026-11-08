import Foundation

/// Whether a workspace is around. Online while its last call is at most 5 minutes old, else "last seen 14:02" /
/// "last seen yesterday 18:40" / "last seen 3 Nov" (relay-api.md: the relay's own `online` is a 2 minute window).
enum Presence: Equatable, Sendable {
    case online
    case lastSeen(Date)
    case unknown

    static let onlineWindow: TimeInterval = 5 * 60

    static func of(lastSeen iso: String?, now: Date = Date()) -> Presence {
        guard let iso, let d = ISO8601DateFormatter().date(from: iso) else { return .unknown }
        return now.timeIntervalSince(d) <= onlineWindow ? .online : .lastSeen(d)
    }

    var isOnline: Bool { self == .online }

    /// "Online", "Last seen 14:02", "Last seen yesterday 18:40", "Last seen 3 Nov", "Offline" when never seen.
    func text(now: Date = Date(), calendar: Calendar = .current, locale: Locale = Locale(identifier: "en_GB")) -> String {
        switch self {
        case .online: return "Online"
        case .unknown: return "Offline"
        case .lastSeen(let d):
            let f = DateFormatter(); f.calendar = calendar; f.locale = locale; f.timeZone = calendar.timeZone
            f.dateFormat = "HH:mm"
            if calendar.isDate(d, inSameDayAs: now) { return "Last seen " + f.string(from: d) }
            if let y = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(d, inSameDayAs: y) { return "Last seen yesterday " + f.string(from: d) }
            f.dateFormat = "d MMM"
            return "Last seen " + f.string(from: d)
        }
    }

    /// The line shown under a name: "online", "last seen 14:02", "last seen 4 Nov" (only the first letter is lowercase).
    func line(now: Date = Date(), calendar: Calendar = .current) -> String {
        let t = text(now: now, calendar: calendar)
        return t.prefix(1).lowercased() + t.dropFirst()
    }
}
