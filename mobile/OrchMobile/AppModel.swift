import Foundation
import Observation

enum Tab: Hashable { case chats, settings }

/// Everything the views show. Lists come from the relay; only the credentials are stored.
@MainActor @Observable
final class AppModel {
    enum Phase: Equatable { case onboarding, notifyStep, ready }
    enum InviteState: Equatable { case none, found(host: String), connecting }

    // Session
    private(set) var phase: Phase = .onboarding
    private(set) var credentials: Credentials?
    private(set) var invite: PairingLink?
    private(set) var inviteState: InviteState = .none
    private(set) var pairedWorkspaces: [WorkspaceRef] = []

    // Data
    private(set) var workspaces: [Workspace] = []
    private(set) var questions: [Question] = []
    /// Texts between this phone and its workspaces, newest first.
    private(set) var messages: [PhoneMessage] = []
    /// Newest work update per ticket (`GET /v1/phone/updates`).
    private(set) var updates: [TicketUpdate] = []
    /// question message id -> the answer this phone sent
    private(set) var answers: [String: String] = [:]
    /// questions someone else answered first (409): `answers` then holds their answer
    private(set) var answeredElsewhere: Set<String> = []
    private(set) var isLoading = false
    private(set) var hasLoaded = false
    /// When the last refresh succeeded (drives "Last updated ...").
    private(set) var lastUpdated: Date?
    /// Spoken to VoiceOver by the views (answer sent, message sent, errors).
    private(set) var announcement: String?
    /// Bumps on each successful answer / send (drives haptics).
    private(set) var answerTick = 0
    private(set) var sendTick = 0
    private(set) var errorTick = 0
    var message: String?            // plain error / info line

    // Navigation
    var tab: Tab = .chats
    /// Chats navigation stack (workspace chat, ticket chat, new chat, info).
    var path: [ChatRoute] = []
    /// Push tap: the question the open chat scrolls to.
    var focusedQuestion: String?
    /// Every question seen since launch, so an answered one stays in its chat.
    private(set) var questionLog: [String: Question] = [:]
    /// Read state per chat (client only, kept in UserDefaults).
    private(set) var readState = ReadState(seen: UserDefaults.standard.dictionary(forKey: "chatRead") as? [String: String] ?? [:])
    /// Texts written offline, sent when the phone is online again.
    private(set) var outbox: [QueuedText] = []
    /// question id -> option waiting out the undo window before it is sent
    private(set) var pendingAnswers: [String: String] = [:]
    private(set) var sendingAnswers: Set<String> = []
    private var undoTimers: [String: Task<Void, Never>] = [:]
    /// 5 s undo window; UI tests widen it with `-undoSeconds N`.
    var undoDelay: Duration = {
        let v = UserDefaults.standard.double(forKey: "undoSeconds")
        return .milliseconds(Int((v > 0 ? v : 5) * 1000))
    }()
    var notificationsEnabled = true


    let useMock: Bool
    private let mock: MockRelay?
    private let session: URLSession
    let voiceMode: VoiceInput.Mode

    init(useMock: Bool = AppModel.configuredMock, session: URLSession = .shared,
         voiceMode: VoiceInput.Mode = AppModel.configuredVoice) {
        self.useMock = useMock
        self.mock = useMock ? MockRelay() : nil
        self.session = session
        self.voiceMode = voiceMode
        if let c = Keychain.load() { credentials = c; phase = .ready }
        outbox = Self.loadOutbox().filter { $0.phone == credentials?.phoneId }
        if credentials == nil { Self.wipeOutbox() }
    }

    /// `-relayMode mock` (launch argument or UserDefaults, UI tests) uses the in-process mock; every real build talks to the relay named in the invitation.
    static var configuredMock: Bool { UserDefaults.standard.string(forKey: "relayMode") == "mock" }
    /// `-voiceFile <path>`: an audio file stands in for the microphone (real-relay check in the Simulator).
    static var configuredVoice: VoiceInput.Mode {
        let d = UserDefaults.standard
        if let path = d.string(forKey: "voiceFile") { return .file(URL(fileURLWithPath: path)) }
        if d.bool(forKey: "fakeVoice") { return .scripted }
        #if targetEnvironment(simulator)
        return configuredMock ? .scripted : .live
        #else
        return .live
        #endif
    }

    private var client: any RelayAPI {
        if let mock { return mock }
        let c = credentials
        return URLSessionRelayClient(base: c?.relay ?? invite?.relay ?? URL(string: "https://relay.invalid")!, credentials: c, session: session)
    }

