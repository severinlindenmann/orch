import XCTest
@testable import OrchMobile

@MainActor
final class ChatTests: XCTestCase {
    private func data(_ m: MockRelay, answers: [String: String] = [:], outbox: [QueuedText] = []) async throws -> ChatData {
        let u = try await m.updates(), q = try await m.questions()
        return ChatData(workspaces: try await m.workspaces(), messages: try await m.messages(),
                        tickets: TicketBuilder.build(updates: u, questions: q, answers: answers), questions: q, answers: answers, outbox: outbox)
    }

    func testSnapshotDecodesWithAndWithoutTheNewFields() throws {
        let old = #"{"id":"m_1","workspace":"ws_a","workspace_name":"A","ticket":"t_1","kind":"working","title":"T","text":"x","reply_to":null,"at":"2026-11-05T10:00:00Z"}"#
        let u0 = try JSONCoding.decoder.decode(TicketUpdate.self, from: Data(old.utf8))
        XCTAssertNil(u0.key); XCTAssertNil(u0.ticketView)
        let new = #"{"id":"m_1","workspace":"ws_a","workspace_name":"A","ticket":"t_1","key":"PIL-12","kind":"working","title":"T","text":"x","reply_to":null,"at":"2026-11-05T10:00:00Z","ticket_view":{"title":"T","running":true,"checklist":[{"text":"a","done":true},{"text":"b"}],"attachments":[{"kind":"image","title":"p.png","blob_id":"b_1"}],"history_tail":[{"by":"agent","text":"hi"}],"extra":1}}"#
        let u1 = try JSONCoding.decoder.decode(TicketUpdate.self, from: Data(new.utf8))
        XCTAssertEqual(u1.key, "PIL-12")
        XCTAssertEqual(u1.ticketView?.running, true)
        XCTAssertEqual(u1.ticketView?.doneCount, 1)       // no explicit "done": counted from the checklist
        XCTAssertEqual(u1.ticketView?.checklist.map(\.done), [true, false])
        XCTAssertEqual(u1.ticketView?.attachments.first?.blobId, "b_1")
        XCTAssertEqual(u1.ticketView?.historyTail.first?.text, "hi")
    }

    func testWorkspaceChatGroupsMyTextsSystemLinesCardsAndQuestions() async throws {
        let d = try await data(MockRelay(latency: .zero))
        let items = ChatBuilder.workspaceItems(MockRelay.pilatus, d)
        XCTAssertEqual(items.map(\.at), items.map(\.at).sorted(), "oldest first")
        XCTAssertTrue(items.contains { if case .mine(let t, false) = $0.kind { return t.hasPrefix("Can you make the Q3") }; return false })
        XCTAssertTrue(items.contains { if case .theirs(let t, _) = $0.kind { return t.hasPrefix("Yes, I can answer") }; return false })
        XCTAssertTrue(items.contains { if case .card(let t) = $0.kind { return t.key == "PIL-12" }; return false })
        XCTAssertTrue(items.contains { if case .question = $0.kind { return true }; return false })
        XCTAssertFalse(items.contains { if case .question(let q) = $0.kind { return q.message.from != MockRelay.pilatus }; return false }, "no other workspace's question")
    }

    func testTicketChatHasHistoryResultAttachmentsAndMyReplies() async throws {
        var d = try await data(MockRelay(latency: .zero))
        d.outbox = [QueuedText(id: "o1", workspace: MockRelay.pilatus, ticket: "t_q3sum1", text: "Please add September", at: "2026-11-06T09:00:00Z")]
        let items = ChatBuilder.ticketItems(MockRelay.pilatus, "t_q3sum1", d)
        let texts = items.compactMap { i -> String? in if case .theirs(let t, _) = i.kind { return t }; return nil }
        XCTAssertTrue(texts.contains("Pulled the numbers from the Q3 sheet."))
        XCTAssertTrue(items.contains { if case .theirs(_, "RESULT") = $0.kind { return true }; return false })
        XCTAssertEqual(items.filter { if case .attachment = $0.kind { return true }; return false }.count, 3)
        XCTAssertEqual(items.last.map { if case .mine(let t, true) = $0.kind { return t }; return "" }, "Please add September", "queued text stays last and marked")
    }

    func testHistoryTailIsLimitedToThirtyLines() {
        let lines = (0..<45).map { TicketSnapshot.Line(at: String(format: "2026-11-05T10:%02d:00Z", $0 % 60), by: "agent", text: "line \($0)") }
        let t = Ticket(id: "ws|t", workspace: "ws", workspaceName: "W", ticket: "t", title: "T", text: "x", status: .working, kind: "working", at: "2026-11-05T11:00:00Z",
                       question: nil, key: "W-1", view: TicketSnapshot(historyTail: lines))
        let items = ChatBuilder.ticketItems("ws", "t", ChatData(tickets: [t]))
        XCTAssertEqual(items.filter { if case .theirs = $0.kind { return true }; return false }.count, 30)
    }

