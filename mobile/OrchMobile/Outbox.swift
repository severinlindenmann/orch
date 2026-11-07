import CryptoKit
import Foundation
import Observation
<<<<<<< HEAD
=======
import os
>>>>>>> origin/develop

// MARK: Drafts (what a composer hands over)

/// Where a message goes. `newTopic` = no ticket, no `general`: the workspace starts a ticket and acks it with `reply_to`.
enum SendTarget: Hashable, Sendable {
    case general(workspace: String)
    case topic(workspace: String, ticket: String)
    case newTopic(workspace: String)

    var workspace: String {
        switch self { case .general(let w), .newTopic(let w): w; case .topic(let w, _): w }
    }
    var ticket: String? { if case .topic(_, let t) = self { t } else { nil } }
    var isGeneral: Bool { if case .general = self { true } else { false } }
}

/// A local file the person picked or recorded. The Outbox copies it, so the caller may delete its own copy.
struct DraftFile: Sendable, Equatable {
    var url: URL
    var kind: MessageAttachment.Kind
    var name: String
    var mime: String
    var duration: Double? = nil
}
struct DraftVoice: Sendable, Equatable {
    var url: URL
    var duration: Double
    var transcript: String
    var lang: String
    var langSource: VoiceMemo.LangSource
}
struct DraftPin: Sendable, Equatable {
    var n: Int
    var anchor: Anchor
    var text: String? = nil
    var voiceFile: URL? = nil
    var transcript: String? = nil
}
struct DraftFeedback: Sendable, Equatable {
    var artifactId: String
    var artifactRev: String
    var verdict: Feedback.Verdict
    var pins: [DraftPin] = []
}
/// Everything one outgoing message can carry. At least one field must be set (SendRequest.validate()).
struct MessageDraft: Sendable, Equatable {
    var text: String? = nil
    var files: [DraftFile] = []
    var voice: DraftVoice? = nil
    var location: LocationShare? = nil
    var feedback: DraftFeedback? = nil
    var replyTo: String? = nil
    init(text: String? = nil, files: [DraftFile] = [], voice: DraftVoice? = nil, location: LocationShare? = nil, feedback: DraftFeedback? = nil, replyTo: String? = nil) {
        self.text = text; self.files = files; self.voice = voice; self.location = location; self.feedback = feedback; self.replyTo = replyTo
    }
}

// MARK: Persisted item

/// A file waiting in the outbox folder; `blobId` is set once it is uploaded (so a restart never uploads it twice).
struct PendingFile: Codable, Sendable, Equatable {
    var file: String                      // name inside the item's folder
    var kind: MessageAttachment.Kind
    var name: String
    var mime: String
    var size: Int
    var duration: Double? = nil
    var blobId: String? = nil
}
struct PendingVoice: Codable, Sendable, Equatable {
    var file: PendingFile
    var transcript: String
    var lang: String
    var langSource: VoiceMemo.LangSource
}
struct PendingPin: Codable, Sendable, Equatable {
    var n: Int
    var anchor: Anchor
    var text: String? = nil
    var voice: PendingFile? = nil
    var transcript: String? = nil
}
struct PendingFeedback: Codable, Sendable, Equatable {
    var artifactId: String
    var artifactRev: String
    var verdict: Feedback.Verdict
    var pins: [PendingPin]
}

struct OutboxItem: Codable, Sendable, Equatable, Identifiable {
    enum Kind: String, Codable, Sendable { case send, answer }
    /// The UUID every retry carries (`client_id`).
    let clientId: String
    let phone: String
    let kind: Kind
    let workspace: String
    let createdAt: String
    var ticket: String? = nil
    var general: Bool = false
    var replyTo: String? = nil
    var text: String? = nil
    var files: [PendingFile] = []
    var voice: PendingVoice? = nil
    var location: LocationShare? = nil
    var feedback: PendingFeedback? = nil
    // answers
    var questionMessageId: String? = nil
    var answer: String? = nil
    // progress
    /// The relay stored it (first tick). The item stays until `/messages` lists it, so a restart in between never sends twice.
    var sentMessageId: String? = nil
    /// A permanent refusal (4xx): shown as "Not sent"; `retry` clears it.
    var failure: String? = nil
    var attempts: Int = 0
<<<<<<< HEAD
=======
    /// Status of the refusal in `failure` (so `retry` knows whether a blob has to be uploaded again).
    var failureStatus: Int? = nil
    /// 408 / 429 / 503: the relay is busy. The item stays queued and is not tried again before this time (ISO).
    var retryAfter: String? = nil
    var throttleCount: Int? = nil
>>>>>>> origin/develop

