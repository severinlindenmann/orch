import Foundation
import EventKit
import Darwin

func absolutePath(_ value: String) -> Bool {
    value.hasPrefix("/") && !value.utf8.contains(0)
}

@available(macOS 14.0, *)
func authorization() -> String {
    switch EKEventStore.authorizationStatus(for: .event) {
    case .fullAccess: return "full"
    case .denied: return "denied"
    case .notDetermined: return "not_asked"
    case .restricted: return "restricted"
    case .writeOnly: return "write_only"
    @unknown default: return "restricted"
    }
}

func kind(_ source: EKSource) -> String {
    switch source.sourceType {
    case .exchange: return "exchange"
    case .subscribed: return "subscribed"
    case .local: return "local"
    case .calDAV:
        let title = source.title.lowercased()
        if title.contains("icloud") { return "icloud" }
        if title.contains("google") || title.contains("gmail") { return "google" }
        return "other"
    default: return "other"
    }
}

func availability(_ event: EKEvent, currentUser: EKParticipant?) -> String {
    if currentUser?.participantStatus == .tentative { return "tentative" }
    switch event.availability {
    case .busy: return "busy"
    case .free: return "free"
    case .tentative: return "tentative"
    case .unavailable: return "unavailable"
    default: return "unknown"
    }
}

func writeAnswer(_ answer: [String: Any], to path: String) -> Bool {
    let partial = path + ".part"
    do {
        let data = try JSONSerialization.data(withJSONObject: answer, options: [.sortedKeys])
        try data.write(to: URL(fileURLWithPath: partial))
        // Renaming within the same directory replaces the answer atomically.
        let result = partial.withCString { source in
            path.withCString { destination in Darwin.rename(source, destination) }
        }
        guard result == 0 else {
            try? FileManager.default.removeItem(atPath: partial)
            return false
        }
        return true
    } catch {
        try? FileManager.default.removeItem(atPath: partial)
        return false
    }
}

