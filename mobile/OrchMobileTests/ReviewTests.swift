import XCTest
@testable import OrchMobile

final class ReviewTests: XCTestCase {
    private func question(_ id: String = "q", review: Bool? = true, options: [String] = ["accept", "changes"],
                          roundId: String = "review-1", workspace: String = "ws", ticket: String = "t", at: String = "2026-11-09T10:00:00Z") -> Question {
        Question(message: QuestionMessage(schema: "orch.msg/1", id: id, from: workspace, to: "phones", type: "question",
            createdAt: at, ticket: ticket, body: QuestionBody(questionId: roundId, title: "Fish", text: "Is this done?",
                options: options, recommended: nil, review: review)), workspaceName: "Workspace")
    }
    private func ticket(_ status: Ticket.Status = .review) -> Ticket {
        Ticket(id: "ws|t", workspace: "ws", workspaceName: "Workspace", ticket: "t", title: "Fish", text: "Ready",
               status: status, kind: "result", at: "2026-11-09T10:00:00Z", question: nil)
    }
    func testDecodeAndReviewShape() throws {
        let json = #"{"message":{"schema":"orch.msg/1","id":"q","from":"ws","to":"phones","type":"question","created_at":"2026-11-09T10:00:00Z","ticket":"t","body":{"question_id":"review-1","title":"Fish","text":"Is this done?","options":["accept","changes"],"review":true,"recommended":null}},"workspace_name":"Workspace"}"#
        let q = try JSONCoding.decoder.decode(Question.self, from: Data(json.utf8))
        XCTAssertTrue(q.isReview)
        XCTAssertEqual(q.message.body.review, true)
        XCTAssertTrue(question(options: ["changes", "accept"]).isReview)
        XCTAssertFalse(question(review: nil).isReview)
        XCTAssertFalse(question(review: false).isReview)
        for options in [["accept"], ["accept", "accept"], ["accept", "changes", "changes"], ["Accept", "changes"], ["yes", "no"]] {
            XCTAssertFalse(question(options: options).isReview)
        }
    }
    func testRuleRequiresCurrentReviewAndMatchingOpenQuestion() {
        let q = question()
        func pick(_ t: Ticket?, _ qs: [Question], _ answers: [String: String] = [:]) -> Question? {
            ReviewRules.reviewQuestion(ticket: t, workspaceId: "ws", ticketId: "t", questions: qs, answers: answers)
        }
        XCTAssertEqual(pick(ticket(), [q]), q)
        XCTAssertNil(pick(nil, [q]))
        for status in [Ticket.Status.needsYou, .working, .paused, .backlog, .done] { XCTAssertNil(pick(ticket(status), [q])) }
        XCTAssertNil(pick(ticket(), [q], [q.id: "accept"]))
        XCTAssertNil(pick(ticket(), [question(workspace: "other")]))
        XCTAssertNil(pick(ticket(), [question(ticket: "other")]))
        XCTAssertNil(pick(ticket(), [question(review: nil)]))
        XCTAssertNil(pick(ticket(), []))
        let newer = question("new", at: "2026-11-09T10:00:00.500Z")
        XCTAssertEqual(pick(ticket(), [newer, q]), newer)
        XCTAssertEqual(pick(ticket(), [newer, q], [newer.id: "accept"]), q)
    }
    func testReviewRoundOrderingAndFallbacks() {
        func pick(_ questions: [Question]) -> Question? {
            ReviewRules.reviewQuestion(ticket: ticket(), workspaceId: "ws", ticketId: "t", questions: questions, answers: [:])
        }
        let second = question("z", roundId: "review-2", at: "2026-11-09T11:00:00Z")
        let tenth = question("a", roundId: "review-10")
        XCTAssertEqual(pick([second, tenth]), tenth)
        XCTAssertEqual(pick([tenth, second]), tenth)
        let later = question("b", roundId: "review-10", at: "2026-11-09T12:00:00Z")
        XCTAssertEqual(pick([later, tenth]), later)
        let tie = question("c", roundId: "review-10", at: "2026-11-09T12:00:00Z")
        XCTAssertEqual(pick([tie, later]), tie)
        let fallback = question("fallback", roundId: "legacy", at: "2026-11-09T12:00:00Z")
        XCTAssertEqual(pick([question(roundId: "legacy"), fallback]), fallback)
        XCTAssertNil(ReviewRules.roundNumber(fallback))
    }