    enum Connection { case checking, ok, unreachable }
    var connection: Connection { message != nil ? .unreachable : (hasLoaded ? .ok : .checking) }
    var lastUpdatedText: String? {
        guard let lastUpdated else { return nil }
        let now = Date()
        if now.timeIntervalSince(lastUpdated) < 60 { return "Last updated just now" }
        let f = RelativeDateTimeFormatter(); f.unitsStyle = .full
        return "Last updated \(f.localizedString(for: min(lastUpdated, now), relativeTo: now))"
    }

    var relayHost: String { credentials?.relay.host ?? invite?.host ?? "your server" }
    var phoneName: String { credentials?.phoneName ?? "This iPhone" }
    /// "Your tickets": Needs you, Working on, Done.
    var tickets: [Ticket] { TicketBuilder.build(updates: updates, questions: questions, answers: answers) }

    /// Everything the chat views draw from.
    var chatData: ChatData {
        ChatData(workspaces: workspaces, messages: messages, tickets: tickets,
                 questions: questionLog.values.sorted { $0.message.createdAt < $1.message.createdAt }.map { $0 }, answers: answers, outbox: outbox)
    }
    var chatRooms: [RoomRow] { ChatBuilder.rooms(chatData, read: readState) }
    var totalUnread: Int { chatRooms.reduce(0) { $0 + $1.unread } }
    func workspace(_ id: String) -> Workspace? { workspaces.first { $0.id == id } }
    func ticket(_ ws: String, _ t: String) -> Ticket? { tickets.first { $0.workspace == ws && $0.ticket == t } }

    func markRead(_ chat: String, items: [ChatItem]) {
        guard let last = items.filter(\.incoming).map(\.at).max() else { return }
        var r = readState; r.markRead(chat, upTo: last)
        guard r != readState else { return }
        readState = r
        UserDefaults.standard.set(r.seen, forKey: "chatRead")
    }

