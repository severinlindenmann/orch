import Foundation
import os

/// What the phone last knew, kept on disk so the Chats list and groups are there at once on the next launch while a refresh runs
/// in the background (prototype: one versioned JSON file, no database). It never leaves the phone and is deleted on sign-out.
struct LocalSnapshot: Codable, Equatable {
    static let currentVersion = 1
    /// Newest messages kept; older ones come back by scrolling up.
    static let messageLimit = 500

    var version = LocalSnapshot.currentVersion
    var phoneId: String
    var savedAt: Date
    var workspaces: [Workspace]
    var questions: [Question]
    var questionLog: [String: Question]
    /// Newest first, at most `messageLimit`.
    var messages: [PhoneMessage]
    var updates: [TicketUpdate]
    var answers: [String: String]
    /// Cursor for older messages; nil when the list was cut at `messageLimit` (the next refresh sets it again).
    var messagesNext: String?
}

enum LocalSnapshotStore {
    private static let log = Logger(subsystem: "io.severin.orch", category: "snapshot")

    /// Next to the outbox folder (not inside it: wiping the outbox must not be what removes or keeps the snapshot).
    static func url(besideOutbox directory: URL) -> URL {
        directory.deletingLastPathComponent().appendingPathComponent(directory.lastPathComponent + "-snapshot.json")
    }

    /// The snapshot for this phone, or nil. A file of another phone, another version or one that does not decode is deleted.
    static func load(from url: URL, phoneId: String) -> LocalSnapshot? {
        writer(for: url).flush()
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        guard let s = try? decoder.decode(LocalSnapshot.self, from: data), s.version == LocalSnapshot.currentVersion, s.phoneId == phoneId else {
            try? FileManager.default.removeItem(at: url)
            return nil
        }
        return s
    }

    static func save(_ snapshot: LocalSnapshot, to url: URL) { writer(for: url).submit(snapshot) }
    static func delete(at url: URL) { writer(for: url).delete() }
    /// Waits until queued writes and deletes have landed (tests, and the load at launch).
    static func flush(at url: URL) { writer(for: url).flush() }

    private static let lock = NSLock()
    nonisolated(unsafe) private static var writers: [URL: Writer] = [:]
    private static func writer(for url: URL) -> Writer {
        lock.lock(); defer { lock.unlock() }
        if let w = writers[url] { return w }
        let w = Writer(url: url); writers[url] = w; return w
    }

    /// Encodes and writes off the main actor, atomically; only the newest queued snapshot is written.
    private final class Writer: @unchecked Sendable {
        private static let queue = DispatchQueue(label: "io.severin.orch.snapshot", qos: .utility)
        private let url: URL
        private let lock = NSLock()
        private var pending: LocalSnapshot?
        private var scheduled = false
        init(url: URL) { self.url = url }

        func submit(_ snapshot: LocalSnapshot) {
            lock.lock(); pending = snapshot; let start = !scheduled; scheduled = true; lock.unlock()
            guard start else { return }
            Self.queue.async { [self] in
                while true {
                    lock.lock()
                    guard let next = pending else { scheduled = false; lock.unlock(); return }
                    pending = nil; lock.unlock()
                    do {
                        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                        let data = try JSONEncoder().encode(next)
                        try data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
                    } catch {
                        LocalSnapshotStore.log.error("snapshot save failed: \(error.localizedDescription, privacy: .public)")
                    }
                }
            }
        }

        /// Drops a queued write and removes the file, after any write already running.
        func delete() {
            lock.lock(); pending = nil; lock.unlock()
            Self.queue.async { [url] in try? FileManager.default.removeItem(at: url) }
        }
        func flush() { Self.queue.sync {} }
    }
}
