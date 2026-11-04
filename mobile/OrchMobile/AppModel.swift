import Foundation
import Observation

enum Tab: Hashable { case home, questions, send, settings }

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
    /// question message id -> the answer this phone sent
    private(set) var answers: [String: String] = [:]
    private(set) var isLoading = false
    private(set) var lastSent: SentNote?
    var message: String?            // plain error / info line

    // Navigation
    var tab: Tab = .home
    var questionFilter: String?     // workspace id, nil = all
    var highlightedQuestion: String?
    var notificationsEnabled = true

    struct SentNote: Equatable { let workspaceName: String; let text: String }

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
    }

    /// `-relayMode real` (launch argument or UserDefaults) switches from the mock to the relay named in the invitation.
    static var configuredMock: Bool { UserDefaults.standard.string(forKey: "relayMode") != "real" }
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

    var relayHost: String { credentials?.relay.host ?? invite?.host ?? "relay" }
    var phoneName: String { credentials?.phoneName ?? "This iPhone" }
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
            inviteState = .found(host: invite.host); message = error.localizedDescription
        }
    }

    func finishSetup(allowNotifications: Bool) async {
        notificationsEnabled = allowNotifications
        if allowNotifications { notificationsEnabled = await PushPermission.request() }
        phase = .ready; tab = .home
        await refresh()
    }

    // MARK: Data

    func refresh() async {
        guard phase == .ready || phase == .notifyStep, credentials != nil else { return }
        isLoading = true; defer { isLoading = false }
        do {
            async let w = client.workspaces()
            async let q = client.questions()
            workspaces = try await w; questions = try await q
            message = nil
        } catch { handle(error) }
    }

    func answer(_ q: Question, with option: String) async {
        do {
            _ = try await client.answer(questionMessageId: q.id, answer: option)
            answers[q.id] = option
            await refresh()
        } catch let RelayError.api(status, code, text) where status == 409 && code == "already_answered" {
            answers[q.id] = text
            message = text
            await refresh()
        } catch { handle(error) }
    }

    func send(to workspaceId: String, text: String) async -> Bool {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return false }
        do {
            _ = try await client.send(to: workspaceId, text: clean, ticket: nil)
            lastSent = SentNote(workspaceName: workspaces.first { $0.id == workspaceId }?.name ?? "workspace", text: clean)
            message = nil
            return true
        } catch { handle(error); return false }
    }

    func transcribe(_ audio: Data) async throws -> String {
        do { return try await client.transcribe(audio: audio, language: nil).text }
        catch RelayError.unauthorized { handle(RelayError.unauthorized); throw RelayError.unauthorized }
    }

    func registerPush(token: String) async {
        try? await client.registerPush(apnsToken: token, sandbox: PushPermission.sandbox)
    }

    /// Push tap.
    func openQuestion(messageId: String) {
        highlightedQuestion = messageId; questionFilter = nil; tab = .questions
        Task { await refresh() }
    }

    func signOut() async {
        try? await client.signOut()
        Keychain.delete()
        reset()
    }

    private func reset() {
        credentials = nil; invite = nil; inviteState = .none; workspaces = []; questions = []; answers = [:]
        pairedWorkspaces = []; lastSent = nil; message = nil; tab = .home; phase = .onboarding
    }

    private func handle(_ error: Error) {
        if case RelayError.unauthorized = error { Keychain.delete(); reset(); message = error.localizedDescription }
        else { message = error.localizedDescription }
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
            tab = ["questions": .questions, "send": .send, "settings": .settings][t] ?? .home
        }
        if phase == .ready, let id = d.string(forKey: "openQuestion") { openQuestion(messageId: id) }  // stands in for a push tap in the Simulator
        if phase == .ready { await refresh(); if !useMock { await PushPermission.registerIfAuthorized() } }
    }
}
