import Foundation

/// In-process fake of the phone endpoints with the shared dataset (Pilatus Workspace + Reports).
/// Same rules as the real relay: first answer wins (409 already_answered), `send` only to reachable workspaces.
actor MockRelay: RelayAPI {
    static let pilatus = "ws_pilatus001", reports = "ws_reports001"
    private(set) var sent: [(to: String, text: String)] = []
    private var answered: [String: String] = [:]
    private var signedOut = false
    private var counter = 0, updateCounter = 0
    private let latency: Duration

    /// Simulator evidence hooks: `-mockLatencyMs N`, `-mockFail YES` (network error), `-mockEmpty YES` (no workspaces or questions).
    private let fail = UserDefaults.standard.bool(forKey: "mockFail")
    private let empty = UserDefaults.standard.bool(forKey: "mockEmpty")

    init(latency: Duration? = nil) {
        if UserDefaults.standard.bool(forKey: "mockAllow") { all.append(Self.allowQuestion) }
        let ms = UserDefaults.standard.integer(forKey: "mockLatencyMs")
        self.latency = latency ?? .milliseconds(ms > 0 ? ms : 150)
    }

    private let names = [pilatus: "Pilatus Workspace", reports: "Reports"]
    private var all: [Question] = [
        Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_q1date0ts0000001", from: pilatus, to: "phones", type: "question",
                                          createdAt: "2026-11-04T10:41:00Z", ticket: "t_7k3f9q",
                                          body: QuestionBody(questionId: "q1", title: "Rename field X in ingestion job", text: "DATE or TIMESTAMP?",
                                                             options: ["DATE", "TIMESTAMP"], recommended: "TIMESTAMP"), key: "PIL-13"),
                 workspaceName: "Pilatus Workspace"),
        Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_q2friday00000002", from: reports, to: "phones", type: "question",
                                          createdAt: "2026-11-04T10:50:00Z", ticket: "t_r2w8k3",
                                          body: QuestionBody(questionId: "q1", title: "Weekly report", text: "Send the report on Friday this week?",
                                                             options: ["Yes", "No"], recommended: "Yes"), key: "RGS-5"),
                 workspaceName: "Reports"),
    ]

    /// Texts workspaces sent to this phone (the mock has one reply from Pilatus waiting).
    private var received: [PhoneMessage] = [
        PhoneMessage(message: TextMessage(id: "m_reply0phone00001", from: pilatus, to: "ph_iphone0001", type: "text",
                                          createdAt: "2026-11-04T10:44:00Z", ticket: nil,
                                          body: TextBody(text: "Yes, I can answer your phone. The report is ready.")),
                     workspaceName: "Pilatus Workspace"),
    ]
    private var sentMessages: [PhoneMessage] = [
        PhoneMessage(message: TextMessage(id: "m_seedsent00000001", from: "ph_iphone0001", to: pilatus, type: "text",
                                          createdAt: "2026-11-05T10:32:00Z", ticket: nil, body: TextBody(text: "Can you make the Q3 summary for the board?")),
                     workspaceName: "Pilatus Workspace"),
    ]

    /// Fake ticket snapshots (the shape the workspace will send as `ticket_view`).
    static let q3View = TicketSnapshot(
        title: "Q3 summary for the board", status: "done", agent: "Claude", summary: "Pulled the numbers, drew the charts, the board deck is ready.",
        checklist: ["Read the Q3 sheet", "Check the totals", "Prepare the summary", "Draw the charts", "Review the board deck"].map { .init(text: $0, done: true) },
        running: false,
        attachments: [.init(kind: "image", title: "q3-chart.png", name: "q3-chart.png", size: 48_000, at: "2026-11-05T11:19:00Z"),
                      .init(kind: "link", title: "Board deck draft", url: "https://docs.pilatus.ch/board-q3", at: "2026-11-05T11:19:30Z"),
                      .init(kind: "file", title: "test-report.pdf", name: "test-report.pdf", size: 84_000, at: "2026-11-05T11:19:40Z")],
        historyTail: [.init(at: "2026-11-05T10:34:00Z", by: "agent", text: "Pulled the numbers from the Q3 sheet."),
                      .init(at: "2026-11-05T10:37:00Z", by: "agent", text: "Draft is ready, charts next.")])
    static let invoiceView = TicketSnapshot(
        title: "Invoice CSV export", status: "working", agent: "Claude", summary: "Writing the export.",
        checklist: [.init(text: "Read the invoice table", done: true), .init(text: "Choose the columns", done: true), .init(text: "Write the export", done: false),
                    .init(text: "Add a test", done: false)],
        running: true,
        attachments: [.init(kind: "link", title: "Fix invoice export #142", url: "https://github.com/pilatus/reports/pull/142", at: "2026-11-05T15:10:00Z")],
        historyTail: [.init(at: "2026-11-05T15:05:00Z", by: "person", text: "Please add an export for the invoices."),
                      .init(at: "2026-11-05T15:08:00Z", by: "agent", text: "Reading the invoice table first.")])

    /// Work updates per (workspace, ticket), newest per ticket is what the feed returns.
    private var updateLog: [TicketUpdate] = [
        TicketUpdate(id: "m_upd0000000000001", workspace: pilatus, workspaceName: "Pilatus Workspace", ticket: "t_q3sum1", kind: "result",
                     title: "Q3 summary", text: "Q3 summary is ready in the shared folder.", replyTo: nil, at: "2026-11-05T11:20:00Z",
                     key: "PIL-12", ticketView: MockRelay.q3View),
        TicketUpdate(id: "m_upd0000000000002", workspace: reports, workspaceName: "Reports", ticket: "t_9k2m4q", kind: "working",
                     title: "Invoice CSV export", text: "Working on: Invoice CSV export", replyTo: nil, at: "2026-11-05T15:12:00Z",
                     key: "RGS-4", ticketView: MockRelay.invoiceView),
    ]

    /// The question the relay add-on asks when a workspace hands over a task that is not allowed yet (relay:allow).
    static let allowQuestion = Question(
        message: QuestionMessage(schema: "orch.msg/1", id: "m_q3allow00000003", from: pilatus, to: "phones", type: "question",
                                 createdAt: "2026-11-05T09:30:00Z", ticket: "t_a110w1",
                                 body: QuestionBody(questionId: "q1", title: "Prepare Q3 numbers",
                                                    text: "Reports wants Pilatus Workspace to: Prepare Q3 numbers.",
                                                    options: ["Once", "Always", "No"], recommended: nil), key: "PIL-14"),
        workspaceName: "Pilatus Workspace")

    /// Simulator and test hook: an allow question arrives.
    func deliverAllow() { if !all.contains(where: { $0.id == Self.allowQuestion.id }) { all.append(Self.allowQuestion) } }
    /// Simulator and test hook: the workspace reports on a ticket.
    func deliverUpdate(workspace: String, ticket: String, kind: String, title: String?, text: String, replyTo: String? = nil, key: String? = nil, view: TicketSnapshot? = nil) {
        updateCounter += 1
        updateLog.append(TicketUpdate(id: String(format: "m_upd%013d", updateCounter + 100), workspace: workspace, workspaceName: names[workspace] ?? workspace,
                                      ticket: ticket, kind: kind, title: title, text: text, replyTo: replyTo, at: ISO8601DateFormatter().string(from: Date()), key: key, ticketView: view))
    }

    /// Simulator and test hook: a workspace writes to the phone after launch (a text push arrived).
    func deliverText(from workspace: String, text: String) {
        counter += 1
        received.append(PhoneMessage(message: TextMessage(id: String(format: "m_wstext%010d", counter), from: workspace, to: "ph_iphone0001",
                                                          type: "text", createdAt: ISO8601DateFormatter().string(from: Date()), ticket: nil,
                                                          body: TextBody(text: text)),
                                     workspaceName: names[workspace] ?? workspace))
    }

    private func check() async throws {
        try? await Task.sleep(for: latency)
        if signedOut { throw RelayError.unauthorized }
        if fail { throw URLError(.notConnectedToInternet) }
    }

    func pair(code: String, name: String) async throws -> PairResponse {
        try? await Task.sleep(for: latency)
        guard code.hasPrefix("pc_") else { throw RelayError.api(status: 404, code: "not_found", message: "This invitation is not valid any more.") }
        // The live relay answers 401 (not 404) for an unknown or used pair code.
        if code.hasPrefix("pc_expired") { throw RelayError.api(status: 401, code: "unauthorized", message: "Missing or wrong token.") }
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
    func messages() async throws -> [PhoneMessage] {
        try await check()
        if empty { return [] }
        // The real relay lists work updates (texts with `update`) in /messages too.
        let updateTexts = updateLog.map { u in
            PhoneMessage(message: TextMessage(id: u.id, from: u.workspace, to: "ph_iphone0001", type: "text", createdAt: u.at, ticket: u.ticket,
                                              body: TextBody(text: u.text, update: TextUpdate(kind: u.kind, title: u.title)), key: u.key),
                         workspaceName: u.workspaceName)
        }
        return (received + sentMessages + updateTexts).sorted { $0.message.createdAt > $1.message.createdAt }
    }
    func updates() async throws -> [TicketUpdate] {
        try await check()
        if empty { return [] }
        var newest: [String: TicketUpdate] = [:]
        for u in updateLog where (newest["\(u.workspace)|\(u.ticket)"]?.at ?? "") <= u.at { newest["\(u.workspace)|\(u.ticket)"] = u }
        return newest.values.sorted { $0.at > $1.at }
    }
    func answer(questionMessageId: String, answer: String) async throws -> String {
        try await check()
        guard all.contains(where: { $0.id == questionMessageId }) else { throw RelayError.api(status: 404, code: "not_found", message: "Question not found.") }
        // Simulator evidence hook `-mockRace YES`: another phone answered "DATE" a moment before this one.
        if UserDefaults.standard.bool(forKey: "mockRace"), answered[questionMessageId] == nil { answered[questionMessageId] = "DATE" }
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
        // The relay add-on's "Got it": a new ticket for a phone text, the same ticket for a reply.
        let ack = String(text.prefix(40)).trimmingCharacters(in: .whitespaces)
        let prior = updateLog.last { $0.ticket == ticket && $0.workspace == to }   // the feed's snapshot and key stay with the ticket
        let newKey = "\(to == Self.pilatus ? "PIL" : "RGS")-\(20 + counter)"
        deliverUpdate(workspace: to, ticket: ticket ?? String(format: "t_ph%06d", counter), kind: "ack", title: ack, text: "Got it: \(ack)",
                      replyTo: String(format: "m_ph0nesend%06d", counter), key: ticket == nil ? newKey : prior?.key,
                      view: ticket == nil ? TicketSnapshot(title: ack, status: "working", agent: "Claude", running: false) : prior?.ticketView)
        sentMessages.append(PhoneMessage(message: TextMessage(id: String(format: "m_ph0nesend%06d", counter), from: "ph_iphone0001", to: to, type: "text",
                                                              createdAt: ISO8601DateFormatter().string(from: Date()), ticket: ticket, body: TextBody(text: text)),
                                         workspaceName: names[to] ?? to))
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