    func testUnreadCountsIncomingOnlyAndMarkRead() async throws {
        let d = try await data(MockRelay(latency: .zero))
        var read = ReadState()
        let before = ChatBuilder.rooms(d, read: read).first { $0.workspace.id == MockRelay.pilatus }!
        XCTAssertGreaterThan(before.unread, 0)
        let items = ChatBuilder.workspaceItems(MockRelay.pilatus, d)
        XCTAssertEqual(before.unread, items.filter(\.incoming).count)
        read.markRead(ReadState.workspaceKey(MockRelay.pilatus), upTo: items.filter(\.incoming).map(\.at).max()!)
        XCTAssertEqual(ChatBuilder.rooms(d, read: read).first { $0.workspace.id == MockRelay.pilatus }!.unread, 0)
        XCTAssertGreaterThan(ChatBuilder.rooms(d, read: read).first { $0.workspace.id == MockRelay.reports }!.unread, 0, "other chats stay unread")
    }

    func testSearchFindsByKeyTitleAndMessageText() async throws {
        let d = try await data(MockRelay(latency: .zero))
        let rooms = ChatBuilder.rooms(d, read: ReadState())
        XCTAssertEqual(ChatBuilder.search("pil-12", d, rows: rooms).chats.map { $0.ticket.key }, ["PIL-12"], "typing the key finds the ticket")
        XCTAssertEqual(ChatBuilder.search("INVOICE", d, rows: rooms).chats.map { $0.ticket.key }, ["RGS-4"])
        XCTAssertTrue(ChatBuilder.search("board", d, rows: rooms).messages.contains { $0.who == "You" })
        XCTAssertEqual(ChatBuilder.search("Pilatus", d, rows: rooms).rooms.count, 1)
        XCTAssertTrue(ChatBuilder.search("zzzz", d, rows: rooms).isEmpty)
        XCTAssertTrue(ChatBuilder.search("   ", d, rows: rooms).isEmpty)
    }

    func testFiltersAndOrderPutNeedsYouFirst() async throws {
        let d = try await data(MockRelay(latency: .zero))
        let rooms = ChatBuilder.rooms(d, read: ReadState())
        XCTAssertEqual(rooms.count, 2)
        XCTAssertTrue(rooms.allSatisfy { $0.openQuestions == 1 })
        XCTAssertEqual(ChatBuilder.filtered(rooms, .needsYou).count, 2)
        var answered = d; answered.answers = Dictionary(uniqueKeysWithValues: d.questions.map { ($0.id, "x") })
        let calm = ChatBuilder.rooms(answered, read: ReadState())
        XCTAssertTrue(ChatBuilder.filtered(calm, .needsYou).allSatisfy { $0.tickets.allSatisfy { $0.ticket.status == .needsYou } })
        XCTAssertEqual(ChatBuilder.filtered(rooms, .tickets).flatMap(\.tickets).count, rooms.flatMap(\.tickets).count)
    }

    func testComposerWording() {
        XCTAssertEqual(ChatBuilder.composerNote(running: true), "Goes in after this step")
        XCTAssertEqual(ChatBuilder.composerNote(running: false), "Saved for the next run")
        XCTAssertEqual(ChatBuilder.composerNote(running: nil), "Saved for the next run")
    }

    func testUndoCancelsTheSendAndLaterSends() async throws {
        let model = AppModel(useMock: true)
        model.undoDelay = .milliseconds(150)
        let q = try await MockRelay(latency: .zero).questions().first!
        model.chooseAnswer(q, "DATE")
        XCTAssertEqual(model.pendingAnswers[q.id], "DATE")
        model.undoAnswer(q)
        XCTAssertNil(model.pendingAnswers[q.id])
        try await Task.sleep(for: .milliseconds(400))
        XCTAssertNil(model.answers[q.id], "undone: nothing sent")
        model.chooseAnswer(q, "TIMESTAMP")
        try await Task.sleep(for: .milliseconds(900))
        XCTAssertEqual(model.answers[q.id], "TIMESTAMP")
        XCTAssertNil(model.pendingAnswers[q.id])
    }

    func testOfflineSendIsQueuedAndKept() async throws {
        UserDefaults.standard.removeObject(forKey: "chatOutbox")
        UserDefaults.standard.set(true, forKey: "mockFail"); defer { UserDefaults.standard.removeObject(forKey: "mockFail"); UserDefaults.standard.removeObject(forKey: "chatOutbox") }
        let model = AppModel(useMock: true)
        let r = await model.sendChat(to: MockRelay.pilatus, text: "  Please add the September totals  ", ticket: "t_q3sum1")
        XCTAssertEqual(r, .queued)
        XCTAssertEqual(model.outbox.map(\.text), ["Please add the September totals"])
        XCTAssertEqual(AppModel(useMock: true).outbox.count, 1, "survives a restart")
    }

    func testTimeText() {
        let now = ISO8601DateFormatter().date(from: "2026-11-06T12:00:00Z")!
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "UTC")!
        XCTAssertEqual(ChatBuilder.timeText("2026-11-05T11:20:00Z", now: now, calendar: cal), "Yesterday")
        XCTAssertEqual(ChatBuilder.timeText("2026-11-01T11:20:00Z", now: now, calendar: cal).isEmpty, false)
    }
}

