import XCTest
@testable import OrchMobile

final class TicketTests: XCTestCase {
    private func lightViewUpdate(_ id: String, view: TicketSnapshot?, text: String = "") -> TicketUpdate {
        TicketUpdate(id: id, workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: "note", title: nil,
                     text: text, replyTo: nil, at: "2026-11-08T10:00:00Z", ticketView: view)
    }

    func testLightViewPreservesFullDetails() throws {
        let full = TicketSnapshot(title: "Fix login", status: "active", agent: "Agent", summary: "A",
                                  checklist: [.init(text: "First", done: true), .init(text: "Second")],
                                  running: true, started: true, attachments: [.init(blobId: "b1", name: "proof.txt")],
                                  historyTail: [.init(text: "Started")], refs: [.init(rawKind: "ticket", ticket: "t_2")])
        let light = TicketSnapshot(status: "waiting", summary: "B", light: true)
        let ticket = try XCTUnwrap(TicketBuilder.build(updates: [lightViewUpdate("1", view: full), lightViewUpdate("2", view: light)],
                                                     questions: [], answers: [:]).first)
        let view = try XCTUnwrap(ticket.view)
        XCTAssertEqual(view.status, "waiting")
        XCTAssertEqual(view.summary, "B")
        XCTAssertEqual(view.checklist.count, 2)
        XCTAssertEqual(view.attachments.count, 1)
        XCTAssertEqual(view.checklist, full.checklist)
        XCTAssertEqual(view.attachments, full.attachments)
        XCTAssertEqual(view.refs, full.refs)
        XCTAssertEqual(view.historyTail, full.historyTail)
        XCTAssertEqual(view.done, full.done)
        XCTAssertEqual(view.total, full.total)
        XCTAssertEqual(view.agent, full.agent)
        XCTAssertEqual(view.running, true)
        XCTAssertEqual(view.started, true)
        XCTAssertNil(view.light)
        XCTAssertEqual(ticket.status, Ticket.Status(ticketStatus: "waiting"))
    }

    func testDashboardTicketWithOnlyLightViews() throws {
        let initial = lightViewUpdate("1", view: TicketSnapshot(title: "Fix login", status: "ready", started: false, light: true))
        let first = try XCTUnwrap(TicketBuilder.build(updates: [initial], questions: [], answers: [:]).first)
        XCTAssertEqual(first.status, .backlog)
        XCTAssertEqual(first.displayTitle, "Fix login")
        let started = lightViewUpdate("2", view: TicketSnapshot(status: "ready", started: true, light: true))
        let second = try XCTUnwrap(TicketBuilder.build(updates: [initial, started], questions: [], answers: [:]).first)
        XCTAssertEqual(second.status, .paused)
        XCTAssertEqual(second.displayTitle, "Fix login")
    }

    func testEmptyLightUpdateKeepsPreviousText() throws {
        let first = lightViewUpdate("1", view: TicketSnapshot(title: "Fix login"), text: "Investigating the login failure")
        let next = lightViewUpdate("2", view: TicketSnapshot(status: "waiting", light: true))
        let ticket = try XCTUnwrap(TicketBuilder.build(updates: [first, next], questions: [], answers: [:]).first)
        XCTAssertEqual(ticket.text, first.text)
    }

    func testNonLightViewReplacesWholeSnapshot() throws {
        let old = TicketSnapshot(title: "Old", summary: "A", checklist: [.init(text: "First"), .init(text: "Second")])
        for light: Bool? in [nil, false] {
            let new = TicketSnapshot(title: "New", checklist: [.init(text: "Replacement")], light: light)
            let ticket = try XCTUnwrap(TicketBuilder.build(updates: [lightViewUpdate("1", view: old), lightViewUpdate("2", view: new)],
                                                         questions: [], answers: [:]).first)
            XCTAssertEqual(ticket.view, new)
            XCTAssertEqual(ticket.view?.checklist, new.checklist)
        }
    }

