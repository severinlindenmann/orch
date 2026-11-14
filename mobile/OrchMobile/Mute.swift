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
    /// "Muted until 8:00", "Muted until tomorrow 8:00", "Muted until you unmute".
    static func mutedText(_ value: String?, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard let value, let end = date(value) else { return "Muted until you unmute" }
        return "Muted until " + endText(end, now: now, calendar: calendar)
    }
    /// "8:00" today, "tomorrow 8:00", "Sunday 8:00" within a week, else "1 Dec 8:00".
    static func endText(_ end: Date, now: Date = Date(), calendar: Calendar = .current) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX"); formatter.calendar = calendar; formatter.timeZone = calendar.timeZone
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: now), to: calendar.startOfDay(for: end)).day ?? 0
        switch days {
        case ...0: formatter.dateFormat = "H:mm"; return formatter.string(from: end)
        case 1: formatter.dateFormat = "H:mm"; return "tomorrow " + formatter.string(from: end)
        case 2...6: formatter.dateFormat = "EEEE H:mm"
        default: formatter.dateFormat = "d MMM H:mm"
        }
        return formatter.string(from: end)
    }
    /// The value of a "Notifications" row: "On", "Muted until 8:00", "Muted until tomorrow 8:00", "Muted".
    static func notificationsValue(_ value: String?, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard isMuted(value, now: now) else { return "On" }
        guard let value, let end = date(value) else { return "Muted" }
        return "Muted until " + endText(end, now: now, calendar: calendar)
    }
}

enum MuteChoice: String, CaseIterable, Identifiable {
    case hour = "1 hour"
    case morning = "Until tomorrow 8:00"
    case forever = "Until I unmute"
    var id: String { rawValue }
    func mute(now: Date = Date(), calendar: Calendar = .current) -> Mute {
        switch self {
        case .hour: return .until(now.addingTimeInterval(3600))
        case .forever: return .forever
        case .morning:
            // Always the next day at 8:00, also when chosen before 8:00.
            let tomorrow = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: now))!
            return .until(calendar.date(bySettingHour: 8, minute: 0, second: 0, of: tomorrow)!)
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
