import XCTest
@testable import OrchMobile

/// One test per bug-hunt item (A2…C12); the id is in the test name.
@MainActor
final class BugHuntFixTests: XCTestCase {
    // MARK: helpers

    private func result(title: String?, docTitle: String?) throws -> TicketResult {
        var doc: [String: Any] = ["schema": "orch.blocks/1", "from": "agent", "blocks": [["type": "summary", "text": "Result"]]]
        if let docTitle { doc["title"] = docTitle }
        var object: [String: Any] = ["id": "j_first1", "from": "agent", "at": "2026-11-11T09:00:00Z", "doc": doc]
        if let title { object["title"] = title }
        return try JSONCoding.decoder.decode(TicketResult.self, from: JSONSerialization.data(withJSONObject: object))
    }

    private func update(_ id: String, kind: String, view: TicketSnapshot?, workspace: String = "ws", ticket: String = "t",
                        at: String = "2026-11-09T10:00:00Z") -> TicketUpdate {
        TicketUpdate(id: id, workspace: workspace, workspaceName: "Workspace", ticket: ticket, kind: kind, title: "Fish", text: "x",
                     replyTo: nil, at: at, ticketView: view)
    }

    private func reviewQuestion(_ id: String, round: String, at: String = "2026-11-09T10:00:00Z") -> Question {
        Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: "ws", to: "phones", type: "question",
            createdAt: at, ticket: "t", body: QuestionBody(questionId: round, title: "Fish", text: "Is this done?",
                options: ["accept", "changes"], recommended: nil, review: true)), workspaceName: "Workspace")
    }

    private func groupMessage(_ id: String, at: String, sender: GroupSender, clientId: String? = nil) -> GroupMessage {
        let text = TextMessage(id: id, from: "ws_h", to: "ph_1", type: "text", createdAt: at, ticket: "t_1",
                               body: TextBody(text: "hi", clientId: clientId))
        return GroupMessage(id: id, at: at, seq: nil, sender: sender, text: "hi", event: nil, task: nil, sharedFiles: [],
                            ticketView: nil, quiet: false, message: PhoneMessage(message: text, workspaceName: "Host"))
    }

    // MARK: A

    func testA2UnsafeDocTitleIsNotShown() throws {
        let r = try result(title: "Passed\u{202E}x", docTitle: "Passed\u{202E}x")
        XCTAssertNil(r.title)
        guard case .shown(let doc) = r.doc else { return XCTFail("valid document refused") }
        XCTAssertNil(doc.title)
        // A safe title stays.
        guard case .shown(let safe) = try result(title: nil, docTitle: "Passed").doc else { return XCTFail("valid document refused") }
        XCTAssertEqual(safe.title, "Passed")
    }

    func testA3DocIsDecodedOnceAndResultsStayEqual() throws {
        let a = try result(title: "Passed", docTitle: "Passed"), b = try result(title: "Passed", docTitle: "Passed")
        XCTAssertEqual(a, b)
        XCTAssertNotEqual(a, try result(title: "Other", docTitle: "Passed"))
        guard case .shown(let first) = a.doc, case .shown(let second) = a.doc else { return XCTFail("valid document refused") }
        XCTAssertEqual(first.texts, second.texts)
        XCTAssertEqual(first.texts, ["Proof", "Passed", "Result"])
        // Cached formatters still format dates as before.
        XCTAssertEqual(BlocksFormat.cell(.string("2026-11-11T09:00:00Z"), kind: "date"), "2026-11-11 09:00:00 UTC")
        XCTAssertEqual(BlocksFormat.cell(.string("2026-11-11T09:00:00.500Z"), kind: "date"), "2026-11-11 09:00:00 UTC")
    }

    func testA4AxisTicksAreCapped() {
        let values = Array(0..<800)
        let ticks = BlocksView.ticks(values)
        XCTAssertLessThanOrEqual(ticks.count, 6)
        XCTAssertEqual(ticks.first, 0)
        XCTAssertEqual(BlocksView.ticks([1.0, 2.0, 3.0]), [1.0, 2.0, 3.0])
        XCTAssertEqual(BlocksView.ticks(Array(0..<7)).count, 4)
        XCTAssertEqual(BlocksView.ticks([String]()), [])
    }

    // MARK: B

    func testB1ApprovalLabels() {
        XCTAssertEqual(GroupApprovalView.approvalLabel("permanent"), "Always")
        XCTAssertEqual(GroupApprovalView.approvalLabel("always"), "Always")
        XCTAssertNil(GroupApprovalView.approvalLabel("Approve"))
        XCTAssertEqual(GroupApprovalView.approvalLabel("no"), "No")
        XCTAssertEqual(GroupApprovalView.approvalLabel("deny"), "No")
        XCTAssertEqual(GroupApprovalView.approvalLabel("once"), "Allow once")
        XCTAssertEqual(GroupApprovalView.approvalLabel("Allow once"), "Allow once")
    }

    func testB2RowIdsUniqueAndMemberClientIdDoesNotHideOutgoing() {
        let m1 = groupMessage("m1", at: "2026-11-09T10:00:00Z", sender: .member("ws_b"), clientId: "dup")
        let m2 = groupMessage("m2", at: "2026-11-09T10:01:00Z", sender: .member("ws_c"), clientId: "dup")
        let out = ConvItem(id: "c1", at: "2026-11-09T10:02:00Z", side: .me, text: "mine", replyTo: "m1", clientId: "dup")
        let rows = GroupTranscript.rows(messages: [m1, m2], outgoing: [out])
        XCTAssertEqual(Set(rows.map(\.id)).count, rows.count, "row ids are unique")
        XCTAssertEqual(rows.map(\.id), ["m-m1", "m-m2", "dup"])
        // The phone's own echo with that client id does hide it.
        let echo = groupMessage("m3", at: "2026-11-09T10:02:01Z", sender: .you, clientId: "dup")
        XCTAssertFalse(GroupTranscript.rows(messages: [m1, m2, echo], outgoing: [out]).contains { $0.isOutgoing })
    }

    func testB4OutgoingNeverAboveItsReplyTarget() {
        let m1 = groupMessage("m1", at: "2026-11-09T10:01:30Z", sender: .member("ws_b"))
        let m2 = groupMessage("m2", at: "2026-11-09T10:05:00Z", sender: .member("ws_b"))
        let out = ConvItem(id: "c1", at: "2026-11-09T10:00:00Z", side: .me, text: "reply", replyTo: "m1", clientId: "c1")
        XCTAssertEqual(GroupTranscript.rows(messages: [m1], outgoing: [out]).map(\.id), ["m-m1", "c1"])
        XCTAssertEqual(GroupTranscript.rows(messages: [m1, m2], outgoing: [out]).map(\.id), ["m-m1", "c1", "m-m2"])
        // Fractional seconds compare as times, not strings.
        let a = groupMessage("a", at: "2026-11-09T10:00:00.500Z", sender: .member("ws_b"))
        let b = groupMessage("b", at: "2026-11-09T10:00:02Z", sender: .member("ws_b"))
        let late = ConvItem(id: "c2", at: "2026-11-09T10:00:01Z", side: .me, text: "x", replyTo: "a", clientId: "c2")
        XCTAssertEqual(GroupTranscript.rows(messages: [a, b], outgoing: [late]).map(\.id), ["m-a", "c2", "m-b"])
    }

    // MARK: C

    func testC1DoneSnapshotWithNoteKindShowsDone() throws {
        let t = try XCTUnwrap(TicketBuilder.build(updates: [update("1", kind: "note", view: TicketSnapshot(title: "Fish", status: "done"))],
                                                  questions: [], answers: [:]).first)
        XCTAssertEqual(t.status, .done)
        XCTAssertEqual(StatusPill(status: t.status, kind: t.kind).text, "Done")
        XCTAssertEqual(t.symbol, "checkmark.circle.fill")
        XCTAssertEqual(StatusPill(status: .done, kind: "failure").text, "Did not work")
        XCTAssertEqual(StatusPill(status: .done, kind: "stopped").text, "Stopped")
    }

    func testC2UpdateWithoutViewKeepsReview() throws {
        let updates = [update("1", kind: "result", view: TicketSnapshot(title: "Fish", status: "review")),
                       update("2", kind: "note", view: nil, at: "2026-11-09T10:05:00Z")]
        let t = try XCTUnwrap(TicketBuilder.build(updates: updates, questions: [], answers: [:]).first)
        XCTAssertEqual(t.status, .review)
        let q = reviewQuestion("q", round: "review-1")
        XCTAssertEqual(ReviewRules.reviewQuestion(ticket: t, workspaceId: "ws", ticketId: "t", questions: [q], answers: [:]), q)
    }

    func testC5ExactNameWinsOverEarlierSuffixMatch() {
        let attachments = [TicketSnapshot.Attachment(name: "old/index.html", artifactId: "a_aaaaaaaaaaaa"),
                           TicketSnapshot.Attachment(name: "index.html", artifactId: "a_bbbbbbbbbbbb")]
        XCTAssertEqual(ArtifactMentions.mentions(in: "open index.html", attachments: attachments).map(\.attachmentId), ["a_bbbbbbbbbbbb"])
        // The suffix rule still works when nothing matches exactly.
        XCTAssertEqual(ArtifactMentions.mentions(in: "open site/old/index.html", attachments: [attachments[0]]).map(\.attachmentId),
                       ["a_aaaaaaaaaaaa"])
    }

    func testC6HugeTextOrNoAttachmentsReturnsNothing() {
        let text = Array(repeating: "report.pdf", count: 50_000).joined(separator: " ")
        XCTAssertEqual(ArtifactMentions.mentions(in: text, attachments: []), [])
        XCTAssertEqual(ArtifactMentions.mentions(in: text, attachments: [.init(kind: "link", url: "https://example.com", name: "report.pdf")]), [])
        XCTAssertEqual(ArtifactMentions.mentions(in: text, attachments: [.init(name: "report.pdf")]), [], "over 20 000 bytes")
    }

    func testC8HugeRoundIsNeverPicked() {
        let second = reviewQuestion("two", round: "review-2")
        let huge = reviewQuestion("huge", round: "review-99999999999999999999", at: "2026-11-09T12:00:00Z")
        let t = Ticket(id: "ws|t", workspace: "ws", workspaceName: "Workspace", ticket: "t", title: "Fish", text: "Ready",
                       status: .review, kind: "result", at: "2026-11-09T10:00:00Z", question: nil)
        for questions in [[second, huge], [huge, second]] {
            XCTAssertEqual(ReviewRules.reviewQuestion(ticket: t, workspaceId: "ws", ticketId: "t", questions: questions, answers: [:]), second)
        }
        XCTAssertNil(ReviewRules.reviewQuestion(ticket: t, workspaceId: "ws", ticketId: "t", questions: [huge], answers: [:]))
        XCTAssertNil(ReviewRules.roundNumber(huge))
        XCTAssertNil(ReviewRules.roundNumber(reviewQuestion("ten", round: "review-1234567890")))
        XCTAssertEqual(ReviewRules.roundNumber(reviewQuestion("nine", round: "review-123456789")), 123_456_789)
    }

    func testC11ProgressFractionIsClamped() {
        XCTAssertEqual(ProgressBar.fraction(done: 7, total: 3), 1)
        XCTAssertEqual(ProgressBar.fraction(done: -1, total: 3), 0)
        XCTAssertEqual(ProgressBar.fraction(done: 1, total: 0), 0)
        XCTAssertEqual(ProgressBar.fraction(done: 1, total: 2), 0.5)
    }

    func testC12BlankTitleFallsBackToKey() {
        func ticket(title: String, viewTitle: String?, key: String?) -> Ticket {
            Ticket(id: "ws|t", workspace: "ws", workspaceName: "Workspace", ticket: "t", title: title, text: "x", status: .working,
                   kind: "note", at: "2026-11-09T10:00:00Z", question: nil, key: key, view: TicketSnapshot(title: viewTitle))
        }
        XCTAssertEqual(ticket(title: "", viewTitle: "", key: "PIL-12").displayTitle, "PIL-12")
        XCTAssertEqual(ticket(title: "Fish", viewTitle: " \n", key: "PIL-12").displayTitle, "Fish")
        XCTAssertEqual(ticket(title: " ", viewTitle: nil, key: nil).displayTitle, "Topic")
        XCTAssertEqual(ticket(title: "Fish", viewTitle: "Fish soup", key: "PIL-12").displayTitle, "Fish soup")
    }
}