    func testUpdateWithoutViewKeepsPreviousSnapshot() throws {
        let view = TicketSnapshot(title: "Fix login", status: "ready", started: true)
        let ticket = try XCTUnwrap(TicketBuilder.build(updates: [lightViewUpdate("1", view: view), lightViewUpdate("2", view: nil, text: "Latest note")],
                                                     questions: [], answers: [:]).first)
        XCTAssertEqual(ticket.view, view)
        XCTAssertEqual(ticket.status, .working)
        XCTAssertEqual(ticket.text, "Latest note")
    }

    func testFailureWithoutViewUsesUpdateKind() throws {
        let view = TicketSnapshot(title: "Fix login", status: "active", running: true)
        let failure = TicketUpdate(id: "2", workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: "failure",
                                   title: nil, text: "Failed", replyTo: nil, at: "2026-11-08T10:01:00Z")
        let ticket = try XCTUnwrap(TicketBuilder.build(updates: [lightViewUpdate("1", view: view), failure],
                                                     questions: [], answers: [:]).first)
        XCTAssertEqual(ticket.status, .done)
        XCTAssertEqual(ticket.kind, "failure")
        XCTAssertEqual(ticket.view, view)
        XCTAssertEqual(ticket.title, view.title)
    }

    func testEmptyLightViewFieldsKeepBase() {
        let base = TicketSnapshot(title: "Fix login", status: "active", agent: "Agent", summary: "Investigating")
        for empty in ["", " \t\n"] {
            let light = TicketSnapshot(title: empty, status: empty, agent: empty, summary: empty, light: true)
            XCTAssertEqual(light.overlaid(on: base), base)
        }
    }