@available(macOS 14.0, *)
func run() -> Int32 {
    let args = Array(CommandLine.arguments.dropFirst())
    var values: [String: String] = [:]
    var argumentError: String?
    var output: String?
    var index = 0
    let allowed: Set<String> = ["--out", "--mode", "--from", "--days"]
    // Continue after an invalid argument so a valid --out can still receive the error.
    while index < args.count {
        let key = args[index]
        guard allowed.contains(key), index + 1 < args.count,
              !args[index + 1].hasPrefix("--") else {
            argumentError = "Use only --out, --mode, and the read options --from and --days."
            index += 1
            continue
        }
        let value = args[index + 1]
        if values[key] != nil { argumentError = "Supply each argument only once." }
        values[key] = value
        if key == "--out", absolutePath(value), output == nil { output = value }
        index += 2
    }
    if values["--out"].map(absolutePath) != true {
        argumentError = "Supply --out with an absolute file path."
    }
    let mode = values["--mode"] ?? ""
    if !["status", "request", "read"].contains(mode) {
        argumentError = "Supply --mode as status, request, or read."
    }

    let zone = TimeZone.current
    var calendar = Calendar.current
    calendar.timeZone = zone
    let dateOnly = DateFormatter()
    dateOnly.locale = Locale(identifier: "en_US_POSIX")
    dateOnly.calendar = Calendar(identifier: .gregorian)
    dateOnly.timeZone = zone
    dateOnly.dateFormat = "yyyy-MM-dd"
    dateOnly.isLenient = false
    var window: (start: Date, end: Date)?
    if mode == "read" {
        if let from = values["--from"],
           from.range(of: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", options: .regularExpression) != nil,
           let date = dateOnly.date(from: from), dateOnly.string(from: date) == from,
           let rawDays = values["--days"],
           rawDays.range(of: "^[0-9]+$", options: .regularExpression) != nil,
           let days = Int(rawDays), (1...35).contains(days) {
            let start = calendar.startOfDay(for: date)
            if let end = calendar.date(byAdding: .day, value: days, to: start) {
                window = (start, calendar.startOfDay(for: end))
            }
        }
        if window == nil { argumentError = "For read, supply --from as YYYY-MM-DD and --days from 1 to 35." }
    } else if values["--from"] != nil || values["--days"] != nil {
        argumentError = "Use --from and --days only with --mode read."
    }

    let utc = ISO8601DateFormatter()
    utc.timeZone = TimeZone(secondsFromGMT: 0)
    var answer: [String: Any] = [
        "schema": "orch.calendar.read/1", "status": authorization(),
        "zone": zone.identifier, "read_at": utc.string(from: Date()),
        "calendars": [[String: Any]](), "events": [[String: Any]](),
        "error": NSNull()
    ]
    if let error = argumentError {
        answer["error"] = error
        if let path = output { _ = writeAnswer(answer, to: path) }
        return 2
    }
    guard let path = output else { return 2 }
    var exitCode: Int32 = 0
    if mode == "request", authorization() == "not_asked" {
        let store = EKEventStore()
        let completed = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var failed = false
        store.requestFullAccessToEvents { _, error in
            lock.lock()
            failed = error != nil
            lock.unlock()
            completed.signal()
        }
        if completed.wait(timeout: .now() + 120) == .timedOut {
            answer["error"] = "Calendar permission timed out; try requesting access again."
            exitCode = 1
        } else {
            lock.lock()
            let requestFailed = failed
            lock.unlock()
            if requestFailed {
                answer["error"] = "Calendar permission could not be requested; try again."
                exitCode = 1
            }
        }
    }
    answer["status"] = authorization()
    if mode == "read", authorization() == "full", let window = window {
        let store = EKEventStore()
        answer["calendars"] = store.calendars(for: .event).map { item -> [String: Any] in
            ["id": item.calendarIdentifier, "title": item.title,
             "account": item.source.title, "kind": kind(item.source),
             "shared": !item.allowsContentModifications && item.type == .calDAV]
        }
        let predicate = store.predicateForEvents(withStart: window.start, end: window.end, calendars: nil)
        let events = store.events(matching: predicate).filter {
            $0.startDate < window.end && $0.endDate > window.start
        }.sorted {
            if $0.startDate != $1.startDate { return $0.startDate < $1.startDate }
            return ($0.title ?? "") < ($1.title ?? "")
        }
        // Use the Mac's offset at each event date, including daylight saving changes.
        let timed = DateFormatter()
        timed.locale = Locale(identifier: "en_US_POSIX")
        timed.calendar = Calendar(identifier: .gregorian)
        timed.timeZone = zone
        timed.dateFormat = "yyyy-MM-dd'T'HH:mm:ssxxx"
        answer["events"] = events.prefix(2000).map { event -> [String: Any] in
            let attendees = event.attendees ?? []
            let currentUser = attendees.first { $0.isCurrentUser }
            // Names only: a "name" that is an email address is left out.
            let people = attendees.filter { !$0.isCurrentUser }.compactMap { $0.name }
                .filter { !$0.contains("@") }.prefix(20)
            var start = timed.string(from: event.startDate)
            var end = timed.string(from: event.endDate)
            if event.isAllDay {
                // All-day: local dates with an exclusive end (EventKit reports 23:59:59 of the last day).
                let first = calendar.startOfDay(for: event.startDate)
                var last = calendar.startOfDay(for: event.endDate)
                if last <= first || event.endDate > last { last = calendar.date(byAdding: .day, value: 1, to: last) ?? last }
                start = dateOnly.string(from: first)
                end = dateOnly.string(from: last)
            }
            return [
                "cal": event.calendar.calendarIdentifier,
                "start": start,
                "end": end,
                "all_day": event.isAllDay, "title": event.title ?? "",
                "people": Array(people), "declined": currentUser?.participantStatus == .declined,
                "availability": availability(event, currentUser: currentUser),
                "tz": event.timeZone.map { $0.identifier as Any } ?? NSNull()
            ]
        }
        if events.count > 2000 {
            answer["error"] = "More than 2000 events; only the first 2000 are shown."
        }
    }
    answer["read_at"] = utc.string(from: Date())
    return writeAnswer(answer, to: path) ? exitCode : 1
}

if #available(macOS 14.0, *) {
    exit(run())
} else {
    exit(1)
}
