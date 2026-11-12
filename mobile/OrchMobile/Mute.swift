import Foundation

struct GroupMute: Codable, Sendable, Equatable {
    let host: String
    let id: String
    let mutedUntil: String?
    var key: GroupKey { GroupKey(host: host, id: id) }
}

enum MuteRules {
    static func date(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions.insert(.withFractionalSeconds)
        return formatter.date(from: value)
    }
    static func isMuted(_ value: String?, now: Date = Date()) -> Bool {
        guard let value else { return false }
        return value == "forever" || (date(value).map { $0 > now } ?? false)
    }
    static func isMuted(all: String?, workspace: String?, group: GroupKey?, groups: [GroupMute], now: Date = Date()) -> Bool {
        isMuted(all, now: now) || isMuted(workspace, now: now) ||
        groups.contains { $0.key == group && isMuted($0.mutedUntil, now: now) }
    }
    static func endLabel(_ value: String?, banner: Bool = false) -> String {
        guard let value, let date = date(value) else {
            return banner ? "until you turn them on" : "Until you turn it back on"
        }
        let formatter = DateFormatter()
        formatter.dateFormat = "H:mm"
        return (banner ? "until " : "Until ") + formatter.string(from: date)
    }
    /// The value of a "Notifications" row: "On", "Muted until 08:00", "Muted until tomorrow 08:00", "Muted".
    static func notificationsValue(_ value: String?, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard isMuted(value, now: now) else { return "On" }
        guard let value, let end = date(value) else { return "Muted" }
        let formatter = DateFormatter()
        formatter.calendar = calendar; formatter.timeZone = calendar.timeZone; formatter.dateFormat = "HH:mm"
        let day = calendar.isDate(end, inSameDayAs: now) ? "" : "tomorrow "
        return "Muted until " + day + formatter.string(from: end)
    }
}

enum MuteChoice: String, CaseIterable, Identifiable {
    case hour = "1 hour"
    case morning = "Until tomorrow"
    case forever = "Until I turn it on"
    var id: String { rawValue }
    func mute(now: Date = Date(), calendar: Calendar = .current) -> Mute {
        switch self {
        case .hour: return .until(now.addingTimeInterval(3600))
        case .forever: return .forever
        case .morning:
            let next = calendar.nextDate(after: now, matching: DateComponents(hour: 8, minute: 0, second: 0), matchingPolicy: .nextTime)!
            return .until(next)
        }
    }
}

struct MuteAllPatch: Encodable, Sendable {
    let mute: Mute
    enum CodingKeys: String, CodingKey { case muteAllUntil }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(mute.wire, forKey: .muteAllUntil)
    }
}
struct GroupMutePatch: Encodable, Sendable {
    let mute: Mute
    enum CodingKeys: String, CodingKey { case mutedUntil }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(mute.wire, forKey: .mutedUntil)
    }
}