    func testLightViewDecodes() throws {
        let view = try JSONCoding.decoder.decode(TicketSnapshot.self, from: Data(#"{"title":"x","light":true}"#.utf8))
        XCTAssertEqual(view.light, true)
    }

    func testUpdatesDecodeFromContractExample() async throws {
        let ex = try Example.find("GET", "/v1/phone/updates")
        StubProtocol.handler = { _ in (ex.status, ex.responseData) }
        let c = URLSessionRelayClient(base: URL(string: "https://relay.severin.io")!,
                                      credentials: Credentials(relay: URL(string: "https://relay.severin.io")!, phoneId: "ph_iphone0001", token: "orn_x", phoneName: "P"),
                                      session: StubProtocol.session())
        let items = try await c.updates()
        XCTAssertEqual(items.map(\.kind), ["result", "working"])
        XCTAssertEqual(items[0].ticket, "t_q3sum1"); XCTAssertEqual(items[0].workspaceName, "Pilatus Workspace")
        XCTAssertEqual(StubProtocol.seen.last?.url?.path, "/v1/phone/updates")
    }

    func testGroupsAndOrder() async throws {
        let m = MockRelay(latency: .zero)
        let t = TicketBuilder.build(updates: try await m.updates(), questions: try await m.questions(), answers: [:])
        XCTAssertEqual(t.filter { $0.status == .needsYou }.count, 2)
        XCTAssertEqual(t.filter { $0.status == .working }.map(\.title), ["Invoice CSV export"])
        XCTAssertEqual(t.filter { $0.status == .done }.map(\.title), ["Q3 summary for the board"])
        XCTAssertEqual(t.map(\.status), t.map(\.status).sorted(), "Needs you first, Done last")
    }

    func testOpenQuestionWinsOverTheLastUpdateAndAnsweredGoesBack() {
        let q = MockRelayTestsFixtures.question
        let u = TicketUpdate(id: "m_u1", workspace: q.message.from, workspaceName: "W", ticket: q.message.ticket!, kind: "working", title: "Rename", text: "Working", replyTo: nil, at: "2026-11-05T10:00:00Z")
        XCTAssertEqual(TicketBuilder.build(updates: [u], questions: [q], answers: [:]).map(\.status), [.needsYou])
        XCTAssertEqual(TicketBuilder.build(updates: [u], questions: [q], answers: [q.id: "DATE"]).map(\.status), [.working])
        // an update of kind question without an open question is not "Needs you"
        let qu = TicketUpdate(id: "m_u2", workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: "question", title: nil, text: "Which?", replyTo: nil, at: "2026-11-05T10:00:00Z")
        XCTAssertEqual(TicketBuilder.build(updates: [qu], questions: [], answers: [:]).map(\.status), [.working])
    }

    func testQuietSyncNotesMakeEveryTicketAChatAndKeepTheirStatus() {
        func u(_ id: String, _ t: String, _ st: String) -> TicketUpdate {
            TicketUpdate(id: id, workspace: "ws_a", workspaceName: "A", ticket: t, kind: "note", title: t, text: "Tasks: 0 of 1 done", replyTo: nil,
                         at: "2026-11-06T10:00:0\(id.count)Z", ticketView: TicketSnapshot(title: "Ticket " + t, status: st))
        }
        let t = TicketBuilder.build(updates: [u("a", "t_1", "open"), u("bb", "t_2", "active"), u("ccc", "t_3", "done")], questions: [], answers: [:])
        XCTAssertEqual(Set(t.compactMap(\.ticket)), ["t_1", "t_2", "t_3"])
        XCTAssertEqual(t.first { $0.ticket == "t_3" }?.status, .done)
        XCTAssertEqual(t.first { $0.ticket == "t_1" }?.status, .backlog)
        XCTAssertEqual(t.first { $0.ticket == "t_2" }?.status, .working)
        // each one is a sub-chat under its workspace
        let d = ChatData(workspaces: [Workspace(id: "ws_a", name: "A", description: nil, tags: [], online: true, lastSeen: nil, openQuestions: 0)], messages: [], tickets: t, questions: [], answers: [:], outbox: [])
        XCTAssertEqual(ChatBuilder.rooms(d, read: ReadState()).first?.tickets.count, 3)
    }

    func testActiveWithoutARunningAgentIsNotWorking() {
        func u(_ running: Bool?) -> TicketUpdate {
            TicketUpdate(id: "m_n", workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: "note", title: "T", text: "Tasks: 0 of 2 done",
                         replyTo: nil, at: "2026-11-08T08:00:00Z", ticketView: TicketSnapshot(title: "T", status: "active", running: running))
        }
        XCTAssertEqual(TicketBuilder.build(updates: [u(false)], questions: [], answers: [:]).map(\.status), [.backlog])
        XCTAssertEqual(TicketBuilder.build(updates: [u(true)], questions: [], answers: [:]).map(\.status), [.working])
        XCTAssertEqual(TicketBuilder.build(updates: [u(nil)], questions: [], answers: [:]).map(\.status), [.working], "older snapshots without running")
        XCTAssertNotEqual(TopicStatus(TicketBuilder.build(updates: [u(false)], questions: [], answers: [:])[0]), .working)
    }

    func testStartedIdleTicketIsPaused() {
        func t(_ status: String, _ running: Bool?, _ started: Bool?) -> Ticket {
            let u = TicketUpdate(id: "m_n", workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: "note", title: "T", text: "x",
                                 replyTo: nil, at: "2026-11-08T08:00:00Z", ticketView: TicketSnapshot(title: "T", status: status, running: running, started: started))
            return TicketBuilder.build(updates: [u], questions: [], answers: [:])[0]
        }
        for status in ["ready", "open", "active"] {
            let paused = t(status, false, true)
            XCTAssertEqual(paused.status, .paused, status); XCTAssertEqual(paused.status.title, "Paused")
            XCTAssertEqual(paused.stateLine, "Paused"); XCTAssertEqual(paused.symbol, "pause.circle")
            XCTAssertEqual(TopicStatus(paused), .paused); XCTAssertEqual(TopicStatus(paused).label, "Paused")
            XCTAssertEqual(TopicStatus(paused).chip, "Paused")
            for started: Bool? in [false, nil] {
                let backlog = t(status, false, started)
                XCTAssertEqual(backlog.status, .backlog, status); XCTAssertEqual(backlog.stateLine, "Not started")
                XCTAssertEqual(TopicStatus(backlog).chip, "Not started")
            }
        }
        for running: Bool? in [true, nil] {
            XCTAssertEqual(t("ready", running, true).status, .paused)
            XCTAssertEqual(t("open", running, true).status, .paused)
            XCTAssertEqual(t("ready", running, nil).status, .backlog)
            XCTAssertEqual(t("open", running, nil).status, .backlog)
            XCTAssertEqual(t("active", running, true).status, .working)
        }
        XCTAssertLessThan(Ticket.Status.working, .paused); XCTAssertLessThan(Ticket.Status.paused, .backlog)
    }

    /// #287: "ready" = an agent stopped or nobody started one; never Working, whatever the update kind says.
    func testReadyWithoutARunIsNotStarted() {
        for kind in ["note", "ack", "working"] {
            let u = TicketUpdate(id: "m_n", workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: kind, title: "T", text: "x",
                                 replyTo: nil, at: "2026-11-08T08:00:00Z", ticketView: TicketSnapshot(title: "T", status: "ready", running: false))
            let t = TicketBuilder.build(updates: [u], questions: [], answers: [:])[0]
            XCTAssertEqual(t.status, .backlog, kind); XCTAssertEqual(t.stateLine, "Not started")
            XCTAssertEqual(TopicStatus(t).chip, "Not started"); XCTAssertNotEqual(TopicStatus(t), .working)
        }
    }

    /// #287: the workspace pushes a `result` when a followed ticket moves to Review or Done (phone tickets, Mobile mode).
    func testPushedResultOnReviewOrDoneMovesTheTopic() {
        func u(_ id: String, _ kind: String, _ status: String, _ running: Bool, _ at: String) -> TicketUpdate {
            TicketUpdate(id: id, workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: kind, title: "Pizza page", text: "x",
                         replyTo: nil, at: at, ticketView: TicketSnapshot(title: "Pizza page", status: status, running: running))
        }
        let working = u("m_1", "note", "active", true, "2026-11-08T08:00:00Z")
        let review = TicketBuilder.build(updates: [working, u("m_2", "result", "review", false, "2026-11-08T08:10:00Z")], questions: [], answers: [:])[0]
        XCTAssertEqual(review.status, .review); XCTAssertEqual(TopicStatus(review).chip, "Ready for review"); XCTAssertEqual(review.stateLine, "Ready for review")
        let done = TicketBuilder.build(updates: [working, u("m_3", "result", "done", false, "2026-11-08T08:20:00Z")], questions: [], answers: [:])[0]
        XCTAssertEqual(done.status, .done); XCTAssertEqual(TopicStatus(done).label, "Done")
    }

    func testFailureAndStoppedAreDoneWithOwnSign() {
        func t(_ k: String) -> Ticket {
            TicketBuilder.build(updates: [TicketUpdate(id: "m", workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: k, title: "X", text: "x", replyTo: nil, at: "2026-11-05T10:00:00Z")],
                                questions: [], answers: [:])[0]
        }
        XCTAssertEqual(t("result").symbol, "checkmark.circle.fill")
        XCTAssertEqual(t("failure").status, .done); XCTAssertEqual(t("failure").symbol, "xmark.circle.fill")
        XCTAssertEqual(t("stopped").status, .done)
    }

    func testStateLine() {
        func t(_ k: String, _ text: String = "Q3 summary is ready in the shared folder today.") -> Ticket {
            TicketBuilder.build(updates: [TicketUpdate(id: "m", workspace: "ws_a", workspaceName: "A", ticket: "t_1", kind: k, title: "X", text: text, replyTo: nil, at: "2026-11-05T10:00:00Z")], questions: [], answers: [:])[0]
        }
        XCTAssertEqual(t("working").stateLine, "Working on it")
        XCTAssertEqual(t("result").stateLine, "Done — Q3 summary is ready in the")
        XCTAssertEqual(t("stopped").stateLine, "Stopped")
        XCTAssertTrue(t("failure", "No access").stateLine.hasPrefix("Did not work"))
        let q = MockRelayTestsFixtures.question
        XCTAssertEqual(TicketBuilder.build(updates: [], questions: [q], answers: [:])[0].stateLine, "Needs you")
    }

    func testTextBodyReadsUpdateKind() throws {
        let json = #"{"id":"m_1","from":"ws_a","to":"ph_1","type":"text","created_at":"2026-11-05T10:00:00Z","ticket":"t_1","body":{"text":"Got it: x","update":{"kind":"ack","title":"x"}}}"#
        let m = try JSONCoding.decoder.decode(TextMessage.self, from: Data(json.utf8))
        XCTAssertEqual(m.body.update?.kind, "ack")
        let plain = try JSONCoding.decoder.decode(TextMessage.self, from: Data(#"{"id":"m_1","from":"ws_a","to":"ph_1","type":"text","created_at":"x","body":{"text":"hi"}}"#.utf8))
        XCTAssertNil(plain.body.update)
    }

    func testAllowQuestionLabelsAndAnswer() async throws {
        let q = MockRelay.allowQuestion
        XCTAssertTrue(q.isAllow)
        XCTAssertEqual(q.message.body.options.map(q.label), ["Allow once", "Always", "No"], "contract chat-groups §3.2: No replaces Ignore on screen")
        XCTAssertFalse(MockRelayTestsFixtures.question.isAllow)
        XCTAssertEqual(MockRelayTestsFixtures.question.label("DATE"), "DATE")
        let m = MockRelay(latency: .zero)
        await m.deliverAllow()
        let qs = try await m.questions(); XCTAssertEqual(qs.count, 3)
        _ = try await m.answer(questionMessageId: q.id, answer: "Once")   // the raw option is what is sent
        let left = try await m.questions(); XCTAssertEqual(left.count, 2)
    }
}

enum MockRelayTestsFixtures {
    static let question = Question(message: QuestionMessage(schema: "orch.msg/1", id: "m_qx", from: "ws_a", to: "phones", type: "question",
                                                            createdAt: "2026-11-05T10:00:00Z", ticket: "t_x",
                                                            body: QuestionBody(questionId: "q1", title: "Rename", text: "DATE or TIMESTAMP?", options: ["DATE", "TIMESTAMP"], recommended: "TIMESTAMP")),
                                   workspaceName: "W")
}

@MainActor
final class TicketModelTests: XCTestCase {
    override func setUp() async throws { Keychain.delete() }
    override func tearDown() async throws { Keychain.delete() }

    private func ready() async -> AppModel {
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openSampleInvite(); await model.connect(phoneName: "Test phone"); await model.finishSetup(allowNotifications: false)
        return model
    }

    private func count(_ model: AppModel, _ st: Ticket.Status) -> Int { model.tickets.filter { $0.status == st }.count }

    func testTicketsGroupFromUpdatesAndQuestions() async {
        let model = await ready()
        XCTAssertEqual(count(model, .needsYou), 2); XCTAssertEqual(count(model, .working), 1); XCTAssertEqual(count(model, .done), 1)
        await model.answer(model.questions[0], with: "TIMESTAMP")
        XCTAssertEqual(count(model, .needsYou), 1)
    }

    func testFreeTextAnswerOutsideOptionsIsRecorded() async throws {
        let model = await ready()
        let q = try XCTUnwrap(model.questions.first { !$0.isAllow && !$0.message.body.options.isEmpty })
        let answer = "Week 46, please"
        XCTAssertFalse(q.message.body.options.contains(answer))
        await model.answer(q, with: answer)
        XCTAssertEqual(model.answers[q.id], answer)
    }

    func testNewTopicGetsAGotItAndReplyKeepsTheTicket() async {
        let model = await ready()
        guard case .sent(let id) = await model.sendChat(to: MockRelay.reports, text: "Prepare the Q3 summary") else { return XCTFail("not sent") }
        let ack = model.ack(for: id)
        XCTAssertEqual(ack?.text, "Got it: Prepare the Q3 summary")
        XCTAssertEqual(count(model, .working), 2, "the new ticket is a chat of its own")
        XCTAssertTrue(model.tickets.contains { $0.ticket == ack?.ticket && $0.workspace == ack?.workspace })
        let t = model.tickets.first { $0.title == "Invoice CSV export" }!
        guard case .sent = await model.sendChat(to: t.workspace, text: "Use semicolons", ticket: t.ticket) else { return XCTFail("not sent") }
        XCTAssertEqual(count(model, .working), 2, "a reply stays on its ticket")
    }

    func testAlreadyAnsweredShowsTheOtherAnswer() async {
        let model = await ready()
        let q = model.questions[0]
        await model.answer(q, with: "DATE")
        // second phone answers the same question: the relay says 409
        await model.answer(q, with: "TIMESTAMP")
        XCTAssertTrue(model.answeredElsewhere.contains(q.id))
        XCTAssertTrue(model.answers[q.id]?.contains("DATE") == true)
    }
}
