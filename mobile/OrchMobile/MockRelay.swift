import Foundation
import CryptoKit
import UIKit

/// In-process fake of the phone endpoints with the shared dataset (Pilatus Workspace + Reports).
/// Same rules as the real relay: first answer wins (409 already_answered), `send` only to reachable workspaces.
actor MockRelay: RelayAPI {
    static let pilatus = "ws_pilatus001", reports = "ws_reports001"
    private(set) var sent: [(to: String, text: String)] = []
    /// Every `send` request that reached the relay (duplicates excluded), for tests.
    private(set) var requests: [SendRequest] = []
    private(set) var uploads: [String: Data] = [:]
    private var clientIds: [String: String] = [:]          // client_id -> message id (send and answer share one namespace)
    private var mutes: [String: String?] = [:]
    private var removed: Set<String> = []
    private var usedCodes: Set<String> = []
    private var phoneSettings = PhoneSettings()
    private var generalReceipts: [PhoneMessage] = []
    /// Test hooks. `autoDeliver`: the workspace acks (delivered_at) a phone text at once. `offline`: every call fails like no network.
    private(set) var autoDeliver = true
    var offline = false
    enum SpeechMode { case ok, capReached, off, failed }
    var speechMode: SpeechMode = .ok
    private var uploadFailures: [Int] = [], sendFailures: [Int] = []
    /// Test hooks: the next upload / send calls fail with these statuses (one status per call), then work again.
    func queueUploadFailures(_ s: [Int]) { uploadFailures = s }
    func queueSendFailures(_ s: [Int]) { sendFailures = s }
    private(set) var uploadCalls = 0
    func setAutoDeliver(_ v: Bool) { autoDeliver = v }
    func setOffline(_ v: Bool) { offline = v }
    func setSpeechMode(_ m: SpeechMode) { speechMode = m }
    private(set) var speechRequests: [(id: String, lang: String?)] = []
    private var answered: [String: String] = [:]
    private var signedOut = false
    private var counter = 0, updateCounter = 0
    private let latency: Duration

    /// Simulator evidence hooks: `-mockLatencyMs N`, `-mockFail YES` (network error), `-mockEmpty YES` (no workspaces or questions).
    private let fail = UserDefaults.standard.bool(forKey: "mockFail")
    private let empty = UserDefaults.standard.bool(forKey: "mockEmpty")

    init(latency: Duration? = nil) {
        if UserDefaults.standard.bool(forKey: "mockMakeTicket") { all.append(Self.makeTicketQuestion) }
        if UserDefaults.standard.bool(forKey: "mockReview") {
            all.append(Self.reviewQuestion)
            updateLog.append(TicketUpdate(id: "m_reviewupdate001", workspace: Self.pilatus, workspaceName: "Pilatus Workspace",
                ticket: Self.reviewTicketId, kind: "result", title: Self.reviewView.title, text: "Your fish test page is ready.", replyTo: nil,
                at: Self.now(), key: "DT-2", ticketView: Self.reviewView))
        }
        if UserDefaults.standard.bool(forKey: "mockAllow") { all.append(Self.allowQuestion) }
        if UserDefaults.standard.bool(forKey: "mockGroups") {
            for (id, name) in GroupMock.names where names[id] == nil { names[id] = name }
            received.append(contentsOf: GroupMock.messages())
            all.append(GroupMock.question(at: Self.now()))
        }
        if UserDefaults.standard.bool(forKey: "mockMemo") { received.append(Self.memo) }
        if UserDefaults.standard.bool(forKey: "mockChatDays") { let d = Self.chatDays(); sentMessages += d.sent; received += d.received }
        let ms = UserDefaults.standard.integer(forKey: "mockLatencyMs")
        self.latency = latency ?? .milliseconds(ms > 0 ? ms : 150)
    }

    static var makeTicketQuestion: Question {
        Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_maketicket00001", from: pilatus,
            to: "phones", type: "question", createdAt: now(), ticket: nil,
            body: QuestionBody(questionId: "proposal-m_maketicket00001", title: "Check the backups",
                text: "Here is a ticket for Friday 13 Nov.", options: ["make", "not_now"], recommended: nil,
                proposal: "make_ticket", when: "2026-11-13")), workspaceName: "Pilatus Workspace")
    }

    private var names = [pilatus: "Pilatus Workspace", reports: "Reports"]
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

    /// A long answer the workspace marked `speak`: shows the memo bubble (screenshots, UI tests): `-mockMemo YES`.
    /// Dated now: Chat shows only today (older days live in History).
    static var memo: PhoneMessage { PhoneMessage(message: TextMessage(id: "m_memo0phone00001", from: pilatus, to: "ph_iphone0001", type: "text",
                                      createdAt: now(), ticket: nil,
                                      body: TextBody(text: "The Q3 numbers are in. Revenue is up eight percent, costs are flat, and the board summary will be ready this afternoon.",
                                                     speak: SpeakHint(lang: "en", summary: "Q3 is up eight percent."))),
                 workspaceName: "Pilatus Workspace") }
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
        attachments: [.init(kind: "image", title: "q3-chart.png", blobId: "b_chart", name: "q3-chart.png", size: 48_000, at: "2026-11-05T11:19:00Z", artifactId: "a_bbbbbbbbbbbb", rev: "r1"),
                      .init(kind: "link", title: "Board deck draft", url: "https://docs.pilatus.ch/board-q3", at: "2026-11-05T11:19:30Z", linkType: "Link", icon: "link"),
                      .init(kind: "file", title: "test-report.pdf", name: "test-report.pdf", size: 84_000, at: "2026-11-05T11:19:40Z")],
        historyTail: [.init(at: "2026-11-05T10:34:00Z", by: "Claude", role: "agent", text: "Pulled the numbers from the Q3 sheet."),
                      .init(at: "2026-11-05T10:37:00Z", by: "Claude", role: "agent", text: "Draft is ready, charts next.")],
        refs: [.init(rawKind: "url", url: "https://docs.pilatus.ch/board-q3", title: "Board deck draft"),
               .init(rawKind: "ticket", ticket: "t_7k3f9q"),
               .init(rawKind: "artifact", ticket: "t_q3sum1", name: "q3-chart.png"),
               .init(rawKind: "file", path: "docs/board/q3.md", line: 12)])
    static let invoiceView = TicketSnapshot(
        title: "Invoice CSV export", status: "active", agent: "Claude", summary: "Writing the export.",
        checklist: [.init(text: "Read the invoice table", done: true), .init(text: "Choose the columns", done: true), .init(text: "Write the export", done: false),
                    .init(text: "Add a test", done: false)],
        running: true,
        attachments: [.init(kind: "link", title: "Fix invoice export #142", url: "https://github.com/pilatus/reports/pull/142", at: "2026-11-05T15:10:00Z",
                            linkType: "GitHub · Pull request", icon: "github", mono: "GH", status: "review")],
        historyTail: [.init(at: "2026-11-05T15:05:00Z", by: "You", role: "person", text: "Please add an export for the invoices."),
                      .init(at: "2026-11-05T15:08:00Z", by: "Claude", role: "agent", text: "Reading the invoice table first.")])

    /// Work updates per (workspace, ticket), newest per ticket is what the feed returns.
    private var updateLog: [TicketUpdate] = [
        TicketUpdate(id: "m_upd0000000000001", workspace: pilatus, workspaceName: "Pilatus Workspace", ticket: "t_q3sum1", kind: "result",
                     title: "Q3 summary", text: "Q3 summary is ready in the shared folder.", replyTo: nil, at: "2026-11-05T11:20:00Z",
                     key: "PIL-12", ticketView: MockRelay.q3View),
        TicketUpdate(id: "m_upd0000000000002", workspace: reports, workspaceName: "Reports", ticket: "t_9k2m4q", kind: "working",
                     title: "Invoice CSV export", text: "Working on: Invoice CSV export", replyTo: nil, at: "2026-11-05T15:12:00Z",
                     key: "RGS-4", ticketView: MockRelay.invoiceView),
    ]

    /// Ready-for-review fixture enabled with -mockReview YES.
    static let reviewTicketId = "t_reviewfish"
    static let reviewView = TicketSnapshot(title: "Test HTML page about fish", status: "review",
        checklist: ["Create page", "Add fish facts", "Review page"].map { .init(text: $0, done: true) }, running: false)
    static var reviewQuestion: Question {
        Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_review000000001", from: pilatus, to: "phones", type: "question",
            createdAt: now(), ticket: reviewTicketId, body: QuestionBody(questionId: "review-1", title: reviewView.title,
                text: "Is this done?", options: ["accept", "changes"], recommended: nil, review: true), key: "DT-2"),
            workspaceName: "Pilatus Workspace")
    }

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

    /// Screenshot hook `-mockChatDays YES`: a Chat with a closed day (History) and today's messages with `by`/`day` (round-8 draft).
    private static func chatDays() -> (sent: [PhoneMessage], received: [PhoneMessage]) {
        let f = ISO8601DateFormatter()
        let now = Date()
        func text(_ id: String, _ ago: TimeInterval, mine: Bool, _ t: String, by: String, day: String) -> PhoneMessage {
            var body = TextBody(text: t, general: true); body.by = by; body.via = mine ? "phone" : "helper"; body.day = day
            return PhoneMessage(message: TextMessage(id: id, from: mine ? "ph_iphone0001" : Self.pilatus, to: mine ? Self.pilatus : "ph_iphone0001", type: "text",
                                                     createdAt: f.string(from: now.addingTimeInterval(-ago)), ticket: nil, body: body), workspaceName: "Pilatus Workspace")
        }
        let today = ChatDay.key(for: now), yesterday = ChatDay.key(for: now.addingTimeInterval(-86_400))
        return ([text("m_cd_y1", 90_000, mine: true, "That's everything for today, thanks.", by: "you", day: yesterday),
                 text("m_cd_t1", 600, mine: true, "Good morning. What is due next?", by: "you", day: today)],
                [text("m_cd_y2", 89_900, mine: false, "All set. Your tickets are saved.", by: Self.pilatus, day: yesterday),
                 text("m_cd_t2", 540, mine: false, "Your car tax is due on 30 Nov.", by: Self.pilatus, day: today)])
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
        if fail || offline { throw URLError(.notConnectedToInternet) }
    }
    private func reachable(_ ws: String) -> Bool { names[ws] != nil && !removed.contains(ws) }
    private static func now() -> String { ISO8601DateFormatter().string(from: Date()) }
    private static func invalid(_ m: String) -> RelayError { .api(status: 422, code: "invalid", message: m) }

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
        func open(_ ws: String) -> Int { all.filter { !$0.isReview && !$0.isMakeTicket && $0.message.from == ws && answered[$0.id] == nil }.count }
        var list = [
            Workspace(id: Self.pilatus, name: "Pilatus Workspace", description: "Data pipelines for the Pilatus client",
                      tags: ["client", "data", "ingestion"], online: true, lastSeen: "2026-11-04T10:41:00Z", openQuestions: open(Self.pilatus),
                      icon: "wallet", color: "amber"),
            Workspace(id: Self.reports, name: "Reports", description: "Weekly and monthly reporting",
                      tags: ["reports", "scheduler"], online: true, lastSeen: "2026-11-04T10:50:00Z", openQuestions: open(Self.reports),
                      can: WorkspaceCan(chat: true, tasks: false, files: false)),
        ]
        if names["ws_home000001"] != nil {
            list.append(Workspace(id: "ws_home000001", name: "Home", description: "", tags: [], online: false, lastSeen: nil, openQuestions: 0))
        }
        for (id, name) in names.sorted(by: { $0.key < $1.key }) where !list.contains(where: { $0.id == id }) {
            list.append(Workspace(id: id, name: name, description: "", tags: [], online: true, lastSeen: Self.now(), openQuestions: open(id)))
        }
        return list.filter { !removed.contains($0.id) }.map { var w = $0; w.mutedUntil = mutes[w.id] ?? nil; return w }
    }
    func questions() async throws -> [Question] {
        try await check()
        if empty { return [] }
        return all.filter { answered[$0.id] == nil }
    }
    func messages(after: String?, limit: Int?) async throws -> ListResponse<PhoneMessage> {
        try await check()
        if empty { return ListResponse(items: [], next: nil) }
        // The real relay lists work updates (texts with `update`) in /messages too.
        let updateTexts = updateLog.map { u in
            PhoneMessage(message: TextMessage(id: u.id, from: u.workspace, to: "ph_iphone0001", type: "text", createdAt: u.at, ticket: u.ticket,
                                              body: TextBody(text: u.text, update: TextUpdate(kind: u.kind, title: u.title), ticketView: u.ticketView),
                                              key: u.key, replyTo: u.replyTo),
                         workspaceName: u.workspaceName)
        }
        let all = (received + sentMessages + updateTexts + generalReceipts).filter { !removed.contains($0.workspaceId) }
            .sorted { ($0.message.createdAt, $0.id) > ($1.message.createdAt, $1.id) }
        var start = 0
        if let after {
            guard let i = all.firstIndex(where: { $0.id == after }) else { throw Self.invalid("after is not in this view") }
            start = i + 1
        }
        let n = min(max(limit ?? 50, 1), 100)
        let page = Array(all.dropFirst(start).prefix(n))
        return ListResponse(items: page, next: start + n < all.count ? page.last?.id : nil)
    }
    func updates() async throws -> [TicketUpdate] {
        try await check()
        if empty { return [] }
        var newest: [String: TicketUpdate] = [:]
        for u in updateLog where (newest["\(u.workspace)|\(u.ticket)"]?.at ?? "") <= u.at { newest["\(u.workspace)|\(u.ticket)"] = u }
        return newest.values.sorted { $0.at > $1.at }
    }
    func answer(_ r: AnswerRequest) async throws -> SendReceipt {
        try await check()
        if let id = clientIds[r.clientId] { return SendReceipt(id: id, clientId: r.clientId, duplicate: true) }
        guard all.contains(where: { $0.id == r.questionMessageId }) else { throw RelayError.api(status: 404, code: "not_found", message: "Question not found.") }
        // Simulator evidence hook `-mockRace YES`: another phone answered "DATE" a moment before this one.
        if UserDefaults.standard.bool(forKey: "mockRace"), answered[r.questionMessageId] == nil { answered[r.questionMessageId] = "DATE" }
        if let a = answered[r.questionMessageId] {
            throw RelayError.api(status: 409, code: "already_answered", message: "This question was already answered: \(a).")
        }
        answered[r.questionMessageId] = r.answer
        counter += 1
        let id = String(format: "m_an5wer%010d", counter)
        clientIds[r.clientId] = id
        return SendReceipt(id: id, clientId: r.clientId)
    }
    func send(_ r: SendRequest) async throws -> SendReceipt {
        try await check()
        if let id = clientIds[r.clientId] { return SendReceipt(id: id, clientId: r.clientId, duplicate: true) }
        if !sendFailures.isEmpty { let s = sendFailures.removeFirst(); throw RelayError.api(status: s, code: "error", message: "Try again later.") }
        do { try r.validate() } catch { throw Self.invalid("Nothing valid to send.") }
        guard reachable(r.to) else { throw RelayError.api(status: 403, code: "not_allowed", message: "This phone may not reach that workspace.") }
        var blobs = r.attachments?.map(\.blobId) ?? []
        if let v = r.voice { blobs.append(v.blobId) }
        blobs += r.feedback?.pins.compactMap(\.voiceBlobId) ?? []
        for b in blobs where uploads[b] == nil { throw RelayError.api(status: 404, code: "not_found", message: "Upload not found.") }
        for a in r.attachments ?? [] where uploads[a.blobId]?.count != a.size { throw Self.invalid("Size does not match the upload.") }
        requests.append(r)
        let to = r.to
        sent.append((to, r.text ?? ""))
        counter += 1
        let id = String(format: "m_ph0nesend%06d", counter)
        clientIds[r.clientId] = id
        let at = Self.now()
        let isNewTopic = r.ticket == nil && r.general != true
        let newTicket = String(format: "t_ph%06d", counter)
        let body = TextBody(text: r.text ?? "", clientId: r.clientId, general: r.general, attachments: r.attachments ?? [], voice: r.voice, location: r.location, feedback: r.feedback)
        sentMessages.append(PhoneMessage(message: TextMessage(id: id, from: "ph_iphone0001", to: to, type: "text", createdAt: at, ticket: r.ticket, body: body, replyTo: r.replyTo),
                                         workspaceName: names[to] ?? to, deliveredAt: nil, clientId: r.clientId))
        guard autoDeliver else { return SendReceipt(id: id, clientId: r.clientId) }
        deliver(id: id)
        // The relay add-on's "Got it": a new ticket for a new topic, the same ticket for a reply, a General receipt in General.
        let label = String((r.text ?? (r.voice?.transcript ?? "Message")).prefix(40)).trimmingCharacters(in: .whitespaces)
        // Test hook: a General text that begins with "Start " makes the workspace open a topic (the ack names the ticket; mockup "PIL-15 started").
        let startsTopic = r.general == true && (r.text ?? "").hasPrefix("Start ")
        if r.general == true {
            generalReceipts.append(PhoneMessage(message: TextMessage(id: String(format: "m_gen4ck%010d", counter), from: to, to: "ph_iphone0001", type: "text", createdAt: at,
                                                                     ticket: startsTopic ? newTicket : nil,
                                                                     body: TextBody(text: "Got it", update: TextUpdate(kind: "ack"), general: true),
                                                                     key: startsTopic ? "\(to == Self.pilatus ? "PIL" : "RGS")-\(20 + counter)" : nil, replyTo: id),
                                                workspaceName: names[to] ?? to))
        } else {
            let prior = updateLog.last { $0.ticket == r.ticket && $0.workspace == to }   // the feed's snapshot and key stay with the ticket
            let newKey = "\(to == Self.pilatus ? "PIL" : "RGS")-\(20 + counter)"
            deliverUpdate(workspace: to, ticket: r.ticket ?? newTicket, kind: "ack", title: label, text: "Got it: \(label)", replyTo: id,
                          key: isNewTopic ? newKey : prior?.key,
                          view: isNewTopic ? TicketSnapshot(title: label, status: "active", agent: "Claude", running: true) : prior?.ticketView)
        }
        return SendReceipt(id: id, clientId: r.clientId)
    }
    private func deliver(id: String) {
        guard let i = sentMessages.firstIndex(where: { $0.id == id }) else { return }
        sentMessages[i].deliveredAt = Self.now()
    }
    /// Test hook: the workspace acks every waiting phone text (second tick).
    func deliverPending() { for m in sentMessages where m.deliveredAt == nil { deliver(id: m.id) } }
    /// Test hook: the workspace says it started on a phone text (`working`, reply_to = that text).
    func deliverWorking(workspace: String, ticket: String, replyTo: String) {
        deliverUpdate(workspace: workspace, ticket: ticket, kind: "working", title: nil, text: "Working on it", replyTo: replyTo)
    }
    func uploadBlob(file: URL, contentType: String) async throws -> BlobUpload {
        try await check()
        uploadCalls += 1
        if !uploadFailures.isEmpty { let s = uploadFailures.removeFirst(); throw RelayError.api(status: s, code: "error", message: "Try again later.") }
        let d = try Data(contentsOf: file)
        guard !d.isEmpty else { throw Self.invalid("Empty upload.") }
        guard d.count <= 25 * 1024 * 1024 else { throw RelayError.api(status: 413, code: "too_large", message: "File too large.") }
        counter += 1
        let id = String(format: "b_up%014d", counter)
        uploads[id] = d
        return BlobUpload(blobId: id, size: d.count, sha256: SHA256.hash(data: d).map { String(format: "%02x", $0) }.joined())
    }
    func speech(messageId: String, lang: String?) async throws -> Data {
        try await check()
        speechRequests.append((messageId, lang))
        if let l = lang, !["de", "en"].contains(l) { throw Self.invalid("lang") }
        switch speechMode {
        case .capReached: throw RelayError.api(status: 402, code: "tts_cap_reached", message: "Read-aloud budget used up.")
        case .off: throw RelayError.api(status: 503, code: "tts_off", message: "Read-aloud is off.")
        case .failed: throw RelayError.api(status: 502, code: "tts_failed", message: "Read-aloud failed.")
        case .ok: break
        }
        guard let m = (updateLog.map(\.id) + received.map(\.id)).first(where: { $0 == messageId }) else { throw RelayError.api(status: 404, code: "not_found", message: "Nothing to read aloud.") }
        return Data("ID3-mock-mp3-\(m)-\(lang ?? "en")".utf8)
    }
    func settings() async throws -> PhoneSettings {
        try await check()
        phoneSettings.groupMutes = phoneSettings.groupMutes?.filter { MuteRules.isMuted($0.mutedUntil) }
        return phoneSettings
    }
    func muteAll(_ mute: Mute) async throws -> PhoneSettings {
        try await check()
        phoneSettings.muteAllUntil = mute.wire
        return try await settings()
    }
    func setGroupMute(_ key: GroupKey, mute: Mute) async throws -> GroupMute {
        try await check()
        guard reachable(key.host) else { throw RelayError.api(status: 404, code: "not_found", message: "Workspace not found.") }
        let result = GroupMute(host: key.host, id: key.id, mutedUntil: mute.wire)
        var active = (phoneSettings.groupMutes ?? []).filter { $0.key != key && MuteRules.isMuted($0.mutedUntil) }
        if MuteRules.isMuted(result.mutedUntil) {
            guard active.count < 100 else { throw Self.invalid("group mutes") }
            active.append(result)
        }
        phoneSettings.groupMutes = active
        return result
    }
    func updateSettings(_ p: SettingsPatch) async throws -> PhoneSettings {
        try await check()
        guard p.isValid else { throw Self.invalid("settings") }
        if let v = p.speak { phoneSettings.speak = v }
        if let v = p.swissGerman { phoneSettings.swissGerman = v }
        if let v = p.ttsCapUsd { phoneSettings.ttsCapUsd = v }
        return phoneSettings
    }
    func redeem(code: String) async throws -> RedeemResponse {
        try await check()
        guard code.hasPrefix("pc_") else { throw RelayError.api(status: 404, code: "not_found", message: "Invitation not found.") }
        if usedCodes.contains(code) || code.hasPrefix("pc_expired") { throw RelayError.api(status: 410, code: "gone", message: "This invitation was already used or has expired.") }
        usedCodes.insert(code)
        names["ws_home000001"] = "Home"; removed.remove("ws_home000001")
        return RedeemResponse(workspaces: [WorkspaceRef(id: "ws_home000001", name: "Home")])
    }
    func setMute(workspace: String, mute: Mute) async throws -> Workspace {
        try await check()
        guard reachable(workspace) else { throw RelayError.api(status: 404, code: "not_found", message: "Workspace not found.") }
        mutes[workspace] = .some(mute.wire)
        guard let w = try await workspaces().first(where: { $0.id == workspace }) else { throw RelayError.api(status: 404, code: "not_found", message: "Workspace not found.") }
        return w
    }
    func turnOffMobileMode(workspace: String) async throws {}
    func removeWorkspace(_ id: String) async throws {
        try await check()
        guard reachable(id) else { throw RelayError.api(status: 404, code: "not_found", message: "Workspace not found.") }
        removed.insert(id)
    }
    /// Fixed transcript, whatever the audio is.
    static let transcript = "Send the weekly report on Friday."
    func transcribe(audio: Data, language: String?) async throws -> Transcript {
        try await check()
        return Transcript(text: Self.transcript, language: language ?? "en", duration: 3.2)
    }
    func signOut() async throws { try await check(); signedOut = true }
    /// A small bar chart for the fake `b_chart` blob; anything else is not found.
    func blob(id: String) async throws -> Data {
        try await check()
        guard id == "b_chart" || (UserDefaults.standard.bool(forKey: "mockGroups") && id == "b_0123456789abcdef") else { throw RelayError.api(status: 404, code: "not_found", message: "Image not found.") }
        let r = UIGraphicsImageRenderer(size: CGSize(width: 240, height: 140))
        return r.pngData { c in
            UIColor(red: 0.08, green: 0.09, blue: 0.11, alpha: 1).setFill(); c.fill(CGRect(x: 0, y: 0, width: 240, height: 140))
            for (i, h) in [40.0, 60, 52, 95].enumerated() {
                (i == 3 ? UIColor(red: 0.18, green: 0.78, blue: 0.64, alpha: 1) : UIColor(red: 0.12, green: 0.3, blue: 0.27, alpha: 1)).setFill()
                c.fill(CGRect(x: 20 + CGFloat(i) * 55, y: 120 - h, width: 40, height: h))
            }
        }
    }
}
