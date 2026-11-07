import XCTest
@testable import OrchMobile

final class TicketTests: XCTestCase {
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
        XCTAssertEqual(TicketBuilder.build(updates: [], questions: [q], answers: [:])[0].stateLine, "Waiting for your answer")
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
        XCTAssertEqual(q.message.body.options.map(q.label), ["Allow once", "Always", "Ignore"])
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
