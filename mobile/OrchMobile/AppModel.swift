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
    private(set) var workspaces: [Workspace] = [] { didSet { rebuildGroups() } }
    private(set) var questions: [Question] = []
    /// Texts between this phone and its workspaces, newest first.
    private(set) var messages: [PhoneMessage] = [] { didSet { rebuildGroups() } }
    private(set) var groups = GroupSnapshot(groups: [], dropped: [])
    /// Newest work update per ticket (`GET /v1/phone/updates`).
    private(set) var updates: [TicketUpdate] = []
    /// question message id -> the answer this phone sent
    private(set) var answers: [String: String] = [:]
    /// question message id -> when this phone's answer was sent (this run only; the Make ticket card's 2-min wait)
    private(set) var answerSentAt: [String: Date] = [:]
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
    /// Archive, delete and auto-archive of chats: phone-local (ArchiveStore.swift).
    private(set) var archive = ArchiveStore.load()
    /// Everything the phone writes (texts, voice, photos, files, locations, feedback, answers): durable, retried with the same client_id.
    private(set) var outbox: Outbox
    /// Per-phone settings kept on the relay (read aloud, Swiss German, monthly cap).
    private(set) var settings = PhoneSettings()
    /// Cursor for older messages (`GET /v1/phone/messages?after=`); nil = everything loaded.
    private(set) var messagesNext: String?
    /// Read-aloud player (Speech.swift).
    let speech: SpeechPlayer
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
    /// The in-process fake when `useMock` (tests flip its offline/delivery switches).
    let mock: MockRelay?
    private let session: URLSession
    let voiceMode: VoiceInput.Mode

    private let outboxDirectory: URL
    private let defaults: UserDefaults
    static let installedMarkerKey = "installedMarker"
    static let pairAgainMessage = "This phone needs to be paired again. Open the invitation from your computer to connect."

    init(useMock: Bool = AppModel.configuredMock, session: URLSession = .shared,
         voiceMode: VoiceInput.Mode = AppModel.configuredVoice, outboxDirectory: URL = Outbox.defaultDirectory(),
         speechCache: URL = SpeechPlayer.defaultCacheDirectory, systemAudioControls: Bool = true,
         defaults: UserDefaults = .standard) {
        self.useMock = useMock
        let mock = useMock ? MockRelay() : nil
        self.mock = mock
        self.session = session
        self.voiceMode = voiceMode
        self.outboxDirectory = outboxDirectory
        self.defaults = defaults
        // The keychain outlives deleting the app. No marker in this app container = a fresh install: drop the stale pairing
        // quietly and show the welcome screen (the red "signed out" message is only for a real sign-out/revoke while installed).
        if !defaults.bool(forKey: AppModel.installedMarkerKey) {
            Keychain.delete()
            defaults.removeObject(forKey: "pairedPhoneId")
            defaults.set(true, forKey: AppModel.installedMarkerKey)
        }
        let creds = Keychain.load()
        // Every stored property is set first; only then is `self` used (the Observation macros need that).
        let holder = ClientHolder()
        let box = Outbox(directory: outboxDirectory, phone: creds?.phoneId ?? "")
        self.outbox = box
        self.speech = SpeechPlayer(fetch: { id, lang in try await holder.client().speech(messageId: id, lang: lang) },
                                   cacheDirectory: speechCache, systemControls: systemAudioControls)
        if let c = creds { credentials = c; phase = .ready } else { box.wipe() }
        if creds == nil, defaults.object(forKey: "pairedPhoneId") != nil {
            message = AppModel.pairAgainMessage
            defaults.removeObject(forKey: "pairedPhoneId")
        }
        holder.make = { [weak self] in self?.client }
    }

    /// Lets the (Sendable) speech fetch reach the current client, which changes with sign-in.
    private final class ClientHolder: @unchecked Sendable {
        var make: (@MainActor @Sendable () -> (any RelayAPI)?)?
        func client() async throws -> any RelayAPI {
            guard let make, let c = await make() else { throw RelayError.unauthorized }
            return c
        }
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
                 questions: questionLog.values.sorted { $0.message.createdAt < $1.message.createdAt }.map { $0 }, answers: answers,
                 outbox: outbox.items.filter { $0.kind == .send && $0.text != nil }.map { QueuedText(id: $0.clientId, workspace: $0.workspace, ticket: $0.ticket, text: $0.text ?? "", at: $0.createdAt, phone: $0.phone) },
                 erased: archive.erased)
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
    var openQuestionCount: Int { questions.filter { !$0.isReview && !$0.isMakeTicket && answers[$0.id] == nil }.count }

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
            defaults.set(c.phoneId, forKey: "pairedPhoneId")
            if outbox.phone != c.phoneId { outbox.wipe(); outbox = Outbox(directory: outboxDirectory, phone: c.phoneId) }
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
    /// Unit tests of the loop against the mock set this instead of the launch argument.
    var watchInMock = false

    /// Keeps lists and chats current: the app shell runs one loop while paired and active, cancelling it in the background.
    /// 10 s; nothing runs against the in-process mock unless `-watchLoop YES` (UI tests must see an idle app).
    func watchWhileOpen(every interval: Duration = .seconds(10)) async {
        if useMock && !UserDefaults.standard.bool(forKey: "watchLoop") && !watchInMock { return }
        let pollInterval: Duration = useMock && UserDefaults.standard.bool(forKey: "mockMakeTicket") ? .seconds(2) : interval
        while !Task.isCancelled {
            try? await Task.sleep(for: pollInterval)
            if Task.isCancelled { break }
            await refresh(retry: false, quiet: true)
        }
    }

    /// `quiet`: the periodic refresh must not flip `isLoading`.
    func refresh(retry: Bool = true, quiet: Bool = false) async {
        guard phase == .ready || phase == .notifyStep, credentials != nil else { return }
        if !quiet { isLoading = true }
        defer { if !quiet { isLoading = false } }
        do {
            do { try await load() }
            catch where retry && !useMock && Self.isOffline(error) {
                // Cold start: the first request can run before the network is ready. Once more before the banner.
                try await Task.sleep(for: retryDelay)
                try await load()
            }
        } catch { handle(error) }
    }

    /// No network yet (cold start) or the relay is unreachable: worth one quiet retry before the offline banner.
    private static func isOffline(_ error: Error) -> Bool {
        if error is URLError { return true }
        if case RelayError.network = error { return true }
        return false
    }

    private func load() async throws {
        do {
            async let w = client.workspaces()
            async let q = client.questions()
            let beforeUpdates = updates
            async let u = (try? await client.updates()) ?? beforeUpdates  // an older relay without /updates must not break the rest
            async let st = try? await client.settings()
            // Assign only what changed: an unchanged poll must not redraw (XCUITest idle, battery).
            let newWorkspaces = try await w, newQuestions = try await q.deduplicated(), newUpdates = await u
            if workspaces != newWorkspaces { workspaces = newWorkspaces }
            if questions != newQuestions { questions = newQuestions }
            if updates != newUpdates { updates = newUpdates }
            if let st = await st, settings != st { settings = st }
            await reloadMessages()
            for item in questions where questionLog[item.id] != item { questionLog[item.id] = item }
            if message != nil { message = nil }
            if !hasLoaded { hasLoaded = true }
            if lastUpdated == nil || Date().timeIntervalSince(lastUpdated ?? .distantPast) > 30 { lastUpdated = Date() }
            await flushOutbox()
        }
    }

    /// The newest page of `/v1/phone/messages`, merged into what is loaded (older pages stay). An older relay without it keeps the list.
    func reloadMessages() async {
        let page: ListResponse<PhoneMessage>
        do { page = try await client.messages(after: nil, limit: pageSize) }
        catch RelayError.unauthorized { handle(RelayError.unauthorized); return }
        catch { return }
        merge(page.items)
        if messagesNext == nil || page.next == nil || messages.count <= page.items.count { messagesNext = page.next }
        // A message we sent can be beyond the first page (lots of other traffic): page on until it is listed, at most 5 more pages.
        var cursor = page.next, extra = 0
        while extra < 5, let c = cursor, !unlistedSentClientIds().isEmpty {
            do {
                let p = try await client.messages(after: c, limit: pageSize)
                merge(p.items); cursor = p.next; messagesNext = p.next; extra += 1
            } catch RelayError.unauthorized { handle(RelayError.unauthorized); return } catch { break }
        }
        outbox.reconcile(with: messages)
    }
    private var firstSeen: [String: Date] = [:]
    private var arrival: [String: Int] = [:]
    private var arrivalCounter = 0

    private func rebuildGroups() {
        let names = Dictionary(workspaces.map { ($0.id, $0.displayName) }, uniquingKeysWith: { first, _ in first })
        let snapshot = GroupStore.build(messages: messages, workspaces: names, ownPhoneId: credentials?.phoneId ?? "",
                                        ownMessageIds: Set(messages.filter(\.fromPhone).map(\.id)), receivedAt: firstSeen, arrival: arrival)
        #if DEBUG
        for drop in snapshot.dropped where !groups.dropped.contains(drop) {
            print("group drop \(drop.rule) \(drop.messageId)")
        }
        #endif
        if groups != snapshot { groups = snapshot }
    }

    private func merge(_ items: [PhoneMessage]) {
        for m in items.reversed() where arrival[m.id] == nil {
            arrival[m.id] = arrivalCounter
            arrivalCounter += 1
            firstSeen[m.id] = Date()
        }
        var byId = Dictionary(uniqueKeysWithValues: messages.map { ($0.id, $0) })
        for m in items { byId[m.id] = m }          // newer data (delivered_at) replaces the old copy
        let merged = byId.values.sorted { ($0.message.createdAt, $0.id) > ($1.message.createdAt, $1.id) }
        if merged != messages { messages = merged }
        let retained = Set(messages.map(\.id))
        arrival = arrival.filter { retained.contains($0.key) }
        firstSeen = firstSeen.filter { retained.contains($0.key) }
    }
    /// client_ids of messages the relay stored (first tick) that `/messages` has not listed yet.
    private func unlistedSentClientIds() -> Set<String> {
        let listed = Set(messages.compactMap { $0.clientId ?? $0.message.body.clientId })
        return Set(outbox.items.filter { $0.kind == .send && $0.sentMessageId != nil && !listed.contains($0.clientId) }.map(\.clientId))
    }
    /// Messages per page (tests make it small).
    var pageSize = 100

    /// Scrolling up: the next older page. No-op when everything is loaded.
    func loadOlderMessages() async {
        guard let cursor = messagesNext else { return }
        do {
            let page = try await client.messages(after: cursor, limit: pageSize)
            merge(page.items); messagesNext = page.next
        } catch RelayError.unauthorized { handle(RelayError.unauthorized) } catch {}
    }
    var hasOlderMessages: Bool { messagesNext != nil }

    func answer(_ q: Question, with option: String) async {
        if q.isAllow && !q.message.body.options.contains(option) { return }
        let me = credentials?.phoneId
        outbox.enqueueAnswer(question: q, answer: option)
        let events = await outbox.flush(using: client)
        guard credentials?.phoneId == me, me != nil || useMock else { return }   // signed out meanwhile: drop the late result
        if events.contains(.offline) { announcement = "No connection. Your answer waits on this phone." }
        await handle(events)
        if events.contains(where: { if case .answered = $0 { true } else { false } }) { await refresh() }
    }

    /// Answers waiting on this phone (question id -> option), shown as "sending" until the relay has them.
    var queuedAnswers: [String: String] {
        Dictionary(outbox.items.compactMap { i in i.kind == .answer ? i.questionMessageId.map { ($0, i.answer ?? "") } : nil }, uniquingKeysWith: { a, _ in a })
    }

    func answerTime(for questionId: String) -> Date? {
        if let sent = answerSentAt[questionId] { return sent }
        return outbox.items.first { $0.kind == .answer && $0.questionMessageId == questionId }
            .flatMap { ISO8601DateFormatter().date(from: $0.createdAt) }
    }

    /// Acts on what the outbox did: answers recorded, refusals announced, sign-out handled.
    private func handle(_ events: [Outbox.Event]) async {
        for e in events {
            switch e {
            case .answered(_, let qid, let opt):
                answerSentAt[qid] = Date()
                answers[qid] = opt; answerTick += 1; announcement = "Answer sent: \(opt)"
            case .answerTaken(_, let qid, let text):
                answers[qid] = text; answeredElsewhere.insert(qid); message = nil
            case .sent: sendTick += 1; announcement = "Message sent"
            case .failed(_, _, let text): message = text; errorTick += 1; announcement = text
            case .unauthorized: handle(RelayError.unauthorized)
            case .throttled: announcement = "Try again later"
            case .offline: break
            }
        }
    }

    /// Only the "Got it" lines, for the sent screen.
    func refreshUpdates() async {
        if let u = try? await client.updates() { updates = u }
    }

    /// Today's chat composer: plain text. `ticket` nil = a new topic. Offline it waits in the outbox.
    enum SendResult: Equatable { case sent(id: String), queued, failed }
    func sendChat(to workspaceId: String, text: String, ticket: String? = nil) async -> SendResult {
        let target: SendTarget = ticket.map { .topic(workspace: workspaceId, ticket: $0) } ?? .newTopic(workspace: workspaceId)
        guard let item = try? await send(MessageDraft(text: text), to: target) else { return .failed }
        if let id = outbox.item(clientId: item.clientId)?.sentMessageId ?? messages.first(where: { $0.clientId == item.clientId })?.id { return .sent(id: id) }
        return outbox.item(clientId: item.clientId)?.failure != nil ? .failed : .queued
    }

    // MARK: Messenger API (v3)

    /// Queue a message (text, voice, photos, files, location, feedback) and send what can be sent. Returns once the relay has it or
    /// the phone is offline (the item then waits in `outbox`, shown with a clock). Throws `SendRequest.Problem` for an empty or
    /// invalid draft. A text for a topic of the relay add-on resolves later via `ConversationBuilder.resolve`.
    @discardableResult
    func send(_ draft: MessageDraft, to target: SendTarget) async throws -> OutboxItem {
        var draft = draft
        if let replyTo = draft.replyTo, isGroupCopy(replyTo) { draft.replyTo = nil }
        return try await sendInternal(draft, to: target)
    }

    func isGroupCopy(_ id: String) -> Bool {
        groups.groups.contains { group in
            group.messages.contains {
                $0.id == id && $0.message.message.from == group.key.host && $0.message.message.to == "phones"
            }
        }
    }

    /// Group sends explicitly opt into fan-out; plain sends strip group-copy quotes first.
    func sendInternal(_ draft: MessageDraft, to target: SendTarget) async throws -> OutboxItem {
        let item = try outbox.enqueue(draft, to: target)
        await flushOutbox()
        if let now = outbox.item(clientId: item.clientId) { return now }
        // Already listed by the relay (so removed from the outbox): report it as sent.
        var done = item; done.sentMessageId = messages.first { ($0.clientId ?? $0.message.body.clientId) == item.clientId }?.id
        return done
    }
    /// Try a refused message again / drop it.
    func retrySend(_ clientId: String) async { outbox.retry(clientId); await flushOutbox() }
    func discardSend(_ clientId: String) { outbox.discard(clientId) }

    func flushOutbox() async {
        let me = credentials?.phoneId
        guard !outbox.items.isEmpty, credentials != nil || useMock else { return }
        let events = await outbox.flush(using: client)
        guard credentials?.phoneId == me else { return }
        if events.contains(.offline) { announcement = "No connection. The message waits on this phone." }
        await handle(events)
        if events.contains(where: { if case .sent = $0 { true } else { false } }) { await reloadMessages(); await refreshUpdates() }
    }

    /// What the conversation builders read.
    var conversationInputs: ConversationInputs {
        let cd = chatData
        return ConversationInputs(workspaces: workspaces, messages: messages, tickets: tickets, questions: cd.questions, answers: answers,
                                  outbox: outbox.items, speak: settings.speak, erased: archive.erased)
    }
    /// The workspace list: presence, General and topics with status, unread, "Starting topic…".
    var workspaceSummaries: [WorkspaceSummary] { ConversationBuilder.summaries(conversationInputs, read: readState) }
    func conversationItems(_ id: ConversationID) -> [ConvItem] { ConversationBuilder.items(ConversationBuilder.resolve(id, conversationInputs), conversationInputs) }
    /// A "starting" conversation becomes its topic once the workspace acked it; others are returned unchanged.
    func resolve(_ id: ConversationID) -> ConversationID { ConversationBuilder.resolve(id, conversationInputs) }
    func presence(of workspaceId: String, now: Date = Date()) -> Presence { workspace(workspaceId)?.presence(now: now) ?? .unknown }

    func unread(_ id: ConversationID) -> Int { readState.unread(ReadState.key(id), in: conversationItems(id)) }
    // Archive, delete, auto-archive (phone-local)

    private func lastAt(_ id: ConversationID) -> String? {
        let summary = workspaceSummaries.first { $0.id == id.workspace }
        if case .general = id { return summary?.general.lastAt }
        return summary?.topics.first { $0.id == id }?.lastAt
    }
    private func change(_ edit: (inout ArchiveStore) -> Void) { var a = archive; edit(&a); archive = a; a.save() }
    func archiveChat(_ id: ConversationID) { let at = lastAt(id); change { $0.archive(ReadState.key(id), lastAt: at) } }
    func moveBack(_ id: ConversationID) { let at = lastAt(id); change { $0.moveBack(ReadState.key(id), lastAt: at) } }
    /// Delete = this phone's copy only; the ticket and the workspace are untouched.
    func deleteChat(_ id: ConversationID) {
        guard let last = conversationItems(id).map(\.at).max() else { return }
        change { $0.erase(ReadState.key(id), upTo: last) }
    }
    func setAutoArchive(days: Int) { change { $0.autoDays = days } }
    /// What the list of one workspace shows, and what is archived.
    func split(_ summary: WorkspaceSummary) -> (topics: [TopicSummary], general: Bool, archived: [ArchivedChat]) { archive.split(summary) }
    var archivedCount: Int { workspaceSummaries.reduce(0) { $0 + archive.split($1).archived.count } }

    /// Opening a conversation (or a new message arriving in the open one) marks it read. Phone-local.
    func markRead(_ id: ConversationID) {
        let items = conversationItems(id)
        guard let last = items.filter(\.incoming).map(\.at).max() else { return }
        var r = readState; r.markRead(ReadState.key(id), upTo: last)
        guard r != readState else { return }
        readState = r
        UserDefaults.standard.set(r.seen, forKey: "chatRead")
    }

    // Settings, mute, remove, invitations

    func updateSettings(_ patch: SettingsPatch) async {
        guard patch.isValid else { return }
        do { settings = try await client.updateSettings(patch); message = nil } catch { handle(error) }
    }
    func muteAll(_ mute: Mute) async {
        do { settings = try await client.muteAll(mute); message = nil } catch { handle(error) }
    }
    func setGroupMute(_ key: GroupKey, _ mute: Mute) async {
        do {
            let result = try await client.setGroupMute(key, mute: mute)
            var groups = (settings.groupMutes ?? []).filter { $0.key != key }
            if MuteRules.isMuted(result.mutedUntil) { groups.append(result) }
            settings.groupMutes = groups
            message = nil
        } catch { handle(error) }
    }
    func isMutedAll(now: Date = Date()) -> Bool { MuteRules.isMuted(settings.muteAllUntil, now: now) }
    func isGroupMuted(_ key: GroupKey, now: Date = Date()) -> Bool {
        (settings.groupMutes ?? []).contains { $0.key == key && MuteRules.isMuted($0.mutedUntil, now: now) }
    }
    func notificationsMuted(workspace: String, group: GroupKey? = nil, now: Date = Date()) -> Bool {
        MuteRules.isMuted(all: settings.muteAllUntil, workspace: self.workspace(workspace)?.mutedUntil,
                          group: group, groups: settings.groupMutes ?? [], now: now)
    }
    func setMute(_ workspaceId: String, _ mute: Mute) async {
        do {
            let w = try await client.setMute(workspace: workspaceId, mute: mute)
            if let i = workspaces.firstIndex(where: { $0.id == w.id }) { workspaces[i] = w }
            message = nil
        } catch { handle(error) }
    }
    /// Asks the workspace to leave Mobile mode; the banner goes once its next heartbeat says so.
    func turnOffMobileMode(_ workspaceId: String) async {
        do { try await client.turnOffMobileMode(workspace: workspaceId); message = nil } catch { handle(error) }
    }
    /// Drops the workspace from this phone (its conversations disappear from the list).
    func removeWorkspace(_ workspaceId: String) async {
        do {
            try await client.removeWorkspace(workspaceId)
            workspaces.removeAll { $0.id == workspaceId }
            messages.removeAll { $0.workspaceId == workspaceId }; updates.removeAll { $0.workspace == workspaceId }
            questions.removeAll { $0.message.from == workspaceId }; questionLog = questionLog.filter { $0.value.message.from != workspaceId }
            for i in outbox.items where i.workspace == workspaceId { outbox.discard(i.clientId) }
            path = []; message = nil
        } catch { handle(error) }
    }
    /// An `orch://pair?...` link opened while already paired: adds its workspaces to this phone. Returns the added workspaces.
    @discardableResult
    func redeemInvitation(_ text: String) async -> [WorkspaceRef] {
        do {
            let link = try PairingLink(text)
            let r = try await client.redeem(code: link.code)
            await refresh()
            return r.workspaces
        } catch {
            if case RelayError.api(let status, _, _) = error, status == 410 { message = "This invitation was already used or has expired. Ask the person who invited you for a new one." }
            else if case RelayError.api(let status, _, _) = error, status == 404 { message = "This invitation is not valid. Ask the person who invited you for a new one." }
            else { handle(error) }
            return []
        }
    }

    // Voice

    /// Settings-aware transcriber: relay first (`swiss_german` -> de-CH), then this phone.
    func voiceTranscriber() -> VoiceTranscriber {
        let c = client
        // The scripted recorder (UI tests, mock) writes bytes that are not audio: asking this phone's speech recognition would only
        // raise the system permission alert or download speech assets, and the memo bubble waits for the transcript.
        if voiceMode == .scripted {
            return VoiceTranscriber(relay: { audio, lang in try await c.transcribe(audio: audio, language: lang) },
                                    onDevice: { _, _ in throw RelayError.network("scripted audio") })
        }
        return VoiceTranscriber(relay: { audio, lang in try await c.transcribe(audio: audio, language: lang) })
    }
    func makeVoiceRecorder() -> VoiceRecorder { VoiceRecorder(mode: voiceMode == .live ? .live : .scripted) }
    /// Record -> transcribe -> a draft ready for `send`. `corrected` = the language picked in the long-press menu.
    func voiceDraft(for segment: VoiceSegment, corrected: String? = nil) async -> DraftVoice {
        let t = await voiceTranscriber().transcribe(file: segment.url, swissGerman: settings.swissGerman, corrected: corrected)
        return DraftVoice(url: segment.url, duration: segment.duration, transcript: t.text, lang: t.lang, langSource: t.langSource)
    }

    // Read aloud

    /// The clip for a workspace text with a play button, nil when it has none.
    func speechClip(_ item: ConvItem, workspaceName: String) -> SpeechClip? {
        guard item.incoming, item.canPlay else { return nil }
        let lang = item.speak?.lang ?? "en"
        return SpeechClip(messageId: item.id, text: item.text, summary: item.speak?.summary, lang: lang, title: workspaceName)
    }
    /// Play one text; the next unheard playable texts of the same conversation follow (auto-next).
    func play(_ item: ConvItem, in id: ConversationID) {
        let name = workspace(id.workspace)?.displayName ?? "orch"
        let items = conversationItems(id)
        guard let clip = speechClip(item, workspaceName: name) else { return }
        let after = items.drop { $0.id != item.id }.dropFirst().filter { !speech.isListened($0.id) }.compactMap { speechClip($0, workspaceName: name) }
        speech.play(clip, then: Array(after))
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
        if q.isMakeTicket {
            path = [.workspace(ws), .general(ws)]
            return
        }
        path = q.message.ticket.map { [.workspace(ws), .ticket(workspace: ws, ticket: $0)] } ?? [.workspace(ws)]
    }

    /// Text push tap: that workspace's chat (the topic when the push names one).
    func openMessages(workspaceId: String, ticket: String? = nil) {
        focusedQuestion = nil; tab = .chats
        path = ticket.map { [.workspace(workspaceId), .ticket(workspace: workspaceId, ticket: $0)] } ?? [.workspace(workspaceId)]
        Task { await refresh() }
    }

    func signOut() async {
        try? await client.signOut()
        Keychain.delete()
        reset()
    }

    private func reset() {
        defaults.removeObject(forKey: "pairedPhoneId")
        for t in undoTimers.values { t.cancel() }
        undoTimers = [:]; pendingAnswers = [:]; sendingAnswers = []
        outbox.wipe(); speech.reset(); settings = PhoneSettings(); messagesNext = nil
        UserDefaults.standard.removeObject(forKey: "chatOutbox"); UserDefaults.standard.removeObject(forKey: "chatRead")
        readState = ReadState(); blobCache = [:]
        archive = ArchiveStore(); UserDefaults.standard.removeObject(forKey: ArchiveStore.defaultsKey)
        credentials = nil; invite = nil; inviteState = .none; workspaces = []; questions = []; questionLog = [:]; path = []; messages = []; updates = []; answers = [:]; answerSentAt = [:]; answeredElsewhere = []; hasLoaded = false
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
        path = []   // a cold start always lands on the Chats list; only a push or `-open` below opens something
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
        #if DEBUG
        // `-open general:<ws>` | `topic:<ws>:<ticket>` | `workspace:<ws>` | `settings:chats` | `archived` (ignored until the archive exists)
        if phase == .ready, let target = d.string(forKey: "open") {
            let p = target.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
            switch p.first {
            case "general" where p.count == 2: path = [.workspace(p[1]), .general(p[1])]
            case "topic" where p.count == 3: path = [.workspace(p[1]), .ticket(workspace: p[1], ticket: p[2])]
            case "workspace" where p.count == 2: path = [.workspace(p[1])]
            case "settings": tab = .settings
            default: break
            }
        }
        #endif
        if phase == .ready { if !useMock { await PushPermission.registerIfAuthorized() } }
    }
}
