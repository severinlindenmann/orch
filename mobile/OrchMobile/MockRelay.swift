import Foundation

/// In-process fake of the phone endpoints with the shared dataset (Pilatus Workspace + Reports).
/// Same rules as the real relay: first answer wins (409 already_answered), `send` only to reachable workspaces.
actor MockRelay: RelayAPI {
    static let pilatus = "ws_pilatus001", reports = "ws_reports001"
    private(set) var sent: [(to: String, text: String)] = []
    private var answered: [String: String] = [:]
    private var signedOut = false
    private var counter = 0
    private let latency: Duration

    /// Simulator evidence hooks: `-mockLatencyMs N`, `-mockFail YES` (network error), `-mockEmpty YES` (no workspaces or questions).
    private let fail = UserDefaults.standard.bool(forKey: "mockFail")
    private let empty = UserDefaults.standard.bool(forKey: "mockEmpty")

    init(latency: Duration? = nil) {
        let ms = UserDefaults.standard.integer(forKey: "mockLatencyMs")
        self.latency = latency ?? .milliseconds(ms > 0 ? ms : 150)
    }

    private let names = [pilatus: "Pilatus Workspace", reports: "Reports"]
    private let all: [Question] = [
        Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_q1date0ts0000001", from: pilatus, to: "phones", type: "question",
                                          createdAt: "2026-11-04T10:41:00Z", ticket: "t_7k3f9q",
                                          body: QuestionBody(questionId: "q1", title: "Rename field X in ingestion job", text: "DATE or TIMESTAMP?",
                                                             options: ["DATE", "TIMESTAMP"], recommended: "TIMESTAMP")),
                 workspaceName: "Pilatus Workspace"),
        Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_q2friday00000002", from: reports, to: "phones", type: "question",
                                          createdAt: "2026-11-04T10:50:00Z", ticket: "t_r2w8k3",
                                          body: QuestionBody(questionId: "q1", title: "Weekly report", text: "Send the report on Friday this week?",
                                                             options: ["Yes", "No"], recommended: "Yes")),
                 workspaceName: "Reports"),
    ]

    private func check() async throws {
        try? await Task.sleep(for: latency)
        if signedOut { throw RelayError.unauthorized }
        if fail { throw URLError(.notConnectedToInternet) }
    }

    func pair(code: String, name: String) async throws -> PairResponse {
        try? await Task.sleep(for: latency)
        guard code.hasPrefix("pc_") else { throw RelayError.api(status: 404, code: "not_found", message: "This invitation is not valid any more.") }
        signedOut = false
        return PairResponse(phoneId: "ph_iphone0001", token: "orn_mock", workspaces: [
            WorkspaceRef(id: Self.pilatus, name: "Pilatus Workspace"), WorkspaceRef(id: Self.reports, name: "Reports")])
    }
    func registerPush(apnsToken: String, sandbox: Bool) async throws { try await check() }

    func workspaces() async throws -> [Workspace] {
        try await check()
        if empty { return [] }
        func open(_ ws: String) -> Int { all.filter { $0.message.from == ws && answered[$0.id] == nil }.count }
        return [
            Workspace(id: Self.pilatus, name: "Pilatus Workspace", description: "Data pipelines for the Pilatus client",
                      tags: ["client", "data", "ingestion"], online: true, lastSeen: "2026-11-04T10:41:00Z", openQuestions: open(Self.pilatus)),
            Workspace(id: Self.reports, name: "Reports", description: "Weekly and monthly reporting",
                      tags: ["reports", "scheduler"], online: true, lastSeen: "2026-11-04T10:50:00Z", openQuestions: open(Self.reports)),
        ]
    }
    func questions() async throws -> [Question] {
        try await check()
        if empty { return [] }
        return all.filter { answered[$0.id] == nil }
    }
    func answer(questionMessageId: String, answer: String) async throws -> String {
        try await check()
        guard all.contains(where: { $0.id == questionMessageId }) else { throw RelayError.api(status: 404, code: "not_found", message: "Question not found.") }
        if let a = answered[questionMessageId] {
            throw RelayError.api(status: 409, code: "already_answered", message: "This question was already answered: \(a).")
        }
        answered[questionMessageId] = answer
        counter += 1
        return String(format: "m_an5wer%010d", counter)
    }
    func send(to: String, text: String, ticket: String?) async throws -> String {
        try await check()
        guard names[to] != nil else { throw RelayError.api(status: 403, code: "not_allowed", message: "This phone may not reach that workspace.") }
        sent.append((to, text))
        counter += 1
        return String(format: "m_ph0nesend%06d", counter)
    }
    /// Fixed transcript, whatever the audio is.
    static let transcript = "Send the weekly report on Friday."
    func transcribe(audio: Data, language: String?) async throws -> Transcript {
        try await check()
        return Transcript(text: Self.transcript, language: language ?? "en", duration: 3.2)
    }
    func signOut() async throws { try await check(); signedOut = true }
}