    private static var outboxURL: URL {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("chat-outbox.json")
    }
    private static func loadOutbox() -> [QueuedText] {
        guard let d = try? Data(contentsOf: outboxURL) else { return [] }
        return (try? JSONDecoder().decode([QueuedText].self, from: d)) ?? []
    }
    private static func wipeOutbox() { try? FileManager.default.removeItem(at: outboxURL) }
    private func saveOutbox() {
        guard let d = try? JSONEncoder().encode(outbox) else { return }
        try? d.write(to: Self.outboxURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    // MARK: Answer with undo

    /// Tap = start the undo window; the answer is sent when it ends.
    func chooseAnswer(_ q: Question, _ option: String) {
        guard answers[q.id] == nil, pendingAnswers[q.id] == nil else { return }
        pendingAnswers[q.id] = option
        undoTimers[q.id] = Task { [undoDelay] in
            try? await Task.sleep(for: undoDelay)
            guard !Task.isCancelled else { return }
            sendingAnswers.insert(q.id)
            await answer(q, with: option)
            sendingAnswers.remove(q.id); pendingAnswers[q.id] = nil; undoTimers[q.id] = nil
        }
    }
    func undoAnswer(_ q: Question) {
        guard !sendingAnswers.contains(q.id) else { return }
        undoTimers[q.id]?.cancel(); undoTimers[q.id] = nil; pendingAnswers[q.id] = nil
    }
    /// The "Got it" line the workspace sent for a text of this phone.
    func ack(for messageId: String) -> TicketUpdate? { updates.first { $0.replyTo == messageId && $0.kind == "ack" } }
    var openQuestionCount: Int { questions.filter { answers[$0.id] == nil }.count }

    // MARK: Onboarding

    /// An `orch://pair?…` link (opened from the admin portal, pasted or scanned).
    func openInvite(_ text: String) {
        do {
            let link = try PairingLink(text)
            invite = link; inviteState = .found(host: link.host); message = nil
        } catch { message = error.localizedDescription }
    }

    func openSampleInvite() { openInvite(PairingLink.sample.link) }

    func connect(phoneName: String) async {
        guard let invite else { return }
        inviteState = .connecting; message = nil
        do {
            let r = try await client.pair(code: invite.code, name: phoneName)
            let c = Credentials(relay: invite.relay, phoneId: r.phoneId, token: r.token, phoneName: phoneName)
            Keychain.save(c); credentials = c
            pairedWorkspaces = r.workspaces
            inviteState = .none
            phase = .notifyStep
        } catch {
            inviteState = .found(host: invite.host)
            if case RelayError.api(let status, _, _) = error, status == 401 || status == 404 || status == 410 {
                message = "This invitation has expired or was already used. Ask the person who invited you for a new one."
            } else if error is URLError {
                message = "Can't reach the server. Check your connection, then tap Connect this phone again."
            } else { message = error.localizedDescription }
        }
    }

    func finishSetup(allowNotifications: Bool) async {
        notificationsEnabled = allowNotifications
        if allowNotifications { notificationsEnabled = await PushPermission.request() }
        phase = .ready; tab = .chats
        await refresh()
    }

    // MARK: Data

    /// Wait before the one automatic retry of a first load that found the network not ready yet (tests shorten it).
    var retryDelay: Duration = .seconds(1)

    /// Keeps an open chat current: refreshes every `interval` until the calling task is cancelled (the chat closes).
    func watchWhileOpen(every interval: Duration = .seconds(4)) async {
        while !Task.isCancelled {
            try? await Task.sleep(for: interval)
            if Task.isCancelled { break }
            await refresh(retry: false)
        }
    }

    func refresh(retry: Bool = true) async {
        guard phase == .ready || phase == .notifyStep, credentials != nil else { return }
        isLoading = true; defer { isLoading = false }
        do {
            do { try await load() }
            catch where retry && Self.isOffline(error) {
                // Cold start: the first request can run before the network is ready. Once more before the banner.
                try await Task.sleep(for: retryDelay)
                try await load()
            }
        } catch { handle(error) }
    }

    private func load() async throws {
        do {
            async let w = client.workspaces()
            async let q = client.questions()
            let before = messages
            async let m = (try? await client.messages()) ?? before  // an older relay without /messages must not break the rest
            let beforeUpdates = updates
            async let u = (try? await client.updates()) ?? beforeUpdates  // same for /updates
            workspaces = try await w; questions = try await q.deduplicated(); messages = await m; updates = await u
            for item in questions { questionLog[item.id] = item }
            message = nil; hasLoaded = true; lastUpdated = Date()
            await flushOutbox()
        }
    }

    func answer(_ q: Question, with option: String) async {
        let me = credentials?.phoneId
        do {
            _ = try await client.answer(questionMessageId: q.id, answer: option)
            guard credentials?.phoneId == me, me != nil || useMock else { return }   // signed out meanwhile: drop the late result
            answers[q.id] = option; answerTick += 1; announcement = "Answer sent: \(option)"
            await refresh()
        } catch let RelayError.api(status, code, text) where status == 409 && code == "already_answered" {
            guard credentials?.phoneId == me else { return }
            answers[q.id] = text; answeredElsewhere.insert(q.id)
            message = nil
            await refresh()
        } catch { handle(error) }
    }

    /// Only the "Got it" lines, for the sent screen.
    func refreshUpdates() async {
        if let u = try? await client.updates() { updates = u }
    }

    /// Chat composer: a failed send because of the network keeps the text on the phone and sends it later.
    enum SendResult: Equatable { case sent(id: String), queued, failed }
    func sendChat(to workspaceId: String, text: String, ticket: String? = nil) async -> SendResult {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return .failed }
        do {
            let id = try await client.send(to: workspaceId, text: clean, ticket: ticket)
            if let m = try? await client.messages() { messages = m }
            if let u = try? await client.updates() { updates = u }
            message = nil; sendTick += 1; announcement = "Message sent"
            return .sent(id: id)
        } catch where Self.isOffline(error) {
            outbox.append(QueuedText(id: UUID().uuidString, workspace: workspaceId, ticket: ticket, text: clean, at: ISO8601DateFormatter().string(from: Date()), phone: credentials?.phoneId ?? ""))
            saveOutbox(); announcement = "No connection. The message waits on this phone."
            return .queued
        } catch { handle(error); return .failed }
    }

    private static func isOffline(_ error: Error) -> Bool {
        if error is URLError { return true }
        if case RelayError.network = error { return true }
        return false
    }

    private var flushing = false
    private func flushOutbox() async {
        guard !outbox.isEmpty, !flushing else { return }
        flushing = true; defer { flushing = false }
        let mine = credentials?.phoneId ?? ""
        if outbox.contains(where: { $0.phone != mine }) { outbox.removeAll { $0.phone != mine }; saveOutbox() }   // never send another phone's text
        for q in outbox {
            guard outbox.contains(where: { $0.id == q.id }) else { continue }     // removed meanwhile (sign-out)
            outbox.removeAll { $0.id == q.id }; saveOutbox()                  // take it out before sending: an overlapping call can never send it twice
            guard (try? await client.send(to: q.workspace, text: q.text, ticket: q.ticket)) != nil else { if credentials?.phoneId == mine { outbox.insert(q, at: 0); saveOutbox() }; return }
        }
        if let m = try? await client.messages() { messages = m }
        if let u = try? await client.updates() { updates = u }
    }

    /// New chat: the first text has no ticket; the workspace's "Got it" creates one. Opens that ticket chat, else the workspace chat.
    func startTopic(workspaceId: String, text: String) async {
        switch await sendChat(to: workspaceId, text: text) {
        case .sent(let id):
            var tries = 0
            while ack(for: id) == nil, tries < 4 { try? await Task.sleep(for: .milliseconds(700)); await refreshUpdates(); tries += 1 }
            if let t = ack(for: id)?.ticket { path = [.ticket(workspace: workspaceId, ticket: t)] } else { path = [.workspace(workspaceId)] }
        case .queued: path = [.workspace(workspaceId)]
        case .failed: break
        }
    }

    func transcribe(_ audio: Data) async throws -> String {
        do { return try await client.transcribe(audio: audio, language: nil).text }
        catch RelayError.unauthorized { handle(RelayError.unauthorized); throw RelayError.unauthorized }
    }

    /// Image bytes of a ticket attachment, from the relay with the paired credentials (cached for this session).
    func blob(_ id: String) async -> Data? {
        if let d = blobCache[id] { return d }
        guard credentials != nil || useMock, let d = try? await client.blob(id: id) else { return nil }
        blobCache[id] = d; return d
    }
    private var blobCache: [String: Data] = [:]

    func registerPush(token: String) async {
        try? await client.registerPush(apnsToken: token, sandbox: PushPermission.sandbox)
    }

    /// Push tap on a question: the right chat, scrolled to the question.
    func openQuestion(messageId: String) {
        focusedQuestion = messageId; tab = .chats
        if let q = questionLog[messageId] { route(to: q) }
        Task { await refresh(); if let q = questionLog[messageId] { route(to: q) } }
    }
    private func route(to q: Question) {
        let ws = q.message.from
        path = q.message.ticket.map { [.workspace(ws), .ticket(workspace: ws, ticket: $0)] } ?? [.workspace(ws)]
    }

    /// Text push tap: that workspace's chat.
    func openMessages(workspaceId: String) {
        focusedQuestion = nil; tab = .chats; path = [.workspace(workspaceId)]
        Task { await refresh() }
    }

    func signOut() async {
        try? await client.signOut()
        Keychain.delete()
        reset()
    }

    private func reset() {
        for t in undoTimers.values { t.cancel() }
        undoTimers = [:]; pendingAnswers = [:]; sendingAnswers = []
        outbox = []; Self.wipeOutbox(); UserDefaults.standard.removeObject(forKey: "chatOutbox"); UserDefaults.standard.removeObject(forKey: "chatRead")
        readState = ReadState(); blobCache = [:]
        credentials = nil; invite = nil; inviteState = .none; workspaces = []; questions = []; questionLog = [:]; path = []; messages = []; updates = []; answers = [:]; answeredElsewhere = []; hasLoaded = false
        pairedWorkspaces = []; lastUpdated = nil; message = nil; tab = .chats; phase = .onboarding
    }

    private func handle(_ error: Error) {
        if case RelayError.unauthorized = error { Keychain.delete(); reset(); message = error.localizedDescription }
        else if error is URLError { message = "Can't reach the server. Check your connection, then try again." }
        else if error is RelayError { message = error.localizedDescription }
        else { message = "Something went wrong. Try again in a moment." }
        errorTick += 1; announcement = message
    }

    /// Test and screenshot hook: `-seedPaired YES` skips onboarding against the mock.
    func seedIfRequested() async {
        let d = UserDefaults.standard
        if d.bool(forKey: "resetState") { Keychain.delete(); reset() }
        if d.bool(forKey: "seedPaired"), credentials == nil, useMock {
            openSampleInvite(); await connect(phoneName: "Severin's iPhone"); await finishSetup(allowNotifications: false)
        }
        if d.bool(forKey: "seedInvite"), phase == .onboarding { openSampleInvite() }
        if d.bool(forKey: "seedNotify"), phase == .onboarding, useMock { openSampleInvite(); await connect(phoneName: "Severin's iPhone") }
        if let t = d.string(forKey: "startTab"), phase == .ready {
            tab = t == "settings" ? .settings : .chats
        }
        if phase == .ready, let id = d.string(forKey: "openQuestion") { openQuestion(messageId: id) }  // stands in for a push tap in the Simulator
        if phase == .ready, let ws = d.string(forKey: "openTextPush") { openMessages(workspaceId: ws) }  // stands in for a text push tap
        if phase == .ready { await refresh() }
        if phase == .ready, let ws = d.string(forKey: "openChat") {   // chat screens in the Simulator: -openChat ws_… [-openTicket t_…]
            path = [.workspace(ws)]
            if let t = d.string(forKey: "openTicket") { path.append(.ticket(workspace: ws, ticket: t)) }
            if d.bool(forKey: "openInfo") { path.append(.info(workspace: ws, ticket: d.string(forKey: "openTicket"))) }
        }
        if d.bool(forKey: "openNewChat"), phase == .ready { path = [.newChat] }
        if phase == .ready { if !useMock { await PushPermission.registerIfAuthorized() } }
    }
}