    var id: String { clientId }
    var isNewTopic: Bool { kind == .send && ticket == nil && !general }
    var isWaiting: Bool { sentMessageId == nil && failure == nil }
<<<<<<< HEAD
=======
    /// Waiting and past its backoff.
    func isDue(now: Date = Date()) -> Bool {
        guard isWaiting else { return false }
        guard let r = retryAfter, let t = ISO8601DateFormatter().date(from: r) else { return true }
        return t <= now
    }
>>>>>>> origin/develop
    /// All local files of the item (attachments, voice memo, pin recordings).
    var allFiles: [PendingFile] { files + (voice.map { [$0.file] } ?? []) + (feedback?.pins.compactMap(\.voice) ?? []) }
}

// MARK: Outbox

/// Durable queue of everything the phone writes: texts, voice memos, photos, files, locations, feedback and question answers.
/// queued -> (uploads) -> sent (relay 201, first tick) -> [leaves the outbox once `/messages` lists its client_id].
/// Delivered (second tick) and started/working come from the messages themselves (`ConversationBuilder`).
/// Every retry reuses the item's `client_id`, so the relay never stores a message twice. Survives restarts; one folder per item
/// holds its files. `directory` can be an app group container (see `defaultDirectory`).
@MainActor @Observable
final class Outbox {
    enum Event: Equatable {
        case sent(clientId: String, messageId: String, duplicate: Bool)
        case answered(clientId: String, questionMessageId: String, answer: String)
        /// The relay refused it for good (not 401/5xx/network). The item stays, marked failed.
        case failed(clientId: String, status: Int, message: String)
        /// Someone else answered first (409).
        case answerTaken(clientId: String, questionMessageId: String, message: String)
        case unauthorized
<<<<<<< HEAD
=======
        /// 408 / 429 / 503: kept queued with a backoff (30 s, doubling, at most 5 min). Show "Try again later".
        case throttled(clientId: String, status: Int)
>>>>>>> origin/develop
        /// No network (or a 5xx): everything stays queued, in order.
        case offline
    }

    private(set) var items: [OutboxItem] = []
    let directory: URL
    private(set) var phone: String
    @ObservationIgnored private var flushing = false
    @ObservationIgnored private var flushAgain = false
    @ObservationIgnored private let fm = FileManager.default

    init(directory: URL, phone: String) {
        self.directory = directory; self.phone = phone
        try? fm.createDirectory(at: directory, withIntermediateDirectories: true)
        if let d = try? Data(contentsOf: indexURL), let all = try? JSONDecoder().decode([OutboxItem].self, from: d) {
            items = all.filter { $0.phone == phone }
            for foreign in all where foreign.phone != phone { removeFolder(foreign.clientId) }   // never send another phone's message
            if items.count != all.count { save() }
        }
    }

    /// App group container when the entitlement exists, else Application Support (the app group name is set in the entitlements by the release lane).
    static func defaultDirectory(appGroup: String = "group.io.severin.orch") -> URL {
        let base = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)
            ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("outbox", isDirectory: true)
    }

    private var indexURL: URL { directory.appendingPathComponent("outbox.json") }
    func folder(_ clientId: String) -> URL { directory.appendingPathComponent(clientId, isDirectory: true) }
    func fileURL(_ item: OutboxItem, _ f: PendingFile) -> URL { folder(item.clientId).appendingPathComponent(f.file) }
    private func removeFolder(_ clientId: String) { try? fm.removeItem(at: folder(clientId)) }