    func testReviewContractVectors() throws {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        func object(_ path: String) throws -> [String: Any] {
            try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("contracts/" + path))) as? [String: Any])
        }
        func decodeQuestion(_ message: [String: Any]) throws -> Question {
            let data = try JSONSerialization.data(withJSONObject: ["message": message, "workspace_name": "Workspace"])
            return try JSONCoding.decoder.decode(Question.self, from: data)
        }
        let vector = try object("vectors/review-question-v1.json")
        let q = try decodeQuestion(XCTUnwrap(vector["question"] as? [String: Any]))
        XCTAssertTrue(q.isReview)
        XCTAssertEqual(ReviewRules.roundNumber(q), 2)
        let cases = try XCTUnwrap(vector["cases"] as? [[String: Any]])
        for item in cases {
            let name = try XCTUnwrap(item["name"] as? String)
            let answer = try XCTUnwrap(item["answer"] as? String)
            if item["do"] as? String == "accept" {
                XCTAssertTrue(ReviewRules.isReservedAnswer(answer), name)
            }
            if name == "changes-with-note" {
                XCTAssertFalse(ReviewRules.isReservedAnswer(answer), name)
                XCTAssertFalse(answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            // A phone answer the workspace ignores while the review is current (e.g. a bare "changes") must never be sent
            // as a change note: the person's request would be lost silently.
            if item["do"] as? String == "nothing", (item["from"] as? String)?.hasPrefix("ph_") == true,
               let state = item["state"] as? [String: Any], state["status"] as? String == "review", state["round"] as? Int == 2,
               !answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                XCTAssertTrue(ReviewRules.isReservedAnswer(answer), name)
            }
            if name == "empty-answer" {
                // Composer.sendText rejects this before dispatching any answer.
                XCTAssertTrue(answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        let valid = try decodeQuestion(object("examples/message/valid-question-review.json"))
        XCTAssertTrue(valid.isReview)
        let invalid = try decodeQuestion(object("examples/message/invalid-question-review-false.json"))
        XCTAssertNil(ReviewRules.roundNumber(invalid))
    }

    func testReviewNeverBecomesQuestionCardOrNeedsYouTicket() {
        let q = question()
        var data = ConversationInputs(); data.questions = [q]
        XCTAssertTrue(ConversationBuilder.items(.topic(workspace: "ws", ticket: "t"), data).isEmpty)
        XCTAssertTrue(ConversationBuilder.items(.general(workspace: "ws"), data).isEmpty)
        XCTAssertTrue(TicketBuilder.build(updates: [], questions: [q], answers: [:]).isEmpty)
        var chat = ChatData(); chat.questions = [q]
        XCTAssertTrue(ChatBuilder.ticketItems("ws", "t", chat).isEmpty)
        XCTAssertFalse(chat.isOpen(q))
        XCTAssertTrue(chat.isOpen(question(review: nil)))
    }
    func testReservedChangeNotes() {
        for text in ["accept", "changes", " ACCEPT\n", "\tChAnGeS "] { XCTAssertTrue(ReviewRules.isReservedAnswer(text)) }
        for text in ["Please accept the new layout", "Change the heading", "changes please"] { XCTAssertFalse(ReviewRules.isReservedAnswer(text)) }
    }

    @MainActor
    func testOpenQuestionCountExcludesReview() async {
        let previous = UserDefaults.standard.object(forKey: "mockReview")
        UserDefaults.standard.set(true, forKey: "mockReview")
        defer { UserDefaults.standard.set(previous, forKey: "mockReview") }
        Keychain.delete()
        defer { Keychain.delete() }
        let model = AppModel(useMock: true, voiceMode: .scripted)
        model.openSampleInvite()
        await model.connect(phoneName: "Review test")
        await model.finishSetup(allowNotifications: false)
        await model.refresh()
        XCTAssertTrue(model.questions.contains(where: \.isReview))
        XCTAssertEqual(model.openQuestionCount, model.questions.filter { !$0.isReview }.count)
        XCTAssertEqual(model.ticket(MockRelay.pilatus, MockRelay.reviewTicketId)?.status, .review)
    }
}