<<<<<<< HEAD
    private func save() {
        guard let d = try? JSONEncoder().encode(items) else { return }
        try? d.write(to: indexURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
=======
    private static let log = Logger(subsystem: "io.severin.orch", category: "outbox")
    /// Set when the index could not be written (disk full...): the queue only lives in memory until the next good save.
    private(set) var lastSaveError: String?
    private static let protection = FileProtectionType.completeUntilFirstUserAuthentication
    private func save() {
        do {
            let d = try JSONEncoder().encode(items)
            try d.write(to: indexURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            lastSaveError = nil
        } catch {
            lastSaveError = error.localizedDescription
            Self.log.error("outbox save failed: \(error.localizedDescription, privacy: .public)")
            assertionFailure("outbox save failed: \(error)")
        }
>>>>>>> origin/develop
    }

    // MARK: Enqueue

    /// Queue a message. Files are copied into the item's folder. Throws `SendRequest.Problem` for an empty or invalid message.
    @discardableResult
    func enqueue(_ draft: MessageDraft, to target: SendTarget, now: Date = Date()) throws -> OutboxItem {
        let clientId = UUID().uuidString.lowercased()
        var item = OutboxItem(clientId: clientId, phone: phone, kind: .send, workspace: target.workspace,
                              createdAt: ISO8601DateFormatter().string(from: now), ticket: target.ticket, general: target.isGeneral, replyTo: draft.replyTo)
        let text = draft.text?.trimmingCharacters(in: .whitespacesAndNewlines)
        item.text = (text?.isEmpty ?? true) ? nil : text
        item.location = draft.location
<<<<<<< HEAD
        try fm.createDirectory(at: folder(clientId), withIntermediateDirectories: true)
=======
        try fm.createDirectory(at: folder(clientId), withIntermediateDirectories: true, attributes: [.protectionKey: Self.protection])
>>>>>>> origin/develop
        do {
            var n = 0
            func copy(_ url: URL, kind: MessageAttachment.Kind, name: String, mime: String, duration: Double?) throws -> PendingFile {
                n += 1
                let local = "\(n)-" + Self.safeFileName(name)
                let dest = folder(clientId).appendingPathComponent(local)
                try fm.copyItem(at: url, to: dest)
<<<<<<< HEAD
=======
                try? fm.setAttributes([.protectionKey: Self.protection], ofItemAtPath: dest.path)    // same protection as the index
>>>>>>> origin/develop
                let size = (try fm.attributesOfItem(atPath: dest.path)[.size] as? Int) ?? 0
                guard size > 0, size <= SendRequest.maxBlobBytes else { throw SendRequest.Problem.attachmentTooBig }
                return PendingFile(file: local, kind: kind, name: name, mime: mime, size: size, duration: duration)
            }
            item.files = try draft.files.map { try copy($0.url, kind: $0.kind, name: $0.name, mime: $0.mime, duration: $0.duration) }
            if let v = draft.voice {
                item.voice = PendingVoice(file: try copy(v.url, kind: .voice, name: "voice.m4a", mime: "audio/m4a", duration: v.duration),
                                          transcript: v.transcript, lang: v.lang, langSource: v.langSource)
            }
            if let f = draft.feedback {
                item.feedback = PendingFeedback(artifactId: f.artifactId, artifactRev: f.artifactRev, verdict: f.verdict, pins: try f.pins.map { p in
                    PendingPin(n: p.n, anchor: p.anchor, text: p.text,
                               voice: try p.voiceFile.map { try copy($0, kind: .voice, name: "pin-\(p.n).m4a", mime: "audio/m4a", duration: nil) }, transcript: p.transcript)
                })
            }
            try Self.request(for: item, dummy: true).validate()
        } catch { removeFolder(clientId); throw error }
        items.append(item); save()
        return item
    }

    /// Queue an answer to a question. The same `client_id` is used on every retry; one answer per question is queued.
    @discardableResult
    func enqueueAnswer(question: Question, answer: String, now: Date = Date()) -> OutboxItem {
        if let existing = items.first(where: { $0.kind == .answer && $0.questionMessageId == question.id }) { return existing }
        let item = OutboxItem(clientId: UUID().uuidString.lowercased(), phone: phone, kind: .answer, workspace: question.message.from,
                              createdAt: ISO8601DateFormatter().string(from: now), questionMessageId: question.id, answer: answer)
        items.append(item); save()
        return item
    }

    // MARK: Manage

    func item(clientId: String) -> OutboxItem? { items.first { $0.clientId == clientId } }
    func discard(_ clientId: String) { items.removeAll { $0.clientId == clientId }; removeFolder(clientId); save() }
    /// Try a refused message again (same client_id).
    func retry(_ clientId: String) {
        guard let i = items.firstIndex(where: { $0.clientId == clientId }) else { return }
<<<<<<< HEAD
        items[i].failure = nil; save()
=======
        // A refusal about a blob (404 not found / 422 size): the upload may be gone, so every file goes up again.
        if items[i].failureStatus == 404 || items[i].failureStatus == 422 { Self.clearBlobIds(&items[i]) }
        items[i].failure = nil; items[i].failureStatus = nil; items[i].retryAfter = nil; items[i].throttleCount = nil; save()
>>>>>>> origin/develop
    }
    /// Sign-out: nothing may stay for the next person.
    func wipe() {
        items = []
<<<<<<< HEAD
        try? fm.removeItem(at: directory)
        try? fm.createDirectory(at: directory, withIntermediateDirectories: true)
=======
        do { try fm.removeItem(at: directory) } catch { Self.log.error("outbox wipe failed: \(error.localizedDescription, privacy: .public)") }
        do { try fm.createDirectory(at: directory, withIntermediateDirectories: true) } catch { Self.log.error("outbox recreate failed: \(error.localizedDescription, privacy: .public)") }
>>>>>>> origin/develop
    }

    /// Items the relay now lists (by `client_id`) are done: drop them and their files. Call after every `/messages` load.
    func reconcile(with messages: [PhoneMessage]) {
        let known = Set(messages.compactMap { $0.clientId ?? $0.message.body.clientId })
        let done = items.filter { $0.kind == .send && known.contains($0.clientId) }
        guard !done.isEmpty else { return }
        for d in done { removeFolder(d.clientId) }
        items.removeAll { i in done.contains { $0.clientId == i.clientId } }
        save()
    }

    // MARK: Flush

    /// Wire request of an item. Needs every blob id (`dummy` = placeholder ids, for validation only).
    nonisolated static func request(for item: OutboxItem, dummy: Bool = false) throws -> SendRequest {
        func blob(_ f: PendingFile) throws -> String {
            if let b = f.blobId { return b }
            if dummy { return "b_" + String(repeating: "0", count: 16) }
            throw SendRequest.Problem.nothingToSend
        }
        var r = SendRequest(to: item.workspace, clientId: item.clientId, text: item.text, ticket: item.ticket,
                            general: item.general ? true : nil, replyTo: item.replyTo)
        if !item.files.isEmpty {
            r.attachments = try item.files.map { MessageAttachment(blobId: try blob($0), kind: $0.kind, name: $0.name, size: $0.size, mime: $0.mime, duration: $0.duration) }
        }
        if let v = item.voice { r.voice = VoiceMemo(blobId: try blob(v.file), transcript: v.transcript, lang: v.lang, langSource: v.langSource) }
        r.location = item.location
        if let f = item.feedback {
            r.feedback = Feedback(artifactId: f.artifactId, artifactRev: f.artifactRev, verdict: f.verdict, pins: try f.pins.map {
                Pin(n: $0.n, anchor: $0.anchor, text: $0.text, voiceBlobId: try $0.voice.map(blob), transcript: $0.transcript)
            })
        }
        return r
    }

    /// Send everything that waits, oldest first. Stops at the first network problem (order is kept); a refused item is marked failed and
    /// the next one goes on. Overlapping calls fold into one pass. Returns what happened.
    @discardableResult
<<<<<<< HEAD
    func flush(using client: any RelayAPI) async -> [Event] {
=======
    func flush(using client: any RelayAPI, now: @autoclosure () -> Date = Date()) async -> [Event] {
>>>>>>> origin/develop
        if flushing { flushAgain = true; return [] }
        flushing = true; defer { flushing = false }
        var events: [Event] = []
        repeat {
            flushAgain = false
            for id in items.filter(\.isWaiting).map(\.clientId) {
                guard let item = self.item(clientId: id), item.isWaiting else { continue }
<<<<<<< HEAD
=======
                if !item.isDue(now: now()) { return events }      // backing off: later items wait too (order is kept)
>>>>>>> origin/develop
                do { events.append(try await deliver(item, client)) }
                catch let e as RelayError {
                    switch e {
                    case .unauthorized: events.append(.unauthorized); return events
                    case .network: events.append(.offline); return events
                    case .api(let status, let code, let message):
<<<<<<< HEAD
                        if status >= 500 || status == 429 { events.append(.offline); return events }
                        if item.kind == .answer && status == 409 && code == "already_answered" {
                            events.append(.answerTaken(clientId: id, questionMessageId: item.questionMessageId ?? "", message: message)); discard(id)
                        } else { mark(id) { $0.failure = message }; events.append(.failed(clientId: id, status: status, message: message)) }
=======
                        if [408, 429, 503].contains(status) {
                            let n = (item.throttleCount ?? 0) + 1
                            let wait = min(30.0 * pow(2, Double(n - 1)), 300)
                            mark(id) { $0.throttleCount = n; $0.retryAfter = ISO8601DateFormatter().string(from: now().addingTimeInterval(wait)) }
                            events.append(.throttled(clientId: id, status: status)); return events
                        }
                        if status >= 500 { events.append(.offline); return events }
                        if item.kind == .answer && status == 409 && code == "already_answered" {
                            events.append(.answerTaken(clientId: id, questionMessageId: item.questionMessageId ?? "", message: message)); discard(id)
                        } else { mark(id) { $0.failure = message; $0.failureStatus = status }; events.append(.failed(clientId: id, status: status, message: message)) }
>>>>>>> origin/develop
                    case .badLink: break
                    }
                } catch is URLError { events.append(.offline); return events }
                catch { mark(id) { $0.failure = "Could not send this." }; events.append(.failed(clientId: id, status: 0, message: "Could not send this.")) }
            }
        } while flushAgain
        return events
    }

<<<<<<< HEAD
=======
    private static func clearBlobIds(_ i: inout OutboxItem) {
        for k in i.files.indices { i.files[k].blobId = nil }
        i.voice?.file.blobId = nil
        if let f = i.feedback { for k in f.pins.indices { i.feedback?.pins[k].voice?.blobId = nil } }
    }

>>>>>>> origin/develop
    private func mark(_ id: String, _ change: (inout OutboxItem) -> Void) {
        guard let i = items.firstIndex(where: { $0.clientId == id }) else { return }
        change(&items[i]); save()
    }

    private func deliver(_ item: OutboxItem, _ client: any RelayAPI) async throws -> Event {
        mark(item.clientId) { $0.attempts += 1 }
        if item.kind == .answer {
            let r = try await client.answer(AnswerRequest(questionMessageId: item.questionMessageId ?? "", answer: item.answer ?? "", clientId: item.clientId))
            discard(item.clientId)
            return .answered(clientId: item.clientId, questionMessageId: item.questionMessageId ?? r.id, answer: item.answer ?? "")
        }
        try await uploadMissing(item.clientId, client)
        guard let fresh = self.item(clientId: item.clientId) else { throw RelayError.network("gone") }
        let r = try await client.send(try Self.request(for: fresh))
<<<<<<< HEAD
        mark(item.clientId) { $0.sentMessageId = r.id }
=======
        mark(item.clientId) { $0.sentMessageId = r.id; $0.retryAfter = nil; $0.throttleCount = nil }
>>>>>>> origin/develop
        return .sent(clientId: item.clientId, messageId: r.id, duplicate: r.duplicate ?? false)
    }

    private func uploadMissing(_ id: String, _ client: any RelayAPI) async throws {
        func upload(_ f: PendingFile, set: @escaping (inout OutboxItem, String) -> Void) async throws {
            guard f.blobId == nil, let it = item(clientId: id) else { return }
            let b = try await client.uploadBlob(file: fileURL(it, f), contentType: f.mime)
            mark(id) { set(&$0, b.blobId) }     // saved at once: a restart never uploads this file again
        }
        guard let item0 = item(clientId: id) else { return }
        for (i, f) in item0.files.enumerated() { try await upload(f) { $0.files[i].blobId = $1 } }
        if let v = item0.voice { try await upload(v.file) { $0.voice?.file.blobId = $1 } }
        for (i, p) in (item0.feedback?.pins ?? []).enumerated() { if let v = p.voice { try await upload(v) { $0.feedback?.pins[i].voice?.blobId = $1 } } }
    }

    nonisolated static func safeFileName(_ name: String) -> String {
        let cleaned = name.unicodeScalars.filter { $0.value >= 32 && $0 != "/" && $0 != "\\" }.map(Character.init)
        var s = String(cleaned).trimmingCharacters(in: .whitespaces)
        while s.hasPrefix(".") { s.removeFirst() }
        return s.isEmpty ? "file" : String(s.prefix(100))
    }
}
